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
(.hestai/decisions/, RATIFIED), which inherits, not asserts, the abstain
policy below. The run LISTING endpoint used below is read-only -- it does
not authorise workflow_dispatch. Rework #5 widened no API surface: it
changes WHICH read the module makes and HOW LONG it is willing to wait,
nothing more.

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
    matching the PR, SKIPPING OVER any newer matching run that is still
    queued/in_progress in favour of an older completed one -- re-running a
    completed run re-reads the comments live, so an older one serves. When
    NONE of the matching runs are completed, this module never attempts --
    and fails -- a rerun call; what it does instead is amended by rework
    #5 below (it waits, rather than abstaining immediately).

Selection & robustness (rework #2, all-four-reviewers CONDITIONAL triage):
  * Finding 3: a run with unverifiable ``pull_requests`` metadata no longer
    suppresses retry when no PR-matching run was found -- retrying may
    still surface a verifiable match on a later listing (the read-after-
    write race this loop exists to win). "Unverifiable" only becomes the
    terminal reason once the retry budget is spent, exactly like the plain
    "not found yet" case.
  * Finding 4 (SUPERSEDED by rework #5): run listing was moved off the
    mutable display name onto the workflow's stable FILE name, via the
    workflow-scoped Actions endpoint (``.../actions/workflows/{file}/runs``).
    Rename-resistance was the right goal; that endpoint was the wrong
    instrument -- see rework #5.
  * Finding 5: the ruleset's required-workflow feature enforces
    ``pull_request``, ``pull_request_target`` AND ``merge_group`` --
    selection accepts runs from any of the three rather than hardcoding
    one, matching what this module's own docstring already promised.
  * Finding 2: an overall time budget (``DEFAULT_OVERALL_BUDGET_SECONDS``)
    now bounds the whole operation, checked BETWEEN steps via an
    injectable clock, with a reduced per-call timeout.

Run location (rework #5): the module abstained "no completed run found"
on EVERY ruleset-wired consuming repo. Two independent causes, one seam.

  * Wrong workflow. The workflow-SCOPED endpoint from finding 4 resolves
    ``review-gate.yml`` against the CONSUMING repo's own workflow entry.
    A ruleset-wired repo has two entries named "Review Gate" at that same
    path: its own caller file, and the ruleset-INJECTED required workflow
    that actually runs. Verified on elevanaltd/elevana-studio PR #1945,
    head 500ce6f8: the scoped listing returned ``total_count=0`` while the
    unscoped one returned run 34159096298 (workflow id 299891129,
    ``event=pull_request``, completed) -- an id absent from that repo's own
    ``actions/workflows`` listing, so no amount of filename resolution can
    reach it. The fix keeps finding 4's rename-resistance and drops only
    its instrument: list runs UNSCOPED at the head SHA and identify the
    gate's runs by the ``path`` each run REPORTS (``WORKFLOW_PATH``).
    A path is as stable as a filename under a display-name rename, and
    strictly more precise. Narrowing then sits in ``_select_run`` beside
    the event and PR-association filters that were always client-side.
    Cost: one page now shared with every workflow at that commit -- see
    ``_MAX_PAGE_SIZE``, where that is bounded and made non-silent.
  * Wrong terminal answer. A matched but not-yet-completed run was treated
    as definitive on the reasoning that it "will evaluate on its own once
    it finishes". False in exactly the case this module exists for: that
    run was fired by an earlier push and PREDATES the verdict comment, so
    self-evaluation reproduces the same red. (Observed: elevana-studio
    #1930 posted its verdict 6s after the gate's status comment -- the run
    was almost certainly still in flight.) The in-flight case is therefore
    RETRYABLE: the existing bounded retry loop waits for completion and
    then re-runs it, and a run that never completes within the budget
    still abstains with a reason naming its state. No budget was raised;
    the ceiling below is untouched.

Budget enforcement (rework #4, CE + coordinator): the rework #2 budget
check was NOT actually a ceiling -- it was checked BEFORE sleeping (never
after, so a retry delay could itself consume the remaining budget and
still be followed by a full-length API call) and no call's DURATION was
ever bounded by the remaining budget (a call starting a moment before the
deadline still ran its full timeout). Both holes are closed the same way:
every time-consuming operation (sleep OR API call) is preceded by a FRESH
remaining-budget read, and both the sleep duration and the call's timeout
are capped by whatever remains -- so no single step, and therefore no
sequence of steps, can push total elapsed time past ``overall_budget``.
When remaining budget drops below ``_MIN_USEFUL_CALL_SECONDS``, this module
abstains rather than issue a call with no realistic chance to complete.
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
# Used for human-readable abstain reasons; run IDENTIFICATION goes through
# WORKFLOW_PATH below.
WORKFLOW_FILE = "review-gate.yml"

# The gate workflow's path, exactly as GitHub reports it in the ``path``
# field of every workflow-run object -- including runs of a ruleset-INJECTED
# required workflow, whose workflow id does not exist in the consuming repo's
# own ``actions/workflows`` listing (rework #5, see module docstring). This
# is what identifies the gate's runs, because it is reported BY the run
# rather than resolved FROM a filename by the consuming repo.
WORKFLOW_PATH = f".github/workflows/{WORKFLOW_FILE}"

# The full set of events GitHub's ruleset required-workflow feature
# actually enforces against (rework #2 finding 5) -- only runs attached to
# one of these carry the required check bound to the PR's head SHA. The
# List Workflow Runs API's own ``event`` query parameter accepts only a
# single value, so filtering across all three happens client-side in
# _select_run() against a single head-SHA-scoped listing, rather than
# issuing one API call per event (which would also worsen the latency
# budget below).
_REQUIRED_EVENTS = frozenset({"pull_request", "pull_request_target", "merge_group"})

# The only run status the rerun endpoint accepts (a non-completed run 422s).
_COMPLETED_STATUS = "completed"

# GitHub's maximum page size, and the ONLY page this module ever fetches.
#
# Rework #5 changes what shares it: the listing is now repo-wide at one head
# SHA, so this single page holds every workflow's runs at that commit (CI,
# deploy previews, bots, ...), not just the gate's. Truncation is therefore
# conceivable where the workflow-scoped listing made it vanishingly unlikely.
# It is handled deliberately rather than silently, on three grounds:
#
#   1. Consequence is bounded. Runs come back newest-first, and the gate run
#      for a just-pushed head SHA is among the newest. If it were ever pushed
#      off the page, selection finds nothing and this module ABSTAINS -- the
#      failure mode is a missed re-trigger, never a wrong run re-run and never
#      a fabricated gate outcome (see the failure policy above).
#   2. It is not silent. A full page with no gate run found says so in the
#      abstain reason (_select_run), so "truncated" is distinguishable from
#      "genuinely absent" without reading code.
#   3. Paginating instead would spend the overall time budget (one extra
#      round-trip per page) on a case that requires 100+ runs at a SINGLE
#      commit -- and would still need a bound. If real repos are ever
#      observed hitting this, the honest fix is a narrower server-side
#      filter, not deeper paging; that is a scope decision, not a diff.
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
# definitive answer) AND, as of rework #5, to a matched run that is not yet
# COMPLETED: that run predates the verdict comment, so waiting for it to
# finish and then re-running it is the point -- see the module docstring.
DEFAULT_RETRY_DELAYS: tuple[float, ...] = (1.0, 2.0, 4.0)

# Maximum timeout offered to any single Actions API call. The ACTUAL
# per-call timeout passed to the client is ``min(_GH_API_TIMEOUT_SECONDS,
# <remaining budget>)`` (rework #4) -- this constant is only the ceiling
# used when plenty of budget remains.
_GH_API_TIMEOUT_SECONDS = 8.0

# Overall wall-clock budget for the ENTIRE re-trigger operation. 25s keeps
# the worst case comfortably under typical stdio/tool-call ceilings, while
# still giving a head lookup + a few retry attempts + a rerun call room to
# complete under normal conditions. Rework #4 makes this an ACTUAL ceiling
# (see module docstring) rather than a check that could still be exceeded
# by an in-flight sleep or call.
DEFAULT_OVERALL_BUDGET_SECONDS = 25.0

# Below this much remaining budget, neither a retry sleep nor an API call
# is attempted -- there is no realistic chance either completes usefully,
# so this module abstains instead of spending the last of the budget on an
# attempt with essentially no chance of succeeding. 1s is generous relative
# to a local subprocess invocation's own overhead while still leaving
# meaningful room for the call itself.
_MIN_USEFUL_CALL_SECONDS = 1.0


class GhApiError(Exception):
    """Internal signal for any Actions-API failure (network, auth, HTTP, parse).

    Never escapes this module -- ``retrigger_review_gate`` catches it (and,
    defensively, any other exception) and converts it to an abstain result.
    """


class ReviewGateClient(Protocol):
    """The three Actions-API operations this module needs, as a Protocol so
    tests can inject a deterministic fake instead of hitting a real gh CLI.

    Every method takes ``timeout`` as a required keyword argument (rework
    #4): the caller (``retrigger_review_gate``) computes it fresh, bounded
    by remaining budget, immediately before each call -- there is no
    client-side default to fall back on, so a call can never silently run
    longer than the budget allows for it.
    """

    def get_pr_head_sha(self, repo: str, pr_number: int, *, timeout: float) -> str: ...

    def list_workflow_runs_for_head_sha(
        self, repo: str, head_sha: str, *, timeout: float
    ) -> list[dict[str, Any]]: ...

    def rerun_workflow_run(self, repo: str, run_id: int, *, timeout: float) -> None: ...


class _GhCliClient:
    """Default ``ReviewGateClient`` backed by the ``gh`` CLI subprocess.

    Stateless: every call site supplies its own ``timeout`` (see
    ``ReviewGateClient``), so there is no instance-level default to drift
    out of sync with the caller's actual remaining budget.
    """

    def _api(self, path: str, *, method: str | None = None, timeout: float) -> tuple[int, str]:
        args = ["gh", "api", "--include"]
        if method:
            args += ["-X", method]
        args.append(path)
        try:
            result = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=timeout,
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

    def get_pr_head_sha(self, repo: str, pr_number: int, *, timeout: float) -> str:
        status, body = self._api(f"repos/{repo}/pulls/{pr_number}", timeout=timeout)
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
        self, repo: str, head_sha: str, *, timeout: float
    ) -> list[dict[str, Any]]:
        """List ALL of the repo's workflow runs at ``head_sha``, newest
        first (GitHub's default list order).

        Deliberately the UNSCOPED runs endpoint (rework #5): the
        workflow-scoped one resolves ``review-gate.yml`` against the
        consuming repo's own workflow entry, which is the wrong entry in a
        ruleset-wired repo (module docstring). Bounded to ``_MAX_PAGE_SIZE``
        (documented, not paginated -- see that constant). No server-side
        filters are available for what matters here: the ``event``
        parameter accepts only one value, and there is no workflow-path
        filter at all.

        Returns the raw run dicts (including ``path``, ``status``,
        ``event`` and ``pull_requests``) -- ALL narrowing, workflow
        identity included, happens in ``_select_run``, so tests can inject
        deterministic run listings without a client implementation of
        their own.
        """
        path = f"repos/{repo}/actions/runs?head_sha={head_sha}&per_page={_MAX_PAGE_SIZE}"
        status, body = self._api(path, timeout=timeout)
        if not (200 <= status < 300):
            raise GhApiError(f"HTTP {status} listing workflow runs")
        try:
            data = json.loads(body)
            runs = data.get("workflow_runs", [])  # same key on both runs endpoints
        except (json.JSONDecodeError, AttributeError) as exc:
            raise GhApiError(f"malformed workflow runs response: {exc}") from exc

        return list(runs)

    def rerun_workflow_run(self, repo: str, run_id: int, *, timeout: float) -> None:
        status, _body = self._api(
            f"repos/{repo}/actions/runs/{run_id}/rerun", method="POST", timeout=timeout
        )
        if not (200 <= status < 300):
            raise GhApiError(f"HTTP {status} re-running workflow run {run_id}")


class _Selection(NamedTuple):
    """Outcome of filtering a run listing down to one PR-scoped, completed run."""

    run_id: int | None
    reason: str | None


def _select_run(runs: list[dict[str, Any]], pr_number: int) -> _Selection:
    """Pick the most recent COMPLETED, ruleset-enforced-event Review Gate
    run belonging to ``pr_number``.

    ``runs`` is assumed newest-first (GitHub's default list order) and
    pre-filtered to the right head SHA by the client -- but NOT to the
    right workflow: the listing is repo-wide, so identifying the gate's
    own runs by their reported ``path`` is this function's job, alongside
    the event and PR-association filters it already applied.
    """
    matching: list[dict[str, Any]] = []
    saw_unverifiable = False
    for run in runs:
        # Workflow identity comes from what the RUN reports, not from what
        # the consuming repo resolves a filename to (module docstring). A
        # run that reports no path cannot be identified as the gate's, so
        # it is not selectable -- excluded, never guessed at.
        if run.get("path") != WORKFLOW_PATH:
            continue
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
        # SAME retried "not found yet" bucket as a plain zero-match
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
        if len(runs) >= _MAX_PAGE_SIZE:
            # Do not let a truncated page masquerade as a genuine absence
            # (see _MAX_PAGE_SIZE): the listing is repo-wide, so a commit
            # with a great many runs could in principle push the gate's own
            # run off the single page this module fetches.
            reason += (
                f" -- NOTE: the listing came back full ({len(runs)} runs, the "
                f"{_MAX_PAGE_SIZE}-run page bound this module fetches), so the "
                "gate's run may have been truncated off the page by other "
                "workflows' runs at the same commit rather than being absent"
            )
        return _Selection(None, reason)

    for run in matching:
        if run.get("status") == _COMPLETED_STATUS:
            run_id = run.get("id")
            if isinstance(run_id, int):
                return _Selection(run_id, None)

    newest_status = matching[0].get("status", "unknown")
    return _Selection(
        None,
        (
            f"the most recent '{WORKFLOW_FILE}' run for PR #{pr_number} was "
            f"still '{newest_status}' (not completed) for the whole retry "
            "budget -- GitHub only allows re-running completed runs, and "
            "letting this one evaluate on its own is not sufficient: it was "
            "fired before the verdict comment existed, so it would reproduce "
            "the same result. Waited for it to finish, it did not in time"
        ),
    )


def _skip(reason: str, *, head_sha: str | None = None, run_id: int | None = None) -> dict[str, Any]:
    return {"status": "skipped", "reason": reason, "run_id": run_id, "head_sha": head_sha}


def _budget_reason(overall_budget: float, remaining: float, insufficient_for: str) -> str:
    """Build a distinct, diagnostic abstain reason for a budget shortfall.

    ``insufficient_for`` names the SPECIFIC step that couldn't be attempted
    (e.g. "to wait for the next retry attempt" vs "for a run-listing
    call") so an operator can tell "ran out while waiting" from "ran out
    before a call" apart at a glance, rather than seeing the same generic
    "budget exhausted" string for every shortfall (rework #4).
    """
    return (
        f"Review Gate re-trigger abandoned: the {overall_budget:.0f}s overall "
        f"budget left only {max(remaining, 0.0):.1f}s remaining, insufficient "
        f"{insufficient_for}"
    )


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
    ``time.monotonic``) used to enforce ``overall_budget`` as an ACTUAL
    ceiling on the whole operation (rework #4 -- see module docstring for
    why the rework #2 version of this check was not one): every sleep and
    every API call is preceded by a fresh remaining-budget read, and both
    the sleep duration and the call's timeout are capped by whatever
    remains, so no step -- and therefore no sequence of steps -- can push
    total elapsed time past ``overall_budget``.

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

    def _remaining(deadline: float) -> float:
        return deadline - _now()

    def _call_timeout(remaining: float) -> float:
        return min(_GH_API_TIMEOUT_SECONDS, remaining)

    # EVERYTHING that can raise lives inside this try, the very first clock
    # read included (CRS): constructing the default client and reading the
    # clock to set the deadline are themselves failure modes, and the
    # abstain policy admits no escape hatch for the ones that happen early.
    try:
        _client: ReviewGateClient = client if client is not None else _GhCliClient()
        deadline = _now() + overall_budget

        if resolve_github_token() is None:
            return _skip(
                "no GitHub token available for the Actions API "
                "(re-trigger requires actions:write; see AUTH_ERROR_MESSAGE "
                "for token resolution)"
            )

        # --- resolve the PR's real head SHA -------------------------------
        remaining = _remaining(deadline)
        if remaining < _MIN_USEFUL_CALL_SECONDS:
            return _skip(_budget_reason(overall_budget, remaining, "to resolve the PR head SHA"))
        try:
            head_sha = _client.get_pr_head_sha(repo, pr_number, timeout=_call_timeout(remaining))
        except Exception as exc:  # noqa: BLE001 -- abstain on ANY failure mode
            return _skip(f"could not resolve PR head SHA: {exc}")

        # --- locate a completed, PR-matching run, with bounded retry -----
        selection = _Selection(None, "no attempt made")
        attempt_delays: tuple[float, ...] = (0.0, *retry_delays)
        for delay in attempt_delays:
            if delay:
                remaining = _remaining(deadline)
                if remaining < _MIN_USEFUL_CALL_SECONDS:
                    selection = _Selection(
                        None,
                        _budget_reason(
                            overall_budget, remaining, "to wait for the next retry attempt"
                        ),
                    )
                    break
                # Cap the sleep itself, not just the call that follows it --
                # otherwise a real time.sleep(delay) still blocks for the
                # full nominal delay regardless of budget (rework #4 hole a).
                _sleep(min(delay, remaining))

            remaining = _remaining(deadline)
            if remaining < _MIN_USEFUL_CALL_SECONDS:
                selection = _Selection(
                    None,
                    _budget_reason(overall_budget, remaining, "for a run-listing call"),
                )
                break
            try:
                runs = _client.list_workflow_runs_for_head_sha(
                    repo, head_sha, timeout=_call_timeout(remaining)
                )
            except Exception as exc:  # noqa: BLE001
                return _skip(
                    f"Actions API error while listing workflow runs: {exc}",
                    head_sha=head_sha,
                )
            selection = _select_run(runs, pr_number)
            if selection.run_id is not None:
                break

        if selection.run_id is None:
            return _skip(selection.reason or "no matching run found", head_sha=head_sha)

        run_id = selection.run_id

        # --- re-run the located run ---------------------------------------
        remaining = _remaining(deadline)
        if remaining < _MIN_USEFUL_CALL_SECONDS:
            return _skip(
                _budget_reason(overall_budget, remaining, f"to re-run run {run_id}"),
                head_sha=head_sha,
                run_id=run_id,
            )
        try:
            _client.rerun_workflow_run(repo, run_id, timeout=_call_timeout(remaining))
        except Exception as exc:  # noqa: BLE001
            return _skip(
                f"Actions API error while re-running run {run_id}: {exc}",
                head_sha=head_sha,
                run_id=run_id,
            )

        return {"status": "re-triggered", "reason": None, "run_id": run_id, "head_sha": head_sha}
    except Exception as exc:  # noqa: BLE001 -- absolute last resort; must never raise
        return _skip(f"unexpected error during Review Gate re-trigger: {exc}")
