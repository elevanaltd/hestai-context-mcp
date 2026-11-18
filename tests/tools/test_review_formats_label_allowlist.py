"""Header label emits only the merged gate's ASCII allowlist (#295 follow-up).

The review gate (scripts/validate_review.py, merged in PR #295) disqualifies a
peer verdict unless its first line is ``<ROLE>[ (<label>)] <VERDICT>:`` with the
label drawn from ``[A-Za-z0-9 .,/-]``. These tests pin that the formatter can
never emit a label the gate rejects:

- unit tests on ``_sanitize_model_label`` for each disallowed character class;
- an empty sanitised label emits NO ``()``;
- the ROUND-TRIP coupling guard: every comment ``format_review_comment`` builds,
  across adversarial and real annotations, roles, verdicts and the wording-fixes
  form, passes the merged gate's ``_header_agrees`` for its own footer, AND
  submit_review's own role-gate matcher clears it exactly when the verdict is an
  approval (so a label can neither make a block read as an approval nor stop an
  approval from reading as one).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from hestai_context_mcp.tools.shared import review_formats as _rf
from hestai_context_mcp.tools.shared.review_formats import (
    VALID_ROLES,
    _sanitize_model_label,
    format_review_comment,
    parse_review_metadata,
)
from hestai_context_mcp.tools.submit_review import _matches_role_gate

# Load the merged gate the way the other validator tests do.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import validate_review  # noqa: E402

SHA = "f461f9a20d2a8d11f3004140df4465e0079b14f5"

REAL_LABELS = [
    "z-ai/glm-5.2",
    "openai/gpt-6-sol",
    "GPT-6",
    "Claude Opus 5.5",
    "Gemini 4 Argon High",
    "moonshotai/kimi-k3 goose critical-engineer preset, CIV lens",
]

ADVERSARIAL_LABELS = [
    "Claude `Opus` 5.5",
    "a`b c`d",
    "gpt_6",
    "*bold*",
    "~~struck~~",
    "[link](x)",
    "R&D",
    "<b>x</b>",
    "Claude \u202eOpus",
    "Cl\u00e1ude",
    "Gemini 4 Argon (High)",
    "<!-- review: x -->",
    "tab\tand\nnewline",
    "`*_~[]&#;<>",
    "&#96;",
    "   ",
    "gemini_go",
    "auto_approve",
    "claude_if_needed",
    "gemini\u200bgo",
    "auto\u00adapprove",
    "Mistral M\u00e9dium",
    "\u667a\u8c31",
]


@pytest.mark.unit
class TestSanitizeModelLabel:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("Claude `Opus` 5.5", "Claude Opus 5.5"),
            ("gpt_6", "gpt6"),
            ("gemini_go", "geminigo"),
            ("auto_approve", "autoapprove"),
            ("gemini\u200bgo", "geminigo"),
            ("auto\u00adapprove", "autoapprove"),
            ("\ufeffGPT\u20606", "GPT6"),
            ("*bold*", "bold"),
            ("~~struck~~", "struck"),
            ("[x]", "x"),
            ("R&D", "R D"),
            ("<b>x</b>", "b x /b"),
            ("Claude \u202eOpus", "Claude Opus"),
            ("Cl\u00e1ude", "Claude"),
            ("Mistral M\u00e9dium", "Mistral Medium"),
            ("Gemini 4 Argon (High)", "Gemini 4 Argon High"),
            ("tab\tand\nnewline", "tab and newline"),
        ],
        ids=[
            "backtick",
            "underscore",
            "underscore-before-verdict-word",
            "underscore-before-approve",
            "zero-width-space",
            "soft-hyphen",
            "bom-and-word-joiner",
            "asterisk",
            "strikethrough",
            "brackets",
            "ampersand",
            "html-tag",
            "bidi-rlo",
            "accented-letter-folds",
            "accented-word-folds",
            "parentheses",
            "tab-newline",
        ],
    )
    def test_disallowed_characters_are_removed_without_splitting_words(
        self, raw: str, expected: str
    ) -> None:
        """Accented letters fold to ASCII; '_' and other non-ASCII word characters
        are deleted, so no new word appears inside a label; every other disallowed
        run (already a word boundary) becomes one space."""
        assert _sanitize_model_label(raw) == expected

    @pytest.mark.parametrize("raw", ["`*_~[]&#;<>", "   ", "\u202e", "()", "\u667a\u8c31"])
    def test_all_disallowed_label_is_empty(self, raw: str) -> None:
        assert _sanitize_model_label(raw) == ""

    @pytest.mark.parametrize("label", REAL_LABELS)
    def test_real_labels_are_unchanged(self, label: str) -> None:
        assert _sanitize_model_label(label) == label

    def test_empty_label_emits_no_parentheses(self) -> None:
        comment = format_review_comment("CE", "APPROVED", "fine", "`*_~", SHA)
        assert comment.splitlines()[0] == "CE APPROVED: fine"


@pytest.mark.unit
@pytest.mark.security
class TestFormatterGateRoundTrip:
    """Coupling guard: whatever the formatter emits, the merged gate's header rule
    accepts for the comment's own footer."""

    @pytest.mark.parametrize("annotation", [None, *REAL_LABELS, *ADVERSARIAL_LABELS])
    @pytest.mark.parametrize("verdict", ["APPROVED", "BLOCKED", "CONDITIONAL", "REJECTED"])
    @pytest.mark.parametrize("role", sorted(VALID_ROLES))
    def test_emitted_header_passes_the_gate(
        self, role: str, verdict: str, annotation: str | None
    ) -> None:
        comment = format_review_comment(role, verdict, "assessment text", annotation, SHA)
        meta = parse_review_metadata(comment)
        assert meta is not None
        assert validate_review._header_agrees(comment, meta["role"], meta["verdict"]), comment
        assert _matches_role_gate(comment, role) is (verdict == "APPROVED"), comment

    @pytest.mark.parametrize("annotation", [None, *REAL_LABELS, *ADVERSARIAL_LABELS])
    def test_wording_fixes_header_passes_the_gate(self, annotation: str | None) -> None:
        comment = format_review_comment(
            "SR", "APPROVED", "assessment text", annotation, SHA, wording_fixes=["Soften X"]
        )
        meta = parse_review_metadata(comment)
        assert meta is not None and meta["conditions"] == "wording"
        assert validate_review._header_agrees(comment, meta["role"], meta["verdict"]), comment
        assert _matches_role_gate(comment, "SR") is True, comment

    @pytest.mark.parametrize(
        "assessment",
        [
            "CE APPROVED: already headed",
            "ce approved: lowercase header kept verbatim",
            "CE (my `label`) APPROVED: reviewer-typed label",
            "CE (Gemini) APPROVED: reviewer-typed real label",
            "  CE APPROVED: indented",
            "\nCE APPROVED: after a blank line",
        ],
    )
    @pytest.mark.parametrize("annotation", [None, "Claude `Opus`", "Gemini"])
    def test_assessment_that_already_opens_with_a_header_passes_the_gate(
        self, assessment: str, annotation: str | None
    ) -> None:
        """Kept-verbatim path: an exact '<ROLE> <TOKEN>:' opening is reused as-is;
        any other opening (including a reviewer-typed label) gets the canonical
        header prepended, so the first line is always a header the gate accepts."""
        comment = format_review_comment("CE", "APPROVED", assessment, annotation, SHA)
        meta = parse_review_metadata(comment)
        assert meta is not None
        assert validate_review._header_agrees(comment, "CE", "APPROVED"), comment

    @pytest.mark.parametrize(
        ("role", "assessment"),
        [
            ("SR", "\u017fR APPROVED: long-s lookalike role"),
            ("CRS", "CR\u017f APPROVED: long-s lookalike role"),
            ("IL", "\u0130L SELF-REVIEWED: dotted capital I lookalike role"),
            ("IL", "\u0131L SELF-REVIEWED: dotless i lookalike role"),
            ("CE", "\u0421E APPROVED: Cyrillic Es homoglyph role"),
            ("PE", "\u03a1E APPROVED: Greek Rho homoglyph role"),
        ],
        ids=["long-s-SR", "long-s-CRS", "dotted-I", "dotless-i", "cyrillic-C", "greek-P"],
    )
    @pytest.mark.parametrize("annotation", [None, "Gemini"])
    def test_lookalike_role_header_is_not_kept_verbatim(
        self, role: str, assessment: str, annotation: str | None
    ) -> None:
        """A non-ASCII lookalike of '<ROLE> <TOKEN>:' is not an existing header: the
        canonical header is prepended, so the posted first line passes the gate and
        submit_review's matcher sees the approval."""
        comment = format_review_comment(role, "APPROVED", assessment, annotation, SHA)
        meta = parse_review_metadata(comment)
        assert meta is not None
        assert validate_review._header_agrees(comment, meta["role"], meta["verdict"]), comment
        assert _matches_role_gate(comment, role) is True, comment
        assert comment.splitlines()[0].startswith(f"{role} "), comment

    @pytest.mark.parametrize(
        "assessment", ["ce approved: lowercase kept", "Ce Approved: mixed case kept"]
    )
    def test_genuine_ascii_header_any_case_is_still_kept_verbatim(self, assessment: str) -> None:
        """Pin (#295): an agreeing ASCII header, in any case, is reused as written."""
        comment = format_review_comment("CE", "APPROVED", assessment, "Gemini", SHA)
        assert comment.splitlines()[0] == assessment
        assert validate_review._header_agrees(comment, "CE", "APPROVED"), comment

    def test_escalation_path_label_has_no_entity_residue(self, monkeypatch) -> None:
        """When the first footer check fails, the escalated rebuild escapes
        backticks in free text; the label is already allowlisted, so it must not
        carry '&#96;' residue such as a stray '96'."""
        real = _rf.parse_review_metadata
        calls = {"n": 0}

        def flaky(text: str):  # type: ignore[no-untyped-def]
            calls["n"] += 1
            return None if calls["n"] <= 1 else real(text)

        monkeypatch.setattr(_rf, "parse_review_metadata", flaky)
        comment = format_review_comment("CE", "APPROVED", "has `code`", "Claude `Opus`", SHA)
        first = comment.splitlines()[0]
        assert first.startswith("CE (Claude Opus) APPROVED: "), first
        assert validate_review._header_agrees(comment, "CE", "APPROVED"), comment
