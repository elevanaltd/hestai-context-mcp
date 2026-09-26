"""RED: caller-.venv linking for the throwaway commit worktree (issue #178).

The linker commits inside a throwaway git worktree (`_create_worktree`) that
has no `.venv` -- any target repo whose pre-commit hooks shell out to
`.venv/bin/python` fails there with an environment error (e.g. exit 127),
never a content verdict, and no PR is ever opened.

Chosen design (operator ruling, option 2b): before the commit, if the
caller's `working_dir` has a `.venv`, symlink it into the throwaway
worktree root as `.venv` so the target repo's REAL hooks run against the
staged record. If a hook still fails (including when the caller has no
`.venv`), the commit is never skipped (`--no-verify` stays OFF) and the
failure surfaces as a structured, named error prefixed
`GOVERNANCE_COMMIT_HOOK_FAILED: `.

These are hermetic real-git fixtures: a bare "origin" plus a clone, with
repo-local git identity, `symbolic-ref HEAD refs/heads/main`, and an
EXPLICIT `core.hooksPath` pointed at the clone's own `.git/hooks` (so a
leaked global `~/.githooks` config can never intercept these tests, and the
REAL hook this file installs is the one that runs). No network, no real gh
(`_open_pr` is stubbed; everything else -- worktree, commit, push to the
bare origin -- runs for real).
"""

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from hestai_context_mcp.tools.governance.linker import run_linker
from hestai_context_mcp.tools.governance.type_checker import validate_octave_content

_LINKER = "hestai_context_mcp.tools.governance.linker"

_TOKEN = "HO-CONTEXT-MCP-HOOKS-20260926"

_DECISION_RECORD_OCTAVE = f"""\
===DECISION_RECORD===
META:
  TYPE::DECISION_RECORD
  VERSION::"1.0"
  TOKEN::"{_TOKEN}"
  STATUS::PROPOSED
  TIER::OPERATIONAL
  DECISION::"Test decision for commit-hook coverage."
  BECAUSE::"Required for TDD (issue #178)."
  AUTHORED_AT::"2026-09-26T00:00:00Z"
===END===
"""

# Mirrors HestAI-MCP's real `validate-namespaces` hook (issue #178): fails
# with exit 127 when `.venv/bin/python` is missing, otherwise runs it for
# real. Emits a `- hook id: ...` line on EVERY path (mirroring the `pre-commit`
# framework's failure-summary format) so the structured error can name it.
_VENV_REQUIRING_HOOK = """#!/bin/sh
if [ ! -x .venv/bin/python ]; then
  echo "- hook id: validate-namespaces"
  echo "validate-namespaces: .venv/bin/python not found"
  exit 127
fi
.venv/bin/python -c "print('validate-namespaces: ok')"
exit 0
"""

# Mirrors HestAI-MCP's `canonical-paths-validate` hook and issue #166: with a
# working `.venv`, still REJECTS the record for a CONTENT reason (missing
# CANONICAL field) -- the defect class these hooks exist to catch, which a
# blanket `--no-verify` would hide until CI.
_CONTENT_REJECTING_HOOK = """#!/bin/sh
if [ ! -x .venv/bin/python ]; then
  echo "- hook id: canonical-paths-validate"
  echo "canonical-paths-validate: .venv/bin/python not found"
  exit 127
fi
if ! grep -rq "CANONICAL::" .hestai/decisions/ 2>/dev/null; then
  echo "- hook id: canonical-paths-validate"
  echo "canonical-paths-validate: record missing CANONICAL field (issue #166)"
  exit 1
fi
exit 0
"""


def _run(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)


def _init_isolated_git_repo(repo: Path) -> Path:
    """Init a repo-local git clone with a real bare origin, hermetic against
    a leaked global hooks config. Returns the bare origin path.

    Unlike other hermetic fixtures in this package, `core.hooksPath` is NOT
    disabled here -- installing a REAL pre-commit hook is the entire point
    of these tests. It is instead pinned EXPLICITLY to this repo's own
    `.git/hooks` (an absolute path, so it resolves correctly even when git
    runs from a linked worktree's different cwd), so a global
    `~/.githooks` config can never intercept these tests, and the hook this
    file installs is guaranteed to be the one that fires.
    """
    _run(["init"], repo)
    _run(["config", "core.hooksPath", str(repo / ".git" / "hooks")], repo)
    _run(["config", "user.email", "test@test.com"], repo)
    _run(["config", "user.name", "Test"], repo)
    (repo / "README.md").write_text("test")
    _run(["add", "."], repo)
    _run(["commit", "-m", "initial"], repo)
    _run(["branch", "-M", "main"], repo)

    bare = repo.parent / f"{repo.name}-origin.git"
    subprocess.run(["git", "init", "--bare", str(bare)], check=True, capture_output=True)
    _run(["symbolic-ref", "HEAD", "refs/heads/main"], bare)
    _run(["remote", "add", "origin", str(bare)], repo)
    _run(["push", "-u", "origin", "main"], repo)
    return bare


def _install_hook(repo: Path, hook_name: str, script: str) -> None:
    hooks_dir = repo / ".git" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    hook_path = hooks_dir / hook_name
    hook_path.write_text(script)
    hook_path.chmod(0o755)


def _install_fake_venv(repo: Path) -> None:
    """A minimal but REAL `.venv/bin/python` -- a symlink to the actual
    running interpreter, so hook scripts that invoke it for real (not just
    check for its existence) work."""
    venv_bin = repo / ".venv" / "bin"
    venv_bin.mkdir(parents=True, exist_ok=True)
    (venv_bin / "python").symlink_to(sys.executable)


def _validate(repo: Path) -> object:
    validation = validate_octave_content(repo, _DECISION_RECORD_OCTAVE)
    assert validation.valid is True, validation.errors
    return validation


@pytest.mark.integration
class TestCallerVenvLinkedIntoThrowawayWorktree:
    def test_with_caller_venv_hook_runs_for_real_and_commit_succeeds(
        self, tmp_path: Path
    ) -> None:
        """(RED 1) The target repo's hook needs `.venv/bin/python`; the
        caller HAS a `.venv`. The linker must symlink it into the throwaway
        worktree so the hook runs for real and the commit succeeds."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_isolated_git_repo(repo)
        _install_hook(repo, "pre-commit", _VENV_REQUIRING_HOOK)
        _install_fake_venv(repo)

        validation = _validate(repo)

        with patch(f"{_LINKER}._open_pr", return_value=("http://pr/1", None)):
            output = run_linker(
                working_dir=repo,
                validation=validation,
                octave_content=_DECISION_RECORD_OCTAVE,
                dry_run=False,
            )

        assert output["error"] is None, output["error"]
        assert output["branch"] is not None
        assert output["pr_url"] == "http://pr/1"

        rel = f".hestai/decisions/{_TOKEN}.oct.md"
        committed = subprocess.run(
            ["git", "show", f"{output['branch']}:{rel}"],
            cwd=str(repo),
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        assert committed == _DECISION_RECORD_OCTAVE

    def test_without_caller_venv_hook_fails_with_structured_error(
        self, tmp_path: Path
    ) -> None:
        """(RED 2) Same hook, caller has NO `.venv`: the commit-hook failure
        must surface as a structured, NAMED GOVERNANCE_COMMIT_HOOK_FAILED
        error carrying the hook's output -- never silently skipped
        (`--no-verify` stays off) -- and no push, no PR, branch rolled back."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_isolated_git_repo(repo)
        _install_hook(repo, "pre-commit", _VENV_REQUIRING_HOOK)
        # Deliberately NO .venv in the caller.

        validation = _validate(repo)

        with patch(f"{_LINKER}._open_pr") as open_pr:
            output = run_linker(
                working_dir=repo,
                validation=validation,
                octave_content=_DECISION_RECORD_OCTAVE,
                dry_run=False,
            )

        assert output["branch"] is None
        assert output["pr_url"] is None
        assert output["error"] is not None
        assert output["error"].startswith("GOVERNANCE_COMMIT_HOOK_FAILED: ")
        assert "validate-namespaces" in output["error"]
        open_pr.assert_not_called()

        # Branch rolled back: no local governance/* branch left behind
        # (existing contract -- issue #108 / cubic P2).
        branches = subprocess.run(
            ["git", "branch", "--list", "governance/*"],
            cwd=str(repo),
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        assert branches.strip() == ""

    def test_content_rejecting_hook_with_venv_present_surfaces_message(
        self, tmp_path: Path
    ) -> None:
        """(RED 3) The #166 defect class: with a WORKING `.venv`, a hook
        that rejects the record for a CONTENT reason must still surface its
        own message through the structured error -- proving the fix does not
        paper over real content-validation failures."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_isolated_git_repo(repo)
        _install_hook(repo, "pre-commit", _CONTENT_REJECTING_HOOK)
        _install_fake_venv(repo)

        validation = _validate(repo)

        with patch(f"{_LINKER}._open_pr") as open_pr:
            output = run_linker(
                working_dir=repo,
                validation=validation,
                octave_content=_DECISION_RECORD_OCTAVE,
                dry_run=False,
            )

        assert output["branch"] is None
        assert output["error"] is not None
        assert output["error"].startswith("GOVERNANCE_COMMIT_HOOK_FAILED: ")
        assert "canonical-paths-validate" in output["error"]
        assert "CANONICAL" in output["error"]
        open_pr.assert_not_called()

    def test_commit_contains_only_intended_paths_no_venv_entry(
        self, tmp_path: Path
    ) -> None:
        """(RED 4) The linked `.venv` must NEVER be staged or committed: the
        resulting commit's file list has no `.venv` entry, only the record
        (and MANIFEST)."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_isolated_git_repo(repo)
        _install_hook(repo, "pre-commit", _VENV_REQUIRING_HOOK)
        _install_fake_venv(repo)

        validation = _validate(repo)

        with patch(f"{_LINKER}._open_pr", return_value=("http://pr/1", None)):
            output = run_linker(
                working_dir=repo,
                validation=validation,
                octave_content=_DECISION_RECORD_OCTAVE,
                dry_run=False,
            )
        assert output["error"] is None, output["error"]
        assert output["branch"] is not None

        files = subprocess.run(
            ["git", "show", "--name-only", "--pretty=format:", output["branch"]],
            cwd=str(repo),
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        names = [line for line in files.splitlines() if line.strip()]
        assert f".hestai/decisions/{_TOKEN}.oct.md" in names
        assert not any(".venv" in name for name in names)
        assert all(name.startswith(".hestai") for name in names)

    def test_after_cleanup_callers_real_venv_is_intact(self, tmp_path: Path) -> None:
        """(RED 5) `_remove_worktree`'s `shutil.rmtree` must NEVER follow the
        top-level `.venv` symlink into the caller's REAL `.venv` -- proven
        via a sentinel file that must still exist, with its content intact,
        after the linker's cleanup runs."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_isolated_git_repo(repo)
        _install_hook(repo, "pre-commit", _VENV_REQUIRING_HOOK)
        _install_fake_venv(repo)
        sentinel = repo / ".venv" / "SENTINEL.txt"
        sentinel.write_text("do not delete me")

        validation = _validate(repo)

        with patch(f"{_LINKER}._open_pr", return_value=("http://pr/1", None)):
            output = run_linker(
                working_dir=repo,
                validation=validation,
                octave_content=_DECISION_RECORD_OCTAVE,
                dry_run=False,
            )

        assert output["error"] is None, output["error"]
        assert sentinel.exists()
        assert sentinel.read_text() == "do not delete me"
