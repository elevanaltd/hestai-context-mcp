"""Review Gate re-trigger helper (issue #145).

``submit_review`` posts a verdict comment, but the org-wide required-status
Review Gate (ruleset 12626210 -> ``.github/workflows/review-gate.yml``) is
enforced ONLY on ``pull_request`` / ``pull_request_target`` / ``merge_group``
events -- GitHub's ruleset required-workflow feature silently drops the
``issue_comment`` / ``pull_request_review`` triggers declared in that
workflow. So a verdict comment posted between pushes never causes the
required check to re-evaluate, and a valid approval reads as a missing
review until the next push.

This module closes that gap by re-running the most recent, COMPLETED
workflow run -- attached to one of the three enforced events -- for the
given PR's HEAD SHA after a verdict has been posted. The re-run re-reads PR
comments live and updates the required check bound to the head commit.

Scope guard: this module has authority to re-run an EXISTING workflow run
ONLY. It must never merge, approve, dispatch arbitrary workflows, or touch
rulesets/branch protection. Binding: HO-SUBMIT-REVIEW-GATE-RETRIGGER-20260810
(.hestai/decisions/), which inherits, not asserts, the abstain policy below.
The workflow-scoped LISTING endpoint used for finding 4 below is still
read-only -- it does not authorise workflow_dispatch.

Failure policy (HO-AGR-SEMANTIC-REVIEWER-ABSTAIN-ON-FAILURE-20260724):
re-triggering is best-effort and strictly additive to posting the verdict
comment. ``retrigger_review_gate`` NEVER raises -- every failure mode
(missing token, PR/run lookup failure, Actions API failure, budget
exhaustion, or any unexpected exception) collapses to a ``"skipped"``
result with a human-readable ``reason``. It never reports ``"re-triggered"``
unless the rerun API call was actually observed to succeed, and it never
infers a gate outcome (approved/cleared) that was not itself observed.

Selection (rework #1, PR #148 cubic triage):
  * A run at the right head SHA is not necessarily for the right PR --
    stacked branches, re-opened duplicates, or a branch pushed to two PRs
    can share a head commit. Selection filters each candidate run's own
    ``pull_requests`` metadata for ``pr_number`` before picking one; if
    that metadata is unusable (GitHub's documented empty-array shape when
    it cannot determine PR association, e.g. fork-triggered runs), this
    module abstains rather than guessing.
  * GitHub's rerun endpoint only accepts COMPLETED runs (a non-completed
    run 422s). Selection picks the most recent COMPLETED run among those
    matching the PR; if the newest matching run is still queued/in_progress,
    this module abstains with a reason naming that state instead of
    attempting -- and failing -- the rerun call. A run already in flight
    will evaluate on its own.

Selection & robustness (rework #2, all-four-reviewers CONDITIONAL triage):
  * Finding 3: a run with unverifiable ``pull_requests`` metadata no longer
    suppresses retry when no PR-matching run was found -- retrying may
    still surface a verifiable match on a later listing (the read-after-
    write race this loop exists to win). "Unverifiable" only becomes the
    terminal reason once the retry budget is spent, exactly like the plain
    "not found yet" case.
  * Finding 4: run listing is now scoped to the workflow's stable FILE name
    via the workflow-scoped Actions endpoint
    (``.../actions/workflows/{file}/runs``), not the mutable display name
    a "Review Gate" -> renamed-workflow migration would silently break.
    The page size is bounded and documented (``_MAX_PAGE_SIZE``) rather
    than an unbounded/undocumented truncation risk.
  * Finding 5: the ruleset's required-workflow feature enforces
    ``pull_request``, ``pull_request_target`` AND ``merge_group`` --
    selection accepts runs from any of the three rather than hardcoding
    one, matching what this module's own docstring already promised.
  * Finding 2: an overall time budget (``DEFAULT_OVERALL_BUDGET_SECONDS``)
    now bounds the whole operation, checked BETWEEN steps via an
    injectable clock, with a reduced per-call timeout -- bounding worst-
    case latency instead of letting per-call timeouts multiply unbounded
    across a head lookup, several retry attempts, and a rerun call.
"""

from __future__ import annotations

import json
import subprocess
from typing import Any, NamedTuple, Protocol

from hestai_context_mcp.tools.shared.gh_http import parse_gh_api_response
from hestai_context_mcp.tools.shared.github_auth import resolve_github_token

# Workflow FILE name (stable) as declared under .github/workflows/ -- NOT
# the display ``name:`` field inside the workflow (rework #2 finding 4: a
# rename of that display name must not silently break every consumer).
WORKFLOW_FILE = "review-gate.yml"

# The full set of events GitHub's ruleset required-workflow feature
# actually enforces against (rework #2 finding 5) -- only runs attached to
# one of these carry the required check bound to the PR's head SHA. The
# List Workflow Runs API's own ``event`` query parameter accepts only a
# single value, so filtering across all three happens client-side in
# _select_run() against a single head-SHA-scoped listing, rather than
# issuing one API call per event (which would also worsen finding 2's
# latency budget).
_REQUIRED_EVENTS = frozenset({"pull_request", "pull_request_target", "merge_group"})

# The only run status the rerun endpoint accepts (a non-completed run 422s).
_COMPLETED_STATUS = "completed"

# GitHub's maximum page size. Combined with scoping the listing to ONE
# workflow file AND one head SHA (rework #2 finding 4), more than 100 runs
# sharing all three is not a realistic scenario -- it would require over
# 100 reruns of the identical workflow at the identical commit. Documented
# bound instead of implementing multi-page fetching, which would also eat
# into the overall time budget (finding 2) for a truncation risk this
# combination of filters already makes vanishingly small.
_MAX_PAGE_SIZE = 100

# Bounded retry delays (seconds) for the read-after-write race: the verdict
# comment was just posted, and the Actions "list runs" listing may not
# immediately reflect a very recently created run. Each entry is the delay
# BEFORE the corresponding retry attempt; the first attempt fires with no
# delay. Small and bounded by design -- this is a bolt-on, not a poller.
#
# Retries apply to the "no PR-matching run found yet" case (rework #2
# finding 3: this INCLUDES runs that exist but have unverifiable PR
# metadata -- that is a genuine listing-propagation race too, not a
# definitive answer). A run that IS matched but not yet COMPLETED is a
# definitive answer -- retrying would just burn the budget waiting on a
# run that will evaluate on its own.
DEFAULT_RETRY_DELAYS: tuple[float, ...] = (1.0, 2.0, 4.0)

# Reduced from an earlier 15.0s (rework #2 finding 2: CE's arithmetic --
# up to 6 calls x 15s + 7s of retry sleeps = 97s worst case, blocking the
# MCP stdio response). 8s is still generous for a single Actions API call
# under normal conditions, while keeping the worst case (budget-respecting
# steps + at most one in-flight per-call timeout) well bounded.
_GH_API_TIMEOUT_SECONDS = 8.0

# Overall wall-clock budget for the ENTIRE re-trigger operation, checked
# BETWEEN steps (not mid-call) via an injectable clock. 25s keeps the
# worst case (25s of budget-respecting steps + at most one already-
# in-flight per-call timeout of 8s =~ 33s) comfortably under typical
# stdio/tool-call ceilings, while still giving a head lookup + a few retry
# attempts + a rerun call room to complete under normal conditions.
DEFAULT_OVERALL_BUDGET_SECONDS = 25.0


class GhApiError(Exception):
    """Internal signal for any Actions-API failure (network, auth, HTTP, parse).

    Never escapes this module -- ``retrigger_review_gate`` catches it (and,
    defensively, any other exception) and converts it to an abstain result.
    """


class ReviewGateClient(Protocol):
    """The three Actions-API operations this module needs, as a Protocol so
    tests can inject a deterministic fake instead of hitting a real gh CLI.
    """

    def get_pr_head_sha(self, repo: str, pr_number: int) -> str: ...

    def list_workflow_runs_for_head_sha(
        self, repo: str, workflow_file: str, head_sha: str
    ) -> list[dict[str, Any]]: ...

    def rerun_workflow_run(self, repo: str, run_id: int) -> None: ...


class _GhCliClient:
    """Default ``ReviewGateClient`` backed by the ``gh`` CLI subprocess."""

    def __init__(self, timeout: float = _GH_API_TIMEOUT_SECONDS) -> None:
        self._timeout = timeout

    def _api(self, path: str, *, method: str | None = None) -> tuple[int, str]:
        args = ["gh", "api", "--include"]
        if method:
            args += ["-X", method]
        args.append(path)
        try:
            result = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=self._timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise GhApiError(f"gh api call timed out: {exc}") from exc
        except Exception as exc:  # noqa: BLE001 -- any subprocess failure mode
            raise GhApiError(f"gh api call failed: {exc}") from exc

        if result.returncode != 0 and not (result.stdout or "").strip():
            raise GhApiError((result.stderr or "gh api call failed").strip())

        # Shared parser (rework #2 finding 6, CRS + CIV): single source of
        # truth also used by submit_review._post_comment(). This module has
        # no use for headers, so they are discarded here.
        status, _headers, body = parse_gh_api_response(result.stdout or "")
        return status, body

    def get_pr_head_sha(self, repo: str, pr_number: int) -> str:
        status, body = self._api(f"repos/{repo}/pulls/{pr_number}")
        if not (200 <= status < 300):
            raise GhApiError(f"HTTP {status} resolving PR head SHA")
        try:
            data = json.loads(body)
            sha = data["head"]["sha"]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise GhApiError(f"malformed PR response: {exc}") from exc
        if not sha or not isinstance(sha, str):
            raise GhApiError("PR response missing head.sha")
        return str(sha)

    def list_workflow_runs_for_head_sha(
        self, repo: str, workflow_file: str, head_sha: str
    ) -> list[dict[str, Any]]:
        """List runs of ``workflow_file`` at ``head_sha``, newest first
        (GitHub's default list order).

        Uses the workflow-SCOPED listing endpoint (rework #2 finding 4),
        keyed on the stable file name rather than the mutable display
        name, and bounded to ``_MAX_PAGE_SIZE`` (documented, not paginated
        -- see module docstring). No event filter is passed server-side
        (that endpoint's ``event`` parameter accepts only one value); event
        membership across all three ruleset-enforced events (finding 5) is
        checked client-side in ``_select_run``.

        Returns the raw run dicts (including ``status``, ``event`` and
        ``pull_requests``) -- selection happens in ``_select_run``, not
        here, so tests can inject deterministic run listings without a
        client implementation of their own.
        """
        path = (
            f"repos/{repo}/actions/workflows/{workflow_file}/runs"
            f"?head_sha={head_sha}&per_page={_MAX_PAGE_SIZE}"
        )
        status, body = self._api(path)
        if not (200 <= status < 300):
            raise GhApiError(f"HTTP {status} listing workflow runs")
        try:
            data = json.loads(body)
            runs = data.get("workflow_runs", [])
        except (json.JSONDecodeError, AttributeError) as exc:
            raise GhApiError(f"malformed workflow runs response: {exc}") from exc

        return list(runs)

    def rerun_workflow_run(self, repo: str, run_id: int) -> None:
        status, _body = self._api(f"repos/{repo}/actions/runs/{run_id}/rerun", method="POST")
        if not (200 <= status < 300):
            raise GhApiError(f"HTTP {status} re-running workflow run {run_id}")


class _Selection(NamedTuple):
    """Outcome of filtering a run listing down to one PR-scoped, completed run."""

    run_id: int | None
    reason: str | None
    # True iff the "not found" outcome could plausibly resolve on a later
    # attempt (a listing-propagation race) -- False for definitive answers
    # (in-flight run) that retrying cannot fix. Unverifiable PR metadata is
    # ALSO retryable (rework #2 finding 3) -- it is folded into the plain
    # "no match yet" case, not treated as its own definitive answer.
    retryable: bool


def _select_run(runs: list[dict[str, Any]], pr_number: int) -> _Selection:
    """Pick the most recent COMPLETED, ruleset-enforced-event run belonging
    to ``pr_number``.

    ``runs`` is assumed newest-first (GitHub's default list order),
    pre-filtered to the right head SHA and workflow file by the client.
    """
    matching: list[dict[str, Any]] = []
    saw_unverifiable = False
    for run in runs:
        if run.get("event") not in _REQUIRED_EVENTS:
            continue
        pull_requests = run.get("pull_requests")
        # GitHub returns an empty array (sometimes null) when it cannot
        # determine which PR(s) a run belongs to (e.g. fork-triggered
        # runs). Either shape means "cannot verify" -- NOT "no match".
        if not pull_requests:
            saw_unverifiable = True
            continue
        if any(isinstance(pr, dict) and pr.get("number") == pr_number for pr in pull_requests):
            matching.append(run)

    if not matching:
        # Rework #2 finding 3: unverifiable metadata is folded into the
        # SAME retryable "not found yet" bucket as a plain zero-match
        # listing -- it must not abort the retry loop on its own. Only the
        # REASON TEXT differs, so the eventual terminal message (once
        # retries are exhausted) still tells the two apart.
        reason = (
            f"could not verify PR association for PR #{pr_number}: the "
            "workflow run listing at this head SHA did not carry usable "
            "pull_requests metadata for any candidate run (GitHub omits "
            "it for some runs, e.g. fork-triggered) -- abstaining rather "
            "than guessing"
            if saw_unverifiable
            else (
                f"no completed {'/'.join(sorted(_REQUIRED_EVENTS))}-attached "
                f"'{WORKFLOW_FILE}' run found for PR #{pr_number} at this "
                "head SHA"
            )
        )
        return _Selection(None, reason, True)

    for run in matching:
        if run.get("status") == _COMPLETED_STATUS:
            run_id = run.get("id")
            if isinstance(run_id, int):
                return _Selection(run_id, None, False)

    newest_status = matching[0].get("status", "unknown")
    return _Selection(
        None,
        (
            f"the most recent '{WORKFLOW_FILE}' run for PR #{pr_number} is "
            f"still '{newest_status}' (not completed) -- GitHub only allows "
            "re-running completed runs, and this run will evaluate on its "
            "own once it finishes, so re-run is skipped rather than "
            "attempted and failed"
        ),
        False,
    )


def _skip(reason: str, *, head_sha: str | None = None, run_id: int | None = None) -> dict[str, Any]:
    return {"status": "skipped", "reason": reason, "run_id": run_id, "head_sha": head_sha}


def retrigger_review_gate(
    repo: str,
    pr_number: int,
    *,
    client: ReviewGateClient | None = None,
    sleep: Any = None,
    now: Any = None,
    retry_delays: tuple[float, ...] = DEFAULT_RETRY_DELAYS,
    overall_budget: float = DEFAULT_OVERALL_BUDGET_SECONDS,
) -> dict[str, Any]:
    """Best-effort re-trigger of the Review Gate for ``pr_number``'s head SHA.

    Deliberately takes NO caller-supplied SHA: the tool's optional
    ``commit_sha`` argument is reviewer-supplied and may be stale, so the
    only SHA this function ever acts on is the one it resolves itself from
    the PR via the Actions API.

    ``now`` is an injectable monotonic-clock callable (defaults to
    ``time.monotonic``) used to enforce ``overall_budget``: a wall-clock
    ceiling on the WHOLE operation, checked between steps (after resolving
    the head SHA, before each run-listing retry attempt, and before the
    rerun call) rather than only bounding individual API calls.

    Returns a dict:
        {
            "status": "re-triggered" | "skipped",
            "reason": str | None,       # populated iff status == "skipped"
            "run_id": int | None,       # the located run, if one was found
            "head_sha": str | None,     # the resolved PR head SHA, if resolved
        }

    NEVER raises -- every failure mode (missing token, API failure, wrong-PR
    run, non-completed run, no matching run, budget exhaustion, or any
    unexpected exception) collapses to a "skipped" result with a diagnostic
    reason. Only reports "re-triggered" when the rerun API call was
    actually observed to succeed.
    """
    import time as _time_module

    _sleep = sleep if sleep is not None else _time_module.sleep
    _now = now if now is not None else _time_module.monotonic
    _client: ReviewGateClient = client if client is not None else _GhCliClient()
    deadline = _now() + overall_budget

    def _budget_exhausted() -> bool:
        return _now() >= deadline

    try:
        if resolve_github_token() is None:
            return _skip(
                "no GitHub token available for the Actions API "
                "(re-trigger requires actions:write; see AUTH_ERROR_MESSAGE "
                "for token resolution)"
            )

        try:
            head_sha = _client.get_pr_head_sha(repo, pr_number)
        except Exception as exc:  # noqa: BLE001 -- abstain on ANY failure mode
            return _skip(f"could not resolve PR head SHA: {exc}")

        if _budget_exhausted():
            return _skip(
                f"Review Gate re-trigger abandoned: {overall_budget:.0f}s "
                "budget exhausted after resolving PR head SHA",
                head_sha=head_sha,
            )

        selection = _Selection(None, "no attempt made", True)
        attempt_delays: tuple[float, ...] = (0.0, *retry_delays)
        for delay in attempt_delays:
            if _budget_exhausted():
                selection = _Selection(
                    None,
                    (
                        f"Review Gate re-trigger abandoned: {overall_budget:.0f}s "
                        "budget exhausted while looking for a matching run"
                    ),
                    False,
                )
                break
            if delay:
                _sleep(delay)
            try:
                runs = _client.list_workflow_runs_for_head_sha(repo, WORKFLOW_FILE, head_sha)
            except Exception as exc:  # noqa: BLE001
                return _skip(
                    f"Actions API error while listing workflow runs: {exc}",
                    head_sha=head_sha,
                )
            selection = _select_run(runs, pr_number)
            if selection.run_id is not None or not selection.retryable:
                break

        if selection.run_id is None:
            return _skip(selection.reason or "no matching run found", head_sha=head_sha)

        run_id = selection.run_id

        if _budget_exhausted():
            return _skip(
                f"Review Gate re-trigger abandoned: {overall_budget:.0f}s budget "
                f"exhausted before re-running run {run_id}",
                head_sha=head_sha,
                run_id=run_id,
            )

        try:
            _client.rerun_workflow_run(repo, run_id)
        except Exception as exc:  # noqa: BLE001
            return _skip(
                f"Actions API error while re-running run {run_id}: {exc}",
                head_sha=head_sha,
                run_id=run_id,
            )

        return {"status": "re-triggered", "reason": None, "run_id": run_id, "head_sha": head_sha}
    except Exception as exc:  # noqa: BLE001 -- absolute last resort; must never raise
        return _skip(f"unexpected error during Review Gate re-trigger: {exc}")
