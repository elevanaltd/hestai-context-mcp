"""Git Orchestrator (Linker) for governance intake.

Accepts a ValidationResult + raw OCTAVE content, then:
  1. Creates a DEDICATED git worktree on a fresh ``governance/{date}-{token-slug}``
     branch based off ``origin/main`` (after a ``git fetch origin``)
  2. Writes OCTAVE content to the computed target_path INSIDE that worktree
  3. Commits with: chore(governance): add {token} [{card_type}]
  4. Updates MANIFEST (write_manifest)
  5. Pushes the branch to origin (git push -u origin <branch>)
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

import logging
import os
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

    Runs ``git push -u origin <branch>``. This MUST happen before
    ``gh pr create`` -- otherwise gh aborts with "you must first push the
    current branch to a remote" (issue #73).

    Returns an error string on failure, None on success. A push failure is
    surfaced as a structured error (PROD I4) and never swallowed.
    """
    code, _, stderr = _run_git(["push", "-u", "origin", branch_name], working_dir)
    if code != 0:
        return f"Failed to push branch '{branch_name}' to origin: {stderr}"
    return None


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
        dry_run, staged_uncommitted, and ``adr_target_path`` (the
        ``docs/adr/<token>.md`` path when ``adr_prose`` is supplied, else None).

        ``branch`` is the would-be branch name on ``dry_run``; on a live run it
        is non-None ONLY when the branch actually reached ``origin`` (a push
        succeeded), and None when a pre-push failure rolled the local branch back
        (no misleading name for a branch that was never persisted — issue #108).
        ``staged_uncommitted`` is always False on the live path: every git
        mutation happens inside a throwaway worktree that is always removed, so
        nothing is ever left staged in the operator's working tree.
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
        return {
            "token": token,
            "card_type": card_type,
            "target_path": target_path_str,
            "adr_target_path": adr_target_path_str,
            "branch": branch_name,
            "pr_url": None,
            "error": None,
            "staged_uncommitted": False,
            "dry_run": True,
        }

    # --- Live path: hermetic worktree git operations ---
    errors: list[str] = []

    # target_path is required before we touch git.
    if target_path is None:
        # Nothing created, nothing staged: no worktree, no branch.
        return {
            "token": token,
            "card_type": card_type,
            "target_path": None,
            "adr_target_path": adr_target_path_str,
            "branch": None,
            "pr_url": None,
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
            return {
                "token": token,
                "card_type": card_type,
                "target_path": target_path_str,
                "adr_target_path": adr_target_path_str,
                "branch": None,
                "pr_url": None,
                "error": (
                    f"target_path {guarded} is outside working_dir {working_dir} "
                    "-- path traversal rejected"
                ),
                "staged_uncommitted": False,
                "dry_run": False,
            }

    # 1. Create the dedicated worktree on a fresh branch off origin/main. The
    #    operator's own working tree (whatever branch it is on) is NEVER touched.
    worktree_path, err = _create_worktree(working_dir, branch_name)
    if err:
        # Worktree creation failed: nothing created, nothing staged.
        return {
            "token": token,
            "card_type": card_type,
            "target_path": target_path_str,
            "adr_target_path": adr_target_path_str,
            "branch": None,
            "pr_url": None,
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

        # 6. Open PR.
        if not errors:
            gh_token = _resolve_github_token()
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
        # Hermetic model: the worktree is always removed and nothing is ever
        # staged in the operator's working tree, so this is always False.
        # Retained for I4 shape stability.
        "staged_uncommitted": False,
        "error": error_str,
        "dry_run": False,
    }
