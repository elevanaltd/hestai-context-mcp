"""Regression tests for issue #85 — Gate-A TYPE:: extraction must be line-anchored.

Write-side root of the read-side P2 closed in #83. The shared Gate-A extractor
``type_checker._TYPE_RE = (?m)TYPE::(\\w+)`` uses an UNANCHORED substring
``.search()``, so a META line such as ``DOCUMENT_TYPE::DECISION_RECORD`` or
``CONTENT_TYPE::X`` false-matches as ``TYPE::...``. The read side worked around
this locally (``agr_read._TYPE_IS_DECISION_RECORD_RE``); this module proves the
shared write-side defect (and the same-class ``_REPO_ID_RE`` leak in the same
file) so the fix can line-anchor the extractor without loosening real-record
acceptance.

TDD RED: every test below MUST fail against the unanchored extractor and pass
once ``_TYPE_RE`` (and ``_REPO_ID_RE``) are line-anchored to ``^\\s*TYPE::`` /
``^\\s*REPO_ID::`` (mirroring the read-side anchored approach).

Constraints honoured (North Star §4 regex-only; PROD I4 structured returns):
the change must only TIGHTEN — reject ``*FIELD::`` substring leaks — never
loosen acceptance of a legitimately indented OCTAVE ``TYPE::`` line.
"""

from pathlib import Path

import pytest

from hestai_context_mcp.tools.governance.type_checker import (
    _extract_repo_id,
    _extract_type,
    validate_octave_content,
)


class TestExtractTypeLineAnchored:
    """``_extract_type`` must reject ``*TYPE::`` substring leaks and trailing garbage."""

    @pytest.mark.unit
    def test_document_type_does_not_leak_as_type(self) -> None:
        """``DOCUMENT_TYPE::DECISION_RECORD`` must NOT be extracted as the TYPE value.

        With the unanchored ``(?m)TYPE::(\\w+)`` + ``.search()``, the substring
        ``TYPE::DECISION_RECORD`` inside ``DOCUMENT_TYPE::DECISION_RECORD`` is
        falsely returned. There is no genuine ``TYPE::`` line here, so the
        anchored extractor must return ``None``.
        """
        content = (
            "===DECISION_RECORD===\n"
            "META:\n"
            "  DOCUMENT_TYPE::DECISION_RECORD\n"
            '  VERSION::"1.0"\n'
            "===END===\n"
        )
        assert _extract_type(content) is None

    @pytest.mark.unit
    def test_content_type_does_not_leak_as_type(self) -> None:
        """``CONTENT_TYPE::CONCEPT_CARD`` must NOT be extracted as the TYPE value."""
        content = "===CONCEPT_CARD===\nMETA:\n  CONTENT_TYPE::CONCEPT_CARD\n===END===\n"
        assert _extract_type(content) is None

    @pytest.mark.unit
    def test_real_indented_type_still_extracts(self) -> None:
        """A legitimately indented OCTAVE ``TYPE::`` line still extracts (no loosening)."""
        content = "===DECISION_RECORD===\nMETA:\n  TYPE::DECISION_RECORD\n===END===\n"
        assert _extract_type(content) == "DECISION_RECORD"

    @pytest.mark.unit
    def test_unindented_type_still_extracts(self) -> None:
        """A column-0 ``TYPE::`` line also extracts (``^\\s*`` admits zero indent)."""
        content = "===DECISION_RECORD===\nTYPE::DECISION_RECORD\n===END===\n"
        assert _extract_type(content) == "DECISION_RECORD"

    @pytest.mark.unit
    def test_trailing_garbage_rejected(self) -> None:
        """``TYPE::DECISION_RECORD EXTRA`` must NOT extract ``DECISION_RECORD``.

        The end-anchor (\\s*$) rejects a trailing-garbage line so a malformed
        TYPE declaration is not silently accepted as a clean value.
        """
        content = "===DECISION_RECORD===\nMETA:\n  TYPE::DECISION_RECORD EXTRA\n===END===\n"
        assert _extract_type(content) is None

    @pytest.mark.unit
    def test_document_type_does_not_shadow_real_type(self) -> None:
        """A ``DOCUMENT_TYPE::`` line preceding the real ``TYPE::`` must not win.

        ``.search()`` returns the FIRST match; with the unanchored regex a
        leading ``DOCUMENT_TYPE::CONCEPT_CARD`` line shadows the genuine
        ``TYPE::DECISION_RECORD`` below it, mis-classifying the record. The
        anchored extractor must skip the ``*TYPE::`` line and return the real
        value ``DECISION_RECORD``.
        """
        content = (
            "===DECISION_RECORD===\n"
            "META:\n"
            "  DOCUMENT_TYPE::CONCEPT_CARD\n"
            "  TYPE::DECISION_RECORD\n"
            "===END===\n"
        )
        assert _extract_type(content) == "DECISION_RECORD"


class TestValidateOctaveContentTypeLeak:
    """End-to-end Gate-A: a ``*TYPE::``-only document must fail with the right error."""

    @pytest.mark.unit
    def test_document_type_only_reports_missing_type(self, tmp_path: Path) -> None:
        """A record with only ``DOCUMENT_TYPE::`` (no real TYPE) must report a missing TYPE.

        Pre-fix, the leak makes ``_extract_type`` return ``DECISION_RECORD`` so
        validation advances past check 2 and emits a misleading "requires a
        TOKEN field" error. Post-fix it must short-circuit with the correct
        "No TYPE field found in META block." (PROD I4 structured return).
        """
        content = (
            "===DECISION_RECORD===\n"
            "META:\n"
            "  DOCUMENT_TYPE::DECISION_RECORD\n"
            '  VERSION::"1.0"\n'
            "===END===\n"
        )
        result = validate_octave_content(tmp_path, content)

        assert result.valid is False
        assert any("No TYPE field found" in e for e in result.errors)
        assert result.card_type is None


class TestExtractRepoIdLineAnchored:
    """Same-class ``*REPO_ID::`` substring leak in the same Gate-A file (#85 audit)."""

    @pytest.mark.unit
    def test_source_repo_id_does_not_leak_as_repo_id(self) -> None:
        """``SOURCE_REPO_ID::evil`` must NOT be extracted as the REPO_ID value.

        ``_REPO_ID_RE = REPO_ID::([^\\s]+)`` is unanchored, so the substring
        ``REPO_ID::evil`` inside ``SOURCE_REPO_ID::evil`` leaks. With no genuine
        ``REPO_ID::`` line the anchored extractor must return ``None``.
        """
        content = "===CONCEPT_CARD===\nMETA:\n  SOURCE_REPO_ID::evil-leak\n===END===\n"
        assert _extract_repo_id(content) is None

    @pytest.mark.unit
    def test_source_repo_id_does_not_shadow_real_repo_id(self) -> None:
        """A leading ``SOURCE_REPO_ID::`` line must not shadow the real ``REPO_ID::``."""
        content = (
            "===CONCEPT_CARD===\n"
            "META:\n"
            "  SOURCE_REPO_ID::evil-leak\n"
            "  REPO_ID::real-repo\n"
            "===END===\n"
        )
        assert _extract_repo_id(content) == "real-repo"

    @pytest.mark.unit
    def test_real_repo_id_still_extracts(self) -> None:
        """A legitimately indented ``REPO_ID::`` line still extracts (no loosening)."""
        content = "===CONCEPT_CARD===\nMETA:\n  REPO_ID::hestai-context-mcp\n===END===\n"
        assert _extract_repo_id(content) == "hestai-context-mcp"
