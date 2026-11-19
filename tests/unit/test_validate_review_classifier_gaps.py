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
