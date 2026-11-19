"""Classifier-gap defect fixes in scripts/validate_review.py.

One section per defect, each with a negative control showing that unrelated
paths classify exactly as before:

* #171  -- SKILL.md by basename (and library-shaped pattern .md), any layout.
* #268  -- anything under a ``tools/`` path segment is SECURITY (rule v3.3 s1).
* #157  -- F2 anchored ``shared/``; F3 TYPE sniff beyond line 50 and fail-closed
           unreadable/deleted ``.oct.md``.
* fail-closed PR-description fetch in CI.
"""

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
import validate_review


def _record(path: str, total: int = 3, status: str = "M", **extra: object) -> dict:
    return {
        "path": path,
        "added": total,
        "deleted": 0,
        "total_changed": total,
        "status": status,
        **extra,
    }


# ---------------------------------------------------------------------------
# #171 -- SKILL.md by basename, before the markdown exemption
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestSkillMdByBasename:
    @pytest.mark.parametrize(
        "path",
        [
            "resources/starter-library/skills/x/SKILL.md",
            "skills/x/SKILL.md",
            "library/skills/x/SKILL.md",
            ".hestai-sys/library/skills/x/SKILL.md",
            "SKILL.md",
            "some/other/layout/SKILL.md",
            "tests/fixtures/rogue/SKILL.md",
            "skills/x/skill.md",
        ],
    )
    def test_skill_md_any_layout_is_executable_spec(self, path: str) -> None:
        assert validate_review._classify_file_facet(path) == "EXECUTABLE_SPEC"

    @pytest.mark.parametrize(
        "path",
        ["resources/starter-library/patterns/x.md", "library/patterns/x.md"],
    )
    def test_library_shaped_pattern_md_is_executable_spec(self, path: str) -> None:
        assert validate_review._classify_file_facet(path) == "EXECUTABLE_SPEC"

    def test_skill_only_pr_requires_ce_crs_sr(self) -> None:
        files = [_record("resources/starter-library/skills/x/SKILL.md")]
        facets, roles, tier, _ = validate_review.classify_pr_facets(files)
        assert facets == {"EXECUTABLE_SPEC"}
        assert roles == {"CE", "CRS", "SR"}
        assert tier not in ("TIER_0_EXEMPT", "TIER_1_SELF")

    @pytest.mark.parametrize(
        "path",
        [
            "README.md",
            "docs/skills.md",
            "docs/SKILL-guide.md",
            "docs/patterns/x.md",
            "docs/library.md",
            "mylibrary-notes/patterns/x.md",
        ],
    )
    def test_negative_control_unrelated_markdown_stays_exempt(self, path: str) -> None:
        assert validate_review._classify_file_facet(path) is None


# ---------------------------------------------------------------------------
# #268 -- anything under a tools/ path segment is SECURITY (rule v3.3 s1)
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestToolsSegmentIsSecurity:
    @pytest.mark.parametrize(
        "path",
        [
            "src/hestai_context_mcp/tools/submit_governance.py",
            "src/hestai_context_mcp/tools/get_context.py",
            "src/hestai_context_mcp/tools/clock_in.py",
            "src/hestai_context_mcp/tools/shared/github_auth.py",
            "src/hestai_context_mcp/modules/tools/x.py",
            "tools/x.py",
            "scripts/tools/helper.sh",
        ],
    )
    def test_tools_segment_is_security(self, path: str) -> None:
        assert validate_review._classify_file_facet(path) == "SECURITY"

    def test_small_tools_edit_is_not_self_review(self) -> None:
        files = [_record("src/hestai_context_mcp/tools/clock_in.py", total=3)]
        facets, roles, tier, _ = validate_review.classify_pr_facets(files)
        assert facets == {"SECURITY"}
        assert roles == validate_review.FACET_ROLE_MAP["SECURITY"]
        assert tier != "TIER_1_SELF"

    @pytest.mark.parametrize(
        ("path", "expected"),
        [
            ("src/hestai_context_mcp/core/engine.py", "ROUTINE_CODE"),
            ("src/hestai_context_mcp/mytools/x.py", "ROUTINE_CODE"),
            ("src/hestai_context_mcp/tools_extra/x.py", "ROUTINE_CODE"),
            ("src/hestai_context_mcp/subtools/x.py", "ROUTINE_CODE"),
            ("tests/tools/test_x.py", None),
            ("docs/tools/usage.md", None),
        ],
    )
    def test_negative_control_unrelated_paths_unchanged(
        self, path: str, expected: str | None
    ) -> None:
        assert validate_review._classify_file_facet(path) == expected


# ---------------------------------------------------------------------------
# #157 F2 -- shared/ anchored like its sibling patterns
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestSharedSegmentAnchored:
    @pytest.mark.parametrize(
        "path", ["shared/utils.py", "src/shared/utils.py", "src/pkg/shared/deep/utils.py"]
    )
    def test_shared_segment_is_security_at_any_depth(self, path: str) -> None:
        assert validate_review._classify_file_facet(path) == "SECURITY"

    @pytest.mark.parametrize(
        ("path", "expected"),
        [
            ("src/unshared/utils.py", "ROUTINE_CODE"),
            ("src/shared_utils/x.py", "ROUTINE_CODE"),
            ("src/myshared/x.py", "ROUTINE_CODE"),
            ("src/shared.py", "ROUTINE_CODE"),
            ("tests/shared/test_x.py", None),
            ("docs/shared/notes.md", None),
        ],
    )
    def test_negative_control_unrelated_paths_unchanged(
        self, path: str, expected: str | None
    ) -> None:
        assert validate_review._classify_file_facet(path) == expected


# ---------------------------------------------------------------------------
# #157 F3 -- TYPE line past line 50 is still read; unreadable/deleted
# .oct.md fails closed
# ---------------------------------------------------------------------------
def _padded_spec(type_name: str, type_line: int) -> str:
    lines = ["===PADDED===", "META:"]
    lines += [f"  // padding {i}" for i in range(type_line - 3)]
    lines.append(f"  TYPE::{type_name}")
    lines.append("===END===")
    assert lines.index(f"  TYPE::{type_name}") + 1 == type_line
    return "\n".join(lines) + "\n"


@pytest.mark.unit
class TestOctaveTypeSniffAndFailClosed:
    @pytest.mark.parametrize("type_line", [50, 51, 56, 500, 2000])
    def test_type_line_beyond_old_cap_is_read(self, type_line: int) -> None:
        text = _padded_spec("AGENT_DEFINITION", type_line)
        assert validate_review._sniff_octave_type(text) == "AGENT_DEFINITION"
        assert validate_review._classify_file_facet("docs/x.oct.md", text) == "EXECUTABLE_SPEC"

    def test_padded_spec_pr_requires_ce_crs_sr(self) -> None:
        files = [
            _record("docs/x.oct.md", new_content=_padded_spec("AGENT_DEFINITION", 56)),
        ]
        _facets, roles, _tier, _ = validate_review.classify_pr_facets(files)
        assert roles == validate_review.FACET_ROLE_MAP["EXECUTABLE_SPEC"]

    def test_unreadable_oct_md_is_executable_spec(self) -> None:
        got = validate_review._classify_file_facet(
            "docs/x.oct.md", validate_review.CONTENT_UNAVAILABLE
        )
        assert got == "EXECUTABLE_SPEC"

    def test_deleted_oct_md_pr_is_executable_spec(self) -> None:
        files = [
            _record(
                "docs/agents/gone.oct.md",
                total=40,
                status="D",
                new_content=validate_review.CONTENT_UNAVAILABLE,
            ),
        ]
        facets, roles, _tier, _ = validate_review.classify_pr_facets(files)
        assert facets == {"EXECUTABLE_SPEC"}
        assert roles == validate_review.FACET_ROLE_MAP["EXECUTABLE_SPEC"]

    def test_record_without_recorded_content_fails_closed(self) -> None:
        facets, _roles, _tier, _ = validate_review.classify_pr_facets([_record("docs/x.oct.md")])
        assert facets == {"EXECUTABLE_SPEC"}

    def test_negative_control_readable_governance_text_stays_governance(self) -> None:
        text = "===R===\nMETA:\n  TYPE::RULE\n===END===\n"
        assert validate_review._classify_file_facet("docs/x.oct.md", text) == "GOVERNANCE"

    def test_negative_control_no_type_text_stays_governance(self) -> None:
        text = "===R===\nMETA:\n  VERSION::1\n===END===\n"
        assert validate_review._classify_file_facet("docs/x.oct.md", text) == "GOVERNANCE"

    def test_negative_control_library_agent_path_unchanged(self) -> None:
        assert (
            validate_review._classify_file_facet("x/library/agents/a.oct.md", "")
            == "EXECUTABLE_SPEC"
        )


# ---------------------------------------------------------------------------
# Fail-closed PR-description fetch (CI)
# ---------------------------------------------------------------------------
def _gh_stub(outcome: object) -> Any:
    """A subprocess.run stand-in for ``gh pr view``: raise ``outcome`` or return it."""

    def run(cmd: list[str], *args: object, **kwargs: object) -> object:
        assert cmd[:3] == ["gh", "pr", "view"], cmd
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    return run


def _gh_ok(stdout: str | None) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr="")


@pytest.fixture
def ci_pr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CI", "true")
    monkeypatch.setenv("PR_NUMBER", "321")


@pytest.mark.unit
class TestPrBodyFetchFailsClosedInCI:
    @pytest.mark.parametrize(
        "outcome",
        [
            subprocess.CalledProcessError(1, ["gh"]),
            OSError("gh not found"),
            _gh_ok("not json"),
            _gh_ok(json.dumps({"title": "no body key"})),
            _gh_ok(json.dumps({"body": 42})),
            _gh_ok(None),  # json.loads(None) -> TypeError
            UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte"),
        ],
        ids=[
            "gh-exit-nonzero",
            "gh-missing",
            "unparseable",
            "body-key-missing",
            "body-not-text",
            "stdout-none-typeerror",
            "undecodable-unicodeerror",
        ],
    )
    def test_fetch_error_raises_in_ci(
        self, ci_pr: None, monkeypatch: pytest.MonkeyPatch, outcome: object
    ) -> None:
        monkeypatch.setattr(validate_review.subprocess, "run", _gh_stub(outcome))
        with pytest.raises(validate_review.PrBodyFetchError):
            validate_review._get_pr_body()

    @pytest.mark.parametrize("body", ["", "text", None])
    def test_empty_but_fetched_body_is_fine(
        self, ci_pr: None, monkeypatch: pytest.MonkeyPatch, body: str | None
    ) -> None:
        stub = _gh_stub(_gh_ok(json.dumps({"body": body})))
        monkeypatch.setattr(validate_review.subprocess, "run", stub)
        assert validate_review._get_pr_body() == (body or "")

    def test_negative_control_local_mode_stays_lenient(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("CI", raising=False)
        monkeypatch.setenv("PR_NUMBER", "321")
        monkeypatch.setattr(
            validate_review.subprocess, "run", _gh_stub(subprocess.CalledProcessError(1, ["gh"]))
        )
        assert validate_review._get_pr_body() == ""

    def _main_env(self, monkeypatch: pytest.MonkeyPatch, files: list[dict]) -> list[str]:
        monkeypatch.setenv("GITHUB_BASE_REF", "origin/main")
        monkeypatch.delenv("CACHED_GATE_DATA", raising=False)
        monkeypatch.setattr(validate_review, "_get_head_sha", lambda: "a" * 40)
        monkeypatch.setattr(validate_review, "_get_base_ref_sha", lambda: "b" * 40)
        monkeypatch.setattr(validate_review, "check_emergency_bypass", lambda: False)
        monkeypatch.setattr(validate_review, "get_changed_files", lambda: files)
        monkeypatch.setattr(validate_review, "_git_show_file", lambda *a, **k: None)
        calls: list[str] = []

        def fake_check(*args: object, **kwargs: object) -> tuple[bool, str, list[str]]:
            calls.append("check_pr_comments")
            return True, "ok", []

        monkeypatch.setattr(validate_review, "check_pr_comments", fake_check)
        return calls

    def test_main_fails_on_fetch_error_even_when_diff_is_tier0_exempt(
        self, ci_pr: None, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        docs_only = [_record("docs/README.md", total=2)]
        calls = self._main_env(monkeypatch, docs_only)
        monkeypatch.setattr(
            validate_review.subprocess, "run", _gh_stub(subprocess.CalledProcessError(1, ["gh"]))
        )
        assert validate_review.main() == 1
        out = capsys.readouterr()
        text = out.out + out.err
        assert "Review Tier: UNKNOWN" in text, text
        assert "Reason: PR description fetch failed" in text, text
        assert "Review not required" not in text
        # No cacheable gate data: the workflow would cache sha + roles from it.
        assert "REVIEW_GATE_JSON" not in text, text
        assert calls == []

    def test_main_empty_but_fetched_body_still_passes_exempt_diff(
        self, ci_pr: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        docs_only = [_record("docs/README.md", total=2)]
        self._main_env(monkeypatch, docs_only)
        monkeypatch.setattr(
            validate_review.subprocess, "run", _gh_stub(_gh_ok(json.dumps({"body": ""})))
        )
        assert validate_review.main() == 0


# ---------------------------------------------------------------------------
# Rework round 1 (CE): case-variant paths
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestCaseVariantPathsClassifyLikeLowercase:
    @pytest.mark.parametrize(
        "path",
        [
            "TOOLS/x.py",
            "Tools/x.py",
            "TOOLS/clock_in.py",
            "src/pkg/Tools/x.py",
            "SHARED/x.py",
            "src/Shared/x.py",
            "Hooks/x.py",
            "src/Auth/handler.py",
            "SRC/SESSION/store.py",
            "Clink/Agents/x.py",
        ],
    )
    def test_case_variant_security_and_architecture_paths_are_security(self, path: str) -> None:
        assert validate_review._classify_file_facet(path) == "SECURITY"

    @pytest.mark.parametrize(
        "path", ["Library/Patterns/x.md", "resources/Starter-Library/PATTERNS/x.md"]
    )
    def test_case_variant_library_pattern_md_is_executable_spec(self, path: str) -> None:
        assert validate_review._classify_file_facet(path) == "EXECUTABLE_SPEC"

    @pytest.mark.parametrize(
        ("path", "expected"),
        [
            ("TOOLS/clock_in.md", None),  # markdown exemption unchanged
            ("Docs/Tools/usage.md", None),
            ("src/MyTools/x.py", "ROUTINE_CODE"),
            ("src/UnShared/x.py", "ROUTINE_CODE"),
            ("Docs/Patterns/x.md", None),
        ],
    )
    def test_negative_control_unchanged(self, path: str, expected: str | None) -> None:
        assert validate_review._classify_file_facet(path) == expected


# ---------------------------------------------------------------------------
# Rework round 1 (CE): truncated .oct.md content fails closed
# ---------------------------------------------------------------------------
_LIMIT = 64 * 1024


def _git_repo_with(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, rel: str, data: bytes) -> None:
    def git(*args: str) -> None:
        subprocess.run(
            ["git", "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false", *args],
            cwd=tmp_path,
            check=True,
            capture_output=True,
            env={
                "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
                "HOME": str(tmp_path),
                "GIT_CONFIG_GLOBAL": "/dev/null",
                "GIT_CONFIG_SYSTEM": "/dev/null",
                "GIT_AUTHOR_NAME": "t",
                "GIT_AUTHOR_EMAIL": "t@example.invalid",
                "GIT_COMMITTER_NAME": "t",
                "GIT_COMMITTER_EMAIL": "t@example.invalid",
            },
        )

    if not (tmp_path / ".git").exists():  # reusable: later calls add a commit
        git("init", "-q")
    target = tmp_path / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    git("add", "-A")
    git("commit", "-q", "-m", "x")
    monkeypatch.chdir(tmp_path)


def _readers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, rel: str, data: bytes) -> dict:
    _git_repo_with(tmp_path, monkeypatch, rel, data)
    return {
        "working-tree": validate_review._read_working_tree_content(rel),
        "revision": validate_review._read_revision_content("HEAD", rel),
    }


@pytest.mark.unit
class TestTruncatedOctaveContentFailsClosed:
    REL = "docs/x.oct.md"

    def test_type_past_the_byte_bound_is_executable_spec_for_both_readers(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        data = b"===P===\nMETA:\n" + b"#" * _LIMIT + b"\n  TYPE::AGENT_DEFINITION\n===END===\n"
        for name, content in _readers(tmp_path, monkeypatch, self.REL, data).items():
            assert (
                validate_review._classify_file_facet(self.REL, content) == "EXECUTABLE_SPEC"
            ), name
            files = [_record(self.REL, new_content=content)]
            facets, _roles, _tier, _ = validate_review.classify_pr_facets(files)
            assert facets == {"EXECUTABLE_SPEC"}, name

    def test_truncated_file_with_type_inside_the_bound_keeps_its_sniffed_facet(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        data = b"===R===\nMETA:\n  TYPE::RULE\n" + b"#" * (2 * _LIMIT)
        for name, content in _readers(tmp_path, monkeypatch, self.REL, data).items():
            assert validate_review._classify_file_facet(self.REL, content) == "GOVERNANCE", name

    def test_untruncated_file_exactly_at_the_bound_without_type_is_governance(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        data = (b"#" * (_LIMIT - 1)) + b"\n"
        assert len(data) == _LIMIT
        for name, content in _readers(tmp_path, monkeypatch, self.REL, data).items():
            assert validate_review._classify_file_facet(self.REL, content) == "GOVERNANCE", name

    def test_read_is_still_byte_bounded(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        data = b"x" * (3 * _LIMIT)
        for name, content in _readers(tmp_path, monkeypatch, self.REL, data).items():
            assert isinstance(content, str) and len(content) <= _LIMIT, name


# ---------------------------------------------------------------------------
# Rework round 1 (CE): fetch-failure diagnostics carry gh's last stderr line
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestPrBodyFetchErrorCarriesStderr:
    def _raise_with(self, monkeypatch: pytest.MonkeyPatch, stderr: str | None) -> str:
        err = subprocess.CalledProcessError(1, ["gh"], stderr=stderr)
        monkeypatch.setattr(validate_review.subprocess, "run", _gh_stub(err))
        with pytest.raises(validate_review.PrBodyFetchError) as info:
            validate_review._get_pr_body()
        return str(info.value)

    def test_last_non_empty_stderr_line_is_included(
        self, ci_pr: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        msg = self._raise_with(monkeypatch, "warning: first\nHTTP 404: Not Found\n\n  \n")
        assert "HTTP 404: Not Found" in msg
        assert "warning: first" not in msg

    def test_control_characters_are_stripped(
        self, ci_pr: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        msg = self._raise_with(monkeypatch, "bad \x1b[31mred\x07 \x00text\r\n")
        assert "bad" in msg and "text" in msg
        assert not any(ord(c) < 32 or ord(c) == 127 for c in msg), repr(msg)

    def test_stderr_line_is_capped_at_200_characters(
        self, ci_pr: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        msg = self._raise_with(monkeypatch, "A" * 5000)
        assert "A" * 200 in msg
        assert "A" * 201 not in msg

    def test_token_values_from_the_environment_are_never_included(
        self, ci_pr: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GH_TOKEN", "ghs_SECRETVALUE123")
        monkeypatch.setenv("GITHUB_TOKEN", "ghs_OTHERSECRET456")
        msg = self._raise_with(
            monkeypatch, "auth failed for ghs_SECRETVALUE123 / ghs_OTHERSECRET456"
        )
        assert "ghs_SECRETVALUE123" not in msg and "ghs_OTHERSECRET456" not in msg
        assert "auth failed" in msg

    def test_missing_stderr_still_raises_the_designed_error(
        self, ci_pr: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        assert "gh pr view 321 failed" in self._raise_with(monkeypatch, None)


@pytest.mark.unit
class TestCutThroughTypeLineFailsClosed:
    """CE round 2: the byte bound can cut THROUGH the TYPE line. Only the final
    line of truncated text can be partial, so no cut position may turn an
    AGENT_DEFINITION into GOVERNANCE (e.g. ``TYPE::AGENT_DEFINITIO``)."""

    REL = "docs/x.oct.md"
    LINE = b"  TYPE::AGENT_DEFINITION\n"

    def _file(self, cut_into_line: int, line: bytes, tail: bytes = b"x" * 16) -> bytes:
        """A file whose first ``_LIMIT`` bytes end ``cut_into_line`` bytes into ``line``."""
        pad = b"#" * (_LIMIT - cut_into_line - 1) + b"\n"
        data = pad + line + tail
        assert data[:_LIMIT].endswith(line[:cut_into_line]) and len(data) > _LIMIT
        return data

    def test_every_cut_offset_through_an_agent_type_line_is_executable_spec(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # k = 0: cut just before the line; k = len(LINE): cut just after its "\n".
        for k in range(len(self.LINE) + 1):
            data = self._file(k, self.LINE)
            for name, content in _readers(tmp_path, monkeypatch, self.REL, data).items():
                facet = validate_review._classify_file_facet(self.REL, content)
                assert (
                    facet == "EXECUTABLE_SPEC"
                ), f"{name}: cut {k} bytes into TYPE line -> {facet}"

    def test_complete_rule_type_line_ending_exactly_at_the_bound_stays_governance(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        line = b"  TYPE::RULE\n"
        data = self._file(len(line), line)
        assert data[:_LIMIT].endswith(line)
        for name, content in _readers(tmp_path, monkeypatch, self.REL, data).items():
            assert isinstance(content, validate_review._TruncatedText), name
            assert validate_review._classify_file_facet(self.REL, content) == "GOVERNANCE", name

    def test_partial_rule_type_line_is_not_trusted_either(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # TYPE::RULE cut to "TYPE::RU" is a partial value: ignored, so the
        # truncated-with-no-TYPE rule applies.
        line = b"  TYPE::RULE\n"
        data = self._file(len(line) - 3, line)
        for name, content in _readers(tmp_path, monkeypatch, self.REL, data).items():
            assert (
                validate_review._classify_file_facet(self.REL, content) == "EXECUTABLE_SPEC"
            ), name

    def test_sniff_ignores_only_the_final_line_of_truncated_text(self) -> None:
        trunc = validate_review._TruncatedText
        assert validate_review._sniff_octave_type(trunc("a\n  TYPE::RULE\n")) == "RULE"
        assert validate_review._sniff_octave_type(trunc("a\n  TYPE::RULE")) == ""
        assert validate_review._sniff_octave_type(trunc("  TYPE::RULE")) == ""
        # Untruncated text keeps its final line: an unterminated last line is complete.
        assert validate_review._sniff_octave_type("a\n  TYPE::RULE") == "RULE"
