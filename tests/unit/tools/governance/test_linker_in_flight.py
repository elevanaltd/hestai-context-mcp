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
from unittest.mock import patch

import pytest

from hestai_context_mcp.tools.governance.linker import (
    _compute_branch_name,
    _token_to_slug,
    find_in_flight_branches,
    run_linker,
)
from hestai_context_mcp.tools.governance.type_checker import validate_octave_content

_LINKER = "hestai_context_mcp.tools.governance.linker"

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
    # TMG finding (PR #179 rework round 1, item 3): git init --bare inherits
    # whatever init.defaultBranch the environment provides. On a system where
    # that is "master" (not "main"), the bare repo's HEAD points at a
    # nonexistent ref -- "warning: remote HEAD refers to nonexistent ref,
    # unable to checkout" on every subsequent `git clone` of this bare, and a
    # `checkout -b <branch>` with no explicit start point would create a root
    # commit with no ancestry link to main ("refusing to merge unrelated
    # histories"). Pin the bare's HEAD explicitly so this fixture is
    # hermetic regardless of the environment's init.defaultBranch.
    _run(["symbolic-ref", "HEAD", "refs/heads/main"], bare)
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

        # A fixed, hard-coded date distinct from today's computed branch name
        # BY CONSTRUCTION (cubic finding): the test's purpose is "a DIFFERENT
        # date prefix is still detected," which the docstring's hard-coded
        # date already guarantees without a wall-clock-coupled assertion that
        # would fail if the suite ever runs on that exact date.
        later_day_branch = f"governance/20260101-{_SLUG}"
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
        """Hermetic: gh is stubbed (TMG / cubic finding) so this test makes
        ZERO real gh CLI calls -- not `gh auth token`, not `gh pr list`. The
        real git fetch/for-each-ref/merge-base calls remain unstubbed (that
        IS the thing under test); only the GitHub-API boundary is faked."""
        repo = tmp_path / "repo"
        bare = tmp_path / "origin.git"
        repo.mkdir()
        _init_isolated_clone(repo, bare)

        in_flight_branch = f"governance/20260101-{_SLUG}"
        _push_governance_branch(bare, tmp_path / "scratch-e", in_flight_branch)

        validation = validate_octave_content(repo, _DECISION_RECORD_OCTAVE)
        assert validation.valid is True, validation.errors

        with (
            patch(f"{_LINKER}._resolve_github_token", return_value=None),
            patch(f"{_LINKER}._resolve_open_pr_urls", return_value=({}, None)) as pr_urls,
        ):
            output = run_linker(
                working_dir=repo,
                validation=validation,
                octave_content=_DECISION_RECORD_OCTAVE,
                dry_run=False,
            )

        # The stub proves no real `gh` subprocess was ever attempted for the
        # PR-URL lookup (it was still CALLED -- with the real in-flight
        # branch list -- just not allowed to shell out).
        pr_urls.assert_called_once()
        assert pr_urls.call_args.args[1] == [in_flight_branch]

        assert output["branch"] is None
        assert output["pr_url"] is None
        assert output["in_flight"] is True
        assert output["in_flight_branches"] == [in_flight_branch]
        assert output["in_flight_pr_urls"] == {}
        assert output["in_flight_pr_lookup_error"] is None
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


@pytest.mark.integration
class TestSquashMergeExcluded:
    """PR #179 rework round 1, item 5 (cubic P2 / CE HIGH finding):
    ``merge-base --is-ancestor`` alone cannot see a squash or rebase merge --
    GitHub's squash/rebase strategies never leave the head branch as an
    ancestor of main. A branch whose content already landed on ``origin/main``
    via ANY merge strategy must be excluded from in-flight status."""

    def test_squash_merged_branch_is_not_in_flight(self, tmp_path: Path) -> None:
        """The branch's OWN commit writes the record at its canonical path
        (round 2 correction: the per-branch content comparison requires the
        CANDIDATE branch itself to carry the matching content, not merely
        SOME branch/commit anywhere -- see TestPerBranchMergedSignal for the
        case where a DIFFERENT branch's content must NOT be cleared by this
        one's squash-merge)."""
        repo = tmp_path / "repo"
        bare = tmp_path / "origin.git"
        repo.mkdir()
        _init_isolated_clone(repo, bare)

        target_rel = f".hestai/decisions/{_TOKEN}.oct.md"
        squash_branch = f"governance/20260104-{_SLUG}"
        # The governance branch itself stays unmerged forever (never an
        # ancestor of main) -- exactly what GitHub's squash-merge leaves
        # behind on the ORIGINAL branch ref. Its OWN commit carries the real
        # record content at its canonical path.
        _push_branch_with_record(
            bare,
            tmp_path / "scratch-squash-branch",
            squash_branch,
            target_rel,
            _DECISION_RECORD_OCTAVE,
        )

        # Simulate "squash and merge": a SEPARATE, independent commit lands
        # directly on main carrying the SAME content at the SAME path --
        # main never merges the branch itself.
        _squash_merge_record_into_main(
            bare, tmp_path / "scratch-squash-main", target_rel, _DECISION_RECORD_OCTAVE, _TOKEN
        )

        # Sanity precondition: the branch really is NOT an ancestor of main
        # (this is what a bare ancestor-only test would get wrong).
        not_ancestor = subprocess.run(
            ["git", "fetch", "origin", "--prune"], cwd=str(repo), check=True, capture_output=True
        )
        del not_ancestor
        ancestor_check = subprocess.run(
            ["git", "merge-base", "--is-ancestor", f"origin/{squash_branch}", "origin/main"],
            cwd=str(repo),
            capture_output=True,
        )
        assert ancestor_check.returncode != 0, "fixture invalid: branch IS an ancestor of main"

        branches, error = find_in_flight_branches(repo, _TOKEN, target_rel)

        assert error is None
        assert branches == []


def _push_branch_with_record(
    bare: Path, scratch: Path, branch_name: str, target_rel: str, content: str
) -> None:
    """Push a governance branch that writes ``content`` at ``target_rel`` --
    the TOKEN's REAL canonical record path (not just a marker file), needed
    for the per-branch content-comparison tests (round 2)."""
    subprocess.run(["git", "clone", str(bare), str(scratch)], check=True, capture_output=True)
    _run(["config", "core.hooksPath", str(scratch / ".git" / "no-hooks")], scratch)
    _run(["config", "user.email", "test-branch@test.com"], scratch)
    _run(["config", "user.name", "TestBranch"], scratch)
    _run(["checkout", "-b", branch_name, "origin/main"], scratch)
    record_file = scratch / target_rel
    record_file.parent.mkdir(parents=True, exist_ok=True)
    record_file.write_text(content)
    _run(["add", "."], scratch)
    _run(["commit", "-m", f"chore(governance): {branch_name}"], scratch)
    _run(["push", "origin", branch_name], scratch)


def _squash_merge_record_into_main(
    bare: Path, scratch: Path, target_rel: str, content: str, token: str
) -> None:
    """Simulate GitHub's "squash and merge": a SEPARATE, independent commit
    lands directly on main carrying ``content`` at ``target_rel`` -- main
    never merges the source branch's history, so the branch is NOT an
    ancestor of main afterwards."""
    subprocess.run(["git", "clone", str(bare), str(scratch)], check=True, capture_output=True)
    _run(["config", "core.hooksPath", str(scratch / ".git" / "no-hooks")], scratch)
    _run(["config", "user.email", "test-squash@test.com"], scratch)
    _run(["config", "user.name", "TestSquash"], scratch)
    _run(["checkout", "main"], scratch)
    record_file = scratch / target_rel
    record_file.parent.mkdir(parents=True, exist_ok=True)
    record_file.write_text(content)
    _run(["add", "."], scratch)
    _run(["commit", "-m", f"chore(governance): squash-merge {token}"], scratch)
    _run(["push", "origin", "main"], scratch)


@pytest.mark.integration
class TestPerBranchMergedSignal:
    """PR #179 rework round 2 (cubic review 5265518720, reproduced at af01c13d):
    ``_token_record_exists_on_origin_main`` short-circuited the WHOLE token to
    "nothing in flight" the moment ANY copy of the record existed on
    origin/main, even when a DIFFERENT, still-genuinely-unmerged branch for
    the SAME token had diverging content. The module docstring's own rule
    ("a branch is excluded if EITHER signal says merged") is PER BRANCH -- the
    round-1 code did not match its own doc. The strategy-independent merged
    signal must be evaluated per CANDIDATE BRANCH: a branch is excluded only
    when ITS OWN copy of the record matches what's on main."""

    def test_squash_merged_a_plus_unmerged_b_reports_only_b(self, tmp_path: Path) -> None:
        """Exact reproduction from the coordinator's report:
        1. Branch A adds the record (v1), is pushed, then SQUASH-merged into
           main (v1 lands on main; A itself is never an ancestor of main).
        2. Branch B changes the record to v2, is pushed, and stays unmerged.
        3. Fresh clone / fresh detection.
        CORRECT: only B is in flight -- A's own content matches what's on
        main (excluded); B's content has since diverged (still in flight)."""
        repo = tmp_path / "repo"
        bare = tmp_path / "origin.git"
        repo.mkdir()
        _init_isolated_clone(repo, bare)

        target_rel = f".hestai/decisions/{_TOKEN}.oct.md"
        branch_a = f"governance/20260101-{_SLUG}"
        branch_b = f"governance/20260921-{_SLUG}"
        record_v1 = _DECISION_RECORD_OCTAVE
        record_v2 = _DECISION_RECORD_OCTAVE.replace(
            'DECISION::"Test decision for in-flight detection coverage."',
            'DECISION::"Test decision v2 -- CHANGED after the squash-merge."',
        )
        assert record_v1 != record_v2  # fixture sanity

        _push_branch_with_record(bare, tmp_path / "scratch-a", branch_a, target_rel, record_v1)
        _squash_merge_record_into_main(
            bare, tmp_path / "scratch-a-squash", target_rel, record_v1, _TOKEN
        )
        _push_branch_with_record(bare, tmp_path / "scratch-b", branch_b, target_rel, record_v2)

        branches, error = find_in_flight_branches(repo, _TOKEN, target_rel)

        assert error is None
        assert branches == [branch_b]
