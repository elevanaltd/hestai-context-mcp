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


def _git_add_and_commit(
    working_dir: Path,
    file_path: Path,
    manifest_path: Path,
    commit_message: str,
) -> str | None:
    """Stage the governance file + MANIFEST and commit.

    Returns an error string on failure, None on success.
    """
    # Stage the governance file
    try:
        rel = file_path.relative_to(working_dir)
    except ValueError:
        rel = file_path
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
) -> dict[str, Any]:
    """Execute the Git Orchestrator for a validated governance artifact.

    Args:
        working_dir: Project root directory.
        validation: Successful ValidationResult from type_checker.
        octave_content: Raw OCTAVE document text to commit.
        dry_run: If True, skip all git/file operations and return
                 what WOULD happen without touching disk or git.

    Returns:
        Dict with keys: token, card_type, target_path, branch,
        pr_url, error, dry_run.
    """
    token = validation.token or ""
    card_type = validation.card_type or ""
    target_path = validation.target_path

    branch_name = _compute_branch_name(token)
    try:
        target_path_str = str(target_path.relative_to(working_dir)) if target_path else None
    except ValueError:
        target_path_str = str(target_path) if target_path else None

    if dry_run:
        return {
            "token": token,
            "card_type": card_type,
            "target_path": target_path_str,
            "branch": branch_name,
            "pr_url": None,
            "error": None,
            "dry_run": True,
        }

    # --- Live path: git operations ---
    errors: list[str] = []

    # 1. Create branch
    err = _create_branch(working_dir, branch_name)
    if err:
        return {
            "token": token,
            "card_type": card_type,
            "target_path": target_path_str,
            "branch": branch_name,
            "pr_url": None,
            "error": err,
            "dry_run": False,
        }

    # 2. Write OCTAVE content to target path
    if target_path is None:
        return {
            "token": token,
            "card_type": card_type,
            "target_path": None,
            "branch": branch_name,
            "pr_url": None,
            "error": "target_path is None -- cannot write file",
            "dry_run": False,
        }

    # Bug 4: path traversal guard -- verify target_path is inside working_dir
    try:
        target_path.resolve().relative_to(working_dir.resolve())
    except (ValueError, RuntimeError, OSError):
        return {
            "token": token,
            "card_type": card_type,
            "target_path": target_path_str,
            "branch": branch_name,
            "pr_url": None,
            "error": (
                f"target_path {target_path} is outside working_dir {working_dir} "
                "-- path traversal rejected"
            ),
            "dry_run": False,
        }

    err = _write_file(target_path, octave_content)
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

    if not errors:
        err = _git_add_and_commit(working_dir, target_path, manifest_path, commit_message)
        if err:
            errors.append(err)

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

    return {
        "token": token,
        "card_type": card_type,
        "target_path": target_path_str,
        "branch": branch_name,
        "pr_url": pr_url,
        "error": error_str,
        "dry_run": False,
    }
