"""Git Orchestrator (Linker) for governance intake.

Accepts a ValidationResult + raw OCTAVE content, then:
  0. Fetches origin fresh and checks whether the TOKEN is already in flight
     (an unmerged origin/governance/* branch for its slug, any date -- issue
     #173 slice 1 / operator ruling 2026-09-21). If so, refuses: no worktree,
     no branch, no push, no PR -- see ``check_in_flight_token``.
  1. Creates a DEDICATED git worktree on a fresh ``governance/{date}-{token-slug}``
     branch based off ``origin/main`` (after a second, redundant ``git fetch
     origin`` internal to ``_create_worktree`` -- left as-is; cheap/idempotent)
  1b. Symlinks the caller's ``.venv`` (if present) into the throwaway
     worktree root -- see ``_link_caller_venv_into_worktree`` and the
     COMMIT-SIDE HOOKS note below (issue #178).
  2. Writes OCTAVE content to the computed target_path INSIDE that worktree
  3. Commits with: chore(governance): add {token} [{card_type}] -- runs the
     TARGET REPO'S OWN local hooks for real (NEVER ``--no-verify`` on this
     call; see the COMMIT-SIDE HOOKS note below)
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

COMMIT-SIDE HOOKS (issue #178; the commit-side sibling of the push rationale
in ``_push_branch`` below): the throwaway worktree is a FRESH checkout with
no ``.venv`` -- any target repo whose pre-commit hooks shell out to
``.venv/bin/python`` (a common pattern: namespace/canonical-path validators,
octave-mcp's own validator) fail there with an ENVIRONMENT error (e.g. exit
127, "no such file"), not a content verdict, and ``run_linker`` never even
reaches ``git push`` -- ``success=false``, no PR, no signal about whether the
record itself was actually good. Unlike the push (which genuinely runs
project-wide quality gates that make no sense from an ephemeral worktree),
the commit-side hooks are exactly the mechanism issue #166's defect class
(a canonical-paths validator) exists to enforce, so blanket ``--no-verify``
here would hide real content defects until CI -- the operator explicitly
rejected that option (RD23, option 2b over option 1). Instead:
  - ``_link_caller_venv_into_worktree`` symlinks the CALLER's OWN ``.venv``
    into the worktree root before the commit, so a hook needing
    ``.venv/bin/python`` finds a REAL interpreter and can do REAL work
    against the staged record, not just fail on a missing binary.
  - If a hook still fails -- including when the caller has no ``.venv`` at
    all -- ``_git_add_and_commit`` surfaces a structured, NAMED
    ``GOVERNANCE_COMMIT_HOOK_FAILED:`` error (PROD I4) carrying the hook's
    combined stdout+stderr, and (where parseable, e.g. the ``pre-commit``
    framework's ``- hook id: <id>`` failure-summary line) the hook's own id.
    The commit is NEVER skipped to paper over this.
  - CONSEQUENCE (part of the design, not an incidental risk): these hooks
    run from the throwaway worktree using origin/main's entry SCRIPTS, but
    any IMPORT of the target repo's own package inside those scripts
    resolves through the CALLER's editable install (``pip install -e``) to
    the CALLER's ``src/`` -- see issue #164. That is the SAME code a
    hand-run ``git commit`` from the caller's own checkout would use, so
    this is not a new class of risk the linker introduces; it is the
    existing editable-install behavior, inherited. The residual risk is a
    FALSE EARLY SIGNAL (a hook could pass or fail based on the caller's
    checked-out revision of the package rather than origin/main's), which
    the PR's own CI run corrects downstream -- the hook here is a fast,
    best-effort local gate, not the final authority.
  - The link is NEVER staged or committed (explicit-path ``git add``
    staging only -- see ``_git_add_and_commit``, never ``git add -A``/``.``)
    and is removed WITH the throwaway worktree by ``_remove_worktree``,
    which never follows the top-level symlink back into the caller's real
    ``.venv`` (``shutil.rmtree`` does not traverse a top-level symlink).

dry_run=True: skips all git/file operations, returns what WOULD happen.

GitHub token resolution is provided by the shared single-source-of-truth helper
``tools.shared.github_auth`` (extracted to remove the CIV-flagged duplication
that previously copied this logic from submit_review). It is re-exported here as
``_resolve_github_token`` so ``run_linker`` resolves it as a module global
(patchable in tests).
"""

import contextlib
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hestai_context_mcp.core.agent_readable_governance_parser import (
    classify_record_text,
    has_yaml_decision_header,
    read_record,
)
from hestai_context_mcp.tools.governance.lexer import declares_token
from hestai_context_mcp.tools.governance.manifest import write_manifest
from hestai_context_mcp.tools.governance.topic_append import record_hash
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


def _run_git_bytes(
    args: list[str], cwd: Path, stdin: bytes | None = None
) -> tuple[int, bytes, str]:
    """Run a git command with optional stdin; stdout is returned as raw bytes.

    Used where exact blob bytes matter (the append_ruling base read hashes
    them): text mode would decode and translate newlines. Same failure mapping
    as ``_run_git``: a timeout or OSError is a non-zero exit.
    """
    try:
        result = subprocess.run(
            ["git", *args],
            input=stdin,
            capture_output=True,
            timeout=_GIT_TIMEOUT,
            cwd=str(cwd),
        )
        return result.returncode, result.stdout, result.stderr.decode("utf-8", "replace").strip()
    except subprocess.TimeoutExpired:
        return 1, b"", "git command timed out"
    except (FileNotFoundError, OSError) as exc:
        return 1, b"", str(exc)


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


def _link_caller_venv_into_worktree(working_dir: Path, worktree_path: Path) -> None:
    """Best-effort: symlink the caller's ``.venv`` into the throwaway
    worktree root as ``.venv`` (issue #178), so the target repo's own
    pre-commit hooks -- which often shell out to ``.venv/bin/python`` -- run
    for REAL against the staged record, instead of failing on a missing
    interpreter in an environment that never had one. See the module
    docstring's COMMIT-SIDE HOOKS note for the full rationale (including the
    editable-install/issue #164 consequence).

    Does nothing (no error, no return value) when the caller's
    ``working_dir`` has no ``.venv`` directory, or when the symlink cannot be
    created for any reason (permissions, an existing ``.venv`` already in
    the fresh worktree, ...) -- this is a best-effort improvement, never a
    requirement: a caller without a usable ``.venv`` still gets a correct,
    structured ``GOVERNANCE_COMMIT_HOOK_FAILED`` outcome if a hook then
    fails (see ``_git_add_and_commit``), it just does not get the hook
    running successfully.

    NEVER staged, NEVER committed: ``_git_add_and_commit`` stages files
    ONLY by their EXPLICIT relative path (never ``git add -A`` / ``git add
    .``), and this symlink is never named in any ``git add`` call -- it
    cannot appear in a commit as long as that staging discipline holds
    (guarded by a dedicated test asserting ``git show --name-only`` has no
    ``.venv`` entry). It is removed WITH the throwaway worktree by
    ``_remove_worktree``'s ``shutil.rmtree`` -- which does NOT follow a
    top-level symlink into the caller's real ``.venv`` (proven by a
    dedicated test using a sentinel file inside the caller's ``.venv``).

    NOT done: writing the link's path into the worktree's
    ``.git/info/exclude`` as an extra defence-in-depth measure. That file is
    NOT per-worktree state -- ``git rev-parse --git-path info/exclude``
    from inside a linked worktree resolves to the CALLER's OWN real
    ``.git/info/exclude`` (the common git dir is shared across all
    worktrees of a repository), so writing to it would mutate the
    operator's real repository configuration as a persistent side effect,
    directly contradicting this file's own "the operator's own working
    tree is NEVER touched" invariant (see the module docstring). The
    explicit-path staging discipline above is the sole safeguard, and is
    sufficient: the symlink is structurally never named in any ``git add``
    call this module makes.
    """
    caller_venv = working_dir / ".venv"
    if not caller_venv.is_dir():
        return
    link_path = worktree_path / ".venv"
    # Best-effort: permissions, an existing path, or any other symlink
    # failure falls through silently -- a hook needing .venv will then fail
    # with its own error, surfaced structurally below.
    with contextlib.suppress(OSError):
        link_path.symlink_to(caller_venv, target_is_directory=True)


# ---------------------------------------------------------------------------
# In-flight TOKEN detection (issue #173 slice 1; operator ruling 2026-09-21,
# HO-GOVERNANCE-IN-FLIGHT-TOKEN-AMENDMENT-20260921; OID round -- the FINAL
# shape after three prior rework rounds)
#
# "In flight" = a governance branch for the TOKEN's slug that exists on
# origin, ANY date prefix, and is NOT merged into origin/main -- OR an open PR
# for it.
#
# ASSUMPTION -- "open PR" coverage without an independent GitHub query: the
# unmerged-origin-branch test is treated as covering "open PR" too, WITHOUT a
# per-submission GitHub API query for open PRs. This holds because governance
# PRs are SAME-REPO by construction: ``_push_branch`` always pushes to
# ``origin`` and ``_open_pr`` runs ``gh pr create`` from inside that same
# pushed worktree, so a governance PR's head branch is NEVER a fork ref -- it
# is always ``origin/governance/<date>-<slug>``. A GitHub PR requires its head
# branch to exist; deleting that branch auto-closes the PR. So "an unmerged
# origin/governance/*-<slug> branch exists" and "an open PR for this token
# exists" are the same fact observed from two angles, FOR THIS REPO'S
# governance flow specifically. If this assumption is ever found false, STOP
# and escalate rather than silently trusting the ref test.
#
# THE OID SHAPE (this round's fix -- CRS/CE/TMG/cubic across three prior
# rounds each found a NEW INSTANCE OF ONE CAUSE: the code verified a ref, then
# RE-READ IT BY NAME in a second git process, and treated a silent exit 1 (or
# stderr presence/absence) as a measurement -- a ref pruned between reads, a
# killed process with empty stderr, and ``_run_git`` mapping a timeout/OSError
# to exit code 1 (indistinguishable from ``merge-base``'s "not an ancestor")
# were all found as separate bugs in separate rounds, because the SHAPE kept
# admitting new instances of the same defect class). The fix is structural,
# not another special case:
#
#   1. EVERY ref is resolved to an immutable OID EXACTLY ONCE:
#      - all candidate branches, together, via ONE
#        ``git for-each-ref --format='%(refname:short) %(objectname)'`` call
#        (see ``_list_remote_governance_candidates_for_slug``);
#      - ``origin/main``, via ONE
#        ``git rev-parse --verify origin/main^{commit}`` call, WITHOUT ``-q``
#        (see ``_resolve_oid``).
#   2. EVERY subsequent check takes an OID, NEVER a ref name:
#      - ancestry: ``git rev-list -1 <branch-oid> ^<main-oid>``
#        (``_is_ancestor_of_main``) -- exit 0 + empty stdout = merged,
#        exit 0 + non-empty stdout = not an ancestor;
#      - the squash-merge content signal:
#        ``git ls-tree <oid> -- <target_path>`` (``_ls_tree_blob``) -- exit 0
#        with empty stdout = no record at that path, exit 0 with output = a
#        parseable ``<mode> <type> <blob-oid>\t<path>`` line.
#   3. THE EXIT-0 CONTRACT: every one of these four git invocations was
#      CHOSEN because its every valid answer exits 0 with the answer on
#      stdout (empty or non-empty stdout both count as valid, DETERMINED
#      answers). Consequently EVERY non-zero exit -- 128 (bad object/ref),
#      137 (SIGKILL, always empty stderr), OR ``_run_git``'s own
#      timeout-as-1 / OSError-as-1 (linker.py's ``_run_git``, UNCHANGED by
#      this round: the exit-0 contract makes a stderr discriminator
#      unnecessary) -- maps uniformly to ``IN_FLIGHT_UNDETERMINED``. NO
#      function on this path inspects stderr CONTENT to decide which branch
#      of the code runs; stderr is not even captured by three of the four
#      calls' undetermined paths (only the exit code is). A masked timeout on
#      the SAME exit code as a genuine measurement can no longer masquerade
#      as one, because there is no code path left where that exit code
#      *could* correspond to two different valid outcomes -- the shape does
#      not depend on discriminating causes of exit 1, because none of these
#      four commands uses exit 1 for two different meanings the way
#      ``merge-base --is-ancestor`` (removed) and ``rev-parse --verify -q``
#      (removed) both did.
#
# REMOVED (obsolete under the OID shape -- code got SMALLER; see the OID
# round report for the exact net line delta):
#   - ``_is_merged_into_origin_main`` (name-based ``merge-base
#     --is-ancestor origin/<branch> origin/main``, exit-1-means-two-things);
#   - ``_blob_sha_at`` (name-based ``rev-parse --verify -q <ref>:<path>``,
#     which could not tell a missing REF from a missing PATH);
#   - ``_verify_ref_resolves`` (a whole extra function that existed ONLY to
#     patch over ``_blob_sha_at``'s ref/path ambiguity -- moot now, since
#     nothing after enumeration is ever looked up by NAME again, so there is
#     no ref left to be ambiguously "missing" at that stage);
#   - ``_branch_record_matches_origin_main`` (folded into
#     ``find_in_flight_branches`` directly, since both OIDs it needs --
#     the branch's and main's -- are already in hand by the time it would
#     run).
#
# MERGED classification (still two independent, PER-CANDIDATE-BRANCH
# signals -- the ratified spec is UNCHANGED, only the git-call SHAPE changed):
# a MERGED-but-undeleted origin branch is excluded from in-flight status even
# though the ref still exists. A branch is "merged" iff EITHER:
#   (1) its OID is an ancestor of main's OID (``_is_ancestor_of_main``) --
#       correct for merge-commit (--no-ff) merges, blind to squash/rebase; OR
#   (2) THAT BRANCH's OWN blob at the token's target_path equals origin/main's
#       blob at that path (compared via ``_ls_tree_blob`` on both OIDs) --
#       strategy-independent, because the record's CONTENT is what actually
#       lands on main regardless of how the merge happened. Evaluated PER
#       BRANCH, NEVER as a token-wide short-circuit (round-2 correction,
#       unchanged this round): branch A being squash-merged must never clear
#       a DIFFERENT, still-unmerged branch B whose content has since
#       diverged from what's on main.
#
# POST-MERGE RE-FILING IS UNCHANGED BY THIS SLICE: what happens when the SAME
# token is re-submitted AFTER its record already landed on origin/main is
# governed ENTIRELY by Check 6 (``type_checker._validate_impl`` ->
# ``lexer.lookup_token_deterministic``), which reads the CALLER's OWN local
# ``working_dir`` tree and does not consult origin/main. This in-flight check
# only EXCLUDES an already-landed branch from being misreported "in flight";
# it is not a new duplicate-rejection path.
#
# Fetch-before-check (not after): ``find_in_flight_branches`` fetches fresh
# remote state itself and is called from ``run_linker`` BEFORE any
# worktree/branch/push, so a same-day or later-day in-flight branch is never
# invisible the way the old Check-6-then-linker-fetch ordering made it.
#
# TRI-STATE ``in_flight`` (``bool | None`` EVERYWHERE this module and its
# callers surface it, unchanged this round):
#   - ``None``  -- UNDETERMINED: detection did not run (``dry_run``) or could
#     not complete (any non-zero exit on the detection path, or a missing
#     ``target_path`` with candidates present). The paired ``error`` string
#     is prefixed ``IN_FLIGHT_UNDETERMINED: ``.
#   - ``True``  -- DETERMINED: at least one unmerged branch was found -- and
#     is NAMED in ``branches`` (acceptance criterion (d): every determined
#     True names the branch(es)).
#   - ``False`` -- DETERMINED: detection ran to completion and found nothing.
# ---------------------------------------------------------------------------

_GOVERNANCE_REMOTE_REF_PREFIX = "refs/remotes/origin/governance/"

# Stable prefix so callers can branch on "detection could not run" without
# parsing the full message.
_IN_FLIGHT_UNDETERMINED_PREFIX = "IN_FLIGHT_UNDETERMINED: "


def _fetch_origin(working_dir: Path) -> str | None:
    """Fetch fresh remote state from origin, pruning stale remote-tracking refs.

    MUST run before any remote-branch-based in-flight check: detection must
    see refs that exist on origin RIGHT NOW, not whatever the local
    remote-tracking namespace last held. ``git fetch``'s only valid answer is
    success (exit 0); any non-zero exit is undetermined.

    Returns an ``IN_FLIGHT_UNDETERMINED``-prefixed error string on failure,
    None on success.
    """
    code, _, stderr = _run_git(["fetch", "origin", "--prune"], working_dir)
    if code != 0:
        return f"{_IN_FLIGHT_UNDETERMINED_PREFIX}git fetch origin failed: {stderr}"
    return None


def _list_remote_governance_candidates_for_slug(
    working_dir: Path, slug: str, *, include_append_branches: bool = False
) -> tuple[list[tuple[str, str]], str | None]:
    """List origin governance branches matching ``slug`` (ANY date prefix),
    EACH PAIRED WITH ITS OID, via ONE
    ``git for-each-ref --format='%(refname:short) %(objectname)'`` call.

    EXIT-0 CONTRACT: for-each-ref's only valid answers are exit 0 (whether or
    not anything matches -- an empty result is not an error). ANY non-zero
    exit is undetermined; this NEVER collapses to an empty list on failure
    (that was the round-1 CRS/CE fail-open finding -- an empty list here must
    always mean "asked and there were none," never "could not ask").

    Requires a prior ``_fetch_origin`` call to see current remote state --
    this function does not fetch.

    Returns ``(candidates, error)``: ``candidates`` is a sorted list of
    ``(branch_name, oid)`` tuples, ``branch_name`` WITHOUT the ``origin/``
    remote-tracking prefix. This is the ONE place a candidate branch's ref is
    ever resolved to an OID -- no candidate ref is read again by name
    anywhere downstream (acceptance criterion (c), READ-ONCE).

    ``include_append_branches`` (issue #203 S2) also matches the append_ruling
    branch shape ``governance/<date>-<slug>-r<n>``, so a pending append to a
    topic record counts as that record being in flight.
    """
    code, out, stderr = _run_git(
        ["for-each-ref", "--format=%(refname:short) %(objectname)", _GOVERNANCE_REMOTE_REF_PREFIX],
        working_dir,
    )
    if code != 0:
        return [], f"{_IN_FLIGHT_UNDETERMINED_PREFIX}git for-each-ref failed: {stderr}"
    if not out:
        return [], None

    # Full-name anchored: governance/<8 digits>-<exact slug>, nothing else --
    # a longer slug that merely ENDS with this slug must not match.
    suffix = r"(?:-r\d+)?" if include_append_branches else ""
    pattern = re.compile(rf"^origin/governance/\d{{8}}-{re.escape(slug)}{suffix}$")
    matches: list[tuple[str, str]] = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.rsplit(" ", 1)
        if len(parts) != 2:
            continue
        ref_name, oid = parts
        if pattern.match(ref_name):
            matches.append((ref_name.removeprefix("origin/"), oid))
    matches.sort(key=lambda pair: pair[0])
    return matches, None


def _resolve_oid(working_dir: Path, ref: str) -> tuple[str | None, str | None]:
    """Resolve ``ref`` to its commit OID via
    ``git rev-parse --verify <ref>^{commit}``, WITHOUT ``-q``.

    EXIT-0 CONTRACT: this command's only valid answer is exit 0 with the OID
    on stdout -- there is no valid "the ref is absent" outcome the way
    ``rev-parse --verify -q <ref>:<path>`` had (that ambiguity is exactly
    what this round removes). WITHOUT ``-q``, a missing ref is ALWAYS a hard
    git failure (non-zero exit, typically 128); ANY non-zero exit maps to
    undetermined, decided by the exit code ALONE -- never by inspecting
    whether stderr happens to be empty or not.
    """
    rev_arg = f"{ref}^{{commit}}"
    code, out, stderr = _run_git(["rev-parse", "--verify", rev_arg], working_dir)
    if code == 0:
        return out.strip(), None
    return None, (
        f"{_IN_FLIGHT_UNDETERMINED_PREFIX}git rev-parse --verify {rev_arg} "
        f"failed (exit {code}): {stderr}"
    )


def _is_ancestor_of_main(
    working_dir: Path, branch_oid: str, main_oid: str
) -> tuple[bool, str | None]:
    """True iff ``branch_oid`` is an ancestor of ``main_oid``, via
    ``git rev-list -1 <branch_oid> ^<main_oid>`` -- OIDs ONLY, never a ref
    name (acceptance criterion (c), READ-ONCE: both OIDs were already
    resolved once, by ``_list_remote_governance_candidates_for_slug`` and
    ``_resolve_oid`` respectively).

    EXIT-0 CONTRACT: ``rev-list``'s only valid answers are exit 0 -- with
    EMPTY stdout when every commit reachable from ``branch_oid`` is also
    reachable from ``main_oid`` (branch_oid is an ancestor: merged), or with
    NON-EMPTY stdout otherwise (not an ancestor: still in flight, pending the
    squash-content signal). ANY non-zero exit -- a bad OID, exit 137 from a
    killed process (always empty stderr), or a masked ``_run_git`` timeout on
    THIS call (exit 1, "git command timed out" -- the exact CRS/CE finding
    this round closes) -- maps to undetermined, decided by the exit code
    alone.
    """
    code, out, stderr = _run_git(["rev-list", "-1", branch_oid, f"^{main_oid}"], working_dir)
    if code != 0:
        return False, (
            f"{_IN_FLIGHT_UNDETERMINED_PREFIX}git rev-list -1 {branch_oid} ^{main_oid} "
            f"failed (exit {code}): {stderr}"
        )
    return not out.strip(), None


def _ls_tree_blob(working_dir: Path, oid: str, target_path: str) -> tuple[str | None, str | None]:
    """Resolve the blob OID for ``target_path`` inside the tree of commit
    ``oid``, via ``git ls-tree <oid> -- <target_path>`` -- an OID, never a
    ref name.

    EXIT-0 CONTRACT: ``ls-tree`` against a valid commit OID always exits 0,
    whether or not ``target_path`` exists in that tree (an empty match is not
    an error -- it is a measured "no record here"). ANY non-zero exit (e.g.
    an invalid/unreadable ``oid``) maps to undetermined, decided by the exit
    code alone.

    Returns ``(blob_oid, error)``: ``(None, None)`` when the path has no
    entry (measured miss, not a failure); ``(blob_oid, None)`` when it does
    (parsed from the ``<mode> <type> <blob-oid>\t<path>`` line); ``(None,
    error)`` on a non-zero exit.
    """
    code, out, stderr = _run_git(["ls-tree", oid, "--", target_path], working_dir)
    if code != 0:
        return None, (
            f"{_IN_FLIGHT_UNDETERMINED_PREFIX}git ls-tree {oid} -- {target_path} "
            f"failed (exit {code}): {stderr}"
        )
    out = out.strip()
    if not out:
        return None, None
    parts = out.split()
    if len(parts) < 3:
        return None, (
            f"{_IN_FLIGHT_UNDETERMINED_PREFIX}git ls-tree {oid} -- {target_path} "
            f"produced unparseable output: {out!r}"
        )
    return parts[2], None


def find_in_flight_branches(
    working_dir: Path, token: str, target_path: str | None = None
) -> tuple[list[str], str | None]:
    """Fetch fresh remote state, then find UNMERGED origin governance branches
    for ``token``'s slug (any date prefix -- covers both the same-day push
    collision and the later-day second-PR case, issue #173).

    ``target_path`` is the TOKEN's own canonical record path (repo-relative),
    used ONLY for the strategy-independent merged signal (``_ls_tree_blob``
    on both the candidate's and main's OID), evaluated PER CANDIDATE BRANCH,
    NEVER as a token-wide short-circuit.

    ``target_path=None`` POLICY (unchanged from round 3): rejected at the
    boundary, ONCE, but ONLY when there is at least one candidate branch to
    evaluate. Without ``target_path`` the content-match signal can never run
    for ANY candidate, so a squash/rebase-merged branch could never be ruled
    out. Scoped to fire ONLY when ``candidates`` is non-empty: a
    ZERO-candidate result is a fully MEASURED "nothing in flight" (reached
    via ref-enumeration alone) regardless of ``target_path``.

    Returns ``(branch_names, error)``. FAILS CLOSED: ``error`` is non-None,
    prefixed ``IN_FLIGHT_UNDETERMINED: ``, whenever ANY git call on the
    detection path returned non-zero (fetch, ref-enumeration, main's OID
    resolution, an ancestry check, or a blob check), or ``target_path`` is
    missing with candidates present; in that case ``branch_names`` is always
    ``[]`` and the caller MUST NOT read that empty list as "nothing in
    flight." Every DETERMINED in-flight result NAMES the branch(es)
    (acceptance criterion (d)).
    """
    fetch_err = _fetch_origin(working_dir)
    if fetch_err:
        return [], fetch_err

    slug = _token_to_slug(token)
    candidates, list_err = _list_remote_governance_candidates_for_slug(working_dir, slug)
    if list_err:
        return [], list_err

    if candidates and not target_path:
        return [], (
            f"{_IN_FLIGHT_UNDETERMINED_PREFIX}target_path is required to evaluate "
            f"{len(candidates)} candidate branch(es) for merged status (the "
            "content-match signal cannot run without it, so a squash/rebase-"
            "merged branch could not be ruled out)"
        )

    if not candidates:
        return [], None

    main_oid, main_oid_err = _resolve_oid(working_dir, "origin/main")
    if main_oid_err:
        return [], main_oid_err
    assert main_oid is not None  # guaranteed by the error contract above

    # target_path is guaranteed non-None here (candidates is non-empty, and
    # the boundary check above already rejected target_path=None in that
    # case).
    assert target_path is not None
    return _classify_in_flight_candidates(working_dir, candidates, main_oid, target_path)


def _classify_in_flight_candidates(
    working_dir: Path, candidates: list[tuple[str, str]], main_oid: str, target_path: str
) -> tuple[list[str], str | None]:
    """Return the candidates that are NOT merged into ``main_oid`` (OIDs only).

    Shared by ``find_in_flight_branches`` and ``find_in_flight_branches_at_oid``
    (issue #203 S2): main's blob is resolved ONCE, then each candidate is
    classified by ancestry and by the per-branch content-match signal. Same
    exit-0 contract: any non-zero exit returns ``([], error)``.
    """
    main_blob_oid, main_blob_err = _ls_tree_blob(working_dir, main_oid, target_path)
    if main_blob_err:
        return [], main_blob_err

    in_flight: list[str] = []
    for branch_name, branch_oid in candidates:
        is_ancestor, ancestor_err = _is_ancestor_of_main(working_dir, branch_oid, main_oid)
        if ancestor_err:
            return [], ancestor_err
        if is_ancestor:
            continue

        branch_blob_oid, branch_blob_err = _ls_tree_blob(working_dir, branch_oid, target_path)
        if branch_blob_err:
            return [], branch_blob_err

        if main_blob_oid is not None and branch_blob_oid == main_blob_oid:
            continue  # this branch's OWN content matches main: squash-merged

        in_flight.append(branch_name)

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


def find_in_flight_branches_at_oid(
    working_dir: Path, token: str, target_path: str, main_oid: str
) -> tuple[list[str], str | None]:
    """In-flight detection against an ALREADY-resolved ``main_oid`` (issue #203 S2).

    The append_ruling path fetches and resolves ``origin/main`` exactly once
    (``read_append_base``); this check reuses that OID, so it neither fetches
    nor reads ``origin/main`` by name. Candidates are the token's creation
    branches AND its append branches (``governance/<date>-<slug>-r<n>``); the
    merged classification is ``find_in_flight_branches``' own, shared.
    """
    candidates, list_err = _list_remote_governance_candidates_for_slug(
        working_dir, _token_to_slug(token), include_append_branches=True
    )
    if list_err:
        return [], list_err
    if not candidates:
        return [], None
    return _classify_in_flight_candidates(working_dir, candidates, main_oid, target_path)


def check_in_flight_at_oid(
    working_dir: Path,
    token: str,
    target_path: str,
    main_oid: str,
    gh_token: str | None = None,
) -> dict[str, Any]:
    """``check_in_flight_token``'s structured shape, evaluated at ``main_oid``."""
    branches, error = find_in_flight_branches_at_oid(working_dir, token, target_path, main_oid)
    if error:
        return {
            "in_flight": None,
            "branches": [],
            "pr_urls": {},
            "pr_lookup_error": None,
            "error": error,
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


# Stable prefix (issue #178) so a commit-hook rejection is distinguishable,
# by callers and by grep, from every other commit failure this function can
# return (a failed `git add`, or a `git commit` failure that isn't a hook --
# e.g. "nothing to commit", a missing git identity, a stale `index.lock`).
# "Named" per the operator's ruling: where the hook's own output is
# parseable (the `pre-commit` framework's failure-summary format,
# `- hook id: <id>`), the id is embedded in the message too.
#
# ASSERTS ONLY WHAT WAS MEASURED (pre-review fix, PR #191 -- the same lesson
# as PR #179's measured-vs-undetermined distinction): this prefix is applied
# IF AND ONLY IF a pre-commit hook was ACTUALLY PRESENT AND EXECUTABLE at the
# path git resolves for the worktree the commit ran in (see
# ``_has_executable_precommit_hook``) at the moment of the failed commit. A
# commit can fail for reasons that have nothing to do with any hook --
# "nothing to commit", a missing identity, a stale ``index.lock`` -- and
# attributing those to a hook that never ran would be exactly the kind of
# asserted-not-measured claim issue #179 spent three rounds eliminating from
# this same file's in-flight detection. When no hook is present (or hook
# presence could not be determined), the ORIGINAL, un-prefixed
# ``"git commit failed: ..."`` shape is returned unchanged.
_GOVERNANCE_COMMIT_HOOK_FAILED_PREFIX = "GOVERNANCE_COMMIT_HOOK_FAILED: "

_PRE_COMMIT_HOOK_ID_RE = re.compile(r"^- hook id: (\S+)", re.MULTILINE)


def _has_executable_precommit_hook(worktree_path: Path) -> bool:
    """True iff a ``pre-commit`` hook is PRESENT and EXECUTABLE at the path
    git itself would actually run a commit's hook from, inside
    ``worktree_path``.

    Resolved via ``git rev-parse --git-path hooks/pre-commit``, run FROM
    ``worktree_path`` so it reflects THAT worktree's config -- verified
    empirically with git 2.52.0 that this HONOURS ``core.hooksPath`` (a
    custom hooks path set on the repo is reflected immediately in the
    resolved path) and returns a path RELATIVE to the invoking cwd when no
    absolute override is configured (git's default ``.git/hooks/...`` is
    returned as the bare relative string ``".git/hooks/pre-commit"``, not an
    absolute path) -- so a relative result is joined onto ``worktree_path``
    here before checking it.

    A present-but-NON-EXECUTABLE hook file is treated as ABSENT: verified
    empirically with git 2.52.0 that git itself silently skips (does not
    run, does not warn, does not fail) a hook file that exists but lacks the
    executable bit -- so attributing a commit failure to that file would
    claim a hook ran when it structurally could not have.

    If the ``git rev-parse`` call itself fails, this returns ``False``
    (fail-safe: an unresolvable hook path can never be asserted as "a hook
    is present" -- the caller then correctly reports a plain, un-attributed
    commit failure rather than guessing).
    """
    code, out, _ = _run_git(["rev-parse", "--git-path", "hooks/pre-commit"], worktree_path)
    if code != 0:
        return False
    hook_path = Path(out.strip())
    if not hook_path.is_absolute():
        hook_path = worktree_path / hook_path
    return hook_path.is_file() and os.access(hook_path, os.X_OK)


def _format_commit_failure(combined_output: str, *, hook_present: bool) -> str:
    """Format a ``git commit`` failure.

    ``hook_present`` (measured by ``_has_executable_precommit_hook`` BEFORE
    the commit ran, from the SAME worktree the commit ran in) decides the
    shape:
      - ``True``  -- a hook was actually present and executable, so a
        rejection is attributed to it: the structured, NAMED
        ``GOVERNANCE_COMMIT_HOOK_FAILED:``-prefixed error (issue #178),
        carrying ``combined_output`` (the commit's stdout+stderr, in that
        order -- where a rejecting hook's own message lives, whether the
        rejection is an ENVIRONMENT problem, e.g. missing
        ``.venv/bin/python``, or a CONTENT problem, e.g. issue #166's
        canonical-paths validator) and, where parseable (the ``pre-commit``
        framework's ``- hook id: <id>`` failure-summary line), the hook's
        own id.
      - ``False`` -- no hook was present (or its presence could not be
        determined): the ORIGINAL, un-prefixed ``"git commit failed: ..."``
        shape, UNCHANGED, so ``"nothing to commit"``, a missing identity, a
        stale ``index.lock``, etc. are never misattributed to a hook.

    Preserves the substring ``"git commit failed"`` in BOTH shapes, for
    byte-compatibility with pre-existing tests/callers that already grep
    for it.
    """
    if not hook_present:
        return f"git commit failed: {combined_output}"
    hook_id_match = _PRE_COMMIT_HOOK_ID_RE.search(combined_output)
    if hook_id_match:
        hook_id = hook_id_match.group(1)
        return (
            f"{_GOVERNANCE_COMMIT_HOOK_FAILED_PREFIX}git commit failed "
            f"(hook '{hook_id}'): {combined_output}"
        )
    return f"{_GOVERNANCE_COMMIT_HOOK_FAILED_PREFIX}git commit failed: {combined_output}"


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

    Staging is ALWAYS by EXPLICIT relative path (never ``git add -A`` /
    ``git add .``) -- this is the load-bearing invariant (issue #178) that
    keeps a caller's ``.venv`` symlink, if ``_link_caller_venv_into_worktree``
    created one in this same worktree, from EVER being staged or committed:
    it is never named in any ``git add`` call here, so it structurally
    cannot appear in the commit.

    The final ``git commit`` NEVER uses ``--no-verify`` (issue #178): unlike
    ``_push_branch``'s push, which bypasses hooks that make no sense from an
    ephemeral worktree, the commit-side hooks are exactly the mechanism
    issue #166's defect class exists to enforce, so they must run for real.
    A failure here is reported via ``_format_commit_failure`` -- a
    structured, ``GOVERNANCE_COMMIT_HOOK_FAILED:``-prefixed error naming the
    hook where parseable.

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

    # Measured BEFORE the commit runs, from the SAME worktree: whether a
    # rejection can be attributed to a hook must reflect what was actually
    # there, not be asserted after the fact (issue #178 pre-review fix).
    hook_present = _has_executable_precommit_hook(working_dir)

    code, out, stderr = _run_git(["commit", "-m", commit_message], working_dir)
    if code != 0:
        combined_output = "\n".join(part for part in (out, stderr) if part)
        return _format_commit_failure(combined_output, hook_present=hook_present)
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

    return _gh_pr_create(working_dir, title, body, gh_token)


def _gh_pr_create(
    working_dir: Path, title: str, body: str, gh_token: str | None
) -> tuple[str | None, str | None]:
    """Run ``gh pr create`` against the pinned ``main`` base (never caller-chosen).

    Returns (pr_url, error_message). One of the two is always None.
    """
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

    # 1b. Symlink the caller's .venv (if any) into the throwaway worktree
    #     BEFORE the commit, so the target repo's own hooks can find a real
    #     interpreter (issue #178). Best-effort, no error path: see
    #     _link_caller_venv_into_worktree and the module docstring's
    #     COMMIT-SIDE HOOKS note.
    _link_caller_venv_into_worktree(working_dir, worktree_path)

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

        # 2a. Read-back (EPIC4 PR-5, hc #220 item 5): the bytes on disk must be a record
        #     the reader accepts. ``read_record`` re-reads a YAML record as RAW bytes, so
        #     a newline-folding write can never commit a record the reader would reject.
        #     Only for a YAML target (``.md``); OCTAVE targets are unchanged.
        if (
            not errors
            and target_in_wt.suffix == ".md"
            and not target_in_wt.name.endswith(".oct.md")
        ):
            try:
                written = read_record(target_in_wt)
            except OSError as exc:
                errors.append(f"read-back of {rels[0]} failed: {exc}")
            else:
                if written.syntax != "yaml" or written.diagnostic is not None:
                    reject = written.diagnostic
                    detail = (
                        f"line {reject['line']}: {reject['construct']}"
                        if reject
                        else "not a YAML front-matter record"
                    )
                    errors.append(f"read-back of {rels[0]} rejected by the reader ({detail})")

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


# ---------------------------------------------------------------------------
# append_ruling on merged topic records (issue #203 S2)
#
# The #173 slice-1 OID shape, applied to the append broker (ADR-RFC-ARCH-004
# §3.5, narrowed): fetch ONCE, resolve ``origin/main`` to an OID ONCE, then
# every read -- locating the record, reading its blob, the in-flight check, and
# the worktree the branch is cut from -- takes that OID, never a ref name.
# Every git call here is one whose valid answers all exit 0 (``fetch``,
# ``rev-parse --verify <ref>^{commit}``, ``ls-tree -r -z <oid>``,
# ``cat-file --batch``), so ANY non-zero exit means "undetermined" and the
# read refuses. stderr content never decides a branch of the code.
#
# The linker only locates, reads and writes bytes: whether the record is a YAML
# topic record, and the rendering, belong to ``topic_append`` (the caller).
# ---------------------------------------------------------------------------

_BASE_UNDETERMINED_PREFIX = "BASE_UNDETERMINED: "
_DECISIONS_DIR = ".hestai/decisions"
_CONCEPTS_DIR = ".hestai/context/concepts"


@dataclass(frozen=True)
class AppendBase:
    """The record as it stands at the ``origin/main`` OID.

    On success ``error_code`` is None, ``data`` holds the blob's exact bytes and
    ``from_record_hash`` their ``sha256:<hex>`` (ADR-RFC-ARCH-004 §1.1: the hash
    of the whole file). On failure ``error_code`` names the refusal
    (``BASE_UNDETERMINED``, ``TOKEN_NOT_FOUND_AT_MAIN``, ``TOKEN_AMBIGUOUS_AT_MAIN``)
    and the record fields are None; ``main_oid`` is kept whenever it was resolved.
    """

    main_oid: str | None = None
    path: str | None = None
    data: bytes | None = None
    from_record_hash: str | None = None
    error_code: str | None = None
    error: str | None = None


def _undetermined(message: str, main_oid: str | None = None) -> AppendBase:
    return AppendBase(
        main_oid=main_oid,
        error_code="BASE_UNDETERMINED",
        error=f"{_BASE_UNDETERMINED_PREFIX}{message}",
    )


def _list_decision_blobs(working_dir: Path, oid: str) -> tuple[list[tuple[str, str]], str | None]:
    """``(blob_oid, path)`` for every ``*.md`` (``.oct.md`` included) under the
    decisions and concepts dirs at ``oid`` (one ``ls-tree``); which of them are
    records, or TOKEN matches, is decided on content."""
    code, out, stderr = _run_git_bytes(
        ["ls-tree", "-r", "-z", oid, "--", _DECISIONS_DIR, _CONCEPTS_DIR], working_dir
    )
    if code != 0:
        return [], (
            f"git ls-tree -r -z {oid} -- {_DECISIONS_DIR} {_CONCEPTS_DIR} "
            f"failed (exit {code}): {stderr}"
        )
    blobs: list[tuple[str, str]] = []
    for raw in out.split(b"\0"):
        if not raw:
            continue
        meta, _, path_bytes = raw.partition(b"\t")
        parts = meta.split()
        if len(parts) != 3 or not path_bytes:
            return [], f"git ls-tree -r -z {oid} produced an unparseable entry: {raw!r}"
        path = path_bytes.decode("utf-8", "replace")
        if parts[1] == b"blob" and path.endswith(".md"):
            blobs.append((parts[2].decode("ascii", "replace"), path))
    return blobs, None


def _read_blobs(working_dir: Path, blob_oids: list[str]) -> tuple[list[bytes], str | None]:
    """Read every blob in ONE ``git cat-file --batch`` call, as exact bytes."""
    if not blob_oids:
        return [], None
    stdin = "".join(f"{oid}\n" for oid in blob_oids).encode("ascii")
    code, out, stderr = _run_git_bytes(["cat-file", "--batch"], working_dir, stdin)
    if code != 0:
        return [], f"git cat-file --batch failed (exit {code}): {stderr}"
    contents: list[bytes] = []
    pos = 0
    for oid in blob_oids:
        eol = out.find(b"\n", pos)
        if eol < 0:
            return [], f"git cat-file --batch output ended before blob {oid}"
        header = out[pos:eol].split()
        if len(header) != 3 or header[1] != b"blob" or not header[2].isdigit():
            return [], f"git cat-file --batch could not read blob {oid}: {out[pos:eol]!r}"
        size = int(header[2])
        start = eol + 1
        if len(out) < start + size:
            return [], f"git cat-file --batch output truncated for blob {oid}"
        contents.append(out[start : start + size])
        pos = start + size + 1  # skip the LF that terminates each object
    return contents, None


def _declares_at_main(path: str, data: bytes, token: str) -> bool:
    """True iff the blob at ``path`` is a record that declares ``token`` (strict pairing).

    Mirrors the readers (ADR-RFC-ARCH-004 §1.1): a ``.oct.md`` is read only as OCTAVE
    (YAML front matter in one is not a record) and any other ``.md`` only as a YAML
    record carrying the ``type:`` DECISION_RECORD header, so READMEs and ADR prose
    never count. A YAML record that does not parse is still located by its ``token:``
    line, so the caller can refuse it loudly instead of reporting it missing.
    """
    record = classify_record_text(data)
    if path.endswith(".oct.md"):
        return record.syntax == "octave" and declares_token(record.text, token)
    return (
        record.syntax == "yaml"
        and has_yaml_decision_header(record.text)
        and declares_token(record.text, token)
    )


def _matches_token_at_main(path: str, data: bytes, token: str) -> bool:
    """True iff the record file at ``path`` could collide with ``token``: it declares it,
    or is named for it. Only ``.md`` / ``.oct.md`` blobs under decisions and concepts
    reach here (``_list_decision_blobs``): the file types ``lookup_token_deterministic``
    scans (HC ruling B), plus ``.md`` under concepts, which that lookup does not read.

    Deliberately broader than the lexer's lookup, so it fails closed. "Declares" is
    exactly ``lexer.declares_token`` on the blob's text, with NO parse requirement and
    NO extension pairing: text opening with a ``---`` fence declares only through its
    fenced ``token:`` line AND the ``type:`` DECISION_RECORD header; any other text (a
    header-less ``.md`` included) declares through a top-level ``TOKEN::`` / ``ID::``
    line. So an unparseable or mis-paired twin, or a header-less ``.md`` with a
    ``TOKEN::`` line, still counts; a fenced ``token:`` without the header does not. A
    same-name file counts whatever it holds. MANIFEST rows are not consulted. It is never a substring test: a record that
    only cites the TOKEN (``AMENDS``, ``RELATED_DECISIONS``, prose) does not match.
    """
    name = path.rsplit("/", 1)[-1]
    if name in (f"{token}.md", f"{token}.oct.md"):
        return True
    return declares_token(classify_record_text(data).text, token)


def read_append_base(working_dir: Path, token: str) -> AppendBase:
    """Fetch, resolve ``origin/main`` ONCE, and read ``token``'s record at that OID.

    The record is located by its TOP-LEVEL TOKEN declaration among the decision
    blobs in the main tree -- never the caller's local tree -- with the readers'
    strict extension pairing (``_declares_at_main``), and its blob bytes are
    hashed for the ADR-RFC-ARCH-004 §1.1/§3.5 CAS.

    TOKEN uniqueness is judged HERE, at the same OID the branch is cut from
    (CE 6538573589): any other record file (``.md`` / ``.oct.md``) under decisions
    or concepts that declares the TOKEN or is named for it, by the deliberately
    broader rule of ``_matches_token_at_main``, refuses the append as
    ``TOKEN_AMBIGUOUS_AT_MAIN``, naming every match. Non-record files and MANIFEST
    rows are not consulted. The caller's checkout cannot hide a twin that main holds.
    """
    fetch_err = _fetch_origin(working_dir)
    if fetch_err:
        return _undetermined(fetch_err.removeprefix(_IN_FLIGHT_UNDETERMINED_PREFIX))
    main_oid, oid_err = _resolve_oid(working_dir, _BASE_REF)
    if oid_err or main_oid is None:
        return _undetermined((oid_err or "").removeprefix(_IN_FLIGHT_UNDETERMINED_PREFIX))

    blobs, list_err = _list_decision_blobs(working_dir, main_oid)
    if list_err:
        return _undetermined(list_err, main_oid)
    contents, read_err = _read_blobs(working_dir, [blob for blob, _ in blobs])
    if read_err:
        return _undetermined(read_err, main_oid)

    listed = list(zip((path for _, path in blobs), contents, strict=True))
    matches = [
        (path, data)
        for path, data in listed
        if path.startswith(f"{_DECISIONS_DIR}/") and _declares_at_main(path, data, token)
    ]
    # Critical-Engineer: consulted for governance record uniqueness and pinned-main validation
    colliding = sorted(path for path, data in listed if _matches_token_at_main(path, data, token))
    if not matches:
        return AppendBase(
            main_oid=main_oid,
            error_code="TOKEN_NOT_FOUND_AT_MAIN",
            error=(
                f"TOKEN '{token}' is not declared by any record under {_DECISIONS_DIR} "
                f"at origin/main ({main_oid}); append_ruling amends merged records only."
            ),
        )
    if len(matches) > 1 or len(colliding) > 1:
        return AppendBase(
            main_oid=main_oid,
            error_code="TOKEN_AMBIGUOUS_AT_MAIN",
            error=(
                f"TOKEN '{token}' matches {len(colliding)} files at origin/main "
                f"({', '.join(colliding)}): each declares the TOKEN or is named for it. "
                "append_ruling rewrites a TOKEN's only file; resolve the duplicate first."
            ),
        )
    path, data = matches[0]
    return AppendBase(main_oid=main_oid, path=path, data=data, from_record_hash=record_hash(data))


def compute_append_branch_name(token: str, first_new_n: int) -> str:
    """``governance/<UTC-date>-<token-slug>-r<first-new-n>`` (issue #203 S2)."""
    date_str = datetime.now(UTC).strftime("%Y%m%d")
    return f"governance/{date_str}-{_token_to_slug(token)}-r{first_new_n}"


def build_append_pr_body(
    *,
    token: str,
    pairs: list[dict[str, str]],
    replaced_ids: list[str],
    from_record_hash: str,
    to_record_hash: str,
    base_oid: str,
) -> str:
    """PR body for an append: each RULE plus its VERBATIM quoted line by line."""
    lines = [
        "## Governance append -- append_ruling (#203 S2)",
        "",
        f"- **Token**: `{token}`",
        f"- **Base**: origin/main @ `{base_oid}`",
        f"- **from_record_hash**: `{from_record_hash}`",
        f"- **to_record_hash**: `{to_record_hash}`",
        f"- **Appended**: {', '.join(p['id'] for p in pairs)}",
        f"- **Replaced**: {', '.join(replaced_ids) if replaced_ids else 'none'}",
        "",
    ]
    for pair in pairs:
        lines += [f"### {pair['id']}", "", f"**RULE**: {pair['rule']}", "", "**VERBATIM**:", ""]
        lines += [f"> {ln}" if ln else ">" for ln in pair["verbatim"].splitlines() or [""]]
        lines.append("")
    lines += [
        "Rendered deterministically through the canonical YAML emitter (the content-mode "
        "write path): no LLM, no compiler, and each VERBATIM reads back byte-exact. "
        "In-flight append is slice S3; the merge-time staleness recheck is slice S4.",
        "",
    ]
    return "\n".join(lines)


def _create_worktree_at_oid(
    working_dir: Path, branch_name: str, oid: str
) -> tuple[Path | None, str | None]:
    """Throwaway worktree on a fresh ``branch_name`` cut from ``oid`` (no fetch).

    Unlike ``_create_worktree`` this neither fetches nor names ``origin/main``:
    the append was rendered against ``oid``, so the branch must start there
    even if the remote-tracking ref has since moved.
    """
    parent = Path(tempfile.mkdtemp(prefix="hestai-governance-"))
    worktree_path = parent / "worktree"
    code, _, stderr = _run_git(
        ["worktree", "add", "-b", branch_name, str(worktree_path), oid], working_dir
    )
    if code != 0:
        shutil.rmtree(parent, ignore_errors=True)
        return None, f"Failed to create governance worktree for '{branch_name}': {stderr}"
    return worktree_path, None


def _read_back_error(written: Path, target_path: str) -> str | None:
    """Re-read the written file as RAW bytes; an error unless the reader accepts it.

    The same read-back ``run_linker`` applies to a YAML target (EPIC4 PR-5), so an
    append can never commit a record the reader would reject.
    """
    try:
        record = read_record(written)
    except OSError as exc:
        return f"read-back of {target_path} failed: {exc}"
    if record.syntax == "yaml" and record.diagnostic is None:
        return None
    reject = record.diagnostic
    detail = f"line {reject['line']}: {reject['construct']}" if reject else "not a YAML record"
    return f"read-back of {target_path} rejected by the reader ({detail})"


def _open_append_pr(
    working_dir: Path, title: str, body: str, gh_token: str | None
) -> tuple[str | None, str | None]:
    """Open the append PR against the pinned ``main`` base."""
    return _gh_pr_create(working_dir, title, body, gh_token)


def run_append_linker(
    working_dir: Path,
    *,
    token: str,
    target_path: str,
    main_oid: str,
    record_text: str,
    branch_name: str,
    appended_ids: list[str],
    pr_body: str,
    gh_token: str | None = None,
) -> dict[str, Any]:
    """Commit ``record_text`` at ``target_path`` on a branch cut from ``main_oid``; open one PR.

    Mirrors ``run_linker``'s hermetic worktree discipline: the operator's tree
    and HEAD are never touched, the worktree is always removed, and a branch
    that never reached origin is rolled back. MANIFEST is not rewritten (the
    TOKEN already exists). Returns ``{token, target_path, branch, pr_url,
    head_sha, error}``; ``branch`` is non-None only once the push succeeded.
    """
    result: dict[str, Any] = {
        "token": token,
        "target_path": target_path,
        "branch": None,
        "pr_url": None,
        "head_sha": None,
        "error": None,
    }
    try:
        rel = (working_dir / target_path).resolve().relative_to(working_dir.resolve())
    except (ValueError, RuntimeError, OSError):
        rel = None
    if rel is None or Path(target_path).is_absolute():
        result["error"] = (
            f"target_path {target_path} is outside working_dir {working_dir} "
            "-- path traversal rejected"
        )
        return result

    worktree_path, err = _create_worktree_at_oid(working_dir, branch_name, main_oid)
    if err:
        result["error"] = err
        return result
    assert worktree_path is not None
    _link_caller_venv_into_worktree(working_dir, worktree_path)

    pushed_ok = False
    try:
        target_in_wt = worktree_path / rel
        try:
            target_in_wt.write_bytes(record_text.encode("utf-8"))
        except OSError as exc:
            result["error"] = f"Failed to write {target_in_wt}: {exc}"
            return result
        err = _read_back_error(target_in_wt, target_path)
        if err:
            result["error"] = err
            return result

        commit_message = f"chore(governance): append ruling(s) {', '.join(appended_ids)} to {token}"
        err = _git_add_and_commit(
            worktree_path,
            target_in_wt,
            worktree_path / ".hestai" / "MANIFEST.md",
            commit_message,
        )
        if err:
            result["error"] = err
            return result
        head_sha, head_err = _resolve_oid(worktree_path, "HEAD")
        if head_err or head_sha is None:
            # Exit-0 contract: the commit just made cannot be identified, so nothing
            # is pushed or opened (CE 6538361209).
            detail = (head_err or "").removeprefix(_IN_FLIGHT_UNDETERMINED_PREFIX)
            result["error"] = (
                f"LINKER_FAILED: git rev-parse HEAD after the append commit failed; "
                f"nothing was pushed. {detail}".rstrip()
            )
            return result
        result["head_sha"] = head_sha

        err = _push_branch(worktree_path, branch_name)
        if err:
            result["error"] = err
            return result
        pushed_ok = True
        result["branch"] = branch_name

        pr_url, pr_err = _open_append_pr(
            worktree_path, f"feat(governance): append ruling(s) to {token}", pr_body, gh_token
        )
        result["pr_url"] = pr_url
        result["error"] = pr_err
        return result
    finally:
        _remove_worktree(working_dir, worktree_path)
        if not pushed_ok:
            _delete_branch(working_dir, branch_name)
