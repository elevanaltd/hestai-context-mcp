"""RED: in-flight governance TOKEN detection (issue #173 slice 1).

Operator ruling 2026-09-21 (HO-GOVERNANCE-IN-FLIGHT-TOKEN-AMENDMENT-20260921):
"in flight" = a governance branch for the TOKEN's slug (ANY date prefix) that
is NOT merged into origin/main, OR an open PR for it. Detection must fetch
fresh remote state BEFORE the check (not after, as the old Check-6-then-
linker-fetch ordering did).

These are hermetic real-git fixtures: a bare "origin" plus a clone, with
repo-local user.name/user.email and no reliance on the developer's global git
config (mirrors tests/unit/tools/test_submit_governance.py::
TestLinkerIntegration and the hermetic-git-test-fixtures pattern). No network.

Coverage (minimum required by the brief):
  (a) later-day case: an unmerged origin/governance/<otherdate>-<slug> ref
  (b) same-day collision: an unmerged branch at TODAY's computed branch name
  (c) a MERGED origin/governance/*-<slug> ref does NOT count as in flight
  (d) fetch-before-check ordering: detection sees a branch that only exists on
      origin AFTER the local clone was made, proving it fetches first
  (+) run_linker itself refuses (no worktree/branch/push/PR) when in flight
"""

import subprocess
from pathlib import Path

import pytest

from hestai_context_mcp.tools.governance.linker import (
    _compute_branch_name,
    _token_to_slug,
    find_in_flight_branches,
    run_linker,
)
from hestai_context_mcp.tools.governance.type_checker import validate_octave_content

# Fake AGR record identifier for fixtures (non-secret governance identifier).
_TOKEN = "HO-CONTEXT-MCP-INFLIGHT-20260921"
_SLUG = _token_to_slug(_TOKEN)

_DECISION_RECORD_OCTAVE = f"""\
===DECISION_RECORD===
META:
  TYPE::DECISION_RECORD
  VERSION::"1.0"
  TOKEN::"{_TOKEN}"
  STATUS::PROPOSED
  TIER::OPERATIONAL
  DECISION::"Test decision for in-flight detection coverage."
  BECAUSE::"Required for TDD (issue #173)."
  AUTHORED_AT::"2026-09-21T00:00:00Z"
===END===
"""


def _run(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)


def _init_isolated_clone(repo: Path, bare: Path) -> None:
    """Init a repo-local, hooks-disabled git clone with a real bare origin."""
    _run(["init"], repo)
    _run(["config", "core.hooksPath", str(repo / ".git" / "no-hooks")], repo)
    _run(["config", "user.email", "test@test.com"], repo)
    _run(["config", "user.name", "Test"], repo)
    (repo / "README.md").write_text("test")
    _run(["add", "."], repo)
    _run(["commit", "-m", "initial"], repo)
    _run(["branch", "-M", "main"], repo)

    subprocess.run(["git", "init", "--bare", str(bare)], check=True, capture_output=True)
    _run(["remote", "add", "origin", str(bare)], repo)
    _run(["push", "-u", "origin", "main"], repo)


def _push_governance_branch(
    bare: Path,
    scratch: Path,
    branch_name: str,
    *,
    merge_into_main: bool = False,
) -> None:
    """Simulate a SECOND session pushing a governance branch straight to origin.

    The primary clone (``repo`` in each test) never sees this push locally
    until it fetches -- exactly the cross-session race issue #173 describes.
    """
    subprocess.run(["git", "clone", str(bare), str(scratch)], check=True, capture_output=True)
    _run(["config", "core.hooksPath", str(scratch / ".git" / "no-hooks")], scratch)
    _run(["config", "user.email", "test2@test.com"], scratch)
    _run(["config", "user.name", "Test2"], scratch)
    _run(["checkout", "-b", branch_name, "origin/main"], scratch)
    marker = scratch / f"marker-{branch_name.replace('/', '-')}.txt"
    marker.write_text("governance marker")
    _run(["add", "."], scratch)
    _run(["commit", "-m", f"chore(governance): {branch_name}"], scratch)
    _run(["push", "origin", branch_name], scratch)

    if merge_into_main:
        _run(["checkout", "main"], scratch)
        _run(["merge", "--no-ff", branch_name, "-m", "merge governance branch"], scratch)
        _run(["push", "origin", "main"], scratch)


@pytest.mark.integration
class TestFindInFlightBranches:
    """find_in_flight_branches: fetch-before-check, real git fixtures."""

    def test_later_day_unmerged_branch_is_in_flight(self, tmp_path: Path) -> None:
        """(a) An unmerged origin/governance/<earlier-date>-<slug> ref IS in flight,
        even though it does not match today's computed branch name."""
        repo = tmp_path / "repo"
        bare = tmp_path / "origin.git"
        repo.mkdir()
        _init_isolated_clone(repo, bare)

        later_day_branch = f"governance/20260101-{_SLUG}"
        assert later_day_branch != _compute_branch_name(_TOKEN)
        _push_governance_branch(bare, tmp_path / "scratch-a", later_day_branch)

        branches, error = find_in_flight_branches(repo, _TOKEN)

        assert error is None
        assert branches == [later_day_branch]

    def test_same_day_branch_collision_is_in_flight(self, tmp_path: Path) -> None:
        """(b) An unmerged branch at EXACTLY today's computed name collides."""
        repo = tmp_path / "repo"
        bare = tmp_path / "origin.git"
        repo.mkdir()
        _init_isolated_clone(repo, bare)

        same_day_branch = _compute_branch_name(_TOKEN)
        _push_governance_branch(bare, tmp_path / "scratch-b", same_day_branch)

        branches, error = find_in_flight_branches(repo, _TOKEN)

        assert error is None
        assert branches == [same_day_branch]

    def test_merged_branch_is_not_in_flight(self, tmp_path: Path) -> None:
        """(c) A MERGED-but-undeleted origin governance branch is EXCLUDED."""
        repo = tmp_path / "repo"
        bare = tmp_path / "origin.git"
        repo.mkdir()
        _init_isolated_clone(repo, bare)

        merged_branch = f"governance/20260102-{_SLUG}"
        _push_governance_branch(bare, tmp_path / "scratch-c", merged_branch, merge_into_main=True)

        branches, error = find_in_flight_branches(repo, _TOKEN)

        assert error is None
        assert branches == []

    def test_detects_branch_that_appears_only_after_fetch(self, tmp_path: Path) -> None:
        """(d) fetch-before-check ordering: the branch is pushed to origin
        AFTER the primary clone exists, so the clone has ZERO local knowledge
        of it beforehand. Detection must still find it, proving it fetches
        fresh remote state as part of (before) the check -- not stale local
        refs left over from clone/init time."""
        repo = tmp_path / "repo"
        bare = tmp_path / "origin.git"
        repo.mkdir()
        _init_isolated_clone(repo, bare)

        # Precondition: the clone has never heard of any governance ref.
        pre_refs = subprocess.run(
            ["git", "for-each-ref", "refs/remotes/origin/governance/"],
            cwd=str(repo),
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        assert pre_refs.strip() == ""

        later_branch = f"governance/20260103-{_SLUG}"
        _push_governance_branch(bare, tmp_path / "scratch-d", later_branch)

        branches, error = find_in_flight_branches(repo, _TOKEN)

        assert error is None
        assert branches == [later_branch]

        # Postcondition: the remote-tracking ref now exists locally -- the
        # fetch happened as part of detection, not as a side effect of
        # something else in this test.
        post_refs = subprocess.run(
            ["git", "for-each-ref", "refs/remotes/origin/governance/"],
            cwd=str(repo),
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        assert _SLUG in post_refs


@pytest.mark.integration
class TestRunLinkerRefusesWhenInFlight:
    """run_linker must NOT create a worktree/branch/push/PR when in flight."""

    def test_run_linker_no_branch_no_pr_no_push_when_in_flight(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        bare = tmp_path / "origin.git"
        repo.mkdir()
        _init_isolated_clone(repo, bare)

        in_flight_branch = f"governance/20260101-{_SLUG}"
        _push_governance_branch(bare, tmp_path / "scratch-e", in_flight_branch)

        validation = validate_octave_content(repo, _DECISION_RECORD_OCTAVE)
        assert validation.valid is True, validation.errors

        output = run_linker(
            working_dir=repo,
            validation=validation,
            octave_content=_DECISION_RECORD_OCTAVE,
            dry_run=False,
        )

        assert output["branch"] is None
        assert output["pr_url"] is None
        assert output["in_flight"] is True
        assert output["in_flight_branches"] == [in_flight_branch]
        assert output["error"] is not None
        assert in_flight_branch in output["error"]

        # No local branch/worktree was left behind either.
        local_branches = subprocess.run(
            ["git", "branch", "--list", in_flight_branch],
            cwd=str(repo),
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        assert local_branches.strip() == ""
