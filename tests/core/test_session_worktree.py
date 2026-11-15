"""Worktree behaviour of the .hestai/state link (issue #197).

In a linked git worktree, ``.hestai/state`` must reach the MAIN checkout's
shared ``.hestai-state``. Before #197, ``SessionManager.ensure_hestai_structure``
created ``<worktree>/.hestai-state`` and rewrote any link that was not the
literal ``../.hestai-state``, which forked session state into the worktree.

These tests use a real ``git worktree`` (no mocks), so the git fixtures are
hermetic: repo-local identity, ``symbolic-ref HEAD refs/heads/main``, no
signing and no inherited hooks. CI runners have no global git identity.
"""

import json
import logging
import os
import subprocess
from pathlib import Path

import pytest

from hestai_context_mcp.core import git_state
from hestai_context_mcp.core.session import SessionManager


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True)


@pytest.fixture
def repo_pair(tmp_path: Path) -> tuple[Path, Path]:
    """Create a main checkout with one commit and a linked worktree.

    Returns (main_root, worktree_root), both resolved.
    """
    main = tmp_path / "main"
    main.mkdir()
    hooks = tmp_path / "no-hooks"
    hooks.mkdir()
    _git(main, "init", "-q")
    _git(main, "symbolic-ref", "HEAD", "refs/heads/main")
    _git(main, "config", "user.email", "test@example.com")
    _git(main, "config", "user.name", "Test")
    _git(main, "config", "commit.gpgsign", "false")
    _git(main, "config", "core.hooksPath", str(hooks))
    (main / "README").write_text("seed\n")
    _git(main, "add", "README")
    _git(main, "commit", "-q", "-m", "seed")
    worktree = tmp_path / "wt"
    _git(main, "worktree", "add", "-q", "-b", "feature", str(worktree))
    return main.resolve(), worktree.resolve()


class TestGetMainCheckoutRoot:
    """get_main_checkout_root: main root for a linked worktree, else None."""

    def test_returns_main_root_for_linked_worktree(self, repo_pair):
        main, worktree = repo_pair
        assert git_state.get_main_checkout_root(worktree) == main

    def test_returns_none_for_main_checkout(self, repo_pair):
        main, _ = repo_pair
        assert git_state.get_main_checkout_root(main) is None

    def test_returns_none_outside_git(self, tmp_path):
        plain = tmp_path / "plain"
        plain.mkdir()
        assert git_state.get_main_checkout_root(plain) is None

    def test_returns_none_when_git_unavailable(self, repo_pair, monkeypatch):
        _, worktree = repo_pair

        def _no_git(*args, **kwargs):
            raise FileNotFoundError("git")

        monkeypatch.setattr("hestai_context_mcp.core.git_state.subprocess.run", _no_git)
        assert git_state.get_main_checkout_root(worktree) is None


class TestEnsureHestaiStructureInWorktree:
    """ensure_hestai_structure in a linked worktree points at the main state."""

    def test_link_to_main_state_is_left_untouched(self, repo_pair):
        """The SessionStart hook's absolute link to main is kept verbatim."""
        main, worktree = repo_pair
        shared = main / ".hestai-state"
        shared.mkdir()
        (worktree / ".hestai").mkdir()
        link = worktree / ".hestai" / "state"
        link.symlink_to(str(shared))

        SessionManager(str(worktree)).ensure_hestai_structure()

        assert link.is_symlink()
        assert os.readlink(str(link)) == str(shared)
        assert not (worktree / ".hestai-state").exists()

    def test_relative_link_resolving_to_main_state_is_left_untouched(self, repo_pair):
        """Correctness is judged by where the link resolves, not its literal text."""
        main, worktree = repo_pair
        (main / ".hestai-state").mkdir()
        (worktree / ".hestai").mkdir()
        link = worktree / ".hestai" / "state"
        relative = os.path.relpath(main / ".hestai-state", worktree / ".hestai")
        link.symlink_to(relative)

        SessionManager(str(worktree)).ensure_hestai_structure()

        assert os.readlink(str(link)) == relative
        assert not (worktree / ".hestai-state").exists()

    def test_wrong_target_link_is_repointed_to_main_state(self, repo_pair):
        main, worktree = repo_pair
        elsewhere = worktree.parent / "elsewhere"
        elsewhere.mkdir()
        (worktree / ".hestai").mkdir()
        link = worktree / ".hestai" / "state"
        link.symlink_to(str(elsewhere))

        SessionManager(str(worktree)).ensure_hestai_structure()

        assert os.readlink(str(link)) == str(main / ".hestai-state")
        assert not (worktree / ".hestai-state").exists()
        assert elsewhere.exists()  # the old target is not touched

    def test_broken_relative_link_is_repointed_to_main_state(self, repo_pair):
        """The pre-#197 relative link with no local data behind it is repaired."""
        main, worktree = repo_pair
        (worktree / ".hestai").mkdir()
        link = worktree / ".hestai" / "state"
        link.symlink_to("../.hestai-state")
        assert not link.exists()  # precondition: broken

        SessionManager(str(worktree)).ensure_hestai_structure()

        assert os.readlink(str(link)) == str(main / ".hestai-state")
        assert link.exists()
        assert not (worktree / ".hestai-state").exists()

    def test_missing_link_is_created_pointing_at_main_state(self, repo_pair):
        main, worktree = repo_pair
        (worktree / ".hestai").mkdir()

        result = SessionManager(str(worktree)).ensure_hestai_structure()

        link = worktree / ".hestai" / "state"
        assert result == "present"
        assert os.readlink(str(link)) == str(main / ".hestai-state")
        assert not (worktree / ".hestai-state").exists()

    def test_missing_hestai_dir_is_created_with_link_to_main_state(self, repo_pair):
        main, worktree = repo_pair

        result = SessionManager(str(worktree)).ensure_hestai_structure()

        link = worktree / ".hestai" / "state"
        assert result == "created"
        assert os.readlink(str(link)) == str(main / ".hestai-state")
        assert (worktree / ".hestai" / "north-star").is_dir()
        assert not (worktree / ".hestai-state").exists()

    def test_plain_file_at_link_path_is_replaced_with_link_to_main(self, repo_pair):
        main, worktree = repo_pair
        (worktree / ".hestai").mkdir()
        (worktree / ".hestai" / "state").write_text("accidental file")

        SessionManager(str(worktree)).ensure_hestai_structure()

        link = worktree / ".hestai" / "state"
        assert os.readlink(str(link)) == str(main / ".hestai-state")
        assert not (worktree / ".hestai-state").exists()

    def test_main_state_subdirectories_are_created_not_local_ones(self, repo_pair):
        main, worktree = repo_pair

        SessionManager(str(worktree)).ensure_hestai_structure()

        shared = main / ".hestai-state"
        for sub in (
            "sessions/active",
            "sessions/archive",
            "context/state",
            "portable/outbox",
            "portable/snapshots",
        ):
            assert (shared / sub).is_dir(), sub
        assert not (worktree / ".hestai-state").exists()

    def test_create_session_writes_into_main_state(self, repo_pair):
        main, worktree = repo_pair

        result = SessionManager(str(worktree)).create_session(role="implementation-lead", focus="x")

        session_file = (
            main / ".hestai-state" / "sessions" / "active" / result["session_id"] / "session.json"
        )
        assert session_file.is_file()
        assert json.loads(session_file.read_text())["focus"] == "x"
        assert not (worktree / ".hestai-state").exists()


class TestExistingWorktreeForkIsWarnedAndLeft:
    """An existing fork is warned about and left for the operator to clean up."""

    def test_relative_link_with_local_data_is_left_and_warned(self, repo_pair, caplog):
        """The pre-#197 fork shape (e.g. worktrees/gov-190) is not modified."""
        main, worktree = repo_pair
        (main / ".hestai-state").mkdir()
        local = worktree / ".hestai-state"
        (local / "context").mkdir(parents=True)
        (local / "context" / "current-focus.oct.md").write_text("forked content")
        (worktree / ".hestai").mkdir()
        link = worktree / ".hestai" / "state"
        link.symlink_to("../.hestai-state")

        with caplog.at_level(logging.WARNING, logger="hestai_context_mcp.core.session"):
            SessionManager(str(worktree)).ensure_hestai_structure()

        assert os.readlink(str(link)) == "../.hestai-state"
        assert (local / "context" / "current-focus.oct.md").read_text() == "forked content"
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any(str(local) in r.getMessage() for r in warnings)

    def test_real_directory_at_link_path_is_left_and_warned(self, repo_pair, caplog):
        """A real .hestai/state directory in a worktree holds data: not migrated or removed."""
        main, worktree = repo_pair
        real = worktree / ".hestai" / "state"
        (real / "context").mkdir(parents=True)
        (real / "context" / "PROJECT-CONTEXT.oct.md").write_text("local content")

        with caplog.at_level(logging.WARNING, logger="hestai_context_mcp.core.session"):
            SessionManager(str(worktree)).ensure_hestai_structure()

        assert real.is_dir() and not real.is_symlink()
        assert (real / "context" / "PROJECT-CONTEXT.oct.md").read_text() == "local content"
        assert not (worktree / ".hestai-state").exists()
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any(str(real) in r.getMessage() for r in warnings)

    def test_stray_local_state_beside_correct_link_is_warned_not_touched(self, repo_pair, caplog):
        """A correct link plus leftover local data: link kept, data kept, warning logged."""
        main, worktree = repo_pair
        shared = main / ".hestai-state"
        shared.mkdir()
        local = worktree / ".hestai-state"
        local.mkdir()
        (local / "learnings-index.jsonl").write_text("{}\n")
        (worktree / ".hestai").mkdir()
        link = worktree / ".hestai" / "state"
        link.symlink_to(str(shared))

        with caplog.at_level(logging.WARNING, logger="hestai_context_mcp.core.session"):
            SessionManager(str(worktree)).ensure_hestai_structure()

        assert os.readlink(str(link)) == str(shared)
        assert (local / "learnings-index.jsonl").read_text() == "{}\n"
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any(str(local) in r.getMessage() for r in warnings)


class TestMainCheckoutUnchanged:
    """A main checkout that is a real git repo keeps the relative convention."""

    def test_main_checkout_gets_relative_link_and_local_state(self, repo_pair):
        main, _ = repo_pair

        SessionManager(str(main)).ensure_hestai_structure()

        link = main / ".hestai" / "state"
        assert os.readlink(str(link)) == "../.hestai-state"
        assert (main / ".hestai-state" / "sessions" / "active").is_dir()
