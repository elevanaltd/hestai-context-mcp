"""Git Orchestrator (Linker) for governance intake.

Accepts a ValidationResult + raw OCTAVE content, then:
  0. Fetches origin fresh and checks whether the TOKEN is already in flight
     (an unmerged origin/governance/* branch for its slug, any date -- issue
     #173 slice 1 / operator ruling 2026-09-21). If so, refuses: no worktree,
     no branch, no push, no PR -- see ``check_in_flight_token``.
  1. Creates a DEDICATED git worktree on a fresh ``governance/{date}-{token-slug}``
     branch based off ``origin/main`` (after a second, redundant ``git fetch
     origin`` internal to ``_create_worktree`` -- left as-is; cheap/idempotent)
  2. Writes OCTAVE content to the computed target_path INSIDE that worktree
  3. Commits with: chore(governance): add {token} [{card_type}]
  4. Updates MANIFEST (write_manifest)
  5. Pushes the branch to origin (git push --no-verify -u origin <branch>)
  6. Opens PR via gh pr create
  7. Removes the worktree (always); rolls back the local branch if nothing was
     pushed.

The worktree is the load-bearing design choice: ALL git mutation happens inside
a throwaway worktree, so the invoking working tree's HEAD is NEVER moved. The
repo the operator is sitting in (``main`` or any feature branch) is left exactly
as it was found — the tool can never "leave" a checkout on ``governance/...``
(issue #108: the old in-place ``git checkout -b`` brute-forced the invoking
tree's branch and stranded it there). This also sidesteps the worktree-discipline
pre-commit hook entirely, since commits are always made from a real worktree.

dry_run=True: skips all git/file operations, returns what WOULD happen.

GitHub token resolution is provided by the shared single-source-of-truth helper
``tools.shared.github_auth`` (extracted to remove the CIV-flagged duplication
that previously copied this logic from submit_review). It is re-exported here as
``_resolve_github_token`` so ``run_linker`` resolves it as a module global
(patchable in tests).
"""

import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hestai_context_mcp.tools.governance.manifest import write_manifest
from hestai_context_mcp.tools.governance.type_checker import ValidationResult
from hestai_context_mcp.tools.shared.github_auth import (
    resolve_github_token as _resolve_github_token,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Branch name computation
# ---------------------------------------------------------------------------


def _token_to_slug(token: str) -> str:
    """Convert a TOKEN to a git branch slug.

    Rules:
      - Lowercase the token.
      - Replace underscores with hyphens.
      - Ensure the result is URL-safe (already guaranteed by TOKEN format).

    Args:
        token: The TOKEN or ID string (e.g. HO-CONTEXT-MCP-TEST-20260531).

    Returns:
        Slug string (e.g. ho-context-mcp-test-20260531).
    """
    return token.lower().replace("_", "-")


def _compute_branch_name(token: str) -> str:
    """Compute the branch name for a governance artifact.

    Format: governance/{date}-{token-slug}

    Args:
        token: The TOKEN or ID string.

    Returns:
        Branch name string.
    """
    date_str = datetime.now(UTC).strftime("%Y%m%d")
    slug = _token_to_slug(token)
    return f"governance/{date_str}-{slug}"


# ---------------------------------------------------------------------------
# Git operations
# ---------------------------------------------------------------------------

_GIT_TIMEOUT = 30  # seconds


def _run_git(args: list[str], cwd: Path) -> tuple[int, str, str]:
    """Run a git command and return (returncode, stdout, stderr)."""
    try:
        result = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT,
            cwd=str(cwd),
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except subprocess.TimeoutExpired:
        return 1, "", "git command timed out"
    except (FileNotFoundError, OSError) as exc:
        return 1, "", str(exc)


# The base ref every governance branch is cut from. The PR also targets ``main``
# (``_open_pr`` passes ``--base main``), so ``origin/main`` keeps the branch base
# and the PR base identical, and guarantees the worktree is cut from the current
# remote tip rather than a possibly-stale local ``main``.
_BASE_REF = "origin/main"


def _create_worktree(working_dir: Path, branch_name: str) -> tuple[Path | None, str | None]:
    """Create a throwaway git worktree on a fresh ``branch_name`` off ``origin/main``.

    ALL git mutation for a governance submission happens inside this dedicated
    worktree so the invoking working tree's HEAD is NEVER moved (issue #108: the
    old in-place ``git checkout -b`` stranded the operator's checkout on the
    ``governance/...`` branch). The worktree is created under a fresh temp dir;
    the caller is responsible for removing it via ``_remove_worktree`` (always,
    in a ``finally``).

    A ``git fetch origin`` runs first so the branch is cut from the current
    remote tip. ``git worktree add -b <branch> <path> origin/main`` then creates
    the branch and checks it out into the worktree in one step.

    Returns ``(worktree_path, None)`` on success or ``(None, error)`` on failure.
    On failure no worktree and no temp dir are left behind.
    """
    code, _, stderr = _run_git(["fetch", "origin"], working_dir)
    if code != 0:
        return None, f"git fetch origin failed: {stderr}"

    # A fresh temp parent; the worktree itself lives in a not-yet-existing subdir
    # (``git worktree add`` creates it). Cleanup removes the whole parent.
    parent = Path(tempfile.mkdtemp(prefix="hestai-governance-"))
    worktree_path = parent / "worktree"

    code, _, stderr = _run_git(
        ["worktree", "add", "-b", branch_name, str(worktree_path), _BASE_REF],
        working_dir,
    )
    if code != 0:
        shutil.rmtree(parent, ignore_errors=True)
        return None, f"Failed to create governance worktree for '{branch_name}': {stderr}"

    return worktree_path, None


def _remove_worktree(working_dir: Path, worktree_path: Path) -> None:
    """Remove the governance worktree and its temp parent dir (best-effort).

    Never raises: a cleanup failure must not mask the linker's own result. The
    branch ref created with the worktree is intentionally NOT deleted here (the
    caller decides whether to roll it back based on whether it was pushed).
    """
    _run_git(["worktree", "remove", "--force", str(worktree_path)], working_dir)
    shutil.rmtree(worktree_path.parent, ignore_errors=True)


def _delete_branch(working_dir: Path, branch_name: str) -> None:
    """Delete the local ``branch_name`` ref (best-effort rollback).

    Called only when a submission failed BEFORE the branch reached ``origin`` —
    so the half-built local branch leaves no trace. Never raises.
    """
    _run_git(["branch", "-D", branch_name], working_dir)


def _push_branch(working_dir: Path, branch_name: str) -> str | None:
    """Push the new branch to origin, setting upstream.

    Runs ``git push --no-verify -u origin <branch>``. This MUST happen before
    ``gh pr create`` -- otherwise gh aborts with "you must first push the
    current branch to a remote" (issue #73).

    ``--no-verify`` bypasses LOCAL pre-push hooks. The push originates from an
    EPHEMERAL temp worktree with a throwaway venv, not the operator's
    environment, so an operator hook that runs project quality gates
    (lint/typecheck/tests) fails there and aborts the push — the AGR authors and
    validates, but no PR is ever opened. Governance branches are doc-only (an
    ``.oct.md`` plus ``MANIFEST.md``); their real gate is CI + human PR review,
    which are unaffected by this flag. Server-side branch protection is likewise
    unaffected (``--no-verify`` is client-side only).

    Returns an error string on failure, None on success. A push failure is
    surfaced as a structured error (PROD I4) and never swallowed.
    """
    code, _, stderr = _run_git(["push", "--no-verify", "-u", "origin", branch_name], working_dir)
    if code != 0:
        return f"Failed to push branch '{branch_name}' to origin: {stderr}"
    return None


# ---------------------------------------------------------------------------
# In-flight TOKEN detection (issue #173 slice 1; operator ruling 2026-09-21,
# HO-GOVERNANCE-IN-FLIGHT-TOKEN-AMENDMENT-20260921; rework round 1 per CRS/CE/
# TMG/cubic review of PR #179)
#
# "In flight" = a governance branch for the TOKEN's slug that exists on
# origin, ANY date prefix, and is NOT merged into origin/main -- OR an open PR
# for it.
#
# ASSUMPTION -- "open PR" coverage without an independent GitHub query: the
# unmerged-origin-branch test is treated as covering "open PR" too, WITHOUT a
# per-submission GitHub API query for open PRs (that would be built, not
# documented, per the rework brief -- explicitly deferred). This holds
# because governance PRs are SAME-REPO by construction: ``_push_branch``
# always pushes to ``origin`` and ``_open_pr`` runs ``gh pr create`` from
# inside that same pushed worktree, so a governance PR's head branch is NEVER
# a fork ref -- it is always ``origin/governance/<date>-<slug>``. A GitHub PR
# requires its head branch to exist; deleting that branch auto-closes the PR.
# So "an unmerged origin/governance/*-<slug> branch exists" and "an open PR
# for this token exists" are the same fact observed from two angles, FOR THIS
# REPO'S governance flow specifically. If this assumption is ever found
# false (e.g. a future slice opens governance PRs from forks, or a branch is
# deleted without closing/merging its PR through some out-of-band path), STOP
# and escalate rather than silently trusting the ref test -- do not paper
# over it with a per-submission network call.
#
# MERGED classification (two independent, PER-CANDIDATE-BRANCH, git-only
# signals; item 5 of round 1, CORRECTED in round 2 -- see the note below): a
# MERGED-but-undeleted origin branch is excluded from in-flight status even
# though the ref still exists (origin keeps merged governance branches;
# issue #173 diagnosis point 4). A branch is "merged" iff EITHER of:
#   (1) ``merge-base --is-ancestor`` -- correct for merge-commit (--no-ff)
#       merges, but CANNOT see a squash or rebase merge (the head branch is
#       never an ancestor of main under those strategies); OR
#   (2) THAT BRANCH's OWN copy of the record at the token's target_path is
#       byte-identical to origin/main's copy -- a git BLOB-HASH comparison
#       (``git rev-parse --verify -q <ref>:<path>``): two blobs share a SHA
#       iff their content is identical, so this is strategy-independent --
#       the record's CONTENT is what actually lands on main regardless of
#       how the merge happened. No extra network call: reads the
#       already-fetched local remote-tracking refs.
# A branch is excluded if EITHER signal, evaluated for THAT branch, says
# merged.
#
# ROUND-2 CORRECTION (cubic review 5265518720, reproduced by the coordinator
# at af01c13d): the round-1 implementation evaluated signal (2) ONCE, for the
# whole TOKEN -- "does ANY copy of the record exist anywhere on
# origin/main?" -- and if so, short-circuited every candidate branch to
# "nothing in flight." That does not match the docstring's own rule above
# (which is stated per BRANCH) and is wrong whenever TWO different branches
# exist for the same token's slug: if branch A was squash-merged (so its
# content now matches main) but branch B is a LATER, genuinely unmerged
# branch with DIFFERENT (diverged) content, the token-wide short-circuit
# wrongly cleared B too. Signal (2) is now evaluated independently for EACH
# candidate branch via ``_branch_record_matches_origin_main`` -- only a
# branch whose OWN content matches main is excluded by this signal; a
# sibling branch with different content is unaffected.
#
# POST-MERGE RE-FILING IS UNCHANGED BY THIS SLICE: what happens when the SAME
# token is re-submitted AFTER its record already landed on origin/main is
# governed ENTIRELY by Check 6 (``type_checker._validate_impl`` ->
# ``lexer.lookup_token_deterministic``), which rejects a re-file ONLY if the
# record is visible in the CALLER's OWN local ``working_dir`` tree
# (MANIFEST.md, then a filesystem walk of ``.hestai/decisions/`` and
# ``.hestai/context/concepts/``) -- it does NOT consult origin/main. If the
# caller's local checkout is stale (has not pulled the commit that merged the
# token), Check 6 will not see it, and THIS in-flight check does not fill
# that gap either: the ``origin/main`` cat-file signal above only EXCLUDES an
# already-landed branch from being misreported "in flight" -- it is not a
# new duplicate-rejection path, and it never touches Check 6. A
# stale-checkout-safe re-file rejection, or an amendment path for an
# already-merged token, is explicitly deferred to a later slice (routing an
# amendment to "the agent that instigated it" is the still-unresolved
# question the original brief scoped out of slice 1). This slice only
# prevents duplicate BRANCHES/PRs for a token that has NOT yet merged.
#
# Fetch-before-check (not after): the OLD flow ran Check 6 (local-only
# lookup_token_deterministic) before ``_create_worktree``'s fetch, so a
# same-day or later-day in-flight branch was invisible until AFTER validation
# already passed. ``check_in_flight_token`` fetches fresh remote state itself
# and is called from ``run_linker`` BEFORE any worktree/branch/push, closing
# that ordering gap.
#
# TRI-STATE ``in_flight`` (rework round 1 addendum A): a fetch or
# ref-enumeration failure means detection COULD NOT RUN -- a different fact
# from "detection ran and found nothing." Collapsing both to
# ``in_flight: False`` would let a caller read an undetermined result as a
# measured "safe to proceed" (the exact CRS/CE fail-open finding). So
# ``in_flight`` is ``bool | None`` EVERYWHERE this module and its callers
# surface it:
#   - ``None``  -- UNDETERMINED: detection did not run (``dry_run``) or could
#     not complete (fetch/ref-enumeration failure). The paired ``error``
#     string is prefixed ``IN_FLIGHT_UNDETERMINED: `` so callers can branch
#     on it without parsing the whole message.
#   - ``True``  -- DETERMINED: at least one unmerged branch was found.
#   - ``False`` -- DETERMINED: detection ran to completion and found nothing.
# ---------------------------------------------------------------------------

_GOVERNANCE_REMOTE_REF_PREFIX = "refs/remotes/origin/governance/"

# Stable prefix so callers can branch on "detection could not run" without
# parsing the full message (rework round 1 addendum A).
_IN_FLIGHT_UNDETERMINED_PREFIX = "IN_FLIGHT_UNDETERMINED: "


def _fetch_origin(working_dir: Path) -> str | None:
    """Fetch fresh remote state from origin, pruning stale remote-tracking refs.

    MUST run before any remote-branch-based in-flight check: detection must
    see refs that exist on origin RIGHT NOW, not whatever the local
    remote-tracking namespace last held from a previous fetch (or never held,
    for a branch pushed by a different session/clone).

    Returns an ``IN_FLIGHT_UNDETERMINED``-prefixed error string on failure,
    None on success.
    """
    code, _, stderr = _run_git(["fetch", "origin", "--prune"], working_dir)
    if code != 0:
        return f"{_IN_FLIGHT_UNDETERMINED_PREFIX}git fetch origin failed: {stderr}"
    return None


def _list_remote_governance_branches_for_slug(
    working_dir: Path, slug: str
) -> tuple[list[str], str | None]:
    """List origin governance branches matching ``slug``, ANY date prefix.

    Returns ``(branch_names, error)``: SHORT branch names
    (``governance/<8-digit-date>-<slug>``), not the ``origin/`` remote-tracking
    prefix. Requires a prior ``_fetch_origin`` call to see current remote
    state -- this function does not fetch.

    FAILS CLOSED (rework round 1, item 1 -- CRS/CE finding): a
    ``git for-each-ref`` failure returns a non-None, ``IN_FLIGHT_UNDETERMINED``
    -prefixed ``error``, NEVER an empty list with no error. An empty list must
    mean "asked and there were none," not "could not ask" -- collapsing those
    two cases previously let a transient ref-listing failure silently pass
    the in-flight gate and open a duplicate branch/PR.
    """
    code, out, stderr = _run_git(
        ["for-each-ref", "--format=%(refname:short)", _GOVERNANCE_REMOTE_REF_PREFIX],
        working_dir,
    )
    if code != 0:
        return [], f"{_IN_FLIGHT_UNDETERMINED_PREFIX}git for-each-ref failed: {stderr}"
    if not out:
        return [], None

    # Full-name anchored: governance/<8 digits>-<exact slug>, nothing else --
    # a longer slug that merely ENDS with this slug must not match.
    pattern = re.compile(rf"^origin/governance/\d{{8}}-{re.escape(slug)}$")
    matches = [
        line.strip().removeprefix("origin/")
        for line in out.splitlines()
        if pattern.match(line.strip())
    ]
    return sorted(matches), None


def _is_merged_into_origin_main(working_dir: Path, branch: str) -> tuple[bool, str | None]:
    """True iff ``origin/<branch>`` is an ancestor of ``origin/main`` (merged).

    Ancestor-only signal 1 of 2 (see the module-level MERGED-classification
    note): correct for merge-commit (``--no-ff``) merges, blind to squash/
    rebase merges -- ``find_in_flight_branches`` pairs this, PER BRANCH, with
    ``_branch_record_matches_origin_main`` (signal 2) so either one deciding
    "merged" is enough to exclude THAT branch.

    Returns ``(merged, error)`` -- MEASURED vs UNDETERMINED (PR #179 round 3,
    CRS 5760485688: this used to collapse "measured not-merged" and "could
    not measure at all" into a single ``False``, which let a downstream
    caller read an unmeasured result as a determined answer):
      - ``(True, None)``  -- exit 0: a genuine, MEASURED ancestor relationship.
      - ``(False, None)`` -- exit 1 with EMPTY stderr: a genuine, MEASURED
        "not an ancestor" (``git merge-base --is-ancestor`` prints nothing on
        this exact outcome).
      - ``(False, error)`` -- anything else, error UNDETERMINED-prefixed:
        any exit code other than 0/1 (a real git failure, e.g. an invalid
        ref), OR exit 1 WITH NON-EMPTY stderr. The latter case exists
        specifically because ``_run_git`` reports a subprocess timeout (or a
        missing git binary / OSError) as ``(1, "", "git command timed
        out")`` -- THE SAME EXIT CODE as a genuine "not an ancestor" result,
        but with a non-empty stderr message. A masked timeout must not
        masquerade as a measured miss; stderr presence is what tells the two
        apart, since a clean "not an ancestor" run is always silent.
    """
    code, _, stderr = _run_git(
        ["merge-base", "--is-ancestor", f"origin/{branch}", "origin/main"],
        working_dir,
    )
    if code == 0:
        return True, None
    if code == 1 and not stderr:
        return False, None
    return (
        False,
        f"{_IN_FLIGHT_UNDETERMINED_PREFIX}"
        f"git merge-base --is-ancestor origin/{branch} origin/main "
        f"failed: {stderr or f'unexpected exit code {code}'}",
    )


def _blob_sha_at(working_dir: Path, ref_and_path: str) -> tuple[str | None, str | None]:
    """Resolve the git blob SHA for ``<ref>:<path>`` (e.g.
    ``origin/main:.hestai/decisions/TOKEN.oct.md``) via
    ``git rev-parse --verify -q``.

    Returns ``(sha, error)``:
      - ``(sha, None)`` -- the path exists at that ref; ``sha`` is its blob
        hash (git hashes CONTENT, so two paths with the same sha have
        byte-identical content).
      - ``(None, None)`` -- the path (or the ref itself) does NOT exist
        there. ``--verify -q`` SUPPRESSES the "fatal: ... does not exist"
        message for exactly this case, so it resolves with an EMPTY stderr --
        that is how this is told apart from a genuine failure below. This is
        a normal, MEASURED outcome, not a failure.
      - ``(None, error)`` -- ``git rev-parse`` itself failed unexpectedly
        (corrupted repo, git binary missing, timeout, ...); because ``-q``
        suppresses the routine "does not exist" message, any STDERR that
        still comes back here is a real failure, not a routine miss.
        ``error`` is ``IN_FLIGHT_UNDETERMINED``-prefixed, consistent with
        every other detection-could-not-run path in this module.
    """
    code, out, stderr = _run_git(["rev-parse", "--verify", "-q", ref_and_path], working_dir)
    if code == 0:
        return out.strip(), None
    if stderr:
        return (
            None,
            f"{_IN_FLIGHT_UNDETERMINED_PREFIX}"
            f"git rev-parse --verify {ref_and_path} failed: {stderr}",
        )
    return None, None


def _verify_ref_resolves(working_dir: Path, ref: str) -> str | None:
    """Verify ``ref`` resolves to a commit object (``git rev-parse --verify
    -q <ref>^{commit}``).

    PR #179 round 3, item 2 (CRS 5760485688): ``_blob_sha_at``'s own
    ``rev-parse --verify -q <ref>:<path>`` exits 1 with EMPTY stderr for
    BOTH a missing PATH at an existing ref AND a MISSING REF -- the two are
    indistinguishable from that call alone. A missing ref (``origin/main``
    itself, or a candidate branch's own remote-tracking ref) is NOT a
    routine "no file here" miss the way a missing path is: it signals
    something is seriously wrong (a race with a prune, a corrupted
    remote-tracking namespace, ...), so it must fail closed rather than be
    silently read as "path absent, no match, not merged."

    Returns ``None`` when ``ref`` resolves; an ``IN_FLIGHT_UNDETERMINED``
    -prefixed error string when it does not (or the check itself fails).
    """
    code, _, stderr = _run_git(["rev-parse", "--verify", "-q", f"{ref}^{{commit}}"], working_dir)
    if code == 0:
        return None
    detail = f": {stderr}" if stderr else ""
    return f"{_IN_FLIGHT_UNDETERMINED_PREFIX}ref '{ref}' does not resolve to a commit{detail}"


def _branch_record_matches_origin_main(
    working_dir: Path, branch: str, target_path: str | None
) -> tuple[bool, str | None]:
    """True iff ``origin/<branch>``'s OWN copy of ``target_path`` is
    byte-identical to ``origin/main``'s copy -- a blob-hash comparison (see
    ``_blob_sha_at``).

    Strategy-independent merged signal 2 of 2, evaluated PER BRANCH (rework
    round 1 item 5, CORRECTED in round 2 -- see the module-level
    ROUND-2 CORRECTION note: this must never be evaluated token-wide). A
    squash or rebase merge never leaves the governance branch as an ancestor
    of ``origin/main``, so ``_is_merged_into_origin_main`` alone
    misclassifies a squash/rebase-merged-but-undeleted branch as permanently
    in flight. Checking whether THIS branch's OWN record content already
    matches what's on ``origin/main`` is independent of merge strategy: if it
    does, this branch's purpose has been fulfilled regardless of how.

    Returns ``(matches, error)``. ``matches`` is ``False`` (not merged via
    THIS signal -- the ancestor test in ``_is_merged_into_origin_main`` still
    applies independently) in every case where identity legitimately could
    NOT be established, none of which is a failure -- these are all
    MEASURED outcomes, not errors:
      (a) the branch's ref resolves fine but has no FILE at ``target_path``,
      (b) ``origin/main``'s ref resolves fine but has no FILE at
          ``target_path``,
      (c) ``target_path`` is ``None`` (nothing to compare).
    ``error`` (``IN_FLIGHT_UNDETERMINED``-prefixed) is set when EITHER the
    branch's OWN ref or ``origin/main`` does not resolve to a commit at all
    (round 3, item 2 -- see ``_verify_ref_resolves``; this is checked BEFORE
    any path lookup, so a missing ref is never misread as case (a)/(b)), or
    when ``git rev-parse`` itself failed unexpectedly while resolving a blob
    -- see ``_blob_sha_at``. No extra network call: reads the already-fetched
    local remote-tracking refs.
    """
    if not target_path:
        return False, None  # (c)

    branch_ref = f"origin/{branch}"
    branch_ref_err = _verify_ref_resolves(working_dir, branch_ref)
    if branch_ref_err:
        return False, branch_ref_err
    main_ref_err = _verify_ref_resolves(working_dir, "origin/main")
    if main_ref_err:
        return False, main_ref_err

    branch_sha, branch_err = _blob_sha_at(working_dir, f"{branch_ref}:{target_path}")
    if branch_err:
        return False, branch_err
    if branch_sha is None:
        return False, None  # (a)

    main_sha, main_err = _blob_sha_at(working_dir, f"origin/main:{target_path}")
    if main_err:
        return False, main_err
    if main_sha is None:
        return False, None  # (b)

    return branch_sha == main_sha, None


def find_in_flight_branches(
    working_dir: Path, token: str, target_path: str | None = None
) -> tuple[list[str], str | None]:
    """Fetch fresh remote state, then find UNMERGED origin governance branches
    for ``token``'s slug (any date prefix -- covers both the same-day push
    collision and the later-day second-PR case, issue #173).

    ``target_path`` is the TOKEN's own canonical record path (repo-relative),
    used ONLY for the strategy-independent merged signal -- see
    ``_branch_record_matches_origin_main``, evaluated PER CANDIDATE BRANCH
    (round 2 correction: NEVER as a token-wide short-circuit).

    ``target_path=None`` POLICY (round 3, item 3 -- CRS 5760485688; chosen
    over the alternative of returning undetermined per-candidate): rejected
    at the boundary, ONCE, but ONLY when there is at least one candidate
    branch to evaluate -- mirroring ``run_linker``'s own precedent of
    rejecting a missing required input before it can silently degrade
    downstream logic, rather than letting each candidate discover the gap
    independently. Without ``target_path`` the content-match signal can
    never run for ANY candidate, so a squash/rebase-merged branch could
    never be ruled out -- returning a "determined" branch list built on an
    incomplete signal set would repeat exactly the CRS/CE finding this round
    fixes for items 1 and 2, just at the boundary instead of inside a single
    signal. This is scoped to fire ONLY when ``candidates`` is non-empty: a
    ZERO-candidate result is a fully MEASURED "nothing in flight" (reached
    via ref-enumeration alone) regardless of ``target_path`` -- there is
    nothing the missing content-match signal COULD have changed, so treating
    that case as undetermined would be needless over-caution, not integrity.

    Returns ``(branch_names, error)``. FAILS CLOSED (item 1): ``error`` is
    non-None, prefixed ``IN_FLIGHT_UNDETERMINED: ``, whenever detection could
    NOT run to completion (fetch failure, ref-enumeration failure, a missing
    ``target_path`` with candidates present, OR a genuine git failure while
    checking a branch's merged status); in that case ``branch_names`` is
    always ``[]`` and the caller MUST NOT read that empty list as "nothing
    in flight" -- pair it with the error, or (as ``check_in_flight_token``
    does) surface ``in_flight: None``.
    """
    fetch_err = _fetch_origin(working_dir)
    if fetch_err:
        return [], fetch_err

    slug = _token_to_slug(token)
    candidates, list_err = _list_remote_governance_branches_for_slug(working_dir, slug)
    if list_err:
        return [], list_err

    if candidates and not target_path:
        return [], (
            f"{_IN_FLIGHT_UNDETERMINED_PREFIX}target_path is required to evaluate "
            f"{len(candidates)} candidate branch(es) for merged status (the "
            "content-match signal cannot run without it, so a squash/rebase-"
            "merged branch could not be ruled out)"
        )

    in_flight: list[str] = []
    for branch in candidates:
        merged, merge_err = _is_merged_into_origin_main(working_dir, branch)
        if merge_err:
            return [], merge_err
        if merged:
            continue

        matches, match_err = _branch_record_matches_origin_main(working_dir, branch, target_path)
        if match_err:
            return [], match_err
        if matches:
            continue

        in_flight.append(branch)

    return sorted(in_flight), None


def _resolve_open_pr_urls(
    working_dir: Path, branches: list[str], gh_token: str | None
) -> tuple[dict[str, str], str | None]:
    """Best-effort: resolve open-PR URLs for ``branches``.

    ONE ``gh pr list --state open --head <branch>`` call PER branch (rework
    round 1, item 6 -- CRS/CE/cubic finding): there are normally 0 or 1 open
    PRs per branch, and a per-branch lookup cannot silently truncate the way
    a single shared ``gh pr list --limit N`` can on a repo with many open
    PRs (a branch past the cutoff would get no URL, indistinguishable from
    "no PR exists").

    Returns ``(urls, pr_lookup_error)``. ``urls`` maps branch -> PR URL for
    every branch a PR was found for. Detection (``in_flight`` /
    ``in_flight_branches``) is NEVER blocked by a gh failure here -- only URL
    enrichment is (fail-soft, matches ``check_in_flight_token``'s contract).
    ``pr_lookup_error`` is None iff every lookup that ran succeeded;
    otherwise it NAMES the branch(es) that failed and why, so the degrade is
    surfaced in the structured result rather than silently indistinguishable
    from "no open PR exists" (CRS/CE/cubic finding: failures must not be
    swallowed).
    """
    if not branches:
        return {}, None

    env = dict(os.environ)
    if gh_token:
        env["GH_TOKEN"] = gh_token

    urls: dict[str, str] = {}
    failures: list[str] = []
    for branch in branches:
        try:
            result = subprocess.run(
                [
                    "gh",
                    "pr",
                    "list",
                    "--state",
                    "open",
                    "--head",
                    branch,
                    "--json",
                    "url",
                    "--limit",
                    "1",
                ],
                capture_output=True,
                text=True,
                timeout=30,
                cwd=str(working_dir),
                env=env,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
            failures.append(f"{branch}: {exc}")
            continue

        if result.returncode != 0:
            failures.append(f"{branch}: gh pr list failed: {result.stderr.strip()}")
            continue

        try:
            records = json.loads(result.stdout)
        except (json.JSONDecodeError, TypeError):
            failures.append(f"{branch}: malformed gh pr list JSON output")
            continue

        if not isinstance(records, list):
            failures.append(f"{branch}: unexpected gh pr list JSON shape")
            continue

        for rec in records:
            if isinstance(rec, dict) and isinstance(rec.get("url"), str):
                urls[branch] = rec["url"]
                break

    pr_lookup_error = "; ".join(failures) if failures else None
    return urls, pr_lookup_error


def check_in_flight_token(
    working_dir: Path,
    token: str,
    target_path: str | None = None,
    gh_token: str | None = None,
) -> dict[str, Any]:
    """Structured in-flight check for ``token`` (issue #173 slice 1).

    Fetches origin fresh, then reports whether ``token`` is already in
    flight: an unmerged origin governance branch for its slug, same-day or
    later-day. Detection itself is git-only and authoritative; PR URLs are
    best-effort per-branch ``gh`` lookups, resolved only when at least one
    in-flight branch was found.

    Returns a dict with keys:
      - ``in_flight``: ``bool | None``. ``None`` means UNDETERMINED (see the
        module-level TRI-STATE note); ``True``/``False`` mean detection ran
        to completion.
      - ``branches``: list[str] of in-flight branch names (empty unless
        ``in_flight is True``).
      - ``pr_urls``: dict[str, str], branch -> open PR URL where resolvable.
      - ``pr_lookup_error``: str | None -- set when at least one per-branch
        ``gh pr list`` lookup failed; detection itself is unaffected.
      - ``error``: str | None -- set (``IN_FLIGHT_UNDETERMINED``-prefixed)
        ONLY when ``in_flight is None``.
    """
    branches, fetch_error = find_in_flight_branches(working_dir, token, target_path)
    if fetch_error:
        return {
            "in_flight": None,
            "branches": [],
            "pr_urls": {},
            "pr_lookup_error": None,
            "error": fetch_error,
        }

    pr_urls, pr_lookup_error = (
        _resolve_open_pr_urls(working_dir, branches, gh_token) if branches else ({}, None)
    )
    return {
        "in_flight": bool(branches),
        "branches": branches,
        "pr_urls": pr_urls,
        "pr_lookup_error": pr_lookup_error,
        "error": None,
    }


def _write_file(target_path: Path, content: str) -> str | None:
    """Write content to target_path, creating parent directories.

    Returns an error string on failure, None on success.
    """
    try:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(content, encoding="utf-8")
        return None
    except OSError as exc:
        return f"Failed to write {target_path}: {exc}"


# ---------------------------------------------------------------------------
# Two-birds: ADR doc placement + deterministic HUMAN_ADR_REF stamp (#112)
# ---------------------------------------------------------------------------


def _compute_adr_path(working_dir: Path, token: str) -> Path:
    """Compute the verbatim-ADR doc path for a token: docs/adr/<TOKEN>.md.

    The doc is named by the AGR's OWN ``token`` so the greppable
    ``HUMAN_ADR_REF::<token>`` in the AGR points straight at it (self-token
    linkage, #112). ``token`` is ``_TOKEN_FORMAT_RE``-validated upstream (no
    ``/`` and no ``.``), so the join cannot introduce a path separator; the
    caller still applies the path-traversal guard as defence-in-depth.
    """
    return working_dir / "docs" / "adr" / f"{token}.md"


def _stamp_human_adr_ref(octave_content: str, token: str) -> str:
    """Return ``octave_content`` with a ``HUMAN_ADR_REF::"<token>"`` META line.

    Deterministic, engine-side stamp (#112): inserted as a SINGLE flat META line
    immediately after the ``META:`` header so it never touches the DECISION /
    BECAUSE bytecode (the ≤40-word reasoning-density guard is unaffected). The
    value is the record's OWN token (token-form #11 — cross-repo survivable, no
    filesystem resolution at Gate A).

    Idempotent: if a ``HUMAN_ADR_REF::`` line is already present, its value is
    overwritten to the correct token (preserving exactly one line). If absent,
    it is inserted immediately after the ``META:`` header.
    """
    lines = octave_content.splitlines(keepends=True)
    stamp_line = f'  HUMAN_ADR_REF::"{token}"\n'

    matching_indices = [
        idx for idx, line in enumerate(lines) if line.lstrip().startswith("HUMAN_ADR_REF::")
    ]

    if len(matching_indices) > 1:
        for idx in reversed(matching_indices):
            lines.pop(idx)
        for idx, line in enumerate(lines):
            if line.strip() == "META:":
                lines.insert(idx + 1, stamp_line)
                return "".join(lines)
    elif len(matching_indices) == 1:
        lines[matching_indices[0]] = stamp_line
        return "".join(lines)
    else:
        for idx, line in enumerate(lines):
            if line.strip() == "META:":
                lines.insert(idx + 1, stamp_line)
                return "".join(lines)

    # No META: header found (malformed record) — return unchanged rather than
    # corrupt the document; Gate-A re-validation downstream will surface it.
    return octave_content


def _git_add_and_commit(
    working_dir: Path,
    file_path: Path,
    manifest_path: Path,
    commit_message: str,
    extra_paths: list[Path] | None = None,
) -> str | None:
    """Stage the governance file (+ any ``extra_paths``) + MANIFEST and commit.

    ``extra_paths`` (#112) carries the two-birds ADR doc so the AGR and its
    verbatim ADR land in ONE commit. Each extra path is staged BEFORE the commit;
    a failed ``git add`` on any of them aborts with a structured error (no commit
    with a missing file).

    Returns an error string on failure, None on success.
    """
    # Stage the governance file (and any companion files, e.g. the ADR doc).
    for path in [file_path, *(extra_paths or [])]:
        try:
            rel = path.relative_to(working_dir)
        except ValueError:
            rel = path
        code, _, stderr = _run_git(["add", str(rel)], working_dir)
        if code != 0:
            return f"git add failed for {rel}: {stderr}"

    # Stage MANIFEST if it was written
    if manifest_path.exists():
        try:
            manifest_rel = manifest_path.relative_to(working_dir)
        except ValueError:
            manifest_rel = manifest_path
        _run_git(["add", str(manifest_rel)], working_dir)

    code, _, stderr = _run_git(["commit", "-m", commit_message], working_dir)
    if code != 0:
        return f"git commit failed: {stderr}"
    return None


def _open_pr(
    working_dir: Path,
    branch_name: str,
    token: str,
    card_type: str,
    gh_token: str | None,
) -> tuple[str | None, str | None]:
    """Open a PR via gh pr create.

    Returns (pr_url, error_message). One of the two is always None.
    """
    title = f"feat(governance): add {token} [{card_type}]"
    body = (
        f"## Governance Intake -- Gate A Rails (RFC #53)\n\n"
        f"- **Token/ID**: `{token}`\n"
        f"- **Type**: `{card_type}`\n"
        f"- **Branch**: `{branch_name}`\n\n"
        "Gate A only -- no LLM, no AST. Dumb Type Checker = regex sentinel + path validation.\n"
        "Gate B will wire octave-mcp validator.\n\n"
        "Closes/References: RFC #53\n"
    )

    env = dict(os.environ)
    if gh_token:
        env["GH_TOKEN"] = gh_token

    try:
        result = subprocess.run(
            [
                "gh",
                "pr",
                "create",
                "--title",
                title,
                "--body",
                body,
                "--base",
                "main",
            ],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(working_dir),
            env=env,
        )
    except subprocess.TimeoutExpired:
        return None, "gh pr create timed out after 60s"
    except (FileNotFoundError, OSError) as exc:
        return None, f"gh CLI not found or failed: {exc}"

    if result.returncode != 0:
        return None, f"gh pr create failed: {result.stderr.strip()}"

    pr_url = result.stdout.strip()
    return pr_url, None


# ---------------------------------------------------------------------------
# Main linker entry point
# ---------------------------------------------------------------------------


def run_linker(
    working_dir: Path,
    validation: ValidationResult,
    octave_content: str,
    dry_run: bool,
    adr_prose: str | None = None,
) -> dict[str, Any]:
    """Execute the Git Orchestrator for a validated governance artifact.

    Args:
        working_dir: Project root directory.
        validation: Successful ValidationResult from type_checker.
        octave_content: Raw OCTAVE document text to commit. When ``adr_prose`` is
            supplied this is expected to ALREADY carry the deterministic
            ``HUMAN_ADR_REF::<token>`` stamp (the caller stamps + re-validates).
        dry_run: If True, skip all git/file operations and return
                 what WOULD happen without touching disk or git.
        adr_prose: Two-birds (#112). When non-None, the VERBATIM prose is
            dumb-written to ``docs/adr/<token>.md`` (no AI, no OCTAVE, no marker)
            and committed ALONGSIDE the AGR in the SAME branch/commit/PR. When
            None the behaviour is byte-stable AGR-only.

    Returns:
        Dict with keys: token, card_type, target_path, branch, pr_url, error,
        dry_run, staged_uncommitted, ``adr_target_path`` (the
        ``docs/adr/<token>.md`` path when ``adr_prose`` is supplied, else None),
        and the issue #173 slice-1 in-flight signal: ``in_flight`` (``bool |
        None`` -- see TRI-STATE below), ``in_flight_branches`` (list[str],
        unmerged origin governance branches found for this token's slug),
        ``in_flight_pr_urls`` (dict[str, str], branch -> open PR URL where
        resolvable), and ``in_flight_pr_lookup_error`` (str | None -- set
        when a per-branch ``gh pr list`` lookup failed; detection itself is
        unaffected by that failure).

        ``branch`` is the would-be branch name on ``dry_run``; on a live run it
        is non-None ONLY when the branch actually reached ``origin`` (a push
        succeeded), and None when a pre-push failure rolled the local branch back
        (no misleading name for a branch that was never persisted — issue #108)
        OR when the token was found in flight (no branch was ever created).
        ``staged_uncommitted`` is always False on the live path: every git
        mutation happens inside a throwaway worktree that is always removed, so
        nothing is ever left staged in the operator's working tree.

        TRI-STATE ``in_flight`` (rework round 1 addendum A): ``None`` means
        UNDETERMINED -- detection did not run (``dry_run``, or the
        target_path/path-traversal guards rejected the submission BEFORE
        detection was reached) or could not complete (a fetch or
        ref-enumeration failure, ``error`` prefixed
        ``IN_FLIGHT_UNDETERMINED: `` in that case). ``True``/``False`` mean
        detection ran to completion and found something / found nothing,
        respectively. A caller MUST NOT read ``None`` as "not in flight" --
        that conflation is exactly the fail-open bug this rework fixes.
        ``dry_run`` in particular performs NEITHER the fetch NOR the
        in-flight check (both are network operations that mutate local
        remote-tracking refs, a side effect dry_run must stay free of), so
        its result is ALWAYS the undetermined shape, never a measured False.
    """
    token = validation.token or ""
    card_type = validation.card_type or ""
    target_path = validation.target_path

    branch_name = _compute_branch_name(token)
    try:
        target_path_str = str(target_path.relative_to(working_dir)) if target_path else None
    except ValueError:
        target_path_str = str(target_path) if target_path else None

    # Two-birds ADR doc path (relative form for the structured return).
    adr_target_path = _compute_adr_path(working_dir, token) if adr_prose is not None else None
    adr_target_path_str = str(adr_target_path.relative_to(working_dir)) if adr_target_path else None

    if dry_run:
        # dry_run performs NEITHER the fetch NOR the in-flight check (issue
        # #173 slice 1 design decision): both are network operations that
        # mutate local remote-tracking refs, which is a side effect dry_run
        # must stay free of (module docstring: "dry_run=True: skips all
        # git/file operations"). in_flight is therefore the UNDETERMINED
        # shape (None), not a measured False (rework round 1 addendum A) --
        # in_flight_branches/in_flight_pr_urls/in_flight_pr_lookup_error stay
        # at their inert empty/None defaults for I4 shape stability.
        return {
            "token": token,
            "card_type": card_type,
            "target_path": target_path_str,
            "adr_target_path": adr_target_path_str,
            "branch": branch_name,
            "pr_url": None,
            "in_flight": None,
            "in_flight_branches": [],
            "in_flight_pr_urls": {},
            "in_flight_pr_lookup_error": None,
            "error": None,
            "staged_uncommitted": False,
            "dry_run": True,
        }

    # --- Live path: hermetic worktree git operations ---
    errors: list[str] = []

    # target_path is required before we touch git.
    if target_path is None:
        # Nothing created, nothing staged: no worktree, no branch. Detection
        # was never reached, so in_flight is UNDETERMINED (None), not False.
        return {
            "token": token,
            "card_type": card_type,
            "target_path": None,
            "adr_target_path": adr_target_path_str,
            "branch": None,
            "pr_url": None,
            "in_flight": None,
            "in_flight_branches": [],
            "in_flight_pr_urls": {},
            "in_flight_pr_lookup_error": None,
            "error": "target_path is None -- cannot write file",
            "staged_uncommitted": False,
            "dry_run": False,
        }

    # Bug 4: path traversal guard -- verify target_path is inside working_dir.
    # #112: the SAME guard is applied to the two-birds ADR path so a crafted
    # token/symlink cannot escape the repo. Both paths are checked here, BEFORE
    # any worktree is created, so a rejection touches nothing. The guard also
    # yields the repo-relative paths we replay INSIDE the worktree.
    guard_paths = [target_path, *([adr_target_path] if adr_target_path is not None else [])]
    rels: list[Path] = []
    for guarded in guard_paths:
        try:
            rels.append(guarded.resolve().relative_to(working_dir.resolve()))
        except (ValueError, RuntimeError, OSError):
            # Nothing created: no worktree, no branch, nothing staged.
            # Detection was never reached, so in_flight is UNDETERMINED.
            return {
                "token": token,
                "card_type": card_type,
                "target_path": target_path_str,
                "adr_target_path": adr_target_path_str,
                "branch": None,
                "pr_url": None,
                "in_flight": None,
                "in_flight_branches": [],
                "in_flight_pr_urls": {},
                "in_flight_pr_lookup_error": None,
                "error": (
                    f"target_path {guarded} is outside working_dir {working_dir} "
                    "-- path traversal rejected"
                ),
                "staged_uncommitted": False,
                "dry_run": False,
            }

    # 0. In-flight TOKEN check (issue #173 slice 1) -- FETCH FRESH REMOTE STATE
    #    THEN check, BEFORE any worktree/branch/push/PR. An unmerged origin
    #    governance branch for this token's slug (same-day collision OR
    #    later-day second-PR case) means the token is already in flight:
    #    submit_governance must refuse to open a second branch/PR rather than
    #    racing `_create_worktree`'s own (later, redundant) fetch.
    gh_token = _resolve_github_token()
    in_flight_status = check_in_flight_token(working_dir, token, target_path_str, gh_token)
    if in_flight_status["error"]:
        # Detection could NOT complete (fetch or ref-enumeration failure):
        # fail CLOSED -- nothing created, nothing staged -- and report the
        # UNDETERMINED shape (in_flight=None), never a measured False, so a
        # caller can never mistake "we don't know" for "confirmed clear"
        # (CRS/CE fail-open finding; rework round 1 addendum A).
        return {
            "token": token,
            "card_type": card_type,
            "target_path": target_path_str,
            "adr_target_path": adr_target_path_str,
            "branch": None,
            "pr_url": None,
            "in_flight": None,
            "in_flight_branches": [],
            "in_flight_pr_urls": {},
            "in_flight_pr_lookup_error": None,
            "error": in_flight_status["error"],
            "staged_uncommitted": False,
            "dry_run": False,
        }
    if in_flight_status["in_flight"]:
        in_flight_branches = in_flight_status["branches"]
        in_flight_pr_urls = in_flight_status["pr_urls"]
        in_flight_pr_lookup_error = in_flight_status["pr_lookup_error"]
        return {
            "token": token,
            "card_type": card_type,
            "target_path": target_path_str,
            "adr_target_path": adr_target_path_str,
            "branch": None,
            "pr_url": None,
            "in_flight": True,
            "in_flight_branches": in_flight_branches,
            "in_flight_pr_urls": in_flight_pr_urls,
            "in_flight_pr_lookup_error": in_flight_pr_lookup_error,
            "error": (
                f"TOKEN '{token}' is already in flight on origin "
                f"(unmerged governance branch(es): {', '.join(in_flight_branches)}); "
                "no new branch or PR was opened."
            ),
            "staged_uncommitted": False,
            "dry_run": False,
        }

    # 1. Create the dedicated worktree on a fresh branch off origin/main. The
    #    operator's own working tree (whatever branch it is on) is NEVER touched.
    worktree_path, err = _create_worktree(working_dir, branch_name)
    if err:
        # Worktree creation failed: nothing created, nothing staged. Detection
        # ran to completion above and determined False, so in_flight is the
        # DETERMINED False shape here (not None) -- we DO know.
        return {
            "token": token,
            "card_type": card_type,
            "target_path": target_path_str,
            "adr_target_path": adr_target_path_str,
            "branch": None,
            "pr_url": None,
            "in_flight": False,
            "in_flight_branches": [],
            "in_flight_pr_urls": {},
            "in_flight_pr_lookup_error": None,
            "error": err,
            "staged_uncommitted": False,
            "dry_run": False,
        }

    # On success ``_create_worktree`` returns a non-None path (err is None).
    assert worktree_path is not None

    pushed_ok = False
    pr_url: str | None = None
    try:
        # Replay the repo-relative paths inside the worktree.
        target_in_wt = worktree_path / rels[0]
        adr_in_wt = (worktree_path / rels[1]) if adr_target_path is not None else None

        # 2. Write OCTAVE content into the worktree.
        err = _write_file(target_in_wt, octave_content)
        if err:
            errors.append(err)

        # 2b. Two-birds (#112): dumb-write the VERBATIM ADR prose alongside the
        #     AGR. No AI, no OCTAVE, no provenance marker. Written only when the
        #     AGR write succeeded so we never leave an orphan ADR doc.
        if not errors and adr_prose is not None and adr_in_wt is not None:
            err = _write_file(adr_in_wt, adr_prose)
            if err:
                errors.append(err)

        # 3. Update MANIFEST (best-effort -- failure is non-fatal, Bug 9 fix).
        if not errors:
            try:
                write_manifest(worktree_path)
            except Exception as exc:  # noqa: BLE001
                # Log warning instead of appending to errors; MANIFEST failure
                # must not block the commit/PR flow (Bug 9: non-fatal).
                logger.warning("MANIFEST update failed (non-fatal): %s", exc)

        # 4. Commit (inside the worktree).
        if not errors:
            commit_message = f"chore(governance): add {token} [{card_type}]"
            manifest_path = worktree_path / ".hestai" / "MANIFEST.md"
            extra_paths = [adr_in_wt] if adr_in_wt is not None else None
            err = _git_add_and_commit(
                worktree_path,
                target_in_wt,
                manifest_path,
                commit_message,
                extra_paths=extra_paths,
            )
            if err:
                errors.append(err)

        # 5. Push branch to origin (REQUIRED before gh pr create -- issue #73).
        #    gh aborts PR creation if the branch is not on a remote. A push
        #    failure is a structured error (PROD I4) and skips PR creation.
        if not errors:
            err = _push_branch(worktree_path, branch_name)
            if err:
                errors.append(err)
            else:
                pushed_ok = True

        # 6. Open PR. Reuses the ``gh_token`` already resolved for the
        #    in-flight PR-URL lookup above (single resolution, no re-fetch).
        if not errors:
            pr_url, pr_err = _open_pr(worktree_path, branch_name, token, card_type, gh_token)
            if pr_err:
                errors.append(pr_err)
    finally:
        # ALWAYS remove the worktree -- the operator's tree was never mutated, so
        # there is no partial state to surface. If the branch never reached
        # origin, roll the local branch back too so no half-built branch lingers.
        # Rollback keys on ``pushed_ok`` ALONE (not on ``errors``): an unexpected
        # exception before the push never populates ``errors``, yet still leaves
        # an unpushed branch that must be cleaned up (cubic P2).
        _remove_worktree(working_dir, worktree_path)
        if not pushed_ok:
            _delete_branch(working_dir, branch_name)

    error_str = "; ".join(errors) if errors else None

    # Report ``branch`` for recovery ONLY when it actually persists on origin (a
    # push succeeded). On a pre-push failure the branch was rolled back, so we
    # report None rather than a misleading name (issue #108: the old in-place
    # code returned a branch that was never persisted).
    persisted_branch = branch_name if pushed_ok else None

    return {
        "token": token,
        "card_type": card_type,
        "target_path": target_path_str,
        "adr_target_path": adr_target_path_str,
        "branch": persisted_branch,
        "pr_url": pr_url,
        # Reached the worktree/push/PR stage, so the in-flight check above
        # already confirmed (DETERMINED False, not undetermined) no unmerged
        # branch existed for this token.
        "in_flight": False,
        "in_flight_branches": [],
        "in_flight_pr_urls": {},
        "in_flight_pr_lookup_error": None,
        # Hermetic model: the worktree is always removed and nothing is ever
        # staged in the operator's working tree, so this is always False.
        # Retained for I4 shape stability.
        "staged_uncommitted": False,
        "error": error_str,
        "dry_run": False,
    }
