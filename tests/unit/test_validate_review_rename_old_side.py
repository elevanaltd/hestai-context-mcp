"""Issue #161 (option C): a rename must not launder a file out of its facet.

The review gate used to classify only a changed file's NEW path, so renaming a
governed file to an exempt name (``specs/agent.oct.md`` -> ``notes.md``) and
editing it in the same change asked for zero reviewers.

Option C makes ``get_changed_files`` the sole producer of every fact
classification needs: it resolves the comparison point once, inside itself,
and records the text of each side on the file record. Classification is then a
pure calculation over those records. These tests pin that contract:

* real git (hermetic) for both ``get_changed_files`` branches -- local
  ``--cached`` and CI ``GITHUB_BASE_REF``;
* a NAMED base branch that advanced after divergence (a SHA-pinned fixture
  cannot express this);
* an old side whose git read itself FAILS, and a hand-built record that names a
  ``previous_path`` but carries no recorded old side;
* the reintroduction guard: classification must run with every git subprocess
  and every file open tripwired;
* the comparison point is resolved exactly once per ``main()`` run;
* identical bytes classify the same on either side of a change.

Scope: these tests cover CLASSIFICATION only. The bitemporal declaration
scanner (``_collect_bitemporal_declarations``) reads base blobs on its own, at
the base-branch tip; that is issue #181 and is deliberately not asserted here.
"""

from __future__ import annotations

import builtins
import io
import os
import pathlib
import subprocess
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
import validate_review

# Captured at import so fixture git calls keep working while a test has
# wrapped or tripwired subprocess.
_REAL_RUN = subprocess.run
_REAL_POPEN = subprocess.Popen

_AGENT_SPEC = (
    "===ROGUE===\n"
    "META:\n"
    "  TYPE::AGENT_DEFINITION\n"
    '  VERSION::"1.0"\n'
    "§1::IDENTITY\n"
    "  ROLE::ROGUE\n"
    "  MISSION::EXAMPLE\n"
    "  NOTES::[one, two, three, four, five]\n"
    "===END===\n"
)
_RULE_SPEC = _AGENT_SPEC.replace("TYPE::AGENT_DEFINITION", "TYPE::RULE")

_EXECUTABLE_SPEC_ROLES = {"CE", "CRS", "SR"}

_GIT_ENV_TO_CLEAR = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_COMMON_DIR",
    "GIT_PREFIX",
)


# ---------------------------------------------------------------------------
# Hermetic real-git fixtures
# ---------------------------------------------------------------------------
def _git(repo: Path, *args: str) -> str:
    result = _REAL_RUN(["git", *args], cwd=repo, capture_output=True, text=True, check=True)
    return result.stdout


@pytest.fixture
def hermetic_git(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Isolate git from the developer's global/system config and any hook env.

    Mirrors a CI runner: no global identity, so every repo sets its own
    (repo-local user.name/email, user.useConfigOnly so macOS cannot derive
    one from the OS user).
    """
    empty_config = tmp_path / "empty-gitconfig"
    empty_config.write_text("")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty_config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for name in _GIT_ENV_TO_CLEAR:
        monkeypatch.delenv(name, raising=False)
    for name in ("CI", "GITHUB_BASE_REF", "PR_BASE_REF", "PR_NUMBER", "CACHED_GATE_DATA"):
        monkeypatch.delenv(name, raising=False)
    return tmp_path


def _init_repo(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q")
    _git(root, "symbolic-ref", "HEAD", "refs/heads/main")
    _git(root, "config", "user.name", "Test")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.useConfigOnly", "true")
    _git(root, "config", "commit.gpgsign", "false")
    _git(root, "config", "core.autocrlf", "false")
    return root


def _write(repo: Path, rel: str, content: str | bytes) -> None:
    target = repo / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        target.write_bytes(content)
    else:
        target.write_text(content, encoding="utf-8")


def _commit_all(repo: Path, message: str) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)


def _base_repo(root: Path, files: dict[str, str | bytes]) -> Path:
    repo = _init_repo(root)
    for rel, content in files.items():
        _write(repo, rel, content)
    _commit_all(repo, "base")
    return repo


def _rename_with_edit(repo: Path, old: str, new: str, *, edit: bool = True) -> None:
    """Stage a rename (plus a one-line edit) in the index."""
    _git(repo, "mv", old, new)
    if edit:
        with (repo / new).open("a", encoding="utf-8") as fh:
            fh.write("  EDITED::true\n")
    _git(repo, "add", "-A")


def _enter_mode(
    monkeypatch: pytest.MonkeyPatch, repo: Path, mode: str, *, base_ref: str = "main"
) -> None:
    """Point the validator at ``repo`` in the requested get_changed_files branch.

    ``local``: changes stay staged, the validator diffs ``--cached``.
    ``ci``: changes are committed on a feature branch; ``GITHUB_BASE_REF`` names
    the base branch, exactly as the workflow exports it.
    """
    if mode == "ci":
        _git(repo, "commit", "-q", "-m", "feature change")
        monkeypatch.setenv("CI", "true")
        monkeypatch.setenv("GITHUB_BASE_REF", base_ref)
    else:
        monkeypatch.delenv("CI", raising=False)
        monkeypatch.delenv("GITHUB_BASE_REF", raising=False)
    monkeypatch.chdir(repo)


def _feature_branch(repo: Path) -> None:
    _git(repo, "checkout", "-q", "-b", "feature")


def _records_for(path: str, files: list[dict[str, Any]]) -> dict[str, Any]:
    matches = [f for f in files if f["path"] == path]
    assert len(matches) == 1, f"expected one record for {path!r}, got {files!r}"
    return matches[0]


MODES = pytest.mark.parametrize("mode", ["local", "ci"])


# ---------------------------------------------------------------------------
# 1. Rename plus edit: the old side's identity must reach classification
# ---------------------------------------------------------------------------
@pytest.mark.behavior
@pytest.mark.security
class TestRenamePlusEditKeepsOldFacet:
    """``specs/agent.oct.md`` (TYPE::AGENT_DEFINITION) -> ``notes.md`` + edit."""

    @MODES
    def test_agent_spec_renamed_to_exempt_name_requires_reviewers(
        self, mode: str, hermetic_git: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = _base_repo(hermetic_git / "repo", {"specs/agent.oct.md": _AGENT_SPEC})
        if mode == "ci":
            _feature_branch(repo)
        _rename_with_edit(repo, "specs/agent.oct.md", "notes.md")
        _enter_mode(monkeypatch, repo, mode)

        files = validate_review.get_changed_files()
        record = _records_for("notes.md", files)
        assert record.get("previous_path") == "specs/agent.oct.md", record

        facets, roles, tier, reason = validate_review.classify_pr_facets(files)
        assert "EXECUTABLE_SPEC" in facets, f"old side must keep its facet, got {facets} ({reason})"
        assert roles >= _EXECUTABLE_SPEC_ROLES, f"reviewers required, got {roles}"
        assert tier not in {"TIER_0_EXEMPT", "TIER_1_SELF"}, tier

    @MODES
    def test_security_path_renamed_to_exempt_name_requires_reviewers(
        self, mode: str, hermetic_git: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The issue's own facet-agnostic repro: ``auth/login.py`` -> ``docs.md``."""
        body = "".join(f"line_{i} = {i}\n" for i in range(12))
        repo = _base_repo(hermetic_git / "repo", {"auth/login.py": body})
        if mode == "ci":
            _feature_branch(repo)
        _rename_with_edit(repo, "auth/login.py", "docs.md")
        _enter_mode(monkeypatch, repo, mode)

        facets, roles, tier, _ = validate_review.classify_pr_facets(
            validate_review.get_changed_files()
        )
        assert "SECURITY" in facets, facets
        assert tier != "TIER_0_EXEMPT", tier
        assert roles, "a renamed security path must require reviewers"


# ---------------------------------------------------------------------------
# 2. A named base branch that advanced after divergence
# ---------------------------------------------------------------------------
@pytest.mark.behavior
@pytest.mark.security
class TestMergeBaseGovernsOldSide:
    """The base branch changes the old path to TYPE::RULE AFTER the feature
    branch diverged. The diff's left side is the merge base, so the merge-base
    content (AGENT_DEFINITION) must govern, not the base-branch tip (RULE)."""

    def test_base_branch_advanced_after_divergence(
        self, hermetic_git: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = _base_repo(hermetic_git / "repo", {"specs/agent.oct.md": _AGENT_SPEC})
        _feature_branch(repo)
        _rename_with_edit(repo, "specs/agent.oct.md", "notes.md")
        _git(repo, "commit", "-q", "-m", "feature: rename + edit")

        _git(repo, "checkout", "-q", "main")
        _write(repo, "specs/agent.oct.md", _RULE_SPEC)
        _commit_all(repo, "main advances: agent spec becomes a rule")
        _git(repo, "checkout", "-q", "feature")

        monkeypatch.setenv("CI", "true")
        monkeypatch.setenv("GITHUB_BASE_REF", "main")
        monkeypatch.chdir(repo)

        files = validate_review.get_changed_files()
        facets, roles, tier, reason = validate_review.classify_pr_facets(files)
        assert "EXECUTABLE_SPEC" in facets, (
            "merge-base content (AGENT_DEFINITION) must govern the old side, "
            f"not the advanced base tip (RULE); got {facets} ({reason})"
        )
        assert roles >= _EXECUTABLE_SPEC_ROLES, roles
        assert tier not in {"TIER_0_EXEMPT", "TIER_1_SELF"}, tier


# ---------------------------------------------------------------------------
# 3. Old side unreadable because the git read itself fails
# ---------------------------------------------------------------------------
def _failing_revision_reads(target_path: str) -> tuple[Callable[..., Any], Callable[..., Any]]:
    """Wrap subprocess so any ``<rev>:<target_path>`` read is sent to a path
    that does not exist -- the real git process runs and FAILS. Everything
    else passes through untouched.
    """
    suffix = f":{target_path}"

    def _rewrite(cmd: Any) -> Any:
        if isinstance(cmd, list | tuple):
            return [
                (
                    (arg[: -len(suffix)] + ":__unreadable_by_test__/missing")
                    if isinstance(arg, str) and arg.endswith(suffix)
                    else arg
                )
                for arg in cmd
            ]
        return cmd

    def run(cmd: Any, *args: Any, **kwargs: Any) -> Any:
        return _REAL_RUN(_rewrite(cmd), *args, **kwargs)

    def popen(cmd: Any, *args: Any, **kwargs: Any) -> Any:
        return _REAL_POPEN(_rewrite(cmd), *args, **kwargs)

    return run, popen


@pytest.mark.behavior
@pytest.mark.security
class TestUnreadableOldSideEscalatesNarrowly:
    """An old side that cannot be read is one ambiguous file inside a known
    diff: escalate (never hard-abort), and only where the old NAME alone lands
    on the ambiguous GOVERNANCE fallback."""

    @MODES
    @pytest.mark.parametrize(
        ("old_path", "old_text", "expected_facets"),
        [
            # Old name alone -> .oct.md GOVERNANCE fallback -> escalate.
            ("specs/agent.oct.md", _AGENT_SPEC, {"EXECUTABLE_SPEC"}),
            # Old name alone has an ordinary category -> keep it, no escalation.
            ("auth/login.py", "".join(f"v{i} = {i}\n" for i in range(12)), {"SECURITY"}),
            ("src/utils.py", "".join(f"u{i} = {i}\n" for i in range(12)), {"ROUTINE_CODE"}),
        ],
    )
    def test_git_read_failure_escalates_without_abort(
        self,
        mode: str,
        old_path: str,
        old_text: str,
        expected_facets: set[str],
        hermetic_git: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        repo = _base_repo(hermetic_git / "repo", {old_path: old_text})
        if mode == "ci":
            _feature_branch(repo)
        _rename_with_edit(repo, old_path, "notes.md")
        _enter_mode(monkeypatch, repo, mode)

        run, popen = _failing_revision_reads(old_path)
        monkeypatch.setattr(subprocess, "run", run)
        monkeypatch.setattr(subprocess, "Popen", popen)

        files = validate_review.get_changed_files()  # must not raise / exit
        record = _records_for("notes.md", files)
        assert record.get("previous_path") == old_path, record

        facets, roles, tier, reason = validate_review.classify_pr_facets(files)
        assert facets == expected_facets, f"{old_path}: got {facets} ({reason})"
        assert tier != "TIER_0_EXEMPT", tier


# ---------------------------------------------------------------------------
# 4. previous_path with NO recorded old side is not "not a rename"
# ---------------------------------------------------------------------------
@pytest.mark.unit
@pytest.mark.security
class TestPreviousPathWithoutOldSideState:
    """Stub and hand-built records reach classification. A record that names a
    previous_path but carries no recorded old side must be treated as
    unreadable -- silence must never read as safety."""

    @pytest.mark.parametrize(
        ("previous_path", "expected_facets"),
        [
            ("specs/agent.oct.md", {"EXECUTABLE_SPEC"}),
            ("auth/login.py", {"SECURITY"}),
            ("src/utils.py", {"ROUTINE_CODE"}),
        ],
    )
    def test_missing_old_side_state_escalates(
        self, previous_path: str, expected_facets: set[str]
    ) -> None:
        record = {
            "path": "notes.md",
            "previous_path": previous_path,
            "status": "R",
            "added": 1,
            "deleted": 1,
            "total_changed": 2,
        }
        facets, roles, tier, reason = validate_review.classify_pr_facets([record])
        assert facets == expected_facets, f"got {facets} ({reason})"
        assert tier != "TIER_0_EXEMPT", tier

    def test_missing_old_side_state_on_spec_is_not_self_review(self) -> None:
        record = {
            "path": "notes.md",
            "previous_path": "specs/agent.oct.md",
            "status": "R",
            "added": 1,
            "deleted": 1,
            "total_changed": 2,
        }
        _, roles, tier, _ = validate_review.classify_pr_facets([record])
        assert tier != "TIER_1_SELF", tier
        assert roles >= _EXECUTABLE_SPEC_ROLES, roles


# ---------------------------------------------------------------------------
# 5. Merge base unresolvable in CI -> exit 1 (settled ruling)
# ---------------------------------------------------------------------------
@pytest.mark.security
class TestUnresolvableMergeBaseExitsOne:
    """Regression guards: green before and after. The diff itself is
    unknowable without a merge base, so the gate fails closed."""

    def test_unrelated_histories_exit_1(
        self, hermetic_git: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = _base_repo(hermetic_git / "repo", {"a.py": "a = 1\n"})
        _git(repo, "checkout", "-q", "--orphan", "feature")
        _git(repo, "rm", "-rq", "--cached", ".")
        _write(repo, "b.py", "b = 2\n")
        _git(repo, "add", "b.py")
        _git(repo, "commit", "-q", "-m", "unrelated root")
        monkeypatch.setenv("CI", "true")
        monkeypatch.setenv("GITHUB_BASE_REF", "main")
        monkeypatch.chdir(repo)

        with pytest.raises(SystemExit) as exc_info:
            validate_review.get_changed_files()
        assert exc_info.value.code == 1

    def test_missing_base_ref_exit_1(
        self, hermetic_git: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = _base_repo(hermetic_git / "repo", {"a.py": "a = 1\n"})
        monkeypatch.setenv("CI", "true")
        monkeypatch.setenv("GITHUB_BASE_REF", "origin/no-such-branch")
        monkeypatch.chdir(repo)

        with pytest.raises(SystemExit) as exc_info:
            validate_review.get_changed_files()
        assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# 6. Reintroduction guard: classification consults neither git nor files
# ---------------------------------------------------------------------------
@contextmanager
def _tripwires() -> Iterator[list[str]]:
    """Make every subprocess call and every file open record itself and raise.

    Recording matters as much as raising: a bare ``except Exception`` inside
    the code under test would swallow the raise, so the recorded list is what
    the test asserts on.
    """
    used: list[str] = []

    def trip(name: str) -> Callable[..., Any]:
        def _tripped(*args: Any, **kwargs: Any) -> Any:
            used.append(f"{name}{args[:2]!r}")
            raise AssertionError(f"classification used {name}")

        return _tripped

    targets: list[tuple[Any, str]] = [
        (subprocess, "run"),
        (subprocess, "Popen"),
        (subprocess, "call"),
        (subprocess, "check_call"),
        (subprocess, "check_output"),
        (builtins, "open"),
        (io, "open"),
        (os, "open"),
        (os, "popen"),
        (pathlib.Path, "open"),
        (pathlib.Path, "read_text"),
        (pathlib.Path, "read_bytes"),
    ]
    saved = [(obj, attr, getattr(obj, attr)) for obj, attr in targets]
    try:
        for obj, attr in targets:
            setattr(obj, attr, trip(f"{getattr(obj, '__name__', obj)}.{attr}"))
        yield used
    finally:
        for obj, attr, original in saved:
            setattr(obj, attr, original)


@pytest.mark.behavior
@pytest.mark.security
class TestClassificationIsPure:
    """REINTRODUCTION GUARD. Any future second lookup during classification --
    by git or by file read -- fails here at once. Scope: CLASSIFICATION only
    (classify_pr_facets / determine_review_tier); the declaration scanner is
    issue #181 and is not covered."""

    @MODES
    def test_classification_makes_no_git_calls_or_file_opens(
        self, mode: str, hermetic_git: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = _base_repo(
            hermetic_git / "repo",
            {"specs/agent.oct.md": _AGENT_SPEC, "src/app.py": "x = 1\n"},
        )
        if mode == "ci":
            _feature_branch(repo)
        _rename_with_edit(repo, "specs/agent.oct.md", "notes.md")
        # Deliberately dissimilar to the renamed spec so git cannot pair them.
        _write(repo, "specs/new_skill.oct.md", "===S===\nMETA:\n  TYPE::SKILL\n===END===\n")
        _git(repo, "add", "-A")
        _enter_mode(monkeypatch, repo, mode)

        files = validate_review.get_changed_files()
        assert any(f.get("previous_path") for f in files), files

        with _tripwires() as used:
            facets, roles, tier, reason = validate_review.classify_pr_facets(files)
            declared_facets, declared_roles, _, _ = validate_review.classify_pr_facets(
                files, declared_roles={"CIV"}
            )
            tier_only, _ = validate_review.determine_review_tier(files)

        assert used == [], f"classification touched git or the filesystem: {used}"
        assert facets == {"EXECUTABLE_SPEC"}, f"got {facets} ({reason})"
        assert roles == _EXECUTABLE_SPEC_ROLES, roles
        assert tier == tier_only == "TIER_2_STANDARD", (tier, tier_only)
        renamed = _records_for("notes.md", files)
        assert renamed.get("previous_path") == "specs/agent.oct.md", renamed
        assert declared_facets == facets
        assert declared_roles == _EXECUTABLE_SPEC_ROLES | {"CIV"}


# ---------------------------------------------------------------------------
# 7. The comparison point is resolved exactly once per main() run
# ---------------------------------------------------------------------------
def _counting_subprocess(
    counter: list[list[str]],
) -> tuple[Callable[..., Any], Callable[..., Any]]:
    """Count every git command that decides the comparison point: an explicit
    ``git merge-base`` or any ``A...B`` symmetric range (which makes git
    compute a merge base internally)."""

    def _note(cmd: Any) -> None:
        if isinstance(cmd, list | tuple) and cmd and cmd[0] == "git":
            args = [str(a) for a in cmd]
            if "merge-base" in args or any("..." in a for a in args[1:]):
                counter.append(args)

    # subprocess.run itself calls subprocess.Popen, so a command issued via
    # run() must be counted once, not again by the Popen wrapper.
    inside_run: list[bool] = []

    def run(cmd: Any, *args: Any, **kwargs: Any) -> Any:
        _note(cmd)
        inside_run.append(True)
        try:
            return _REAL_RUN(cmd, *args, **kwargs)
        finally:
            inside_run.pop()

    def popen(cmd: Any, *args: Any, **kwargs: Any) -> Any:
        if not inside_run:
            _note(cmd)
        return _REAL_POPEN(cmd, *args, **kwargs)

    return run, popen


@pytest.mark.behavior
@pytest.mark.security
class TestComparisonPointResolvedOnce:
    """Driven through main(). The #174 cycle-3 blocker was a re-resolution
    after a failed first resolution, so the failure case is pinned too."""

    def _prepare(self, hermetic_git: Path, monkeypatch: pytest.MonkeyPatch, base_ref: str) -> None:
        repo = _base_repo(hermetic_git / "repo", {"specs/agent.oct.md": _AGENT_SPEC})
        _feature_branch(repo)
        _rename_with_edit(repo, "specs/agent.oct.md", "notes.md")
        _enter_mode(monkeypatch, repo, "ci", base_ref=base_ref)
        monkeypatch.setattr(validate_review, "_get_pr_body", lambda: "")
        monkeypatch.setattr(
            validate_review,
            "check_pr_comments",
            lambda *a, **k: (False, "missing reviews", sorted(k.get("required_roles", []))),
        )

    def test_resolved_exactly_once_on_success(
        self,
        hermetic_git: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        self._prepare(hermetic_git, monkeypatch, "main")
        resolutions: list[list[str]] = []
        run, popen = _counting_subprocess(resolutions)
        monkeypatch.setattr(subprocess, "run", run)
        monkeypatch.setattr(subprocess, "Popen", popen)

        exit_code = validate_review.main()

        out = capsys.readouterr().out
        assert (
            len(resolutions) == 1
        ), f"comparison point resolved {len(resolutions)}x: {resolutions}"
        assert exit_code == 1, out  # reviews required and missing, in CI
        assert "EXECUTABLE_SPEC" in out, out

    def test_failed_first_resolution_is_not_retried(
        self, hermetic_git: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._prepare(hermetic_git, monkeypatch, "origin/no-such-branch")
        resolutions: list[list[str]] = []
        run, popen = _counting_subprocess(resolutions)
        monkeypatch.setattr(subprocess, "run", run)
        monkeypatch.setattr(subprocess, "Popen", popen)

        with pytest.raises(SystemExit) as exc_info:
            validate_review.main()

        assert exc_info.value.code == 1
        assert (
            len(resolutions) == 1
        ), f"comparison point resolved {len(resolutions)}x: {resolutions}"


# ---------------------------------------------------------------------------
# 8. Identical bytes classify the same on either side of a change
# ---------------------------------------------------------------------------
@pytest.mark.behavior
@pytest.mark.security
class TestIdenticalBytesClassifyTheSameOnEitherSide:
    """``str.splitlines`` also breaks on \\x0c, \\x85, U+2028 and U+2029 where
    ``readline`` does not. With 60 such separators ahead of TYPE::, two
    different line rules put TYPE:: inside or outside the 50-line sniff window
    -- attacker-authorable bytes deciding the facet by which side they
    arrive on. One decode policy and one line rule for both sides."""

    @MODES
    @pytest.mark.parametrize("separator", ["\x0c", "\x85", " ", " "])
    def test_old_side_and_new_side_agree(
        self,
        mode: str,
        separator: str,
        hermetic_git: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        payload = (("A" + separator) * 60 + "TYPE::AGENT_DEFINITION\n").encode("utf-8")

        # Old side only: the payload is renamed away to an exempt name.
        old_repo = _base_repo(hermetic_git / "old", {"specs/payload.oct.md": payload})
        if mode == "ci":
            _feature_branch(old_repo)
        _rename_with_edit(old_repo, "specs/payload.oct.md", "notes.md", edit=False)
        _enter_mode(monkeypatch, old_repo, mode)
        old_facets, _, _, old_reason = validate_review.classify_pr_facets(
            validate_review.get_changed_files()
        )

        # New side only: identical bytes arrive as a new file.
        new_repo = _base_repo(hermetic_git / "new", {"src/app.py": "x = 1\n"})
        if mode == "ci":
            _feature_branch(new_repo)
        _write(new_repo, "specs/payload.oct.md", payload)
        _git(new_repo, "add", "-A")
        _enter_mode(monkeypatch, new_repo, mode)
        new_facets, _, _, new_reason = validate_review.classify_pr_facets(
            validate_review.get_changed_files()
        )

        # Pin the expected facet on EACH side first: equality alone would also
        # pass if both sides regressed together (e.g. both to GOVERNANCE).
        # With one line rule (universal newlines) these separators do not
        # split lines, so TYPE::AGENT_DEFINITION sits on line 1.
        assert new_facets == {"EXECUTABLE_SPEC"}, new_reason
        assert old_facets == {"EXECUTABLE_SPEC"}, old_reason
        assert old_facets == new_facets, (
            f"identical bytes classified differently: old side {old_facets} ({old_reason}) "
            f"vs new side {new_facets} ({new_reason})"
        )


# ---------------------------------------------------------------------------
# 9. Content reads are bounded by BYTES (issue #185 item 2)
# ---------------------------------------------------------------------------
@pytest.mark.behavior
class TestRecordedContentIsByteBounded:
    """A single enormous line must not be read whole on either side."""

    _HUGE = b"TYPE::RULE " + b"x" * (2 * 1024 * 1024)

    @staticmethod
    def _assert_bounded(content: str) -> None:
        limit = validate_review._CONTENT_READ_LIMIT_BYTES
        # The documented contract (issue #185 item 2): changing the bound is a
        # reviewed decision, not a silent drift.
        assert limit == 64 * 1024, limit
        # Every decoded character consumed at least one byte, so this bounds
        # the bytes read too.
        assert len(content) <= limit, (len(content), limit)

    @MODES
    def test_new_side_read_is_bounded(
        self, mode: str, hermetic_git: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = _base_repo(hermetic_git / "repo", {"src/app.py": "x = 1\n"})
        if mode == "ci":
            _feature_branch(repo)
        _write(repo, "specs/huge.oct.md", self._HUGE)
        _git(repo, "add", "-A")
        _enter_mode(monkeypatch, repo, mode)

        record = _records_for("specs/huge.oct.md", validate_review.get_changed_files())
        content = record["new_content"]
        assert isinstance(content, str)
        assert content.startswith("TYPE::RULE")
        self._assert_bounded(content)

    @MODES
    def test_old_side_read_is_bounded(
        self, mode: str, hermetic_git: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = _base_repo(hermetic_git / "repo", {"specs/huge.oct.md": self._HUGE})
        if mode == "ci":
            _feature_branch(repo)
        _rename_with_edit(repo, "specs/huge.oct.md", "notes.md", edit=False)
        _enter_mode(monkeypatch, repo, mode)

        record = _records_for("notes.md", validate_review.get_changed_files())
        content = record["old_content"]
        assert isinstance(content, str)
        assert content.startswith("TYPE::RULE")
        self._assert_bounded(content)


# ---------------------------------------------------------------------------
# 10. A tracked .oct.md SYMLINK is conservatively an executable spec
#     (CE BLOCKED on PR #187, rework round 1)
# ---------------------------------------------------------------------------
def _symlink(repo: Path, rel: str, target: str) -> None:
    link = repo / rel
    link.parent.mkdir(parents=True, exist_ok=True)
    if link.is_symlink() or link.exists():
        link.unlink()
    os.symlink(target, link)


_SYMLINK_TARGETS = pytest.mark.parametrize(
    "target",
    [
        "../lib/real_agent.oct.md",  # resolves to a real agent spec
        "../lib/does_not_exist.oct.md",  # dangling
    ],
)


@pytest.mark.behavior
@pytest.mark.security
class TestOctaveSymlinkIsExecutableSpec:
    """In CI the new side is read as a git object, so a tracked ``.oct.md``
    symlink used to be sniffed as its link-target TEXT (no TYPE::) and fall to
    GOVERNANCE -- losing CE and CRS. The producer must take the object mode
    from the diff it already runs and mark the side explicitly; classification
    then treats an ``.oct.md`` symlink as EXECUTABLE_SPEC, with no I/O.

    Scope: only ``.oct.md`` paths are content-classified, so only they are
    affected. Symlinks under any other name keep their path classification.
    """

    @staticmethod
    def _repo(hermetic_git: Path, files: dict[str, str | bytes] | None = None) -> Path:
        return _base_repo(
            hermetic_git / "repo",
            {"lib/real_agent.oct.md": _AGENT_SPEC, "README.md": "readme\n", **(files or {})},
        )

    @MODES
    @_SYMLINK_TARGETS
    def test_new_octave_symlink_is_executable_spec(
        self, mode: str, target: str, hermetic_git: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = self._repo(hermetic_git)
        if mode == "ci":
            _feature_branch(repo)
        _symlink(repo, "specs/link.oct.md", target)
        _git(repo, "add", "-A")
        _enter_mode(monkeypatch, repo, mode)

        files = validate_review.get_changed_files()
        facets, roles, tier, reason = validate_review.classify_pr_facets(files)
        assert facets == {"EXECUTABLE_SPEC"}, f"got {facets} ({reason})"
        assert {"CE", "CRS"} <= roles, roles
        assert tier not in {"TIER_0_EXEMPT", "TIER_1_SELF"}, tier

    @MODES
    @pytest.mark.parametrize("change", ["retarget", "regular_to_symlink"])
    def test_modified_octave_symlink_is_executable_spec(
        self, mode: str, change: str, hermetic_git: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A modified symlink (new target), and a regular RULE file replaced by
        a symlink (git status T), are symlinks on the new side too."""
        if change == "retarget":
            repo = self._repo(hermetic_git)
            _symlink(repo, "specs/link.oct.md", "../lib/real_agent.oct.md")
            _commit_all(repo, "base symlink")
        else:
            repo = self._repo(hermetic_git, {"specs/link.oct.md": _RULE_SPEC})
        if mode == "ci":
            _feature_branch(repo)
        _symlink(repo, "specs/link.oct.md", "../lib/does_not_exist.oct.md")
        _git(repo, "add", "-A")
        _enter_mode(monkeypatch, repo, mode)

        facets, roles, tier, reason = validate_review.classify_pr_facets(
            validate_review.get_changed_files()
        )
        assert facets == {"EXECUTABLE_SPEC"}, f"got {facets} ({reason})"
        assert {"CE", "CRS"} <= roles, roles

    @MODES
    def test_renamed_away_octave_symlink_old_side_is_executable_spec(
        self, mode: str, hermetic_git: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = self._repo(hermetic_git)
        _symlink(repo, "specs/link.oct.md", "../lib/real_agent.oct.md")
        _commit_all(repo, "base symlink")
        if mode == "ci":
            _feature_branch(repo)
        _rename_with_edit(repo, "specs/link.oct.md", "notes.md", edit=False)
        _enter_mode(monkeypatch, repo, mode)

        files = validate_review.get_changed_files()
        record = _records_for("notes.md", files)
        assert record.get("previous_path") == "specs/link.oct.md", record
        facets, roles, tier, reason = validate_review.classify_pr_facets(files)
        assert facets == {"EXECUTABLE_SPEC"}, f"got {facets} ({reason})"
        assert {"CE", "CRS"} <= roles, roles
        assert tier not in {"TIER_0_EXEMPT", "TIER_1_SELF"}, tier

    @MODES
    def test_producer_marks_symlink_sides_explicitly(
        self, mode: str, hermetic_git: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The mark is its OWN state -- never text, never CONTENT_UNAVAILABLE."""
        repo = self._repo(hermetic_git)
        _symlink(repo, "specs/old_link.oct.md", "../lib/real_agent.oct.md")
        _commit_all(repo, "base symlink")
        if mode == "ci":
            _feature_branch(repo)
        _rename_with_edit(repo, "specs/old_link.oct.md", "notes.md", edit=False)
        _symlink(repo, "specs/new_link.oct.md", "../lib/real_agent.oct.md")
        _git(repo, "add", "-A")
        _enter_mode(monkeypatch, repo, mode)

        files = validate_review.get_changed_files()
        renamed = _records_for("notes.md", files)
        added = _records_for("specs/new_link.oct.md", files)
        assert renamed["old_content"] is validate_review.CONTENT_SYMLINK, renamed
        assert added["new_content"] is validate_review.CONTENT_SYMLINK, added
        assert validate_review.CONTENT_SYMLINK is not validate_review.CONTENT_UNAVAILABLE

    @MODES
    def test_regular_rule_octave_stays_governance(
        self, mode: str, hermetic_git: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No over-escalation: a regular (non-symlink) TYPE::RULE file is GOVERNANCE."""
        repo = self._repo(hermetic_git)
        if mode == "ci":
            _feature_branch(repo)
        _write(repo, "docs/rules/naming.oct.md", _RULE_SPEC)
        _git(repo, "add", "-A")
        _enter_mode(monkeypatch, repo, mode)

        facets, _, _, reason = validate_review.classify_pr_facets(
            validate_review.get_changed_files()
        )
        # Facet only: whether a small GOVERNANCE-only change self-reviews is
        # #180's question, and these commits must not depend on it.
        assert facets == {"GOVERNANCE"}, f"got {facets} ({reason})"

    @MODES
    @pytest.mark.parametrize(
        ("link", "target", "expected"),
        [
            ("src/link.py", "../lib/real_agent.oct.md", {"ROUTINE_CODE"}),
            ("docs/link.md", "../README.md", set()),
        ],
    )
    def test_non_octave_symlink_keeps_path_classification(
        self,
        mode: str,
        link: str,
        target: str,
        expected: set[str],
        hermetic_git: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        repo = self._repo(hermetic_git)
        if mode == "ci":
            _feature_branch(repo)
        _symlink(repo, link, target)
        _git(repo, "add", "-A")
        _enter_mode(monkeypatch, repo, mode)

        facets, _, _, reason = validate_review.classify_pr_facets(
            validate_review.get_changed_files()
        )
        assert facets == expected, f"got {facets} ({reason})"

    @MODES
    def test_symlink_classification_is_pure(
        self, mode: str, hermetic_git: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The symlink mark is decided by the producer; classifying it does no I/O."""
        repo = self._repo(hermetic_git)
        _symlink(repo, "specs/old_link.oct.md", "../lib/real_agent.oct.md")
        _commit_all(repo, "base symlink")
        if mode == "ci":
            _feature_branch(repo)
        _rename_with_edit(repo, "specs/old_link.oct.md", "notes.md", edit=False)
        _symlink(repo, "specs/new_link.oct.md", "../lib/does_not_exist.oct.md")
        _git(repo, "add", "-A")
        _enter_mode(monkeypatch, repo, mode)

        files = validate_review.get_changed_files()
        with _tripwires() as used:
            facets, roles, _, reason = validate_review.classify_pr_facets(files)
        assert used == [], f"classification touched git or the filesystem: {used}"
        assert facets == {"EXECUTABLE_SPEC"}, f"got {facets} ({reason})"
        assert {"CE", "CRS"} <= roles, roles
