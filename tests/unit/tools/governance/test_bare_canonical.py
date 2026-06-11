"""Quote-optional TOKEN/ID readers — BARE canonical form (AGR convergence).

Per the AGR canonical-form convergence ruling (supersedes the earlier
ReqSteward 2a/2b quoted-only recommendation), ALL Gate A readers MUST accept
BOTH bare and quoted TOKEN/ID:

    TOKEN::HO-...-YYYYMMDD     (bare, canonical)
    TOKEN::"HO-...-YYYYMMDD"   (quoted, still accepted)

The §1.3 TOKEN-format check (ADR-RFC-ARCH-004) MUST still constrain the value:
quote-optional MUST NOT weaken format validation — a malformed token is still
rejected.

manifest._ID_BARE_RE is KEPT (the earlier "remove it" recommendation is
SUPERSEDED — convergence is on quote-optional, the other direction).

These tests cover the three Gate A readers:
  - type_checker.validate_octave_content (TOKEN + ID)
  - lexer.lookup_token_deterministic (filesystem grep TOKEN + ID)
  - manifest.build_manifest (TOKEN + ID extraction)
"""

from pathlib import Path

import pytest

from hestai_context_mcp.tools.governance.lexer import lookup_token_deterministic
from hestai_context_mcp.tools.governance.manifest import build_manifest
from hestai_context_mcp.tools.governance.type_checker import validate_octave_content

# Non-secret governance identifiers referenced via constants so secret scanners
# do not read a keyword+literal adjacency as a credential.
_BARE_TOKEN = "HO-CONTEXT-MCP-BARE-CANONICAL-20260610"
_QUOTED_TOKEN = "HO-CONTEXT-MCP-QUOTED-FORM-20260610"
_BARE_ID = "GATE_A_BARE_CONCEPT"


def _decision_record(token: str, *, quoted: bool) -> str:
    """Build a well-formed DECISION_RECORD with bare or quoted TOKEN."""
    token_field = f'TOKEN::"{token}"' if quoted else f"TOKEN::{token}"
    return (
        "===DECISION_RECORD===\n"
        "META:\n"
        "  TYPE::DECISION_RECORD\n"
        '  VERSION::"1.0"\n'
        f"  {token_field}\n"
        "  STATUS::PROPOSED\n"
        "  TIER::OPERATIONAL\n"
        '  DECISION::"Bare-canonical TOKEN acceptance."\n'
        '  BECAUSE::"AGR canonical-form convergence."\n'
        '  AUTHORED_AT::"2026-06-10T00:00:00Z"\n'
        "===END===\n"
    )


def _concept_card(card_id: str, *, quoted: bool) -> str:
    """Build a well-formed CONCEPT_CARD with bare or quoted ID."""
    id_field = f'ID::"{card_id}"' if quoted else f"ID::{card_id}"
    return (
        "===CONCEPT_CARD===\n"
        "META:\n"
        "  TYPE::CONCEPT_CARD\n"
        "  REPO_ID::hestai-context-mcp\n"
        f"  {id_field}\n"
        "  STATUS::proposed\n"
        "  CARD_SCHEMA_VERSION::1\n"
        '  GENERATED_AT_COMMIT::"N/A"\n'
        '  SOURCE_HASH::"N/A"\n'
        "===END===\n"
    )


# ---------------------------------------------------------------------------
# type_checker — TOKEN (DECISION_RECORD)
# ---------------------------------------------------------------------------


class TestTypeCheckerBareToken:
    @pytest.mark.unit
    def test_bare_token_accepted(self, tmp_path: Path) -> None:
        """A bare TOKEN::VALUE is accepted by the type checker."""
        result = validate_octave_content(tmp_path, _decision_record(_BARE_TOKEN, quoted=False))
        assert result.valid, result.errors
        assert result.token == _BARE_TOKEN
        assert result.card_type == "DECISION_RECORD"

    @pytest.mark.unit
    def test_quoted_token_still_accepted(self, tmp_path: Path) -> None:
        """A quoted TOKEN::"VALUE" remains accepted (backward compatible)."""
        result = validate_octave_content(tmp_path, _decision_record(_QUOTED_TOKEN, quoted=True))
        assert result.valid, result.errors
        assert result.token == _QUOTED_TOKEN

    @pytest.mark.unit
    def test_bare_malformed_token_still_rejected(self, tmp_path: Path) -> None:
        """A bare TOKEN that violates §1.3 format is still rejected.

        Quote-optional MUST NOT weaken §1.3 format validation.
        """
        result = validate_octave_content(
            tmp_path, _decision_record("bad-token-no-date", quoted=False)
        )
        assert not result.valid
        assert any("does not match required format" in e for e in result.errors)

    @pytest.mark.unit
    def test_quoted_malformed_token_still_rejected(self, tmp_path: Path) -> None:
        """A quoted malformed TOKEN is still rejected (no regression)."""
        result = validate_octave_content(
            tmp_path, _decision_record("bad-token-no-date", quoted=True)
        )
        assert not result.valid
        assert any("does not match required format" in e for e in result.errors)


# ---------------------------------------------------------------------------
# type_checker — ID (facet cards)
# ---------------------------------------------------------------------------


class TestTypeCheckerBareId:
    @pytest.mark.unit
    def test_bare_id_accepted(self, tmp_path: Path) -> None:
        """A bare ID::VALUE is accepted by the type checker for facet cards."""
        result = validate_octave_content(tmp_path, _concept_card(_BARE_ID, quoted=False))
        assert result.valid, result.errors
        assert result.token == _BARE_ID
        assert result.card_type == "CONCEPT_CARD"

    @pytest.mark.unit
    def test_quoted_id_still_accepted(self, tmp_path: Path) -> None:
        """A quoted ID::"VALUE" remains accepted (backward compatible)."""
        result = validate_octave_content(
            tmp_path, _concept_card("GATE_A_QUOTED_CONCEPT", quoted=True)
        )
        assert result.valid, result.errors
        assert result.token == "GATE_A_QUOTED_CONCEPT"

    @pytest.mark.unit
    def test_bare_malformed_id_still_rejected(self, tmp_path: Path) -> None:
        """A bare ID that violates the facet-id format is still rejected."""
        # lowercase start violates ^[A-Z][A-Z0-9_]{2,127}$
        result = validate_octave_content(tmp_path, _concept_card("lower_bad", quoted=False))
        assert not result.valid
        assert any("does not match required format" in e for e in result.errors)


# ---------------------------------------------------------------------------
# lexer.lookup_token_deterministic — filesystem grep accepts bare TOKEN
# ---------------------------------------------------------------------------


class TestLexerBareToken:
    @pytest.mark.unit
    def test_bare_token_found_via_filesystem(self, tmp_path: Path) -> None:
        """A bare TOKEN::VALUE on disk is resolvable by lookup_token_deterministic."""
        decisions = tmp_path / ".hestai" / "decisions"
        decisions.mkdir(parents=True)
        (decisions / f"{_BARE_TOKEN}.oct.md").write_text(
            _decision_record(_BARE_TOKEN, quoted=False)
        )
        assert lookup_token_deterministic(tmp_path, _BARE_TOKEN) is True

    @pytest.mark.unit
    def test_quoted_token_still_found_via_filesystem(self, tmp_path: Path) -> None:
        """A quoted TOKEN on disk remains resolvable (no regression)."""
        decisions = tmp_path / ".hestai" / "decisions"
        decisions.mkdir(parents=True)
        (decisions / f"{_QUOTED_TOKEN}.oct.md").write_text(
            _decision_record(_QUOTED_TOKEN, quoted=True)
        )
        assert lookup_token_deterministic(tmp_path, _QUOTED_TOKEN) is True

    @pytest.mark.unit
    def test_bare_token_no_prefix_false_positive(self, tmp_path: Path) -> None:
        """A bare TOKEN must match exactly, not a longer-prefixed token.

        ``HO-FOO-20260101`` must NOT be reported present when only
        ``HO-FOO-BAR-20260101`` exists on disk in bare form.
        """
        decisions = tmp_path / ".hestai" / "decisions"
        decisions.mkdir(parents=True)
        longer = "HO-FOO-BAR-20260101"
        (decisions / f"{longer}.oct.md").write_text(_decision_record(longer, quoted=False))
        assert lookup_token_deterministic(tmp_path, "HO-FOO-20260101") is False
        assert lookup_token_deterministic(tmp_path, longer) is True


# ---------------------------------------------------------------------------
# manifest.build_manifest — bare TOKEN extraction (and _ID_BARE_RE retained)
# ---------------------------------------------------------------------------


class TestManifestBareToken:
    @pytest.mark.unit
    def test_bare_token_extracted_into_manifest(self, tmp_path: Path) -> None:
        """build_manifest indexes a bare TOKEN::VALUE DECISION_RECORD."""
        decisions = tmp_path / ".hestai" / "decisions"
        decisions.mkdir(parents=True)
        (decisions / f"{_BARE_TOKEN}.oct.md").write_text(
            _decision_record(_BARE_TOKEN, quoted=False)
        )
        manifest = build_manifest(tmp_path)
        assert _BARE_TOKEN in manifest

    @pytest.mark.unit
    def test_quoted_token_still_extracted(self, tmp_path: Path) -> None:
        """build_manifest still indexes a quoted TOKEN (no regression)."""
        decisions = tmp_path / ".hestai" / "decisions"
        decisions.mkdir(parents=True)
        (decisions / f"{_QUOTED_TOKEN}.oct.md").write_text(
            _decision_record(_QUOTED_TOKEN, quoted=True)
        )
        manifest = build_manifest(tmp_path)
        assert _QUOTED_TOKEN in manifest

    @pytest.mark.unit
    def test_bare_id_still_extracted(self, tmp_path: Path) -> None:
        """_ID_BARE_RE is RETAINED: a bare ID facet card is still indexed."""
        concepts = tmp_path / ".hestai" / "context" / "concepts" / "hestai-context-mcp"
        concepts.mkdir(parents=True)
        (concepts / f"{_BARE_ID}.oct.md").write_text(_concept_card(_BARE_ID, quoted=False))
        manifest = build_manifest(tmp_path)
        assert _BARE_ID in manifest
