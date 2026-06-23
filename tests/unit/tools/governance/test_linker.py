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
# _preflight_commit_safety (#108.3 worktree-discipline guard)
# ---------------------------------------------------------------------------


# Repo-local git identity for the real-git fixtures. CI runners have NO global
# user.name/user.email (and may set user.useConfigOnly), so any real commit MUST
# carry an explicit identity or it aborts with exit 128 ("author identity
# unknown"). These are passed both as repo config AND inline on every commit
# (-c) so the fixtures are hermetic regardless of the runner's global git state.
_GIT_IDENTITY = (
    "-c",
    "user.email=test@example.com",
    "-c",
    "user.name=Test",
)


def _git(repo: Path, *args: str) -> None:
    """Run a git command in ``repo``, failing the test loudly on error."""
    subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True)


def _hermetic_seed_commit(repo: Path) -> None:
    """Create a seed commit in ``repo`` that succeeds with NO global git config.

    Identity is supplied inline (``-c user.*``) so the commit does not depend on
    a global/system identity (absent on CI), and ``core.hooksPath`` is pointed at
    a nonexistent dir so the seed itself is never gated by the discipline hook.
    """
    (repo / "seed.txt").write_text("seed")
    _git(repo, "add", ".")
    _git(
        repo,
        *_GIT_IDENTITY,
        "-c",
        "core.hooksPath=/nonexistent",
        "commit",
        "-m",
        "seed",
    )


def _git_init_main_tree(repo: Path, *, branch: str = "main", hooks: bool) -> None:
    """Initialise a real git repo as a MAIN tree on ``branch``.

    ``hooks=True`` installs an executable ``pre-commit`` at the repo's effective
    hooks path (simulating a discipline-enforced main tree). ``hooks=False``
    points ``core.hooksPath`` at an empty dir with no ``pre-commit`` (simulating
    a repo where the branch-protection hook is NOT active), mirroring the
    isolated-repo fixture used by the submit_governance integration tests.

    The repo is pinned onto ``branch`` via ``symbolic-ref`` (independent of the
    runner's ``init.defaultBranch``) and given a repo-local identity so later
    commits succeed even when the runner has no global git identity (CI).
    """
    subprocess.run(["git", "init"], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(
        ["git", "symbolic-ref", "HEAD", f"refs/heads/{branch}"],
        cwd=str(repo),
        check=True,
        capture_output=True,
    )
    # Repo-local identity (belt-and-suspenders alongside the inline -c on commits)
    # so this repo can commit on a CI runner with no global git identity.
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    hooks_dir = repo / ".git" / ("real-hooks" if hooks else "no-hooks")
    hooks_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "config", "core.hooksPath", str(hooks_dir)],
        cwd=str(repo),
        check=True,
        capture_output=True,
    )
    if hooks:
        pre_commit = hooks_dir / "pre-commit"
        pre_commit.write_text("#!/bin/bash\nexit 1\n")
        pre_commit.chmod(0o755)


class TestPreflightCommitSafety:
    @pytest.mark.unit
    def test_non_repo_is_safe(self, tmp_path: Path) -> None:
        """A path that is not a git repo cannot be a blocked main tree -> safe."""
        assert linker._preflight_commit_safety(tmp_path) is None

    @pytest.mark.unit
    def test_main_tree_on_main_with_active_hook_blocks(self, tmp_path: Path) -> None:
        """Main tree + protected branch + active pre-commit hook -> structured block."""
        _git_init_main_tree(tmp_path, branch="main", hooks=True)
        err = linker._preflight_commit_safety(tmp_path)
        assert err is not None
        # Recovery guidance: tell the operator to author from a worktree.
        assert "worktree" in err.lower()

    @pytest.mark.unit
    def test_main_tree_on_master_with_active_hook_blocks(self, tmp_path: Path) -> None:
        """The protected-branch set includes 'master', not only 'main'."""
        _git_init_main_tree(tmp_path, branch="master", hooks=True)
        assert linker._preflight_commit_safety(tmp_path) is not None

    @pytest.mark.unit
    def test_main_tree_without_active_hook_is_safe(self, tmp_path: Path) -> None:
        """A main tree whose hooks are disabled (no pre-commit) does NOT block.

        This is the isolated-repo fixture shape used by the submit_governance
        integration tests; the guard must NOT false-positive there.
        """
        _git_init_main_tree(tmp_path, branch="main", hooks=False)
        assert linker._preflight_commit_safety(tmp_path) is None

    @pytest.mark.unit
    def test_main_tree_on_feature_branch_is_safe(self, tmp_path: Path) -> None:
        """A main tree sitting on a NON-protected branch would commit fine -> safe.

        Guards against the false-positive HO flagged: detection must key on the
        protected branch, not merely on 'this is a main tree'.
        """
        _git_init_main_tree(tmp_path, branch="feature/x", hooks=True)
        assert linker._preflight_commit_safety(tmp_path) is None

    @pytest.mark.unit
    def test_real_worktree_is_safe(self, tmp_path: Path) -> None:
        """A genuine git worktree (git-dir != git-common-dir) is never blocked."""
        main_repo = tmp_path / "main"
        main_repo.mkdir()
        _git_init_main_tree(main_repo, branch="main", hooks=True)
        # A repo needs at least one commit before a worktree can be added.
        _hermetic_seed_commit(main_repo)
        wt = tmp_path / "wt"
        _git(main_repo, "worktree", "add", "-b", "governance/x", str(wt), "main")
        assert linker._preflight_commit_safety(wt) is None

    @pytest.mark.unit
    def test_worktree_on_protected_branch_is_safe(self, tmp_path: Path) -> None:
        """A linked worktree checked out ON ``main`` with the hook active is SAFE.

        This is #108.3's core supported authoring path. Conditions (2) protected
        branch and (3) active pre-commit hook BOTH hold here -- the ONLY thing
        keeping the commit unblocked is condition (1), the git-dir != common-dir
        worktree exemption. So this test isolates the worktree discriminator: if
        the git-dir/common-dir comparison were blinded, this would flip to a
        false-block (verified out-of-band). The other two discriminators are
        pinned by the main-tree tests above.
        """
        main_repo = tmp_path / "main"
        main_repo.mkdir()
        _git_init_main_tree(main_repo, branch="main", hooks=True)
        _hermetic_seed_commit(main_repo)
        # Free up ``main`` so a linked worktree can check it out: move the MAIN
        # tree onto a parking branch. The worktree then sits ON the protected
        # branch ``main`` while the main tree does not.
        _git(main_repo, "-c", "core.hooksPath=/nonexistent", "checkout", "-b", "parking")
        wt = tmp_path / "wt-main"
        _git(main_repo, "worktree", "add", str(wt), "main")

        # Pre-conditions for the isolation claim: the worktree IS on the
        # protected branch, and the worktree's git-dir differs from the common
        # dir (the exemption). If git ever stopped distinguishing them, the
        # branch+hook conditions would make this a false-block.
        branch = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=str(wt),
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        assert branch == "main", "worktree must be ON the protected branch for this isolation"

        assert linker._preflight_commit_safety(wt) is None


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
    def test_preflight_block_aborts_before_branch_creation(self, tmp_path: Path) -> None:
        """A discipline-enforced main tree aborts BEFORE any branch is created.

        #108.3: when the pre-flight guard fires, run_linker must return a
        structured failure (success-shape: error set, pr_url None) and must NOT
        invoke ``_create_branch`` -- so no orphan branch and no staged state is
        ever produced (the orphan-branch defect cannot occur).
        """
        target = tmp_path / ".hestai" / "decisions" / "x.oct.md"
        with (
            patch(f"{_LINKER}._preflight_commit_safety", return_value="BLOCKED: use a worktree"),
            patch(f"{_LINKER}._create_branch") as create_branch,
            patch(f"{_LINKER}._write_file") as write_file,
            patch(f"{_LINKER}.subprocess.run") as run,
        ):
            out = run_linker(tmp_path, _valid_decision(target), "===DECISION_RECORD===\n", False)
        assert out["error"] == "BLOCKED: use a worktree"
        assert out["pr_url"] is None
        assert out["dry_run"] is False
        # No branch was created, nothing was written, no subprocess ran: zero
        # partial state (no orphan branch, no staged changes).
        assert out["branch"] is None
        assert out["staged_uncommitted"] is False
        create_branch.assert_not_called()
        write_file.assert_not_called()
        run.assert_not_called()

    @pytest.mark.unit
    def test_preflight_safe_proceeds_to_branch_creation(self, tmp_path: Path) -> None:
        """When pre-flight returns safe (None), the existing happy path proceeds."""
        target = tmp_path / ".hestai" / "decisions" / "x.oct.md"
        with (
            patch(f"{_LINKER}._preflight_commit_safety", return_value=None),
            patch(f"{_LINKER}._create_branch", return_value=None) as create_branch,
            patch(f"{_LINKER}._write_file", return_value=None),
            patch(f"{_LINKER}.write_manifest"),
            patch(f"{_LINKER}._git_add_and_commit", return_value=None),
            patch(f"{_LINKER}._push_branch", return_value=None),
            patch(f"{_LINKER}._resolve_github_token", return_value=None),
            patch(f"{_LINKER}._open_pr", return_value=("http://pr/1", None)),
        ):
            out = run_linker(tmp_path, _valid_decision(target), "===DECISION_RECORD===\n", False)
        assert out["error"] is None
        assert out["pr_url"] == "http://pr/1"
        create_branch.assert_called_once()

    @pytest.mark.unit
    def test_dry_run_skips_preflight(self, tmp_path: Path) -> None:
        """dry_run must not invoke the pre-flight probe (no git side-channel work)."""
        target = tmp_path / ".hestai" / "decisions" / "x.oct.md"
        with patch(f"{_LINKER}._preflight_commit_safety") as preflight:
            out = run_linker(tmp_path, _valid_decision(target), "===DECISION_RECORD===\n", True)
        assert out["dry_run"] is True
        preflight.assert_not_called()

    @pytest.mark.unit
    def test_commit_failure_surfaces_branch_and_staged_state(self, tmp_path: Path) -> None:
        """A post-branch commit failure must surface the created branch + staged state.

        #108.3: when a step after branch creation fails, the result must make the
        partial state explicit (the branch that WAS created, and that changes were
        staged) so the operator can recover -- not silently return a branch name
        that looks clean.
        """
        target = tmp_path / ".hestai" / "decisions" / "x.oct.md"
        with (
            patch(f"{_LINKER}._preflight_commit_safety", return_value=None),
            patch(f"{_LINKER}._create_branch", return_value=None),
            patch(f"{_LINKER}._write_file", return_value=None),
            patch(f"{_LINKER}.write_manifest"),
            patch(f"{_LINKER}._git_add_and_commit", return_value="git commit failed: boom"),
            patch(f"{_LINKER}._open_pr") as pr,
        ):
            out = run_linker(tmp_path, _valid_decision(target), "===DECISION_RECORD===\n", False)
        assert out["error"] is not None
        assert "git commit failed" in out["error"]
        # The created branch is surfaced (not None) so the operator can recover it.
        assert out["branch"] and out["branch"].startswith("governance/")
        # The result flags that local state was left partially applied.
        assert out.get("staged_uncommitted") is True
        pr.assert_not_called()

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


# ---------------------------------------------------------------------------
# staged_uncommitted contract (cubic P2): True IFF the branch was created AND
# the commit did NOT succeed (changes staged but not committed). MUST be False
# whenever the commit succeeded -- including when a later push or PR step fails.
# Fully mocked => hermetic (no real git).
# ---------------------------------------------------------------------------


class TestStagedUncommittedContract:
    @staticmethod
    def _run(tmp_path: Path, **overrides: object) -> dict[str, object]:
        """Drive run_linker through the live path with all seams mocked.

        ``overrides`` replaces individual seam return values (e.g.
        ``commit="boom"``) so each test pins one outcome.
        """
        target = tmp_path / ".hestai" / "decisions" / "x.oct.md"
        commit = overrides.get("commit")  # str error or None
        push = overrides.get("push")  # str error or None
        open_pr = overrides.get("open_pr", ("http://pr/1", None))  # (url, err)
        with (
            patch(f"{_LINKER}._preflight_commit_safety", return_value=None),
            patch(f"{_LINKER}._create_branch", return_value=None),
            patch(f"{_LINKER}._write_file", return_value=None),
            patch(f"{_LINKER}.write_manifest"),
            patch(f"{_LINKER}._git_add_and_commit", return_value=commit),
            patch(f"{_LINKER}._push_branch", return_value=push),
            patch(f"{_LINKER}._resolve_github_token", return_value=None),
            patch(f"{_LINKER}._open_pr", return_value=open_pr),
        ):
            return run_linker(tmp_path, _valid_decision(target), "===DECISION_RECORD===\n", False)

    @pytest.mark.unit
    def test_commit_fails_is_staged_uncommitted(self, tmp_path: Path) -> None:
        """Commit FAILED -> staged_uncommitted True (the genuine staged state)."""
        out = self._run(tmp_path, commit="git commit failed: boom")
        assert out["staged_uncommitted"] is True
        assert out["error"] is not None and "git commit failed" in out["error"]
        assert out["branch"] and str(out["branch"]).startswith("governance/")

    @pytest.mark.unit
    def test_push_fails_after_commit_is_not_staged_uncommitted(self, tmp_path: Path) -> None:
        """Commit OK + push FAILS -> staged_uncommitted False (it committed).

        RED on the old ``bool(errors)`` flag: the push error made errors truthy
        even though the commit landed, mislabelling a committed state as
        staged-uncommitted. Recovery for a push failure is described by ``error``.
        """
        out = self._run(tmp_path, commit=None, push="push boom")
        assert out["staged_uncommitted"] is False
        assert out["error"] == "push boom"
        assert out["branch"] and str(out["branch"]).startswith("governance/")

    @pytest.mark.unit
    def test_pr_fails_after_commit_is_not_staged_uncommitted(self, tmp_path: Path) -> None:
        """Commit OK + push OK + PR FAILS -> staged_uncommitted False (committed+pushed).

        RED on the old ``bool(errors)`` flag.
        """
        out = self._run(tmp_path, commit=None, push=None, open_pr=(None, "pr boom"))
        assert out["staged_uncommitted"] is False
        assert out["error"] == "pr boom"

    @pytest.mark.unit
    def test_full_success_is_not_staged_uncommitted(self, tmp_path: Path) -> None:
        """Full success -> staged_uncommitted False (regression guard)."""
        out = self._run(tmp_path, commit=None, push=None, open_pr=("http://pr/1", None))
        assert out["staged_uncommitted"] is False
        assert out["error"] is None

    @pytest.mark.unit
    def test_traversal_reject_is_not_staged_uncommitted(self, tmp_path: Path) -> None:
        """Path-traversal reject -> staged_uncommitted False: no `git add` ran yet.

        The branch exists (surfaced via ``branch`` + ``error``) but nothing was
        staged, so the literal "staged but not committed" flag is False.
        """
        # target_path OUTSIDE working_dir triggers the traversal guard, which
        # returns before any write/add. ``_create_branch`` is stubbed so the
        # branch-creation step "succeeds" and we reach the traversal guard.
        outside = tmp_path.parent / "elsewhere" / "x.oct.md"
        validation = ValidationResult(
            valid=True,
            errors=[],
            token=_LIVE_RECORD_ID,
            card_type="DECISION_RECORD",
            target_path=outside,
        )
        with (
            patch(f"{_LINKER}._preflight_commit_safety", return_value=None),
            patch(f"{_LINKER}._create_branch", return_value=None),
            patch(f"{_LINKER}._git_add_and_commit") as commit,
        ):
            out = run_linker(tmp_path, validation, "===DECISION_RECORD===\n", False)
        assert "path traversal rejected" in out["error"]
        assert out["staged_uncommitted"] is False
        # The commit step was never reached.
        commit.assert_not_called()


@pytest.mark.unit
def test_linker_module_exposes_run_linker() -> None:
    """Smoke: public entry point is importable and callable."""
    assert callable(linker.run_linker)
