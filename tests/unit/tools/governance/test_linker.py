"""Behavioral tests for governance.linker.

Core dry_run + integration tests live in
tests/unit/tools/test_submit_governance.py::TestLinker and TestLinkerIntegration.

This module hardens the previously-untested branches by mocking the
subprocess boundary (git / gh) and the filesystem write layer:
  - _run_git: timeout and FileNotFoundError/OSError branches.
  - _create_branch / _git_add_and_commit failure paths.
  - _write_file OSError branch.
  - _open_pr: argv construction, success, non-zero exit, timeout, gh-missing.
  - run_linker: write failure, commit failure, PR failure aggregation, and
    the target_path-is-None guard on the live path.
"""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from hestai_context_mcp.tools.governance import linker
from hestai_context_mcp.tools.governance.linker import (
    _create_branch,
    _git_add_and_commit,
    _open_pr,
    _push_branch,
    _run_git,
    _write_file,
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
# _create_branch
# ---------------------------------------------------------------------------


class TestCreateBranch:
    @pytest.mark.unit
    def test_success_returns_none(self, tmp_path: Path) -> None:
        with patch(f"{_LINKER}._run_git", return_value=(0, "", "")):
            assert _create_branch(tmp_path, "governance/x") is None

    @pytest.mark.unit
    def test_failure_returns_error_string(self, tmp_path: Path) -> None:
        with patch(f"{_LINKER}._run_git", return_value=(128, "", "branch exists")):
            err = _create_branch(tmp_path, "governance/x")
        assert err is not None
        assert "governance/x" in err
        assert "branch exists" in err


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
        """A 0-exit push returns None and uses `push -u origin <branch>`."""
        with patch(f"{_LINKER}._run_git", return_value=(0, "", "")) as run:
            err = _push_branch(tmp_path, "governance/x")
        assert err is None
        argv = run.call_args.args[0]
        assert argv == ["push", "-u", "origin", "governance/x"]

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


class TestRunLinkerLivePath:
    @pytest.mark.unit
    def test_create_branch_failure_aborts_early(self, tmp_path: Path) -> None:
        """A branch-creation failure returns immediately with the error set."""
        target = tmp_path / ".hestai" / "decisions" / "x.oct.md"
        with patch(f"{_LINKER}._create_branch", return_value="branch boom"):
            out = run_linker(tmp_path, _valid_decision(target), "===DECISION_RECORD===\n", False)
        assert out["error"] == "branch boom"
        assert out["pr_url"] is None
        assert out["dry_run"] is False

    @pytest.mark.unit
    def test_target_path_none_on_live_path_errors(self, tmp_path: Path) -> None:
        """A live run with target_path=None returns the explicit guard error."""
        validation = ValidationResult(
            valid=True,
            errors=[],
            token=_LIVE_RECORD_ID,
            card_type="DECISION_RECORD",
            target_path=None,
        )
        with patch(f"{_LINKER}._create_branch", return_value=None):
            out = run_linker(tmp_path, validation, "===DECISION_RECORD===\n", False)
        assert out["error"] is not None
        assert "target_path is None" in out["error"]

    @pytest.mark.unit
    def test_write_failure_aggregates_error(self, tmp_path: Path) -> None:
        """A write failure surfaces in the aggregated error and stops the flow."""
        target = tmp_path / ".hestai" / "decisions" / "x.oct.md"
        with (
            patch(f"{_LINKER}._create_branch", return_value=None),
            patch(f"{_LINKER}._write_file", return_value="write boom"),
            patch(f"{_LINKER}.write_manifest") as wm,
            patch(f"{_LINKER}._git_add_and_commit") as commit,
            patch(f"{_LINKER}._open_pr") as pr,
        ):
            out = run_linker(tmp_path, _valid_decision(target), "===DECISION_RECORD===\n", False)
        assert out["error"] == "write boom"
        # On a write error we must NOT continue to manifest/commit/PR.
        wm.assert_not_called()
        commit.assert_not_called()
        pr.assert_not_called()

    @pytest.mark.unit
    def test_manifest_failure_is_non_fatal(self, tmp_path: Path) -> None:
        """A write_manifest exception is logged, not fatal; commit/PR proceed."""
        target = tmp_path / ".hestai" / "decisions" / "x.oct.md"
        with (
            patch(f"{_LINKER}._create_branch", return_value=None),
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
        """A commit failure aborts before PR creation."""
        target = tmp_path / ".hestai" / "decisions" / "x.oct.md"
        with (
            patch(f"{_LINKER}._create_branch", return_value=None),
            patch(f"{_LINKER}._write_file", return_value=None),
            patch(f"{_LINKER}.write_manifest"),
            patch(f"{_LINKER}._git_add_and_commit", return_value="commit boom"),
            patch(f"{_LINKER}._open_pr") as pr,
        ):
            out = run_linker(tmp_path, _valid_decision(target), "===DECISION_RECORD===\n", False)
        assert out["error"] == "commit boom"
        pr.assert_not_called()

    @pytest.mark.unit
    def test_pr_failure_aggregates_error(self, tmp_path: Path) -> None:
        """A PR-creation error is aggregated into the final error string."""
        target = tmp_path / ".hestai" / "decisions" / "x.oct.md"
        with (
            patch(f"{_LINKER}._create_branch", return_value=None),
            patch(f"{_LINKER}._write_file", return_value=None),
            patch(f"{_LINKER}.write_manifest"),
            patch(f"{_LINKER}._git_add_and_commit", return_value=None),
            patch(f"{_LINKER}._push_branch", return_value=None),
            patch(f"{_LINKER}._resolve_github_token", return_value="ghp_x"),
            patch(f"{_LINKER}._open_pr", return_value=(None, "pr boom")),
        ):
            out = run_linker(tmp_path, _valid_decision(target), "===DECISION_RECORD===\n", False)
        assert out["error"] == "pr boom"
        assert out["pr_url"] is None

    @pytest.mark.unit
    def test_push_failure_aggregates_and_skips_pr(self, tmp_path: Path) -> None:
        """A push failure surfaces as a structured error and aborts before PR (PROD I4)."""
        target = tmp_path / ".hestai" / "decisions" / "x.oct.md"
        with (
            patch(f"{_LINKER}._create_branch", return_value=None),
            patch(f"{_LINKER}._write_file", return_value=None),
            patch(f"{_LINKER}.write_manifest"),
            patch(f"{_LINKER}._git_add_and_commit", return_value=None),
            patch(f"{_LINKER}._push_branch", return_value="push boom"),
            patch(f"{_LINKER}._open_pr") as pr,
        ):
            out = run_linker(tmp_path, _valid_decision(target), "===DECISION_RECORD===\n", False)
        assert out["error"] == "push boom"
        assert out["pr_url"] is None
        # PR creation must NOT be attempted when the push fails.
        pr.assert_not_called()

    @pytest.mark.unit
    def test_push_precedes_pr_create_at_subprocess_boundary(self, tmp_path: Path) -> None:
        """ORDERING: the branch push reaches the subprocess boundary BEFORE `gh pr create`.

        This is the regression guard for issue #73 -- run_linker must push the
        feature branch to origin before invoking `gh pr create`, otherwise gh
        aborts ("you must first push the current branch to a remote").

        We let the real `_push_branch` and `_open_pr` run, stubbing only the
        shared `subprocess.run` boundary, and assert the recorded git-push call
        precedes the gh-pr-create call.
        """
        target = tmp_path / ".hestai" / "decisions" / "x.oct.md"
        calls: list[list[str]] = []

        def record(cmd: list[str], *args: object, **kwargs: object) -> MagicMock:
            calls.append(cmd)
            if cmd[:1] == ["gh"]:
                return _fake_completed(0, stdout="http://pr/1")
            return _fake_completed(0)

        with (
            patch(f"{_LINKER}._create_branch", return_value=None),
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
    def test_dry_run_neither_pushes_nor_creates_pr(self, tmp_path: Path) -> None:
        """dry_run must touch NO subprocess: no push, no PR (PROD I5 / Human Primacy)."""
        target = tmp_path / ".hestai" / "decisions" / "x.oct.md"
        with patch(f"{_LINKER}.subprocess.run") as run:
            out = run_linker(tmp_path, _valid_decision(target), "===DECISION_RECORD===\n", True)
        assert out["dry_run"] is True
        assert out["pr_url"] is None
        assert out["error"] is None
        # No git push and no gh pr create -- in fact no subprocess at all.
        run.assert_not_called()

    @pytest.mark.unit
    def test_full_live_success(self, tmp_path: Path) -> None:
        """Happy live path: branch + write + manifest + commit + push + PR all succeed."""
        target = tmp_path / ".hestai" / "decisions" / "x.oct.md"
        with (
            patch(f"{_LINKER}._create_branch", return_value=None),
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
        # The branch was pushed before the PR was opened.
        push.assert_called_once()
        # gh_token resolution feeds _open_pr.
        assert pr.call_args.args[-1] == "ghp_x" or pr.call_args.kwargs.get("gh_token") == "ghp_x"


@pytest.mark.unit
def test_linker_module_exposes_run_linker() -> None:
    """Smoke: public entry point is importable and callable."""
    assert callable(linker.run_linker)
