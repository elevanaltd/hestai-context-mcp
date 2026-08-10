"""Unit tests for the Review Gate re-trigger helper (issue #145).

``retrigger_review_gate`` is invoked by ``submit_review`` AFTER a verdict
comment has been posted successfully. It is best-effort and strictly
additive to posting (HO-AGR-SEMANTIC-REVIEWER-ABSTAIN-ON-FAILURE-20260724):
it must NEVER raise, and must NEVER report an outcome it did not actually
observe. These tests exercise the module directly with an injected fake
client -- no live GitHub API calls, no real sleeping.
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


class _FakeClient:
    """Deterministic stand-in for the gh CLI Actions client.

    Each method can be configured with either a fixed return value or a
    sequence of values/exceptions consumed one per call (for retry tests).
    """

    def __init__(
        self,
        head_sha: str | Exception = "abc123headsha",
        find_run_results: list[Any] | None = None,
        rerun_result: Exception | None = None,
    ) -> None:
        self._head_sha = head_sha
        self._find_run_results = list(find_run_results) if find_run_results is not None else [42]
        self._rerun_result = rerun_result
        self.find_run_calls = 0
        self.rerun_calls: list[tuple[str, int]] = []
        self.head_sha_calls = 0

    def get_pr_head_sha(self, repo: str, pr_number: int) -> str:
        self.head_sha_calls += 1
        if isinstance(self._head_sha, Exception):
            raise self._head_sha
        return self._head_sha

    def find_latest_pull_request_run(
        self, repo: str, workflow_name: str, head_sha: str
    ) -> int | None:
        idx = self.find_run_calls
        self.find_run_calls += 1
        if idx >= len(self._find_run_results):
            result = self._find_run_results[-1]
        else:
            result = self._find_run_results[idx]
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
        assert client.find_run_calls == 0
        assert client.rerun_calls == []


@pytest.mark.unit
class TestHappyPath:
    def test_reruns_latest_pull_request_run_for_head_sha(self) -> None:
        client = _FakeClient(head_sha="deadbeef00", find_run_results=[99])
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
        client = _FakeClient(head_sha="freshly-resolved-sha", find_run_results=[7])
        with patch(f"{_MOD}.resolve_github_token", return_value="fake-token"):
            result = retrigger_review_gate("owner/repo", 3, client=client, sleep=lambda _: None)

        assert client.head_sha_calls == 1
        assert result["head_sha"] == "freshly-resolved-sha"


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

    def test_no_pull_request_attached_run_found_skips(self) -> None:
        client = _FakeClient(head_sha="abc123", find_run_results=[None, None, None])
        with patch(f"{_MOD}.resolve_github_token", return_value="fake-token"):
            result = retrigger_review_gate(
                "owner/repo",
                1,
                client=client,
                sleep=lambda _: None,
                retry_delays=(1.0, 2.0),
            )

        assert result["status"] == "skipped"
        assert "no" in result["reason"].lower()
        assert result["run_id"] is None
        assert result["head_sha"] == "abc123"
        assert client.rerun_calls == []
        assert client.find_run_calls == 3  # initial attempt + 2 retries

    def test_actions_api_error_on_rerun_call_skips(self) -> None:
        client = _FakeClient(
            head_sha="abc123",
            find_run_results=[55],
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
        assert result["head_sha"] == "abc123"

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
        client = _FakeClient(head_sha="abc123", find_run_results=[None, None, 123])
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
        assert client.find_run_calls == 3
        # Two delays consumed (before attempt 2 and attempt 3); the initial
        # attempt fires immediately with no delay.
        assert sleeps == [1.0, 2.0]

    def test_no_sleep_needed_when_run_found_on_first_attempt(self) -> None:
        client = _FakeClient(head_sha="abc123", find_run_results=[1])
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
