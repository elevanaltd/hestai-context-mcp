"""Unit tests for the Review Gate re-trigger helper (issue #145, rework #1).

``retrigger_review_gate`` is invoked by ``submit_review`` AFTER a verdict
comment has been posted successfully. It is best-effort and strictly
additive to posting (HO-AGR-SEMANTIC-REVIEWER-ABSTAIN-ON-FAILURE-20260724):
it must NEVER raise, and must NEVER report an outcome it did not actually
observe. These tests exercise the module directly with an injected fake
client -- no live GitHub API calls, no real sleeping.

Rework #1 (cubic triage on PR #148) added two selection constraints on top
of the original head-SHA + event + name filter:

  1. A run at the right head SHA is not necessarily for the right PR --
     stacked branches / re-opened duplicates / a branch pushed to two PRs
     can share a head commit. Selection must filter each candidate run's
     ``pull_requests`` metadata for ``pr_number`` before picking one.
  2. GitHub's rerun endpoint only accepts COMPLETED runs (verified against
     GitHub's REST API docs/community reports: a non-completed run 422s).
     Selection must pick the most recent COMPLETED run for the PR, and
     abstain -- rather than attempt-and-fail -- when the newest matching
     run is still queued/in_progress.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from hestai_context_mcp.tools.shared.review_gate_retrigger import (
    GhApiError,
    retrigger_review_gate,
)

_MOD = "hestai_context_mcp.tools.shared.review_gate_retrigger"


def _run(run_id: int, pr_number: int | None, status: str = "completed") -> dict[str, Any]:
    """Build a workflow-run dict shaped like GitHub's list-runs response.

    ``pr_number=None`` produces an empty ``pull_requests`` list -- GitHub's
    documented shape for runs whose PR association it cannot determine
    (e.g. fork-triggered runs), which must be treated as unverifiable
    rather than "not a match".
    """
    return {
        "id": run_id,
        "status": status,
        "name": "Review Gate",
        "pull_requests": [] if pr_number is None else [{"number": pr_number}],
    }


class _FakeClient:
    """Deterministic stand-in for the gh CLI Actions client.

    ``runs_sequence`` supplies one "list of run dicts" (or an exception) per
    ``list_pull_request_runs`` call, for retry tests; the last entry repeats
    once exhausted.
    """

    def __init__(
        self,
        head_sha: str | Exception = "abc123headsha",
        runs_sequence: list[Any] | None = None,
        rerun_result: Exception | None = None,
    ) -> None:
        self._head_sha = head_sha
        self._runs_sequence = list(runs_sequence) if runs_sequence is not None else [[]]
        self._rerun_result = rerun_result
        self.list_calls = 0
        self.rerun_calls: list[tuple[str, int]] = []
        self.head_sha_calls = 0

    def get_pr_head_sha(self, repo: str, pr_number: int) -> str:
        self.head_sha_calls += 1
        if isinstance(self._head_sha, Exception):
            raise self._head_sha
        return self._head_sha

    def list_pull_request_runs(
        self, repo: str, workflow_name: str, head_sha: str
    ) -> list[dict[str, Any]]:
        idx = self.list_calls
        self.list_calls += 1
        result = self._runs_sequence[idx] if idx < len(self._runs_sequence) else self._runs_sequence[-1]
        if isinstance(result, Exception):
            raise result
        return result

    def rerun_workflow_run(self, repo: str, run_id: int) -> None:
        self.rerun_calls.append((repo, run_id))
        if self._rerun_result is not None:
            raise self._rerun_result


@pytest.mark.unit
class TestNoToken:
    def test_no_token_skips_without_touching_client(self) -> None:
        """No resolvable token -> abstain, and the Actions client is never called."""
        client = _FakeClient()
        with patch(f"{_MOD}.resolve_github_token", return_value=None):
            result = retrigger_review_gate("owner/repo", 1, client=client)

        assert result["status"] == "skipped"
        assert result["reason"]
        assert "token" in result["reason"].lower()
        assert result["run_id"] is None
        assert result["head_sha"] is None
        assert client.head_sha_calls == 0
        assert client.list_calls == 0
        assert client.rerun_calls == []


@pytest.mark.unit
class TestHappyPath:
    def test_reruns_latest_completed_run_matching_pr_number(self) -> None:
        client = _FakeClient(
            head_sha="deadbeef00", runs_sequence=[[_run(99, pr_number=7, status="completed")]]
        )
        with patch(f"{_MOD}.resolve_github_token", return_value="fake-token"):
            result = retrigger_review_gate("owner/repo", 7, client=client, sleep=lambda _: None)

        assert result == {
            "status": "re-triggered",
            "reason": None,
            "run_id": 99,
            "head_sha": "deadbeef00",
        }
        assert client.rerun_calls == [("owner/repo", 99)]

    def test_resolves_head_sha_from_pr_not_a_caller_supplied_value(self) -> None:
        """The tool's optional ``commit_sha`` argument is reviewer-supplied and
        may be stale -- retrigger_review_gate has no such parameter at all,
        so it can only ever act on the head SHA it resolves itself from the
        PR via the client.
        """
        client = _FakeClient(
            head_sha="freshly-resolved-sha", runs_sequence=[[_run(7, pr_number=3)]]
        )
        with patch(f"{_MOD}.resolve_github_token", return_value="fake-token"):
            result = retrigger_review_gate("owner/repo", 3, client=client, sleep=lambda _: None)

        assert client.head_sha_calls == 1
        assert result["head_sha"] == "freshly-resolved-sha"


@pytest.mark.unit
class TestPrNumberSelection:
    """Finding 1 (P1): a run at the right head SHA is not necessarily for the
    right PR. Selection must filter on the run's own ``pull_requests``
    metadata, not just head SHA + event + name.
    """

    def test_selects_run_matching_pr_number_ignoring_other_prs_at_same_sha(self) -> None:
        """Newest run (id 10) belongs to PR 999 (e.g. a stacked branch sharing
        this head commit); the older run (id 20) belongs to PR 7, the PR
        this call is actually about. Only run 20 may be re-run.
        """
        client = _FakeClient(
            runs_sequence=[
                [
                    _run(10, pr_number=999, status="completed"),
                    _run(20, pr_number=7, status="completed"),
                ]
            ]
        )
        with patch(f"{_MOD}.resolve_github_token", return_value="fake-token"):
            result = retrigger_review_gate("owner/repo", 7, client=client, sleep=lambda _: None)

        assert result["status"] == "re-triggered"
        assert result["run_id"] == 20
        assert client.rerun_calls == [("owner/repo", 20)]

    def test_abstains_when_no_run_matches_pr_number(self) -> None:
        client = _FakeClient(runs_sequence=[[_run(10, pr_number=999, status="completed")]])
        with patch(f"{_MOD}.resolve_github_token", return_value="fake-token"):
            result = retrigger_review_gate(
                "owner/repo", 7, client=client, sleep=lambda _: None, retry_delays=()
            )

        assert result["status"] == "skipped"
        assert "7" in result["reason"]
        assert result["run_id"] is None
        assert client.rerun_calls == []

    def test_abstains_when_pull_requests_metadata_unusable(self) -> None:
        """Every candidate run has an empty ``pull_requests`` list (GitHub's
        documented shape when it cannot determine PR association, e.g.
        fork-triggered runs) -- we cannot verify any of them belong to our
        PR, so we must abstain rather than guess which one to re-run.
        """
        client = _FakeClient(
            runs_sequence=[
                [_run(10, pr_number=None, status="completed"), _run(20, pr_number=None)]
            ]
        )
        with patch(f"{_MOD}.resolve_github_token", return_value="fake-token"):
            result = retrigger_review_gate("owner/repo", 7, client=client, sleep=lambda _: None)

        assert result["status"] == "skipped"
        assert "verify" in result["reason"].lower() or "metadata" in result["reason"].lower()
        assert result["run_id"] is None
        assert client.rerun_calls == []
        # Unverifiable metadata is a definitive answer, not a listing race --
        # must not burn the retry budget.
        assert client.list_calls == 1


@pytest.mark.unit
class TestRunStatusSelection:
    """Finding 2 (P2): the rerun endpoint only accepts COMPLETED runs.
    Selection must skip non-completed runs and abstain rather than attempt
    a rerun call doomed to fail.
    """

    def test_prefers_completed_run_over_newer_in_progress_run(self) -> None:
        client = _FakeClient(
            runs_sequence=[
                [
                    _run(50, pr_number=7, status="in_progress"),
                    _run(40, pr_number=7, status="completed"),
                ]
            ]
        )
        with patch(f"{_MOD}.resolve_github_token", return_value="fake-token"):
            result = retrigger_review_gate("owner/repo", 7, client=client, sleep=lambda _: None)

        assert result["status"] == "re-triggered"
        assert result["run_id"] == 40
        assert client.rerun_calls == [("owner/repo", 40)]

    def test_abstains_when_only_matching_run_is_in_progress(self) -> None:
        client = _FakeClient(runs_sequence=[[_run(50, pr_number=7, status="in_progress")]])
        with patch(f"{_MOD}.resolve_github_token", return_value="fake-token"):
            result = retrigger_review_gate("owner/repo", 7, client=client, sleep=lambda _: None)

        assert result["status"] == "skipped"
        assert "in_progress" in result["reason"]
        assert result["run_id"] is None
        assert client.rerun_calls == []
        # An in-flight run is a definitive answer (it will evaluate on its
        # own) -- must not retry waiting for it to complete.
        assert client.list_calls == 1


@pytest.mark.unit
class TestAbstainPaths:
    def test_head_sha_lookup_failure_skips(self) -> None:
        client = _FakeClient(head_sha=GhApiError("HTTP 404 resolving PR head SHA"))
        with patch(f"{_MOD}.resolve_github_token", return_value="fake-token"):
            result = retrigger_review_gate("owner/repo", 1, client=client, sleep=lambda _: None)

        assert result["status"] == "skipped"
        assert "404" in result["reason"]
        assert result["run_id"] is None
        assert result["head_sha"] is None
        assert client.rerun_calls == []

    def test_no_pull_request_attached_run_found_skips_after_retries(self) -> None:
        client = _FakeClient(runs_sequence=[[], [], []])
        with patch(f"{_MOD}.resolve_github_token", return_value="fake-token"):
            result = retrigger_review_gate(
                "owner/repo",
                1,
                client=client,
                sleep=lambda _: None,
                retry_delays=(1.0, 2.0),
            )

        assert result["status"] == "skipped"
        assert "1" in result["reason"]
        assert result["run_id"] is None
        assert result["head_sha"] == "abc123headsha"
        assert client.rerun_calls == []
        assert client.list_calls == 3  # initial attempt + 2 retries

    def test_actions_api_error_on_rerun_call_skips(self) -> None:
        client = _FakeClient(
            runs_sequence=[[_run(55, pr_number=1)]],
            rerun_result=GhApiError("HTTP 403 re-running workflow run 55"),
        )
        with patch(f"{_MOD}.resolve_github_token", return_value="fake-token"):
            result = retrigger_review_gate("owner/repo", 1, client=client, sleep=lambda _: None)

        assert result["status"] == "skipped"
        assert "403" in result["reason"]
        # The run WAS located (observed) even though the rerun call failed --
        # surfaced for diagnostic value, but status must stay "skipped" since
        # the rerun outcome itself was never observed as successful.
        assert result["run_id"] == 55
        assert result["head_sha"] == "abc123headsha"

    def test_unexpected_exception_from_client_never_propagates(self) -> None:
        """Defense in depth: even a non-GhApiError exception from the client
        must collapse to an abstain, never raise out of the tool.
        """
        client = _FakeClient(head_sha=ValueError("something broke"))
        with patch(f"{_MOD}.resolve_github_token", return_value="fake-token"):
            result = retrigger_review_gate("owner/repo", 1, client=client, sleep=lambda _: None)

        assert result["status"] == "skipped"
        assert result["reason"]


@pytest.mark.unit
class TestRetryRaceHandling:
    def test_retries_finding_the_run_before_giving_up(self) -> None:
        """Simulates the read-after-write race: the run doesn't appear on the
        first listing but shows up on a later attempt within the bounded
        retry budget.
        """
        client = _FakeClient(runs_sequence=[[], [], [_run(123, pr_number=1)]])
        sleeps: list[float] = []
        with patch(f"{_MOD}.resolve_github_token", return_value="fake-token"):
            result = retrigger_review_gate(
                "owner/repo",
                1,
                client=client,
                sleep=sleeps.append,
                retry_delays=(1.0, 2.0, 4.0),
            )

        assert result["status"] == "re-triggered"
        assert result["run_id"] == 123
        assert client.list_calls == 3
        # Two delays consumed (before attempt 2 and attempt 3); the initial
        # attempt fires immediately with no delay.
        assert sleeps == [1.0, 2.0]

    def test_no_sleep_needed_when_run_found_on_first_attempt(self) -> None:
        client = _FakeClient(runs_sequence=[[_run(1, pr_number=1)]])
        sleeps: list[float] = []
        with patch(f"{_MOD}.resolve_github_token", return_value="fake-token"):
            result = retrigger_review_gate(
                "owner/repo", 1, client=client, sleep=sleeps.append, retry_delays=(1.0, 2.0)
            )

        assert result["status"] == "re-triggered"
        assert sleeps == []


@pytest.mark.unit
class TestDefaultClientIsGhCli:
    def test_default_client_used_when_none_injected(self) -> None:
        """Without an injected client, the module must fall back to a real
        gh-CLI-backed client rather than silently no-op'ing. We verify this
        by observing that it attempts a subprocess call (mocked) rather than
        skipping straight through with zero client interaction.
        """
        with (
            patch(f"{_MOD}.resolve_github_token", return_value="fake-token"),
            patch(f"{_MOD}.subprocess.run") as mock_run,
        ):
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = "HTTP/2 500 Internal Server Error\n\n{}"
            mock_run.return_value.stderr = ""

            result = retrigger_review_gate("owner/repo", 1, sleep=lambda _: None)

        assert mock_run.called
        assert result["status"] == "skipped"
