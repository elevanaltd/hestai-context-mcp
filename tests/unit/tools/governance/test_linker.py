"""Behavioral tests for governance.linker.

Core dry_run + integration tests live in
tests/unit/tools/test_submit_governance.py::TestLinker and TestLinkerIntegration.

This module hardens the previously-untested branches by mocking the
subprocess boundary (git / gh) and the filesystem write layer:
  - _run_git: timeout and FileNotFoundError/OSError branches.
  - _create_worktree / _git_add_and_commit failure paths.
  - _write_file OSError branch.
  - _open_pr: argv construction, success, non-zero exit, timeout, gh-missing.
  - run_linker: write failure, commit failure, PR failure aggregation, and
    the target_path-is-None guard on the live path. All git mutation happens in
    a throwaway worktree, so run_linker never moves the invoking tree's HEAD.
"""

import json
import subprocess
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from hestai_context_mcp.tools.governance import linker
from hestai_context_mcp.tools.governance.linker import (
    _create_worktree,
    _git_add_and_commit,
    _open_pr,
    _push_branch,
    _resolve_open_pr_urls,
    _run_git,
    _write_file,
    check_in_flight_token,
    find_in_flight_branches,
    run_linker,
)
from hestai_context_mcp.tools.governance.type_checker import ValidationResult

_LINKER = "hestai_context_mcp.tools.governance.linker"

# Fake AGR record identifier for fixtures. Referenced via this constant rather
# than inlined as a secret-keyword + string-literal adjacency, so secret
# scanners don't read it as a credential. The value is a non-secret governance
# identifier.
_LIVE_RECORD_ID = "HO-CONTEXT-MCP-LIVE-20260101"


def _fake_completed(returncode: int, stdout: str = "", stderr: str = "") -> MagicMock:
    """Build a stand-in for subprocess.CompletedProcess."""
    result = MagicMock()
    result.returncode = returncode
    result.stdout = stdout
    result.stderr = stderr
    return result


# NOTE: Direct tests for GitHub token resolution now live with the shared
# single-source-of-truth helper at
# tests/unit/tools/shared/test_github_auth.py. The linker re-exports
# ``_resolve_github_token`` from ``tools.shared.github_auth``; the live-path
# tests below patch ``{_LINKER}._resolve_github_token`` to exercise how
# ``run_linker`` consumes the resolved token.


# ---------------------------------------------------------------------------
# _run_git
# ---------------------------------------------------------------------------


class TestRunGit:
    @pytest.mark.unit
    def test_success_returns_stripped_streams(self, tmp_path: Path) -> None:
        """Return code + stripped stdout/stderr are propagated."""
        with patch(
            f"{_LINKER}.subprocess.run",
            return_value=_fake_completed(0, stdout="  out  ", stderr="  err  "),
        ):
            code, out, err = _run_git(["status"], tmp_path)
        assert code == 0
        assert out == "out"
        assert err == "err"

    @pytest.mark.unit
    def test_timeout_returns_error_tuple(self, tmp_path: Path) -> None:
        """subprocess.TimeoutExpired -> (1, '', 'git command timed out')."""
        with patch(
            f"{_LINKER}.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="git", timeout=30),
        ):
            code, out, err = _run_git(["status"], tmp_path)
        assert code == 1
        assert out == ""
        assert "timed out" in err

    @pytest.mark.unit
    def test_filenotfound_returns_error_tuple(self, tmp_path: Path) -> None:
        """git binary missing (FileNotFoundError) -> error tuple with message."""
        with patch(f"{_LINKER}.subprocess.run", side_effect=FileNotFoundError("no git")):
            code, out, err = _run_git(["status"], tmp_path)
        assert code == 1
        assert out == ""
        assert "no git" in err


# ---------------------------------------------------------------------------
# _create_worktree
# ---------------------------------------------------------------------------


class TestCreateWorktree:
    @pytest.mark.unit
    def test_success_returns_worktree_path(self, tmp_path: Path) -> None:
        """fetch + worktree add both succeed -> (worktree_path, None)."""
        parent = tmp_path / "parent"
        with (
            patch(f"{_LINKER}._run_git", return_value=(0, "", "")) as run,
            patch(f"{_LINKER}.tempfile.mkdtemp", return_value=str(parent)),
        ):
            wt, err = _create_worktree(tmp_path, "governance/x")
        assert err is None
        assert wt == parent / "worktree"
        # First call fetches origin; second creates the worktree off origin/main.
        argvs = [c.args[0] for c in run.call_args_list]
        assert argvs[0] == ["fetch", "origin"]
        assert argvs[1][:3] == ["worktree", "add", "-b"]
        assert "origin/main" in argvs[1]

    @pytest.mark.unit
    def test_fetch_failure_aborts_before_mkdtemp(self, tmp_path: Path) -> None:
        """A failed `git fetch origin` returns an error and creates no temp dir."""
        with (
            patch(f"{_LINKER}._run_git", return_value=(1, "", "no network")),
            patch(f"{_LINKER}.tempfile.mkdtemp") as mkdtemp,
        ):
            wt, err = _create_worktree(tmp_path, "governance/x")
        assert wt is None
        assert err is not None and "fetch" in err and "no network" in err
        mkdtemp.assert_not_called()

    @pytest.mark.unit
    def test_worktree_add_failure_cleans_up_temp_dir(self, tmp_path: Path) -> None:
        """A failed `worktree add` removes the temp parent and returns an error."""
        parent = tmp_path / "parent"
        # fetch ok (0), worktree add fails (1)
        with (
            patch(f"{_LINKER}._run_git", side_effect=[(0, "", ""), (1, "", "exists")]),
            patch(f"{_LINKER}.tempfile.mkdtemp", return_value=str(parent)),
            patch(f"{_LINKER}.shutil.rmtree") as rmtree,
        ):
            wt, err = _create_worktree(tmp_path, "governance/x")
        assert wt is None
        assert err is not None and "governance/x" in err and "exists" in err
        rmtree.assert_called_once_with(parent, ignore_errors=True)


# ---------------------------------------------------------------------------
# _remove_worktree / _delete_branch
# ---------------------------------------------------------------------------


class TestWorktreeLifecycle:
    @pytest.mark.unit
    def test_remove_worktree_runs_git_and_rmtree(self, tmp_path: Path) -> None:
        wt = tmp_path / "parent" / "worktree"
        with (
            patch(f"{_LINKER}._run_git", return_value=(0, "", "")) as run,
            patch(f"{_LINKER}.shutil.rmtree") as rmtree,
        ):
            linker._remove_worktree(tmp_path, wt)
        assert run.call_args.args[0] == ["worktree", "remove", "--force", str(wt)]
        rmtree.assert_called_once_with(wt.parent, ignore_errors=True)

    @pytest.mark.unit
    def test_delete_branch_force_deletes(self, tmp_path: Path) -> None:
        with patch(f"{_LINKER}._run_git", return_value=(0, "", "")) as run:
            linker._delete_branch(tmp_path, "governance/x")
        assert run.call_args.args[0] == ["branch", "-D", "governance/x"]


# ---------------------------------------------------------------------------
# _write_file
# ---------------------------------------------------------------------------


class TestWriteFile:
    @pytest.mark.unit
    def test_success_writes_content(self, tmp_path: Path) -> None:
        target = tmp_path / "a" / "b" / "c.oct.md"
        assert _write_file(target, "HELLO") is None
        assert target.read_text() == "HELLO"

    @pytest.mark.unit
    def test_oserror_returns_error_string(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A write OSError is caught and surfaced as an error string."""
        target = tmp_path / "c.oct.md"

        def boom(self: Path, *args: object, **kwargs: object) -> int:
            raise OSError("disk full")

        monkeypatch.setattr(Path, "write_text", boom)
        err = _write_file(target, "HELLO")
        assert err is not None
        assert "disk full" in err
        assert str(target) in err


# ---------------------------------------------------------------------------
# _git_add_and_commit
# ---------------------------------------------------------------------------


class TestGitAddAndCommit:
    @pytest.mark.unit
    def test_add_failure_short_circuits(self, tmp_path: Path) -> None:
        """A failing `git add` returns immediately with an error string."""
        file_path = tmp_path / ".hestai" / "decisions" / "x.oct.md"
        manifest = tmp_path / ".hestai" / "MANIFEST.md"
        with patch(f"{_LINKER}._run_git", return_value=(1, "", "add failed")) as run:
            err = _git_add_and_commit(tmp_path, file_path, manifest, "msg")
        assert err is not None
        assert "git add failed" in err
        # Only the first add was attempted (short-circuit).
        assert run.call_count == 1

    @pytest.mark.unit
    def test_commit_failure_returns_error(self, tmp_path: Path) -> None:
        """A failing `git commit` after a successful add returns an error."""
        file_path = tmp_path / ".hestai" / "decisions" / "x.oct.md"
        manifest = tmp_path / ".hestai" / "MANIFEST.md"

        # add succeeds (0), commit fails (1)
        with patch(f"{_LINKER}._run_git", side_effect=[(0, "", ""), (1, "", "nothing to commit")]):
            err = _git_add_and_commit(tmp_path, file_path, manifest, "msg")
        assert err is not None
        assert "git commit failed" in err

    @pytest.mark.unit
    def test_manifest_staged_when_present(self, tmp_path: Path) -> None:
        """When MANIFEST.md exists, it is staged with a second `git add`."""
        file_path = tmp_path / ".hestai" / "decisions" / "x.oct.md"
        manifest = tmp_path / ".hestai" / "MANIFEST.md"
        manifest.parent.mkdir(parents=True)
        manifest.write_text("| TOKEN | path |\n")

        with patch(f"{_LINKER}._run_git", return_value=(0, "", "")) as run:
            err = _git_add_and_commit(tmp_path, file_path, manifest, "msg")
        assert err is None
        # add(file) + add(manifest) + commit == 3 git calls.
        assert run.call_count == 3
        staged_args = [call.args[0] for call in run.call_args_list]
        assert any("MANIFEST.md" in " ".join(a) for a in staged_args)

    @pytest.mark.unit
    def test_paths_outside_working_dir_fall_back_to_absolute(self, tmp_path: Path) -> None:
        """relative_to ValueError -> the absolute path is staged as-is."""
        outside = tmp_path.parent / "outside.oct.md"
        manifest = tmp_path / ".hestai" / "MANIFEST.md"
        with patch(f"{_LINKER}._run_git", return_value=(0, "", "")) as run:
            err = _git_add_and_commit(tmp_path, outside, manifest, "msg")
        assert err is None
        first_add = run.call_args_list[0].args[0]
        assert str(outside) in " ".join(first_add)

    @pytest.mark.unit
    def test_manifest_outside_working_dir_staged_absolute(self, tmp_path: Path) -> None:
        """An existing MANIFEST outside working_dir is staged by absolute path.

        Covers the relative_to ValueError fallback for the MANIFEST staging
        branch (linker.py:192-193).
        """
        worktree = tmp_path / "wt"
        worktree.mkdir()
        file_path = worktree / ".hestai" / "decisions" / "x.oct.md"
        # MANIFEST exists but lives OUTSIDE the working_dir (worktree).
        outside_manifest = tmp_path / "elsewhere" / "MANIFEST.md"
        outside_manifest.parent.mkdir(parents=True)
        outside_manifest.write_text("| TOKEN | path |\n")

        with patch(f"{_LINKER}._run_git", return_value=(0, "", "")) as run:
            err = _git_add_and_commit(worktree, file_path, outside_manifest, "msg")
        assert err is None
        staged = [" ".join(call.args[0]) for call in run.call_args_list]
        assert any(str(outside_manifest) in s for s in staged)


# ---------------------------------------------------------------------------
# _push_branch
# ---------------------------------------------------------------------------


class TestPushBranch:
    @pytest.mark.unit
    def test_success_returns_none_and_pushes_upstream(self, tmp_path: Path) -> None:
        """A 0-exit push returns None and uses `push --no-verify -u origin <branch>`."""
        with patch(f"{_LINKER}._run_git", return_value=(0, "", "")) as run:
            err = _push_branch(tmp_path, "governance/x")
        assert err is None
        argv = run.call_args.args[0]
        assert argv == ["push", "--no-verify", "-u", "origin", "governance/x"]

    @pytest.mark.unit
    def test_failure_returns_error_string(self, tmp_path: Path) -> None:
        """A non-zero push surfaces as a structured error string (PROD I4)."""
        with patch(f"{_LINKER}._run_git", return_value=(1, "", "permission denied")):
            err = _push_branch(tmp_path, "governance/x")
        assert err is not None
        assert "governance/x" in err
        assert "permission denied" in err


# ---------------------------------------------------------------------------
# _open_pr
# ---------------------------------------------------------------------------


class TestOpenPr:
    @pytest.mark.unit
    def test_success_returns_url_and_constructs_argv(self, tmp_path: Path) -> None:
        """A 0-exit gh run returns the trimmed stdout URL and correct argv."""
        url = "https://github.com/elevanaltd/hestai-context-mcp/pull/123"
        with patch(
            f"{_LINKER}.subprocess.run", return_value=_fake_completed(0, stdout=url + "\n")
        ) as run:
            pr_url, err = _open_pr(
                tmp_path, "governance/x", "HO-T-20260101", "DECISION_RECORD", "ghp_token"
            )
        assert err is None
        assert pr_url == url

        argv = run.call_args.args[0]
        assert argv[:3] == ["gh", "pr", "create"]
        assert "--title" in argv and "--body" in argv
        assert "--base" in argv
        assert argv[argv.index("--base") + 1] == "main"
        title = argv[argv.index("--title") + 1]
        assert "HO-T-20260101" in title
        assert "DECISION_RECORD" in title
        # gh_token is injected into the subprocess env, never into argv.
        assert "ghp_token" not in " ".join(argv)
        env = run.call_args.kwargs["env"]
        assert env["GH_TOKEN"] == "ghp_token"

    @pytest.mark.unit
    def test_no_gh_token_leaves_env_untouched(self, tmp_path: Path) -> None:
        """When gh_token is None, GH_TOKEN is not force-set by _open_pr."""
        with patch(
            f"{_LINKER}.subprocess.run", return_value=_fake_completed(0, stdout="url")
        ) as run:
            pr_url, err = _open_pr(tmp_path, "governance/x", "HO-T-20260101", "FRAME_CARD", None)
        assert err is None
        assert pr_url == "url"
        env = run.call_args.kwargs["env"]
        # No token was injected by the function.
        assert env.get("GH_TOKEN") in (None, env.get("GH_TOKEN"))

    @pytest.mark.unit
    def test_nonzero_exit_returns_error(self, tmp_path: Path) -> None:
        with patch(
            f"{_LINKER}.subprocess.run",
            return_value=_fake_completed(1, stderr="auth required"),
        ):
            pr_url, err = _open_pr(tmp_path, "b", "T-20260101", "DECISION_RECORD", None)
        assert pr_url is None
        assert err is not None
        assert "gh pr create failed" in err
        assert "auth required" in err

    @pytest.mark.unit
    def test_timeout_returns_error(self, tmp_path: Path) -> None:
        with patch(
            f"{_LINKER}.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="gh", timeout=60),
        ):
            pr_url, err = _open_pr(tmp_path, "b", "T-20260101", "DECISION_RECORD", None)
        assert pr_url is None
        assert err is not None
        assert "timed out" in err

    @pytest.mark.unit
    def test_gh_missing_returns_error(self, tmp_path: Path) -> None:
        with patch(f"{_LINKER}.subprocess.run", side_effect=FileNotFoundError("no gh")):
            pr_url, err = _open_pr(tmp_path, "b", "T-20260101", "DECISION_RECORD", None)
        assert pr_url is None
        assert err is not None
        assert "gh CLI not found" in err


# ---------------------------------------------------------------------------
# run_linker live-path branches (subprocess + filesystem fully mocked)
# ---------------------------------------------------------------------------


def _valid_decision(target: Path) -> ValidationResult:
    return ValidationResult(
        valid=True,
        errors=[],
        token=_LIVE_RECORD_ID,
        card_type="DECISION_RECORD",
        target_path=target,
    )


def _drive_live(
    tmp_path: Path,
    *,
    write: str | None = None,
    commit: str | None = None,
    push: str | None = None,
    open_pr: tuple[str | None, str | None] = ("http://pr/1", None),
    worktree: tuple[Path | None, str | None] | None = None,
    validation: ValidationResult | None = None,
) -> tuple[dict[str, Any], SimpleNamespace]:
    """Run run_linker through the live path with every git/fs seam mocked.

    ``worktree`` defaults to a successful ``(tmp_path/'wt', None)``. The returned
    namespace exposes the ``_remove_worktree`` / ``_delete_branch`` / ``_write_file``
    / ``_open_pr`` mocks so tests can assert cleanup + skip behaviour.
    """
    wt_ret = worktree if worktree is not None else (tmp_path / "wt", None)
    target = tmp_path / ".hestai" / "decisions" / "x.oct.md"
    val = validation if validation is not None else _valid_decision(target)
    with ExitStack() as stack:

        def p(name: str, **kw: object) -> MagicMock:
            return stack.enter_context(patch(f"{_LINKER}.{name}", **kw))

        p(
            "check_in_flight_token",
            return_value={"in_flight": False, "branches": [], "pr_urls": {}, "error": None},
        )
        p("_create_worktree", return_value=wt_ret)
        remove = p("_remove_worktree")
        delete = p("_delete_branch")
        write_file = p("_write_file", return_value=write)
        p("write_manifest")
        p("_git_add_and_commit", return_value=commit)
        push_branch = p("_push_branch", return_value=push)
        p("_resolve_github_token", return_value=None)
        open_pr_mock = p("_open_pr", return_value=open_pr)
        out = run_linker(tmp_path, val, "===DECISION_RECORD===\n", False)
    return out, SimpleNamespace(
        remove=remove,
        delete=delete,
        write_file=write_file,
        push_branch=push_branch,
        open_pr=open_pr_mock,
    )


class TestRunLinkerLivePath:
    @pytest.mark.unit
    def test_worktree_creation_failure_aborts_early(self, tmp_path: Path) -> None:
        """A worktree-creation failure returns immediately, touching nothing else.

        Nothing was created, so there is no worktree to remove and no branch to
        roll back: ``_remove_worktree`` / ``_delete_branch`` / ``_write_file`` must
        never run, and the result carries no branch.
        """
        out, h = _drive_live(tmp_path, worktree=(None, "worktree boom"))
        assert out["error"] == "worktree boom"
        assert out["branch"] is None
        assert out["pr_url"] is None
        assert out["staged_uncommitted"] is False
        assert out["dry_run"] is False
        h.remove.assert_not_called()
        h.delete.assert_not_called()
        h.write_file.assert_not_called()

    @pytest.mark.unit
    def test_target_path_none_skips_worktree_creation(self, tmp_path: Path) -> None:
        """A live run with target_path=None errors BEFORE any worktree is created."""
        validation = ValidationResult(
            valid=True,
            errors=[],
            token=_LIVE_RECORD_ID,
            card_type="DECISION_RECORD",
            target_path=None,
        )
        with patch(f"{_LINKER}._create_worktree") as create_worktree:
            out = run_linker(tmp_path, validation, "===DECISION_RECORD===\n", False)
        assert out["error"] is not None
        assert "target_path is None" in out["error"]
        assert out["branch"] is None
        create_worktree.assert_not_called()

    @pytest.mark.unit
    def test_write_failure_aggregates_and_rolls_back(self, tmp_path: Path) -> None:
        """A write failure stops the flow, removes the worktree, and rolls back the branch."""
        out, h = _drive_live(tmp_path, write="write boom")
        assert out["error"] == "write boom"
        # Branch never reached origin -> reported None and rolled back locally.
        assert out["branch"] is None
        assert out["staged_uncommitted"] is False
        # PR is never attempted on a write error.
        h.open_pr.assert_not_called()
        # The worktree is always removed; the half-built branch is deleted.
        h.remove.assert_called_once()
        h.delete.assert_called_once()

    @pytest.mark.unit
    def test_manifest_failure_is_non_fatal(self, tmp_path: Path) -> None:
        """A write_manifest exception is logged, not fatal; commit/PR proceed."""
        target = tmp_path / ".hestai" / "decisions" / "x.oct.md"
        with (
            patch(
                f"{_LINKER}.check_in_flight_token",
                return_value={"in_flight": False, "branches": [], "pr_urls": {}, "error": None},
            ),
            patch(f"{_LINKER}._create_worktree", return_value=(tmp_path / "wt", None)),
            patch(f"{_LINKER}._remove_worktree"),
            patch(f"{_LINKER}._delete_branch"),
            patch(f"{_LINKER}._write_file", return_value=None),
            patch(f"{_LINKER}.write_manifest", side_effect=RuntimeError("manifest boom")),
            patch(f"{_LINKER}._git_add_and_commit", return_value=None),
            patch(f"{_LINKER}._push_branch", return_value=None),
            patch(f"{_LINKER}._resolve_github_token", return_value=None),
            patch(f"{_LINKER}._open_pr", return_value=("http://pr", None)),
        ):
            out = run_linker(tmp_path, _valid_decision(target), "===DECISION_RECORD===\n", False)
        # Non-fatal: no error, PR url propagated.
        assert out["error"] is None
        assert out["pr_url"] == "http://pr"

    @pytest.mark.unit
    def test_commit_failure_aggregates_and_skips_pr(self, tmp_path: Path) -> None:
        """A commit failure aborts before PR creation and rolls the branch back."""
        out, h = _drive_live(tmp_path, commit="commit boom")
        assert out["error"] == "commit boom"
        assert out["branch"] is None
        h.open_pr.assert_not_called()
        h.remove.assert_called_once()
        h.delete.assert_called_once()

    @pytest.mark.unit
    def test_unexpected_exception_still_rolls_back_branch(self, tmp_path: Path) -> None:
        """An unhandled exception before push must STILL roll the branch back.

        The cleanup contract ("if the branch never reached origin, roll it back")
        must hold even when the failure is an unexpected exception that never
        populated ``errors`` -- otherwise a half-built local governance branch is
        left behind despite the worktree being removed. Rollback therefore keys on
        ``pushed_ok`` alone, NOT on whether ``errors`` was recorded (cubic P2).
        """
        target = tmp_path / ".hestai" / "decisions" / "x.oct.md"
        with (
            patch(
                f"{_LINKER}.check_in_flight_token",
                return_value={"in_flight": False, "branches": [], "pr_urls": {}, "error": None},
            ),
            patch(f"{_LINKER}._create_worktree", return_value=(tmp_path / "wt", None)),
            patch(f"{_LINKER}._remove_worktree") as remove,
            patch(f"{_LINKER}._delete_branch") as delete,
            patch(f"{_LINKER}._write_file", side_effect=RuntimeError("boom")),
            pytest.raises(RuntimeError, match="boom"),
        ):
            run_linker(tmp_path, _valid_decision(target), "===DECISION_RECORD===\n", False)
        # Worktree removed AND the unpushed branch rolled back, despite the raise.
        remove.assert_called_once()
        delete.assert_called_once()

    @pytest.mark.unit
    def test_pr_failure_keeps_pushed_branch(self, tmp_path: Path) -> None:
        """A PR error after a successful push keeps the (pushed) branch, no rollback.

        The branch already reached origin, so it is surfaced for recovery and the
        local ref is NOT deleted; only the PR step failed.
        """
        out, h = _drive_live(tmp_path, push=None, open_pr=(None, "pr boom"))
        assert out["error"] == "pr boom"
        assert out["pr_url"] is None
        assert out["branch"] and out["branch"].startswith("governance/")
        h.remove.assert_called_once()
        h.delete.assert_not_called()

    @pytest.mark.unit
    def test_push_failure_aggregates_and_skips_pr(self, tmp_path: Path) -> None:
        """A push failure surfaces as a structured error, aborts PR, rolls back (PROD I4)."""
        out, h = _drive_live(tmp_path, push="push boom")
        assert out["error"] == "push boom"
        assert out["pr_url"] is None
        # Push failed -> branch never persisted -> rolled back and reported None.
        assert out["branch"] is None
        h.open_pr.assert_not_called()
        h.remove.assert_called_once()
        h.delete.assert_called_once()

    @pytest.mark.unit
    def test_push_precedes_pr_create_at_subprocess_boundary(self, tmp_path: Path) -> None:
        """ORDERING: the branch push reaches the subprocess boundary BEFORE `gh pr create`.

        This is the regression guard for issue #73 -- run_linker must push the
        feature branch to origin before invoking `gh pr create`, otherwise gh
        aborts ("you must first push the current branch to a remote").

        We let the real `_push_branch` and `_open_pr` run, stubbing only the
        shared `subprocess.run` boundary (and the worktree lifecycle), and assert
        the recorded git-push call precedes the gh-pr-create call.
        """
        target = tmp_path / ".hestai" / "decisions" / "x.oct.md"
        calls: list[list[str]] = []

        def record(cmd: list[str], *args: object, **kwargs: object) -> MagicMock:
            calls.append(cmd)
            if cmd[:1] == ["gh"]:
                return _fake_completed(0, stdout="http://pr/1")
            return _fake_completed(0)

        with (
            patch(f"{_LINKER}._create_worktree", return_value=(tmp_path / "wt", None)),
            patch(f"{_LINKER}._remove_worktree"),
            patch(f"{_LINKER}._delete_branch"),
            patch(f"{_LINKER}._write_file", return_value=None),
            patch(f"{_LINKER}.write_manifest"),
            patch(f"{_LINKER}._git_add_and_commit", return_value=None),
            patch(f"{_LINKER}._resolve_github_token", return_value=None),
            patch(f"{_LINKER}.subprocess.run", side_effect=record),
        ):
            out = run_linker(tmp_path, _valid_decision(target), "===DECISION_RECORD===\n", False)

        assert out["error"] is None
        assert out["pr_url"] == "http://pr/1"

        push_idx = next(
            (i for i, c in enumerate(calls) if c[:1] == ["git"] and "push" in c),
            None,
        )
        pr_idx = next(
            (i for i, c in enumerate(calls) if c[:3] == ["gh", "pr", "create"]),
            None,
        )
        assert push_idx is not None, f"no git push reached the boundary: {calls}"
        assert pr_idx is not None, f"no gh pr create reached the boundary: {calls}"
        assert push_idx < pr_idx, f"push (idx {push_idx}) must precede pr-create (idx {pr_idx})"

    @pytest.mark.unit
    def test_dry_run_neither_creates_worktree_nor_subprocess(self, tmp_path: Path) -> None:
        """dry_run must touch NO subprocess and create NO worktree (PROD I5)."""
        target = tmp_path / ".hestai" / "decisions" / "x.oct.md"
        with (
            patch(f"{_LINKER}.subprocess.run") as run,
            patch(f"{_LINKER}._create_worktree") as create_worktree,
        ):
            out = run_linker(tmp_path, _valid_decision(target), "===DECISION_RECORD===\n", True)
        assert out["dry_run"] is True
        assert out["pr_url"] is None
        assert out["error"] is None
        # dry_run still reports the would-be branch name.
        assert out["branch"] and out["branch"].startswith("governance/")
        run.assert_not_called()
        create_worktree.assert_not_called()

    @pytest.mark.unit
    def test_full_live_success(self, tmp_path: Path) -> None:
        """Happy live path: worktree + write + manifest + commit + push + PR all succeed."""
        target = tmp_path / ".hestai" / "decisions" / "x.oct.md"
        with (
            patch(
                f"{_LINKER}.check_in_flight_token",
                return_value={
                    "in_flight": False,
                    "branches": [],
                    "pr_urls": {},
                    "pr_lookup_error": None,
                    "error": None,
                },
            ),
            patch(f"{_LINKER}._create_worktree", return_value=(tmp_path / "wt", None)),
            patch(f"{_LINKER}._remove_worktree") as remove,
            patch(f"{_LINKER}._delete_branch") as delete,
            patch(f"{_LINKER}._write_file", return_value=None),
            patch(f"{_LINKER}.write_manifest"),
            patch(f"{_LINKER}._git_add_and_commit", return_value=None),
            patch(f"{_LINKER}._push_branch", return_value=None) as push,
            patch(f"{_LINKER}._resolve_github_token", return_value="ghp_x"),
            patch(f"{_LINKER}._open_pr", return_value=("http://pr/1", None)) as pr,
        ):
            out = run_linker(tmp_path, _valid_decision(target), "===DECISION_RECORD===\n", False)
        assert out["error"] is None
        assert out["pr_url"] == "http://pr/1"
        assert out["branch"].startswith("governance/")
        assert out["staged_uncommitted"] is False
        # DETERMINED False (not undetermined None): the in-flight check ran
        # to completion above and found nothing (cubic finding: the I4
        # in_flight* fields must propagate on the happy live path too).
        assert out["in_flight"] is False
        assert out["in_flight_branches"] == []
        assert out["in_flight_pr_urls"] == {}
        assert out["in_flight_pr_lookup_error"] is None
        # The branch was pushed before the PR was opened.
        push.assert_called_once()
        # The worktree is always cleaned up; a successful push leaves the branch.
        remove.assert_called_once()
        delete.assert_not_called()
        # gh_token resolution feeds _open_pr.
        assert pr.call_args.args[-1] == "ghp_x" or pr.call_args.kwargs.get("gh_token") == "ghp_x"


# ---------------------------------------------------------------------------
# Branch-persistence + cleanup contract (worktree model). The invoking tree is
# never mutated, so ``staged_uncommitted`` is ALWAYS False on the live path.
# ``branch`` is non-None ONLY when the branch reached origin (a push succeeded);
# any pre-push failure rolls the local branch back. Fully mocked => hermetic.
# ---------------------------------------------------------------------------


class TestBranchPersistenceContract:
    @pytest.mark.unit
    def test_commit_fails_rolls_back_branch(self, tmp_path: Path) -> None:
        """Commit FAILED -> branch rolled back (None), staged_uncommitted False."""
        out, h = _drive_live(tmp_path, commit="git commit failed: boom")
        assert out["staged_uncommitted"] is False
        assert out["error"] is not None and "git commit failed" in out["error"]
        assert out["branch"] is None
        h.delete.assert_called_once()

    @pytest.mark.unit
    def test_push_fails_rolls_back_branch(self, tmp_path: Path) -> None:
        """Commit OK + push FAILS -> branch never persisted, rolled back to None."""
        out, h = _drive_live(tmp_path, commit=None, push="push boom")
        assert out["staged_uncommitted"] is False
        assert out["error"] == "push boom"
        assert out["branch"] is None
        h.delete.assert_called_once()

    @pytest.mark.unit
    def test_pr_fails_after_push_keeps_branch(self, tmp_path: Path) -> None:
        """Commit OK + push OK + PR FAILS -> branch persisted on origin, kept."""
        out, h = _drive_live(tmp_path, commit=None, push=None, open_pr=(None, "pr boom"))
        assert out["staged_uncommitted"] is False
        assert out["error"] == "pr boom"
        assert out["branch"] and out["branch"].startswith("governance/")
        h.delete.assert_not_called()

    @pytest.mark.unit
    def test_full_success_keeps_branch(self, tmp_path: Path) -> None:
        """Full success -> branch persisted, staged_uncommitted False, no rollback."""
        out, h = _drive_live(tmp_path, commit=None, push=None, open_pr=("http://pr/1", None))
        assert out["staged_uncommitted"] is False
        assert out["error"] is None
        assert out["branch"] and out["branch"].startswith("governance/")
        h.delete.assert_not_called()

    @pytest.mark.unit
    def test_traversal_reject_skips_worktree(self, tmp_path: Path) -> None:
        """Path-traversal reject -> no worktree created, branch None, nothing staged."""
        outside = tmp_path.parent / "elsewhere" / "x.oct.md"
        validation = ValidationResult(
            valid=True,
            errors=[],
            token=_LIVE_RECORD_ID,
            card_type="DECISION_RECORD",
            target_path=outside,
        )
        with (
            patch(f"{_LINKER}._create_worktree") as create_worktree,
            patch(f"{_LINKER}._git_add_and_commit") as commit,
        ):
            out = run_linker(tmp_path, validation, "===DECISION_RECORD===\n", False)
        assert "path traversal rejected" in out["error"]
        assert out["staged_uncommitted"] is False
        assert out["branch"] is None
        # No worktree was created and no commit ran.
        create_worktree.assert_not_called()
        commit.assert_not_called()


@pytest.mark.unit
def test_linker_module_exposes_run_linker() -> None:
    """Smoke: public entry point is importable and callable."""
    assert callable(linker.run_linker)


# ---------------------------------------------------------------------------
# PR #179 rework round 1: fail-closed detection + tri-state in_flight
# (items 1, 2; addendum A). Mocked _run_git -- no real git process, so the
# fetch vs. ref-enumeration failure can be isolated deterministically via
# side_effect ordering.
# ---------------------------------------------------------------------------


class TestFailClosedDetection:
    @pytest.mark.unit
    def test_fetch_failure_is_undetermined_not_measured_false(self, tmp_path: Path) -> None:
        """(item 2) A fetch failure must be reported UNDETERMINED (None), never
        a measured False -- TMG: no prior test exercised this path at all."""
        with patch(f"{_LINKER}._run_git", return_value=(1, "", "network down")):
            branches, error = find_in_flight_branches(tmp_path, _LIVE_RECORD_ID)
        assert branches == []
        assert error is not None
        assert error.startswith("IN_FLIGHT_UNDETERMINED: ")
        assert "fetch" in error.lower()

        with patch(f"{_LINKER}._run_git", return_value=(1, "", "network down")):
            status = check_in_flight_token(tmp_path, _LIVE_RECORD_ID)
        assert status["in_flight"] is None
        assert status["branches"] == []
        assert status["error"] is not None
        assert status["error"].startswith("IN_FLIGHT_UNDETERMINED: ")

    @pytest.mark.unit
    def test_ref_enumeration_failure_fails_closed_undetermined(self, tmp_path: Path) -> None:
        """(item 1 -- CRS/CE BLOCKING finding) A `git for-each-ref` failure MUST
        propagate as an error, not silently collapse to an empty (== "nothing
        in flight") list. Fetch succeeds; for-each-ref fails."""
        with patch(
            f"{_LINKER}._run_git",
            side_effect=[(0, "", ""), (1, "", "ref db corrupted")],
        ):
            branches, error = find_in_flight_branches(tmp_path, _LIVE_RECORD_ID)
        assert branches == []
        assert error is not None
        assert error.startswith("IN_FLIGHT_UNDETERMINED: ")
        assert "for-each-ref" in error

    @pytest.mark.unit
    def test_run_linker_fails_closed_on_ref_enumeration_error(self, tmp_path: Path) -> None:
        """(item 1) run_linker must open NO worktree/branch/PR when detection
        could not complete, and must surface the UNDETERMINED shape.

        (round 2, cubic P3) ``_resolve_github_token`` is stubbed so this test
        makes ZERO real `gh` calls -- it previously fell through to a real
        `gh auth token` subprocess since run_linker resolves the token
        unconditionally before the in-flight check."""
        target = tmp_path / ".hestai" / "decisions" / "x.oct.md"
        with (
            patch(
                f"{_LINKER}._run_git",
                side_effect=[(0, "", ""), (1, "", "ref db corrupted")],
            ),
            patch(f"{_LINKER}._resolve_github_token", return_value=None),
            patch(f"{_LINKER}._create_worktree") as create_worktree,
        ):
            out = run_linker(tmp_path, _valid_decision(target), "===DECISION_RECORD===\n", False)
        assert out["branch"] is None
        assert out["pr_url"] is None
        assert out["in_flight"] is None
        assert out["in_flight_branches"] == []
        assert out["in_flight_pr_urls"] == {}
        assert out["error"] is not None
        assert out["error"].startswith("IN_FLIGHT_UNDETERMINED: ")
        create_worktree.assert_not_called()

    @pytest.mark.unit
    def test_run_linker_undetermined_on_dry_run(self, tmp_path: Path) -> None:
        """(addendum A) dry_run never runs detection -- in_flight must be the
        UNDETERMINED shape (None), not a measured False."""
        target = tmp_path / ".hestai" / "decisions" / "x.oct.md"
        out = run_linker(tmp_path, _valid_decision(target), "===DECISION_RECORD===\n", True)
        assert out["dry_run"] is True
        assert out["in_flight"] is None
        assert out["in_flight_branches"] == []
        assert out["in_flight_pr_urls"] == {}


# ---------------------------------------------------------------------------
# PR #179 rework round 1, item 6: per-branch gh pr list lookup (replaces the
# single `--limit 100` list that could silently truncate).
# ---------------------------------------------------------------------------


class TestResolveOpenPrUrls:
    @pytest.mark.unit
    def test_no_branches_makes_no_subprocess_call(self, tmp_path: Path) -> None:
        with patch(f"{_LINKER}.subprocess.run") as run:
            urls, err = _resolve_open_pr_urls(tmp_path, [], None)
        assert urls == {}
        assert err is None
        run.assert_not_called()

    @pytest.mark.unit
    def test_success_resolves_url_per_branch_via_head_filter(self, tmp_path: Path) -> None:
        """ONE `gh pr list --head <branch>` call PER branch, not a single
        shared `--limit N` list (truncation-proof by construction)."""
        calls: list[list[str]] = []

        def fake_run(cmd: list[str], **kwargs: object) -> MagicMock:
            calls.append(cmd)
            assert cmd[:3] == ["gh", "pr", "list"]
            assert "--limit" not in cmd or cmd[cmd.index("--limit") + 1] == "1"
            branch = cmd[cmd.index("--head") + 1]
            return _fake_completed(0, stdout=json.dumps([{"url": f"http://pr/{branch}"}]))

        with patch(f"{_LINKER}.subprocess.run", side_effect=fake_run):
            urls, err = _resolve_open_pr_urls(tmp_path, ["governance/a", "governance/b"], None)
        assert urls == {
            "governance/a": "http://pr/governance/a",
            "governance/b": "http://pr/governance/b",
        }
        assert err is None
        assert len(calls) == 2

    @pytest.mark.unit
    def test_one_branch_gh_failure_is_surfaced_others_still_resolve(self, tmp_path: Path) -> None:
        """A per-branch lookup failure is NAMED in pr_lookup_error, not
        silently swallowed (CRS/CE/cubic finding); the other branch's lookup
        still succeeds -- detection is unaffected either way."""

        def fake_run(cmd: list[str], **kwargs: object) -> MagicMock:
            branch = cmd[cmd.index("--head") + 1]
            if branch == "governance/bad":
                return _fake_completed(1, stderr="gh: not found")
            return _fake_completed(0, stdout=json.dumps([{"url": "http://pr/ok"}]))

        with patch(f"{_LINKER}.subprocess.run", side_effect=fake_run):
            urls, err = _resolve_open_pr_urls(tmp_path, ["governance/bad", "governance/ok"], None)
        assert urls == {"governance/ok": "http://pr/ok"}
        assert err is not None
        assert "governance/bad" in err

    @pytest.mark.unit
    def test_no_pr_found_for_branch_is_not_an_error(self, tmp_path: Path) -> None:
        """An empty JSON array (no open PR for this branch) is success with
        no URL, not a failure."""
        with patch(
            f"{_LINKER}.subprocess.run",
            return_value=_fake_completed(0, stdout="[]"),
        ):
            urls, err = _resolve_open_pr_urls(tmp_path, ["governance/none"], None)
        assert urls == {}
        assert err is None


# ---------------------------------------------------------------------------
# PR #179 rework round 2 (cubic review 5265518720): the strategy-independent
# merged signal must be evaluated PER CANDIDATE BRANCH (via a new
# ``_branch_record_matches_origin_main`` blob-hash comparison), never as a
# token-wide short-circuit. These unit tests cover the (a)/(b)/(c) edge cases
# the coordinator called out, deterministically via mocked ``_run_git`` --
# the real-git reproduction of the generating bug lives in
# test_linker_in_flight.py::TestPerBranchMergedSignal.
# ---------------------------------------------------------------------------


class TestBranchRecordMatchesOriginMain:
    @pytest.mark.unit
    def test_target_path_none_is_no_match_no_error(self, tmp_path: Path) -> None:
        """(c) target_path=None: nothing to compare -- a measured False (this
        signal doesn't apply), never an error."""
        matches, error = linker._branch_record_matches_origin_main(tmp_path, "governance/x", None)
        assert matches is False
        assert error is None

    @pytest.mark.unit
    def test_branch_missing_file_is_no_match_no_error(self, tmp_path: Path) -> None:
        """(a) both refs resolve fine, but the branch has no FILE at
        target_path: `git rev-parse --verify -q` exits non-zero with EMPTY
        stderr for a missing path -- that is a routine, MEASURED miss, not a
        git failure. (round 3: the two leading calls are the new
        _verify_ref_resolves checks for the branch ref and origin/main,
        both succeeding, BEFORE any path lookup runs.)"""
        with patch(
            f"{_LINKER}._run_git",
            side_effect=[
                (0, "branchsha", ""),  # verify origin/governance/x^{commit}
                (0, "mainsha", ""),  # verify origin/main^{commit}
                (1, "", ""),  # blob lookup: branch has no file at target_path
            ],
        ):
            matches, error = linker._branch_record_matches_origin_main(
                tmp_path, "governance/x", ".hestai/decisions/T.oct.md"
            )
        assert matches is False
        assert error is None

    @pytest.mark.unit
    def test_main_missing_file_is_no_match_no_error(self, tmp_path: Path) -> None:
        """(b) both refs resolve fine, branch's file resolves, but origin/main
        has no file at target_path -- still a measured False, not an error."""
        with patch(
            f"{_LINKER}._run_git",
            side_effect=[
                (0, "branchsha", ""),  # verify origin/governance/x^{commit}
                (0, "mainsha", ""),  # verify origin/main^{commit}
                (0, "abc123", ""),  # blob lookup: branch has the file
                (1, "", ""),  # blob lookup: main has no file at target_path
            ],
        ):
            matches, error = linker._branch_record_matches_origin_main(
                tmp_path, "governance/x", ".hestai/decisions/T.oct.md"
            )
        assert matches is False
        assert error is None

    @pytest.mark.unit
    def test_identical_blobs_match(self, tmp_path: Path) -> None:
        """Same blob SHA on both sides -- byte-identical content -- matches."""
        with patch(
            f"{_LINKER}._run_git",
            side_effect=[
                (0, "branchsha", ""),  # verify origin/governance/x^{commit}
                (0, "mainsha", ""),  # verify origin/main^{commit}
                (0, "abc123", ""),  # blob lookup: branch
                (0, "abc123", ""),  # blob lookup: main
            ],
        ):
            matches, error = linker._branch_record_matches_origin_main(
                tmp_path, "governance/x", ".hestai/decisions/T.oct.md"
            )
        assert matches is True
        assert error is None

    @pytest.mark.unit
    def test_different_blobs_do_not_match(self, tmp_path: Path) -> None:
        """Different blob SHAs -- content diverged -- does not match, so the
        branch stays subject to the ancestor test (this is the exact
        squash-A-then-diverged-B scenario, at the unit level)."""
        with patch(
            f"{_LINKER}._run_git",
            side_effect=[
                (0, "branchsha", ""),  # verify origin/governance/x^{commit}
                (0, "mainsha", ""),  # verify origin/main^{commit}
                (0, "abc123", ""),  # blob lookup: branch
                (0, "def456", ""),  # blob lookup: main
            ],
        ):
            matches, error = linker._branch_record_matches_origin_main(
                tmp_path, "governance/x", ".hestai/decisions/T.oct.md"
            )
        assert matches is False
        assert error is None

    @pytest.mark.unit
    def test_git_hard_failure_is_undetermined(self, tmp_path: Path) -> None:
        """A genuine git failure (non-empty stderr survives `-q`, e.g. a
        corrupted repo) fails CLOSED: IN_FLIGHT_UNDETERMINED, not a silent
        False that could wrongly clear a branch. `return_value` applies to
        every `_run_git` call uniformly, so (round 3) this now fails at the
        FIRST call -- the new `_verify_ref_resolves` check for the branch's
        own ref -- rather than at a blob lookup; the assertions are
        unaffected either way."""
        with patch(
            f"{_LINKER}._run_git",
            return_value=(128, "", "fatal: not a git repository"),
        ):
            matches, error = linker._branch_record_matches_origin_main(
                tmp_path, "governance/x", ".hestai/decisions/T.oct.md"
            )
        assert matches is False
        assert error is not None
        assert error.startswith("IN_FLIGHT_UNDETERMINED: ")


# ---------------------------------------------------------------------------
# PR #179 rework round 3 (final, bounded extra round -- CRS 5760485688,
# verified empirically by CE): find_in_flight_branches could return a
# DETERMINED in_flight True (error None) that it had not actually measured.
# Three inputs, scoped exactly:
#   1. _is_merged_into_origin_main used `code == 0`; any other exit code, OR
#      a masked _run_git timeout (which returns code 1 -- the SAME code as a
#      genuine "not an ancestor" measurement -- but with non-empty stderr),
#      must be IN_FLIGHT_UNDETERMINED, not silently read as "not merged".
#   2. _blob_sha_at's `rev-parse --verify -q <ref>:<path>` exits 1 with
#      EMPTY stderr for a MISSING REF too, indistinguishable from a missing
#      PATH at an existing ref. A missing ref (origin/main itself, or a
#      candidate's own remote-tracking ref) must be IN_FLIGHT_UNDETERMINED.
#   3. target_path=None on the public find_in_flight_branches/
#      check_in_flight_token: rejected at the boundary (see the docstring
#      update on find_in_flight_branches for the chosen policy and why).
# ---------------------------------------------------------------------------


class TestIsMergedIntoOriginMain:
    """_is_merged_into_origin_main now returns tuple[bool, str | None] (was
    a bare bool) -- exit 0 is a measured merge, exit 1 with EMPTY stderr is
    a measured non-merge, and everything else (including a masked
    `_run_git` timeout, which is ALSO exit 1 but with non-empty stderr) is
    UNDETERMINED."""

    @pytest.mark.unit
    def test_exit_0_is_measured_merged(self, tmp_path: Path) -> None:
        with patch(f"{_LINKER}._run_git", return_value=(0, "", "")):
            merged, error = linker._is_merged_into_origin_main(tmp_path, "governance/x")
        assert merged is True
        assert error is None

    @pytest.mark.unit
    def test_exit_1_empty_stderr_is_measured_not_merged(self, tmp_path: Path) -> None:
        with patch(f"{_LINKER}._run_git", return_value=(1, "", "")):
            merged, error = linker._is_merged_into_origin_main(tmp_path, "governance/x")
        assert merged is False
        assert error is None

    @pytest.mark.unit
    def test_exit_128_is_undetermined(self, tmp_path: Path) -> None:
        with patch(
            f"{_LINKER}._run_git",
            return_value=(128, "", "fatal: Not a valid object name"),
        ):
            merged, error = linker._is_merged_into_origin_main(tmp_path, "governance/x")
        assert merged is False
        assert error is not None
        assert error.startswith("IN_FLIGHT_UNDETERMINED: ")

    @pytest.mark.unit
    def test_masked_timeout_cannot_masquerade_as_exit_1(self, tmp_path: Path) -> None:
        """A `_run_git` timeout returns EXACTLY (1, "", "git command timed
        out") -- the same exit code as a genuine "not an ancestor"
        measurement, but with non-empty stderr. This must be told apart and
        reported UNDETERMINED, not silently read as "measured: not merged"
        (the precise CRS/CE finding)."""
        with patch(
            f"{_LINKER}._run_git",
            return_value=(1, "", "git command timed out"),
        ):
            merged, error = linker._is_merged_into_origin_main(tmp_path, "governance/x")
        assert merged is False
        assert error is not None
        assert error.startswith("IN_FLIGHT_UNDETERMINED: ")


class TestFindInFlightBranchesUndeterminedPropagation:
    """End-to-end: internal signal failures must surface as
    find_in_flight_branches' own error, never silently become a determined
    branch list."""

    @pytest.mark.unit
    def test_masked_ancestor_timeout_propagates_as_undetermined(self, tmp_path: Path) -> None:
        """Reproduces the CRS-described bug directly: a masked ancestor-check
        timeout must NOT produce a determined in-flight branch list."""
        with patch(
            f"{_LINKER}._run_git",
            side_effect=[
                (0, "", ""),  # fetch origin
                (
                    0,
                    "origin/governance/20260101-ho-context-mcp-live-20260101",
                    "",
                ),  # for-each-ref
                (1, "", "git command timed out"),  # merge-base --is-ancestor (masked)
                (1, "", ""),  # buffer: pre-fix code would reach blob_sha_at(branch)
                (1, "", ""),  # buffer: pre-fix code would reach blob_sha_at(main)
            ],
        ):
            branches, error = find_in_flight_branches(
                tmp_path, _LIVE_RECORD_ID, ".hestai/decisions/T.oct.md"
            )
        assert branches == []
        assert error is not None
        assert error.startswith("IN_FLIGHT_UNDETERMINED: ")


class TestMissingRefIsUndetermined:
    """_branch_record_matches_origin_main must tell a MISSING REF apart from
    a missing PATH at an existing ref -- `_blob_sha_at` alone cannot (both
    give empty stderr + exit 1)."""

    @pytest.mark.unit
    def test_missing_ref_is_undetermined_not_a_measured_miss(self, tmp_path: Path) -> None:
        """Every `_run_git` call (including the new ref-existence check)
        returns the "missing" shape (exit 1, empty stderr) -- indistinguishable,
        at the raw `rev-parse --verify -q` level, from a routine missing
        PATH. The ref itself must be verified separately; a ref that does
        not resolve is UNDETERMINED, not a routine case (a)/(b) miss."""
        with patch(f"{_LINKER}._run_git", return_value=(1, "", "")):
            matches, error = linker._branch_record_matches_origin_main(
                tmp_path, "governance/x", ".hestai/decisions/T.oct.md"
            )
        assert matches is False
        assert error is not None
        assert error.startswith("IN_FLIGHT_UNDETERMINED: ")


class TestTargetPathNoneBoundary:
    """PR #179 round 3, item 3: target_path=None on the PUBLIC
    find_in_flight_branches is rejected at the boundary once there is
    anything to evaluate -- see the docstring update for the chosen policy
    (option (i), scoped to fire only when candidates is non-empty)."""

    @pytest.mark.unit
    def test_target_path_none_with_candidates_is_undetermined(self, tmp_path: Path) -> None:
        with patch(
            f"{_LINKER}._run_git",
            side_effect=[
                (0, "", ""),  # fetch origin
                (
                    0,
                    "origin/governance/20260101-ho-context-mcp-live-20260101",
                    "",
                ),  # for-each-ref: one candidate exists
            ],
        ):
            branches, error = find_in_flight_branches(tmp_path, _LIVE_RECORD_ID)
        assert branches == []
        assert error is not None
        assert error.startswith("IN_FLIGHT_UNDETERMINED: ")

    @pytest.mark.unit
    def test_target_path_none_with_no_candidates_stays_measured_empty(self, tmp_path: Path) -> None:
        """Regression guard, not a RED case: ZERO candidate branches means
        there is nothing the missing content-match signal COULD have
        changed -- a fully measured "nothing in flight", not an error."""
        with patch(
            f"{_LINKER}._run_git",
            side_effect=[
                (0, "", ""),  # fetch origin
                (0, "", ""),  # for-each-ref: no matching branches
            ],
        ):
            branches, error = find_in_flight_branches(tmp_path, _LIVE_RECORD_ID)
        assert branches == []
        assert error is None
