"""Git Orchestrator (Linker) for governance intake.

Accepts a ValidationResult + raw OCTAVE content, then:
  1. Creates branch: governance/{date}-{token-slug}
  2. Writes OCTAVE content to the computed target_path
  3. Commits with: chore(governance): add {token} [{card_type}]
  4. Updates MANIFEST (write_manifest)
  5. Pushes the branch to origin (git push -u origin <branch>)
  6. Opens PR via gh pr create

dry_run=True: skips all git/file operations, returns what WOULD happen.

GitHub token resolution is provided by the shared single-source-of-truth helper
``tools.shared.github_auth`` (extracted to remove the CIV-flagged duplication
that previously copied this logic from submit_review). It is re-exported here as
``_resolve_github_token`` so ``run_linker`` resolves it as a module global
(patchable in tests).
"""

import logging
import os
import subprocess
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


# Branches the global worktree-discipline pre-commit hook protects. A commit on
# one of these, from a MAIN working tree (not a worktree), is blocked.
_PROTECTED_BRANCHES = frozenset({"main", "master"})


def _preflight_commit_safety(working_dir: Path) -> str | None:
    """Return a recovery error iff committing here would be blocked, else None.

    #108.3: the global worktree-discipline pre-commit hook
    (``~/.githooks/pre-commit``) blocks a commit when ALL of the following hold:

      1. ``working_dir`` is a MAIN working tree -- NOT a linked worktree. Git
         reports the same path for ``--git-dir`` and ``--git-common-dir`` in a
         main tree; a linked worktree's ``--git-dir`` is ``.git/worktrees/<name>``
         and differs from the common dir.
      2. the current branch is a protected branch (``main``/``master``).
      3. an executable ``pre-commit`` hook is actually installed at the repo's
         effective ``core.hooksPath`` (so a repo with hooks disabled -- e.g. the
         isolated test fixture -- does NOT trip this guard).

    The hook also auto-reverts a ``git checkout -b`` back to the protected branch
    (a companion ``post-checkout`` hook), so the linker's own branch creation
    cannot escape the block from a main tree -- hence we MUST fail fast *before*
    creating a branch rather than relying on the checkout to move us off main.

    When this returns a non-None error the linker aborts before touching git, so
    no branch is created and nothing is staged (PROD::I4 structured failure with
    explicit recovery guidance). Returns ``None`` (proceed) whenever the path is
    not a git repo or any of conditions 1-3 do not hold -- including every linked
    worktree, which is the supported authoring location.
    """
    # Not a git repo (or git unavailable) -> cannot be a blocked main tree.
    code, git_dir, _ = _run_git(["rev-parse", "--absolute-git-dir"], working_dir)
    if code != 0 or not git_dir:
        return None
    code, common_dir, _ = _run_git(
        ["rev-parse", "--path-format=absolute", "--git-common-dir"], working_dir
    )
    if code != 0 or not common_dir:
        return None

    # (1) MAIN tree iff the per-worktree git-dir IS the common dir.
    if Path(git_dir).resolve() != Path(common_dir).resolve():
        return None  # linked worktree -> supported, never blocked.

    # (2) Protected branch only. A main tree on a feature branch commits fine.
    code, branch, _ = _run_git(["branch", "--show-current"], working_dir)
    if code != 0 or branch not in _PROTECTED_BRANCHES:
        return None

    # (3) An executable pre-commit hook must actually be installed at the repo's
    #     effective hooks path; a repo with hooks disabled does not block.
    code, hooks_dir, _ = _run_git(["rev-parse", "--git-path", "hooks"], working_dir)
    if code != 0 or not hooks_dir:
        return None
    hook_path = (working_dir / hooks_dir / "pre-commit").resolve()
    if not (hook_path.is_file() and os.access(hook_path, os.X_OK)):
        return None

    return (
        f"BLOCKED: cannot author governance from the main working tree on "
        f"'{branch}' -- the worktree-discipline pre-commit hook blocks commits "
        f"here. Author from a git worktree instead:\n"
        f"  git worktree add -b governance/your-record ../<repo>-governance main\n"
        f"  # then re-run submit_governance with working_dir pointed at that "
        f"worktree.\n"
        f"No branch was created and nothing was staged."
    )


def _create_branch(working_dir: Path, branch_name: str) -> str | None:
    """Create and checkout a new git branch.

    Returns an error string on failure, None on success.
    """
    code, _, stderr = _run_git(["checkout", "-b", branch_name], working_dir)
    if code != 0:
        return f"Failed to create branch '{branch_name}': {stderr}"
    return None


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

    # --- Live path: git operations ---
    errors: list[str] = []

    # 0. Pre-flight (#108.3): if committing here would be blocked by the
    #    worktree-discipline hook, fail fast BEFORE creating any branch so no
    #    orphan branch and no staged state is ever produced. Honours a worktree
    #    working_dir (which is the supported authoring location) unchanged.
    preflight_err = _preflight_commit_safety(working_dir)
    if preflight_err:
        # Aborted before branch creation: no branch, nothing staged.
        return {
            "token": token,
            "card_type": card_type,
            "target_path": target_path_str,
            "adr_target_path": adr_target_path_str,
            "branch": None,
            "pr_url": None,
            "error": preflight_err,
            "staged_uncommitted": False,
            "dry_run": False,
        }

    # 1. Create branch
    err = _create_branch(working_dir, branch_name)
    if err:
        # Branch creation itself failed: no branch, nothing staged.
        return {
            "token": token,
            "card_type": card_type,
            "target_path": target_path_str,
            "adr_target_path": adr_target_path_str,
            "branch": branch_name,
            "pr_url": None,
            "error": err,
            "staged_uncommitted": False,
            "dry_run": False,
        }

    # 2. Write OCTAVE content to target path
    if target_path is None:
        # Branch WAS created (surfaced via ``branch`` for recovery) but no write
        # or ``git add`` ran, so nothing is staged-uncommitted (contract: False).
        return {
            "token": token,
            "card_type": card_type,
            "target_path": None,
            "adr_target_path": adr_target_path_str,
            "branch": branch_name,
            "pr_url": None,
            "error": "target_path is None -- cannot write file",
            "staged_uncommitted": False,
            "dry_run": False,
        }

    # Bug 4: path traversal guard -- verify target_path is inside working_dir.
    # #112: the SAME guard is applied to the two-birds ADR path so a crafted
    # token/symlink cannot escape the repo. Both paths are checked here, BEFORE
    # any write, so a rejection writes/stages nothing.
    guard_paths = [target_path, *([adr_target_path] if adr_target_path is not None else [])]
    for guarded in guard_paths:
        try:
            guarded.resolve().relative_to(working_dir.resolve())
        except (ValueError, RuntimeError, OSError):
            # Branch WAS created (surfaced via ``branch``) but the write was
            # rejected before any ``git add``, so nothing is staged-uncommitted
            # (contract: False); recovery is conveyed by ``branch`` + ``error``.
            return {
                "token": token,
                "card_type": card_type,
                "target_path": target_path_str,
                "adr_target_path": adr_target_path_str,
                "branch": branch_name,
                "pr_url": None,
                "error": (
                    f"target_path {guarded} is outside working_dir {working_dir} "
                    "-- path traversal rejected"
                ),
                "staged_uncommitted": False,
                "dry_run": False,
            }

    err = _write_file(target_path, octave_content)
    if err:
        errors.append(err)

    # 2b. Two-birds (#112): dumb-write the VERBATIM ADR prose alongside the AGR.
    #     No AI, no OCTAVE, no provenance marker. Guarded above; written only
    #     when the AGR write succeeded so we never leave an orphan ADR doc.
    if not errors and adr_prose is not None and adr_target_path is not None:
        err = _write_file(adr_target_path, adr_prose)
        if err:
            errors.append(err)

    # 3. Update MANIFEST (best-effort -- failure is non-fatal, Bug 9 fix)
    if not errors:
        try:
            write_manifest(working_dir)
        except Exception as exc:  # noqa: BLE001
            # Log warning instead of appending to errors; MANIFEST failure
            # must not block the commit/PR flow (Bug 9: non-fatal).
            logger.warning("MANIFEST update failed (non-fatal): %s", exc)

    # 4. Commit
    commit_message = f"chore(governance): add {token} [{card_type}]"
    manifest_path = working_dir / ".hestai" / "MANIFEST.md"

    # Track commit failure explicitly. ``_git_add_and_commit`` stages (git add)
    # BEFORE committing, so a commit failure leaves changes staged-but-uncommitted
    # -- the ONLY state where ``staged_uncommitted`` is True. A successful commit,
    # or a step that never reached the commit (write/traversal failure: nothing
    # staged), is NOT staged-uncommitted.
    commit_failed = False
    if not errors:
        extra_paths = [adr_target_path] if adr_target_path is not None else None
        err = _git_add_and_commit(
            working_dir, target_path, manifest_path, commit_message, extra_paths=extra_paths
        )
        if err:
            errors.append(err)
            commit_failed = True

    # 5. Push branch to origin (REQUIRED before gh pr create -- issue #73).
    #    gh aborts PR creation if the branch is not on a remote. A push
    #    failure is a structured error (PROD I4) and skips PR creation.
    if not errors:
        err = _push_branch(working_dir, branch_name)
        if err:
            errors.append(err)

    # 6. Open PR
    pr_url: str | None = None
    if not errors:
        gh_token = _resolve_github_token()
        pr_url, pr_err = _open_pr(working_dir, branch_name, token, card_type, gh_token)
        if pr_err:
            errors.append(pr_err)

    error_str = "; ".join(errors) if errors else None

    # #108.3 orphan/partial-state surfacing (cubic P2 contract): the branch HAS
    # been created (step 1 succeeded) by this point. ``staged_uncommitted`` is
    # True IFF the commit itself failed -- i.e. changes were staged (git add) but
    # not committed. It is False whenever the commit succeeded, INCLUDING when a
    # later push (step 5) or PR-creation (step 6) failed: those are committed
    # states with a different recovery, already described by ``error``. The flag
    # stays literally "staged but not committed," matching its name.
    staged_uncommitted = commit_failed

    return {
        "token": token,
        "card_type": card_type,
        "target_path": target_path_str,
        "adr_target_path": adr_target_path_str,
        "branch": branch_name,
        "pr_url": pr_url,
        "error": error_str,
        "staged_uncommitted": staged_uncommitted,
        "dry_run": False,
    }
