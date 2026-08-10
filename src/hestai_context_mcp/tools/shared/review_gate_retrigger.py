"""Review Gate re-trigger helper (issue #145).

``submit_review`` posts a verdict comment, but the org-wide required-status
Review Gate (ruleset 12626210 -> ``.github/workflows/review-gate.yml``) is
enforced ONLY on ``pull_request`` / ``pull_request_target`` / ``merge_group``
events -- GitHub's ruleset required-workflow feature silently drops the
``issue_comment`` / ``pull_request_review`` triggers declared in that
workflow. So a verdict comment posted between pushes never causes the
required check to re-evaluate, and a valid approval reads as a missing
review until the next push.

This module closes that gap by re-running the most recent ``pull_request``-
attached, COMPLETED Review Gate workflow run for the given PR's HEAD SHA
after a verdict has been posted. The re-run re-reads PR comments live and
updates the required check bound to the head commit.

Scope guard: this module has authority to re-run an EXISTING workflow run
ONLY. It must never merge, approve, dispatch arbitrary workflows, or touch
rulesets/branch protection. Binding: HO-SUBMIT-REVIEW-GATE-RETRIGGER-20260810
(.hestai/decisions/), which inherits, not asserts, the abstain policy below.

Failure policy (HO-AGR-SEMANTIC-REVIEWER-ABSTAIN-ON-FAILURE-20260724):
re-triggering is best-effort and strictly additive to posting the verdict
comment. ``retrigger_review_gate`` NEVER raises -- every failure mode
(missing token, PR/run lookup failure, Actions API failure, or any
unexpected exception) collapses to a ``"skipped"`` result with a
human-readable ``reason``. It never reports ``"re-triggered"`` unless the
rerun API call was actually observed to succeed, and it never infers a
gate outcome (approved/cleared) that was not itself observed.

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
"""

from __future__ import annotations

import json
import subprocess
from typing import Any, NamedTuple, Protocol

from hestai_context_mcp.tools.shared.github_auth import resolve_github_token

# Workflow name as declared in review-gate.yml; GitHub's list-runs response
# surfaces this as the run's "name" field.
WORKFLOW_NAME = "Review Gate"

# The event GitHub's ruleset required-workflow feature actually enforces
# against -- see module docstring. Only runs attached to this event carry
# the required check bound to the PR's head SHA.
_REQUIRED_EVENT = "pull_request"

# The only run status the rerun endpoint accepts (a non-completed run 422s).
_COMPLETED_STATUS = "completed"

# Bounded retry delays (seconds) for the read-after-write race: the verdict
# comment was just posted, and the Actions "list runs" listing may not
# immediately reflect a very recently created run. Each entry is the delay
# BEFORE the corresponding retry attempt; the first attempt fires with no
# delay. Small and bounded by design -- this is a bolt-on, not a poller.
#
# Retries apply ONLY to the "no matching run found yet" case, which is a
# genuine listing-propagation race. A run that IS found but is not yet
# COMPLETED, or whose PR association cannot be verified, is a definitive
# answer -- retrying either would just burn the budget waiting on a run
# that will evaluate on its own, or metadata that will not appear.
DEFAULT_RETRY_DELAYS: tuple[float, ...] = (1.0, 2.0, 4.0)

_GH_API_TIMEOUT_SECONDS = 15.0


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

    def list_pull_request_runs(
        self, repo: str, workflow_name: str, head_sha: str
    ) -> list[dict[str, Any]]: ...

    def rerun_workflow_run(self, repo: str, run_id: int) -> None: ...


def _parse_http_response(raw_output: str) -> tuple[int, str]:
    """Parse ``gh api --include`` output into (status_code, body).

    Minimal, header-agnostic variant of the parser used by ``submit_review``
    -- this module only needs the status code and the JSON body, never the
    headers, so it does not carry the extra header-dict bookkeeping.
    """
    for separator in ("\r\n\r\n", "\n\n"):
        if separator in raw_output:
            header_section, body = raw_output.split(separator, 1)
            break
    else:
        return 0, raw_output

    status_line = header_section.split("\n", 1)[0].strip()
    parts = status_line.split()
    if len(parts) < 2:
        return 0, raw_output

    try:
        return int(parts[1]), body
    except ValueError:
        return 0, raw_output


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

        return _parse_http_response(result.stdout or "")

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

    def list_pull_request_runs(
        self, repo: str, workflow_name: str, head_sha: str
    ) -> list[dict[str, Any]]:
        """List ``pull_request``-attached runs at ``head_sha`` named
        ``workflow_name``, newest first (GitHub's default list order).

        Returns the raw run dicts (including ``status`` and
        ``pull_requests``) -- PR-association and status filtering happens
        in ``_select_run``, not here, so tests can inject deterministic run
        listings without a client implementation of their own.
        """
        path = (
            f"repos/{repo}/actions/runs"
            f"?head_sha={head_sha}&event={_REQUIRED_EVENT}&per_page=20"
        )
        status, body = self._api(path)
        if not (200 <= status < 300):
            raise GhApiError(f"HTTP {status} listing workflow runs")
        try:
            data = json.loads(body)
            runs = data.get("workflow_runs", [])
        except (json.JSONDecodeError, AttributeError) as exc:
            raise GhApiError(f"malformed workflow runs response: {exc}") from exc

        return [run for run in runs if run.get("name") == workflow_name]

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
    # (in-flight run, unverifiable metadata) that retrying cannot fix.
    retryable: bool


def _select_run(runs: list[dict[str, Any]], pr_number: int) -> _Selection:
    """Pick the most recent COMPLETED run belonging to ``pr_number``.

    ``runs`` is assumed newest-first (GitHub's default list order),
    pre-filtered to the right head SHA / event / workflow name.
    """
    matching: list[dict[str, Any]] = []
    saw_unverifiable = False
    for run in runs:
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
        if saw_unverifiable:
            return _Selection(
                None,
                (
                    f"could not verify PR association for PR #{pr_number}: the "
                    f"workflow run listing at this head SHA did not carry usable "
                    "pull_requests metadata (GitHub omits it for some runs, e.g. "
                    "fork-triggered) -- abstaining rather than guessing"
                ),
                False,
            )
        return _Selection(
            None,
            (
                f"no completed {_REQUIRED_EVENT}-attached '{WORKFLOW_NAME}' run found "
                f"for PR #{pr_number} at this head SHA"
            ),
            True,
        )

    for run in matching:
        if run.get("status") == _COMPLETED_STATUS:
            run_id = run.get("id")
            if isinstance(run_id, int):
                return _Selection(run_id, None, False)

    newest_status = matching[0].get("status", "unknown")
    return _Selection(
        None,
        (
            f"the most recent '{WORKFLOW_NAME}' run for PR #{pr_number} is still "
            f"'{newest_status}' (not completed) -- GitHub only allows re-running "
            "completed runs, and this run will evaluate on its own once it "
            "finishes, so re-run is skipped rather than attempted and failed"
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
    retry_delays: tuple[float, ...] = DEFAULT_RETRY_DELAYS,
) -> dict[str, Any]:
    """Best-effort re-trigger of the Review Gate for ``pr_number``'s head SHA.

    Deliberately takes NO caller-supplied SHA: the tool's optional
    ``commit_sha`` argument is reviewer-supplied and may be stale, so the
    only SHA this function ever acts on is the one it resolves itself from
    the PR via the Actions API.

    Returns a dict:
        {
            "status": "re-triggered" | "skipped",
            "reason": str | None,       # populated iff status == "skipped"
            "run_id": int | None,       # the located run, if one was found
            "head_sha": str | None,     # the resolved PR head SHA, if resolved
        }

    NEVER raises -- every failure mode (missing token, API failure, wrong-PR
    run, non-completed run, no matching run, or any unexpected exception)
    collapses to a "skipped" result with a diagnostic reason. Only reports
    "re-triggered" when the rerun API call was actually observed to succeed.
    """
    import time as _time_module

    _sleep = sleep if sleep is not None else _time_module.sleep
    _client: ReviewGateClient = client if client is not None else _GhCliClient()

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

        selection = _Selection(None, "no attempt made", True)
        attempt_delays: tuple[float, ...] = (0.0, *retry_delays)
        for delay in attempt_delays:
            if delay:
                _sleep(delay)
            try:
                runs = _client.list_pull_request_runs(repo, WORKFLOW_NAME, head_sha)
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
