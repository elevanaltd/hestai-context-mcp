"""Unit tests for the Review Gate re-trigger helper (issue #145, rework #2).

``retrigger_review_gate`` is invoked by ``submit_review`` AFTER a verdict
comment has been posted successfully. It is best-effort and strictly
additive to posting (HO-AGR-SEMANTIC-REVIEWER-ABSTAIN-ON-FAILURE-20260724):
it must NEVER raise, and must NEVER report an outcome it did not actually
observe. These tests exercise the module directly with an injected fake
client -- no live GitHub API calls, no real sleeping, no real clock reads.

Rework #2 (all-four-reviewers CONDITIONAL triage on PR #148) fixed:

  2. Worst-case latency (CE): an overall time budget now bounds the whole
     re-trigger, checked between steps, with a reduced per-call timeout.
  3. Retry aborted by one unverifiable run (CRS): a run with unusable
     ``pull_requests`` metadata no longer suppresses retry when no PR match
     was found -- it only becomes the terminal reason once the retry
     budget is spent.
  4. Fragile run lookup (CE + CRS): listing is now scoped to the workflow
     FILE name (stable) via the workflow-scoped endpoint, not the mutable
     display name, with an explicit, tested page-size bound instead of an
     unbounded/undocumented truncation risk.
  5. Event filter too narrow (CRS/coordinator): the ruleset enforces
     pull_request, pull_request_target AND merge_group -- selection now
     accepts all three rather than hardcoding one.
  7. Vacuous default-client test: now asserts the abstain reason actually
     carries the observed HTTP signal, not just that status == "skipped".
  9/10. Additional coverage: a listing failure mid-retry-loop, the outer
     catch-all exception path, and more `_GhCliClient` edge cases.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from hestai_context_mcp.tools.shared.review_gate_retrigger import (
    DEFAULT_OVERALL_BUDGET_SECONDS,
    WORKFLOW_FILE,
    GhApiError,
    retrigger_review_gate,
)

_MOD = "hestai_context_mcp.tools.shared.review_gate_retrigger"

# The gate workflow's path as GitHub reports it on every run object. Stated
# as a literal here (not imported from the module under test) so these tests
# assert an independent expectation rather than tautologically agreeing with
# whatever the module happens to define.
_GATE_WORKFLOW_PATH = ".github/workflows/review-gate.yml"


def _run(
    run_id: int,
    pr_number: int | None,
    status: str = "completed",
    event: str = "pull_request",
    path: str = _GATE_WORKFLOW_PATH,
    workflow_id: int = 224758050,
) -> dict[str, Any]:
    """Build a workflow-run dict shaped like GitHub's list-runs response.

    ``pr_number=None`` produces an empty ``pull_requests`` list -- GitHub's
    documented shape for runs whose PR association it cannot determine
    (e.g. fork-triggered runs), which must be treated as unverifiable
    rather than "not a match".
    """
    return {
        "id": run_id,
        "status": status,
        "event": event,
        "path": path,
        "workflow_id": workflow_id,
        "pull_requests": [] if pr_number is None else [{"number": pr_number}],
    }


class _FakeClient:
    """Deterministic stand-in for the gh CLI Actions client.

    ``runs_sequence`` supplies one "list of run dicts" (or an exception) per
    ``list_workflow_runs_for_head_sha`` call, for retry tests; the last
    entry repeats once exhausted.

    Every method records the ``timeout`` it was called with (rework #4:
    the caller now computes a fresh, budget-bounded timeout for every
    call), so tests unconcerned with timing can ignore it while
    budget-focused tests can assert on it directly.
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
        self.list_call_args: list[tuple[str, ...]] = []
        self.list_call_timeouts: list[float] = []
        self.rerun_calls: list[tuple[str, int]] = []
        self.rerun_timeouts: list[float] = []
        self.head_sha_calls = 0
        self.head_sha_timeouts: list[float] = []

    def get_pr_head_sha(self, repo: str, pr_number: int, *, timeout: float) -> str:
        self.head_sha_calls += 1
        self.head_sha_timeouts.append(timeout)
        if isinstance(self._head_sha, Exception):
            raise self._head_sha
        return self._head_sha

    def list_workflow_runs_for_head_sha(
        self, repo: str, *args: str, timeout: float
    ) -> list[dict[str, Any]]:
        """Accepts BOTH listing shapes, so one test body can state the
        contract across the endpoint change instead of the fake dictating it:

          * workflow-SCOPED (old): ``(repo, workflow_file, head_sha)``
          * UNSCOPED        (new): ``(repo, head_sha)``

        Which shape was actually used is recorded in ``list_call_args`` and
        asserted directly by the tests that care.
        """
        self.list_call_args.append((repo, *args))
        self.list_call_timeouts.append(timeout)
        idx = self.list_calls
        self.list_calls += 1
        result = (
            self._runs_sequence[idx] if idx < len(self._runs_sequence) else self._runs_sequence[-1]
        )
        if isinstance(result, Exception):
            raise result
        return result

    def rerun_workflow_run(self, repo: str, run_id: int, *, timeout: float) -> None:
        self.rerun_calls.append((repo, run_id))
        self.rerun_timeouts.append(timeout)
        if self._rerun_result is not None:
            raise self._rerun_result


class _SimClock:
    """Stateful simulated monotonic clock for budget-ceiling tests.

    Starts at ``t=0`` and only advances when explicitly told to (via
    ``advance()``), from an injected ``sleep`` and from simulated call
    durations (see ``_SimTimingClient`` below) -- so ``now()`` always
    reflects the TOTAL simulated time consumed so far, and a test can make
    a single, direct assertion: the last time read never exceeds the
    budget's deadline. This is what makes it possible to assert the
    ceiling itself, not just that some abstain happened (rework #4).
    """

    def __init__(self) -> None:
        self.t = 0.0

    def now(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        assert seconds >= 0.0
        self.t += seconds

    def sleep(self, seconds: float) -> None:
        """Usable directly as the injected ``sleep`` callable: simulated
        sleeping really does consume simulated time, exactly like a real
        ``time.sleep`` call would consume real wall-clock time.
        """
        self.advance(seconds)


class _SimTimingClient:
    """Fake ``ReviewGateClient`` whose calls consume simulated clock time,
    mirroring real ``subprocess.run(timeout=...)`` semantics: a call whose
    configured ``duration`` exceeds the ``timeout`` it was given only
    consumes time UP TO that timeout before raising -- it does not run to
    completion and then get reported as a timeout after the fact. This is
    what makes it possible to prove a call's ACTUAL wall-clock consumption
    is bounded by the timeout it was passed, not by some larger fixed
    value (rework #4 hole b).
    """

    def __init__(
        self,
        clock: _SimClock,
        *,
        head_sha: str = "abc123headsha",
        head_sha_duration: float = 0.1,
        list_duration: float = 0.1,
        list_results: list[Any] | None = None,
        rerun_duration: float = 0.1,
    ) -> None:
        self._clock = clock
        self._head_sha = head_sha
        self._head_sha_duration = head_sha_duration
        self._list_duration = list_duration
        # One "list of run dicts" per call (repeats the last entry once
        # exhausted), same convention as _FakeClient.runs_sequence -- lets
        # a test simulate "no match yet, then a match on a later attempt"
        # while still exercising real simulated-time consumption.
        self._list_results: list[Any] = list(list_results) if list_results is not None else [[]]
        self._list_call_count = 0
        self._rerun_duration = rerun_duration
        self.list_call_timeouts: list[float] = []
        self.rerun_calls: list[tuple[str, int]] = []

    def _consume(self, configured_duration: float, timeout: float, *, label: str) -> None:
        if configured_duration > timeout:
            self._clock.advance(timeout)
            raise GhApiError(
                f"gh api call timed out: simulated {label} duration "
                f"{configured_duration:.1f}s exceeds passed timeout {timeout:.1f}s"
            )
        self._clock.advance(configured_duration)

    def get_pr_head_sha(self, repo: str, pr_number: int, *, timeout: float) -> str:
        self._consume(self._head_sha_duration, timeout, label="head-SHA lookup")
        return self._head_sha

    def list_workflow_runs_for_head_sha(
        self, repo: str, *args: str, timeout: float
    ) -> list[dict[str, Any]]:
        self.list_call_timeouts.append(timeout)
        self._consume(self._list_duration, timeout, label="run-listing")
        idx = self._list_call_count
        self._list_call_count += 1
        return self._list_results[idx] if idx < len(self._list_results) else self._list_results[-1]

    def rerun_workflow_run(self, repo: str, run_id: int, *, timeout: float) -> None:
        self._consume(self._rerun_duration, timeout, label="rerun")
        self.rerun_calls.append((repo, run_id))


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

    def test_lists_runs_unscoped_at_the_head_sha_not_scoped_to_the_workflow_file(
        self,
    ) -> None:
        """The listing must NOT be keyed on the gate's workflow FILE name.

        The workflow-scoped endpoint resolves ``review-gate.yml`` against the
        CONSUMING repo's own workflow entry, which in a ruleset-wired repo is
        not the entry that actually ran (see ``TestRulesetWiredRepo``). Every
        run object reports its own ``path`` regardless of which workflow
        entry owns it, so the listing is taken unscoped at the head SHA and
        narrowed on that path during selection instead.
        """
        client = _FakeClient(runs_sequence=[[_run(1, pr_number=1)]])
        with patch(f"{_MOD}.resolve_github_token", return_value="fake-token"):
            retrigger_review_gate("owner/repo", 1, client=client, sleep=lambda _: None)

        assert client.list_call_args == [("owner/repo", "abc123headsha")]


class _RulesetWiredClient:
    """Simulates a consuming repo wired by an org ruleset, reproduced from
    live ``gh api`` output for elevanaltd/elevana-studio PR #1945 at head
    500ce6f8c7c6db8ee3cc917c9057cfe0b544eefc:

      * ``repos/{repo}/actions/workflows`` lists ONE entry named "Review
        Gate" at ``.github/workflows/review-gate.yml`` -- the repo's OWN
        caller file, id 224758050, with zero runs at that SHA.
      * the run that actually executed belongs to the ruleset-INJECTED
        required workflow, id 299891129. It is invisible to the
        workflow-scoped endpoint (``.../actions/workflows/review-gate.yml/
        runs?head_sha=...`` returned ``total_count=0``) yet reports the very
        same ``path``.

    Hence: the workflow-SCOPED call shape yields nothing, while the UNSCOPED
    call shape yields every run at the SHA, the injected one included.
    """

    OWN_WORKFLOW_ID = 224758050
    INJECTED_WORKFLOW_ID = 299891129

    def __init__(self, runs: list[dict[str, Any]]) -> None:
        self._runs = runs
        self.scoped_calls = 0
        self.unscoped_calls = 0
        self.rerun_calls: list[tuple[str, int]] = []

    def get_pr_head_sha(self, repo: str, pr_number: int, *, timeout: float) -> str:
        return "500ce6f8c7c6db8ee3cc917c9057cfe0b544eefc"

    def list_workflow_runs_for_head_sha(
        self, repo: str, *args: str, timeout: float
    ) -> list[dict[str, Any]]:
        if len(args) == 2:  # (workflow_file, head_sha) -- the scoped endpoint
            self.scoped_calls += 1
            return [r for r in self._runs if r["workflow_id"] == self.OWN_WORKFLOW_ID]
        self.unscoped_calls += 1
        return list(self._runs)

    def rerun_workflow_run(self, repo: str, run_id: int, *, timeout: float) -> None:
        self.rerun_calls.append((repo, run_id))


@pytest.mark.unit
class TestRulesetWiredRepo:
    """The primary case this module exists for: a repo whose Review Gate is
    injected by an org ruleset. Two workflow entries share the name "Review
    Gate" at the same path -- the repo's own caller file and the injected
    required workflow -- and only the latter ever runs.
    """

    def test_locates_the_ruleset_injected_run_the_scoped_endpoint_cannot_see(
        self,
    ) -> None:
        injected = _run(
            34159096298,
            pr_number=1945,
            workflow_id=_RulesetWiredClient.INJECTED_WORKFLOW_ID,
        )
        client = _RulesetWiredClient([injected])

        with patch(f"{_MOD}.resolve_github_token", return_value="fake-token"):
            result = retrigger_review_gate(
                "elevanaltd/elevana-studio",
                1945,
                client=client,
                sleep=lambda _: None,
                retry_delays=(),
            )

        assert result["status"] == "re-triggered"
        assert result["run_id"] == 34159096298
        assert client.rerun_calls == [("elevanaltd/elevana-studio", 34159096298)]
        # Run location must not depend on the consuming repo resolving
        # `review-gate.yml` to the right workflow id at all.
        assert client.scoped_calls == 0
        assert client.unscoped_calls == 1

    def test_ignores_other_workflows_runs_returned_by_the_unscoped_listing(
        self,
    ) -> None:
        """The unscoped listing returns EVERY workflow's runs at the SHA, so
        selection must narrow on the gate's own workflow path -- a completed
        CI run for the same PR at the same SHA is not the required check.
        """
        client = _FakeClient(
            runs_sequence=[
                [
                    _run(
                        60,
                        pr_number=7,
                        path=".github/workflows/ci.yml",
                        workflow_id=987654,
                    )
                ]
            ]
        )
        with patch(f"{_MOD}.resolve_github_token", return_value="fake-token"):
            result = retrigger_review_gate(
                "owner/repo", 7, client=client, sleep=lambda _: None, retry_delays=()
            )

        assert result["status"] == "skipped"
        assert result["run_id"] is None
        assert client.rerun_calls == []

    def test_run_without_a_path_field_is_excluded_not_crashed_on(self) -> None:
        """TMG gap: GitHub always reports ``path`` on run objects, but
        selection must degrade to "not the gate's run" if it is ever absent
        -- never raise, and never select a run whose workflow it could not
        identify.
        """
        pathless = _run(70, pr_number=7)
        del pathless["path"]
        client = _FakeClient(runs_sequence=[[pathless]])

        with patch(f"{_MOD}.resolve_github_token", return_value="fake-token"):
            result = retrigger_review_gate(
                "owner/repo", 7, client=client, sleep=lambda _: None, retry_delays=()
            )

        assert result["status"] == "skipped"
        assert result["run_id"] is None
        assert client.rerun_calls == []


@pytest.mark.unit
class TestPrNumberSelection:
    """Finding 1 (rework #1): a run at the right head SHA is not necessarily
    for the right PR. Selection must filter on the run's own
    ``pull_requests`` metadata, not just head SHA + event.
    """

    def test_selects_run_matching_pr_number_ignoring_other_prs_at_same_sha(self) -> None:
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


@pytest.mark.unit
class TestUnverifiableMetadataRetries:
    """Finding 3 (rework #2, CRS): a single unverifiable run must NOT abort
    the retry loop -- it only becomes the terminal reason once the retry
    budget is spent, exactly like the plain "not found yet" case.
    """

    def test_keeps_retrying_past_an_unverifiable_run_before_abstaining(self) -> None:
        # Every attempt sees only an unverifiable run (empty pull_requests).
        # If unverifiable runs wrongly aborted retry, list_calls would stop
        # at 1; the fix requires it to consume the full retry budget.
        client = _FakeClient(
            runs_sequence=[
                [_run(9, pr_number=None, status="completed")],
                [_run(9, pr_number=None, status="completed")],
                [_run(9, pr_number=None, status="completed")],
            ]
        )
        with patch(f"{_MOD}.resolve_github_token", return_value="fake-token"):
            result = retrigger_review_gate(
                "owner/repo",
                148,
                client=client,
                sleep=lambda _: None,
                retry_delays=(1.0, 2.0),
            )

        assert result["status"] == "skipped"
        assert "verify" in result["reason"].lower() or "metadata" in result["reason"].lower()
        assert result["run_id"] is None
        assert client.rerun_calls == []
        assert client.list_calls == 3  # initial attempt + 2 retries -- NOT aborted early

    def test_finds_real_match_on_a_later_attempt_despite_earlier_unverifiable_run(self) -> None:
        """The propagation race this retry loop exists to win: an
        unverifiable (fork-triggered) run shows up first, and the real
        PR-matching run only appears on a later listing.
        """
        client = _FakeClient(
            runs_sequence=[
                [_run(9, pr_number=None, status="completed")],
                [_run(9, pr_number=None), _run(20, pr_number=148, status="completed")],
            ]
        )
        with patch(f"{_MOD}.resolve_github_token", return_value="fake-token"):
            result = retrigger_review_gate(
                "owner/repo",
                148,
                client=client,
                sleep=lambda _: None,
                retry_delays=(1.0, 2.0),
            )

        assert result["status"] == "re-triggered"
        assert result["run_id"] == 20
        assert client.list_calls == 2


@pytest.mark.unit
class TestRunStatusSelection:
    """Finding 2 (rework #1): the rerun endpoint only accepts COMPLETED runs.
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

    def test_waits_for_an_in_flight_run_and_reruns_it_once_completed(self) -> None:
        """An in-flight run is NOT a definitive answer.

        The run in flight when a verdict lands was fired by an earlier push
        (``pull_request: opened``) and therefore PREDATES the verdict comment
        -- letting it "evaluate on its own once it finishes" reproduces
        exactly the red the re-trigger exists to clear. So the in-flight case
        must be retryable: the existing bounded retry loop waits for
        completion and then re-runs it.
        """
        client = _FakeClient(
            runs_sequence=[
                [_run(50, pr_number=7, status="queued")],
                [_run(50, pr_number=7, status="in_progress")],
                [_run(50, pr_number=7, status="completed")],
            ]
        )
        with patch(f"{_MOD}.resolve_github_token", return_value="fake-token"):
            result = retrigger_review_gate(
                "owner/repo",
                7,
                client=client,
                sleep=lambda _: None,
                retry_delays=(1.0, 2.0),
            )

        assert result["status"] == "re-triggered"
        assert result["run_id"] == 50
        assert client.list_calls == 3
        assert client.rerun_calls == [("owner/repo", 50)]

    def test_abstains_naming_the_in_flight_state_once_retries_are_exhausted(
        self,
    ) -> None:
        """Waiting is bounded: a run that never completes within the retry
        budget still abstains, with a reason naming its non-completed state
        -- never a rerun call GitHub would 422, and never a fabricated
        outcome.
        """
        client = _FakeClient(runs_sequence=[[_run(50, pr_number=7, status="in_progress")]])
        with patch(f"{_MOD}.resolve_github_token", return_value="fake-token"):
            result = retrigger_review_gate(
                "owner/repo",
                7,
                client=client,
                sleep=lambda _: None,
                retry_delays=(1.0, 2.0),
            )

        assert result["status"] == "skipped"
        assert "in_progress" in result["reason"]
        assert result["run_id"] is None
        assert client.rerun_calls == []
        assert client.list_calls == 3  # initial attempt + 2 retries


@pytest.mark.unit
class TestEventSet:
    """Finding 5: the ruleset's required-workflow feature enforces
    pull_request, pull_request_target AND merge_group -- selection must
    accept runs from all three, not hardcode ``pull_request`` alone.
    """

    def test_pull_request_target_run_is_selected(self) -> None:
        client = _FakeClient(
            runs_sequence=[[_run(5, pr_number=1, status="completed", event="pull_request_target")]]
        )
        with patch(f"{_MOD}.resolve_github_token", return_value="fake-token"):
            result = retrigger_review_gate("owner/repo", 1, client=client, sleep=lambda _: None)

        assert result["status"] == "re-triggered"
        assert result["run_id"] == 5

    def test_merge_group_run_is_selected(self) -> None:
        client = _FakeClient(
            runs_sequence=[[_run(6, pr_number=1, status="completed", event="merge_group")]]
        )
        with patch(f"{_MOD}.resolve_github_token", return_value="fake-token"):
            result = retrigger_review_gate("owner/repo", 1, client=client, sleep=lambda _: None)

        assert result["status"] == "re-triggered"
        assert result["run_id"] == 6

    def test_unrelated_event_is_ignored(self) -> None:
        """A run at the right head SHA/PR but from an unenforced event (e.g.
        ``workflow_dispatch``) must not be selected -- it is not the run
        backing the required check.
        """
        client = _FakeClient(
            runs_sequence=[[_run(7, pr_number=1, status="completed", event="workflow_dispatch")]]
        )
        with patch(f"{_MOD}.resolve_github_token", return_value="fake-token"):
            result = retrigger_review_gate(
                "owner/repo", 1, client=client, sleep=lambda _: None, retry_delays=()
            )

        assert result["status"] == "skipped"
        assert client.rerun_calls == []


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

    def test_listing_failure_mid_retry_loop_skips(self) -> None:
        """Finding 9: the listing call can fail on a LATER retry attempt,
        not just the first one -- must abstain cleanly there too.
        """
        client = _FakeClient(
            runs_sequence=[[], GhApiError("HTTP 502 listing workflow runs")],
        )
        with patch(f"{_MOD}.resolve_github_token", return_value="fake-token"):
            result = retrigger_review_gate(
                "owner/repo",
                1,
                client=client,
                sleep=lambda _: None,
                retry_delays=(1.0, 2.0),
            )

        assert result["status"] == "skipped"
        assert "502" in result["reason"]
        assert client.list_calls == 2
        assert client.rerun_calls == []

    def test_a_throwing_clock_never_propagates(self) -> None:
        """CRS: the injected clock's FIRST read (computing the deadline) sat
        outside the outer catch-all, so a clock that raises escaped the
        "NEVER raises" contract entirely -- before any Actions call, and
        before the token check. Every failure mode must collapse to an
        abstain, the clock included.
        """

        def broken_clock() -> float:
            raise RuntimeError("clock failed")

        client = _FakeClient()
        with patch(f"{_MOD}.resolve_github_token", return_value="fake-token"):
            result = retrigger_review_gate(
                "owner/repo", 1, client=client, sleep=lambda _: None, now=broken_clock
            )

        assert result["status"] == "skipped"
        assert "clock failed" in result["reason"]
        assert client.head_sha_calls == 0
        assert client.rerun_calls == []

    def test_outer_catch_all_never_propagates_unexpected_token_resolution_failure(self) -> None:
        """Finding 10: cover the OUTER catch-all (wrapping the whole
        function body), not just the inner per-step try/excepts. Force an
        exception at a point with no dedicated try/except of its own
        (resolve_github_token raising instead of returning None).
        """
        client = _FakeClient()
        with patch(f"{_MOD}.resolve_github_token", side_effect=RuntimeError("keyring exploded")):
            result = retrigger_review_gate("owner/repo", 1, client=client, sleep=lambda _: None)

        assert result["status"] == "skipped"
        assert "keyring exploded" in result["reason"]
        assert client.head_sha_calls == 0


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
class TestOverallTimeBudget:
    """Rework #4 (CE, confirmed by coordinator): the rework #2 budget check
    was not an actual ceiling. Two holes: (a) the deadline was checked
    BEFORE sleeping, never after, so a retry delay could itself consume
    the remaining budget and still be followed by a full-length call; (b)
    nothing bounded a call's DURATION by the remaining budget, so a call
    starting just before the deadline still ran its full per-call timeout.
    Demonstrated concretely: a 25s budget with three 8s-timeout listing
    calls at t=100.1/109.1/119.1 finished at 27.1s -- a 2.1s overrun on a
    "25s budget".

    These tests assert the CEILING directly (final simulated elapsed time
    never exceeds the budget), using a stateful simulated clock/sleep/
    client where sleeping and calls actually consume simulated time --
    not just that an abstain happened, which is what let the 27.1s run
    look like a 25s budget in the first place.
    """

    def test_default_budget_is_documented_and_bounded(self) -> None:
        # 25s keeps worst case comfortably under typical stdio/tool call
        # ceilings, while still allowing a head lookup + a few retry
        # attempts + a rerun call to complete under normal conditions.
        assert 15.0 <= DEFAULT_OVERALL_BUDGET_SECONDS <= 30.0

    def test_sleep_is_capped_so_it_cannot_cross_the_deadline(self) -> None:
        """Hole (a): a nominal retry delay (20s) far exceeds the remaining
        budget (10s). The sleep itself must be capped at the remaining
        budget -- not the full nominal delay -- so total elapsed can never
        exceed the deadline. The budget is re-checked immediately AFTER
        the (capped) sleep too, so the now-exhausted remainder correctly
        abstains rather than issuing another call -- both checks (before
        AND after the sleep) matter: this scenario passes the before-sleep
        check (there was still time to make sleeping worthwhile) and is
        then caught by the after-sleep check once the capped sleep has
        consumed exactly what remained.
        """
        clock = _SimClock()
        client = _SimTimingClient(clock, list_results=[[]])  # every listing: no match, retryable

        with patch(f"{_MOD}.resolve_github_token", return_value="fake-token"):
            result = retrigger_review_gate(
                "owner/repo",
                1,
                client=client,
                sleep=clock.sleep,
                now=clock.now,
                overall_budget=10.0,
                retry_delays=(20.0,),
            )

        assert clock.now() <= 10.0, "total simulated elapsed time exceeded the budget"
        assert clock.now() == pytest.approx(10.0)
        assert result["status"] == "skipped"
        assert "budget" in result["reason"].lower()
        assert "run-listing call" in result["reason"]
        # Only the FIRST attempt's listing call happened; the second was
        # correctly abandoned (by the after-sleep check) before being issued.
        assert len(client.list_call_timeouts) == 1

    def test_abstains_before_sleeping_when_remaining_budget_already_too_small(self) -> None:
        """The PRE-sleep check's own distinct message: when remaining budget
        is already below the useful threshold before a retry delay would
        even be attempted, no sleep happens at all -- distinguishable from
        the post-sleep "insufficient for a run-listing call" message
        exercised above.
        """
        clock = _SimClock()
        # head-SHA lookup + first listing call consume 9.5s of a 10s budget,
        # leaving 0.5s -- below the 1.0s minimum-useful threshold, so the
        # second attempt's retry delay must never be slept at all.
        client = _SimTimingClient(
            clock, head_sha_duration=5.0, list_duration=4.5, list_results=[[]]
        )

        with patch(f"{_MOD}.resolve_github_token", return_value="fake-token"):
            result = retrigger_review_gate(
                "owner/repo",
                1,
                client=client,
                sleep=clock.sleep,
                now=clock.now,
                overall_budget=10.0,
                retry_delays=(1.0,),
            )

        assert clock.now() == pytest.approx(9.5), "no sleep should have been attempted"
        assert clock.now() <= 10.0
        assert result["status"] == "skipped"
        assert "budget" in result["reason"].lower()
        assert "wait for the next retry attempt" in result["reason"]
        assert len(client.list_call_timeouts) == 1  # only the first attempt's call

    def test_call_timeout_is_capped_so_a_call_cannot_run_past_the_deadline(self) -> None:
        """Hole (b): even with no sleeping involved, a call whose nominal
        duration (8s) exceeds the REMAINING budget (5s, after a 5s head-SHA
        lookup against a 10s budget) must be capped to that remaining
        budget -- not allowed to run its full nominal duration past the
        deadline.
        """
        clock = _SimClock()
        client = _SimTimingClient(
            clock,
            head_sha_duration=5.0,
            list_duration=8.0,  # would exceed remaining budget once capped
        )

        with patch(f"{_MOD}.resolve_github_token", return_value="fake-token"):
            result = retrigger_review_gate(
                "owner/repo",
                1,
                client=client,
                sleep=clock.sleep,
                now=clock.now,
                overall_budget=10.0,
                retry_delays=(),
            )

        assert clock.now() <= 10.0, "total simulated elapsed time exceeded the budget"
        assert clock.now() == pytest.approx(10.0)
        # The timeout PASSED to the client was capped at the remaining
        # budget (5.0s), not the module's 8.0s per-call ceiling.
        assert client.list_call_timeouts == [pytest.approx(5.0)]
        assert result["status"] == "skipped"
        assert "Actions API error while listing workflow runs" in result["reason"]

    def test_per_call_timeout_shrinks_as_budget_depletes(self) -> None:
        """The timeout handed to the client on each successive call must
        shrink to track the remaining budget, not stay fixed at the
        module's per-call ceiling.
        """
        clock = _SimClock()
        client = _SimTimingClient(
            clock,
            head_sha_duration=1.0,
            list_duration=1.0,
            # First listing call: no match (forces a retry). Second (after
            # the retry delay): a completed match.
            list_results=[[], [_run(42, pr_number=1, status="completed")]],
        )

        with patch(f"{_MOD}.resolve_github_token", return_value="fake-token"):
            result = retrigger_review_gate(
                "owner/repo",
                1,
                client=client,
                sleep=clock.sleep,
                now=clock.now,
                overall_budget=10.0,
                retry_delays=(2.0,),
            )

        assert result["status"] == "re-triggered"
        assert client.list_call_timeouts == [pytest.approx(8.0), pytest.approx(6.0)]
        assert client.list_call_timeouts[0] > client.list_call_timeouts[1]
        assert clock.now() <= 10.0

    def test_in_flight_retrying_still_cannot_cross_the_deadline(self) -> None:
        """TMG gap: an in-flight run is retryable as of this change, so it
        now drives the retry loop. Waiting for it must remain bounded by the
        SAME overall ceiling -- a run that never completes exhausts the
        budget and abstains, it does not extend it.
        """
        clock = _SimClock()
        client = _SimTimingClient(
            clock,
            head_sha_duration=0.5,
            list_duration=0.5,
            list_results=[[_run(50, pr_number=7, status="in_progress")]],
        )

        with patch(f"{_MOD}.resolve_github_token", return_value="fake-token"):
            result = retrigger_review_gate(
                "owner/repo",
                7,
                client=client,
                sleep=clock.sleep,
                now=clock.now,
                overall_budget=10.0,
                retry_delays=(4.0, 4.0, 4.0),
            )

        assert clock.now() <= 10.0, "total simulated elapsed time exceeded the budget"
        assert result["status"] == "skipped"
        # It really did wait across more than the first attempt...
        assert len(client.list_call_timeouts) > 1
        # ...and stopped because the budget ran out, without ever attempting
        # a rerun call GitHub would reject.
        assert client.rerun_calls == []

    def test_completes_normally_well_within_budget(self) -> None:
        """A generous budget against fast simulated calls must not perturb
        the happy path or come anywhere near the ceiling.
        """
        clock = _SimClock()
        client = _SimTimingClient(clock, list_results=[[_run(1, pr_number=1, status="completed")]])

        with patch(f"{_MOD}.resolve_github_token", return_value="fake-token"):
            result = retrigger_review_gate(
                "owner/repo",
                1,
                client=client,
                sleep=clock.sleep,
                now=clock.now,
                overall_budget=25.0,
            )

        assert result["status"] == "re-triggered"
        assert result["run_id"] == 1
        assert clock.now() < 1.0
        assert clock.now() <= 25.0


@pytest.mark.unit
class TestPageSizeBound:
    """The run listing is taken from the repo-wide (unscoped) runs endpoint
    at one head SHA, with an explicit, tested page bound. Because that page
    is now shared with every other workflow that fired at the same commit,
    truncation must be NAMED in the abstain reason rather than silently
    reported as "not found".
    """

    def test_truncated_listing_is_named_in_the_abstain_reason(self) -> None:
        """A full page of other workflows' runs can, in principle, push the
        gate's own run off the single bounded page. That degrades to an
        abstain (never a wrong rerun), but the reason must say the page was
        full so an operator can tell truncation from a genuine absence.
        """
        crowd = [
            _run(i, pr_number=999, path=".github/workflows/ci.yml", workflow_id=987654)
            for i in range(100)
        ]
        client = _FakeClient(runs_sequence=[crowd])
        with patch(f"{_MOD}.resolve_github_token", return_value="fake-token"):
            result = retrigger_review_gate(
                "owner/repo", 7, client=client, sleep=lambda _: None, retry_delays=()
            )

        assert result["status"] == "skipped"
        assert "100" in result["reason"]
        assert "truncat" in result["reason"].lower()
        assert client.rerun_calls == []

    def test_untruncated_listing_does_not_claim_truncation(self) -> None:
        """The truncation note must be conditional on a FULL page, not
        appended to every not-found abstain.
        """
        client = _FakeClient(runs_sequence=[[]])
        with patch(f"{_MOD}.resolve_github_token", return_value="fake-token"):
            result = retrigger_review_gate(
                "owner/repo", 7, client=client, sleep=lambda _: None, retry_delays=()
            )

        assert result["status"] == "skipped"
        assert "truncat" not in result["reason"].lower()

    def test_default_client_requests_the_documented_max_page_size(self) -> None:
        with (
            patch(f"{_MOD}.resolve_github_token", return_value="fake-token"),
            patch(f"{_MOD}.subprocess.run") as mock_run,
        ):
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = "HTTP/2 200 OK\n\n" '{"head": {"sha": "abc123"}}'
            mock_run.return_value.stderr = ""

            retrigger_review_gate("owner/repo", 1, sleep=lambda _: None)

        # Second call is the runs listing (first is the PR head-SHA lookup).
        list_call_args = mock_run.call_args_list[1].args[0]
        joined = " ".join(list_call_args)
        assert "repos/owner/repo/actions/runs" in joined
        # The workflow-SCOPED endpoint resolves the filename against the
        # consuming repo's own workflow entry, which is the wrong one in a
        # ruleset-wired repo -- it must not be used.
        assert f"actions/workflows/{WORKFLOW_FILE}" not in joined
        assert "per_page=100" in joined
        assert "head_sha=abc123" in joined


@pytest.mark.unit
class TestDefaultClientIsGhCli:
    def test_default_client_used_when_none_injected(self) -> None:
        """Without an injected client, the module must fall back to a real
        gh-CLI-backed client rather than silently no-op'ing. Finding 7: this
        must discriminate on the OBSERVED failure signal (HTTP 500), not
        just on "some skip happened" -- a client that crashed locally
        before issuing any request would also produce status == "skipped"
        and previously passed this test.
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
        assert "500" in result["reason"]

    def test_default_client_surfaces_subprocess_not_found(self) -> None:
        """Finding 10: FileNotFoundError (gh CLI missing) is a distinct
        `_GhCliClient` edge case from a timeout or a non-2xx response.
        """
        with (
            patch(f"{_MOD}.resolve_github_token", return_value="fake-token"),
            patch(f"{_MOD}.subprocess.run", side_effect=FileNotFoundError("gh")),
        ):
            result = retrigger_review_gate("owner/repo", 1, sleep=lambda _: None)

        assert result["status"] == "skipped"
        assert "could not resolve PR head SHA" in result["reason"]

    def test_default_client_surfaces_subprocess_timeout(self) -> None:
        import subprocess as sp

        with (
            patch(f"{_MOD}.resolve_github_token", return_value="fake-token"),
            patch(
                f"{_MOD}.subprocess.run",
                side_effect=sp.TimeoutExpired(cmd="gh", timeout=8),
            ),
        ):
            result = retrigger_review_gate("owner/repo", 1, sleep=lambda _: None)

        assert result["status"] == "skipped"
        assert "timed out" in result["reason"]

    def test_default_client_nonzero_returncode_with_stderr_and_no_stdout(self) -> None:
        with (
            patch(f"{_MOD}.resolve_github_token", return_value="fake-token"),
            patch(f"{_MOD}.subprocess.run") as mock_run,
        ):
            mock_run.return_value.returncode = 1
            mock_run.return_value.stdout = ""
            mock_run.return_value.stderr = "authentication required"

            result = retrigger_review_gate("owner/repo", 1, sleep=lambda _: None)

        assert result["status"] == "skipped"
        assert "authentication required" in result["reason"]
