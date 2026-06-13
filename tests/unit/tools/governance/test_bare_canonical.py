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


# ---------------------------------------------------------------------------
# Trailing-garbage rejection (cubic P2 — asymmetric strictness fix)
#
# A TOKEN/ID line with trailing content after a valid value MUST be rejected.
# The end-anchor (\s*$) lives OUTSIDE the quote alternation so BOTH the quoted
# and bare branches are line-anchored — neither silently captures a valid value
# and ignores the trailing garbage.
# ---------------------------------------------------------------------------

# Valid §1.3 token used as the "clean" part before injected garbage.
_VALID_TOKEN = "HO-CONTEXT-MCP-TRAILING-GUARD-20260513"
_VALID_ID = "GATE_A_TRAILING_GUARD"


def _decision_record_raw_token_line(token_line: str) -> str:
    """Build a DECISION_RECORD with a caller-supplied raw TOKEN field line.

    ``token_line`` is the exact text after the two-space indent (e.g.
    ``TOKEN::"HO-...-20260513" garbage``).
    """
    return (
        "===DECISION_RECORD===\n"
        "META:\n"
        "  TYPE::DECISION_RECORD\n"
        '  VERSION::"1.0"\n'
        f"  {token_line}\n"
        "  STATUS::PROPOSED\n"
        "  TIER::OPERATIONAL\n"
        '  DECISION::"Trailing-garbage guard."\n'
        '  BECAUSE::"AGR canonical-form convergence."\n'
        '  AUTHORED_AT::"2026-05-13T00:00:00Z"\n'
        "===END===\n"
    )


def _concept_card_raw_id_line(id_line: str) -> str:
    """Build a CONCEPT_CARD with a caller-supplied raw ID field line."""
    return (
        "===CONCEPT_CARD===\n"
        "META:\n"
        "  TYPE::CONCEPT_CARD\n"
        "  REPO_ID::hestai-context-mcp\n"
        f"  {id_line}\n"
        "  STATUS::proposed\n"
        "  CARD_SCHEMA_VERSION::1\n"
        '  GENERATED_AT_COMMIT::"N/A"\n'
        '  SOURCE_HASH::"N/A"\n'
        "===END===\n"
    )


class TestTypeCheckerTrailingGarbageRejected:
    @pytest.mark.unit
    def test_quoted_token_trailing_garbage_rejected(self, tmp_path: Path) -> None:
        """TOKEN::"valid" garbage must NOT validate (quoted branch anchored)."""
        content = _decision_record_raw_token_line(f'TOKEN::"{_VALID_TOKEN}" EXTRA STUFF')
        result = validate_octave_content(tmp_path, content)
        assert result.valid is False
        # Rejected at TOKEN extraction (no clean line match) → required-field error.
        assert any("TOKEN" in e for e in result.errors)

    @pytest.mark.unit
    def test_bare_token_trailing_garbage_rejected(self, tmp_path: Path) -> None:
        """TOKEN::HO-...-20260513 EXTRA STUFF must NOT validate (bare anchored)."""
        content = _decision_record_raw_token_line(f"TOKEN::{_VALID_TOKEN} EXTRA STUFF")
        result = validate_octave_content(tmp_path, content)
        assert result.valid is False

    @pytest.mark.unit
    def test_quoted_id_trailing_garbage_rejected(self, tmp_path: Path) -> None:
        """ID::"VALUE"garbage must NOT validate (quoted ID branch anchored)."""
        content = _concept_card_raw_id_line(f'ID::"{_VALID_ID}"garbage')
        result = validate_octave_content(tmp_path, content)
        assert result.valid is False

    @pytest.mark.unit
    def test_bare_id_trailing_garbage_rejected(self, tmp_path: Path) -> None:
        """ID::VALUE garbage must NOT validate (bare ID branch anchored)."""
        content = _concept_card_raw_id_line(f"ID::{_VALID_ID} garbage")
        result = validate_octave_content(tmp_path, content)
        assert result.valid is False

    @pytest.mark.unit
    def test_clean_quoted_token_still_accepted(self, tmp_path: Path) -> None:
        """The clean quoted TOKEN line (no trailing junk) still validates."""
        content = _decision_record_raw_token_line(f'TOKEN::"{_VALID_TOKEN}"')
        result = validate_octave_content(tmp_path, content)
        assert result.valid, result.errors
        assert result.token == _VALID_TOKEN

    @pytest.mark.unit
    def test_clean_bare_token_still_accepted(self, tmp_path: Path) -> None:
        """The clean bare TOKEN line (no trailing junk) still validates."""
        content = _decision_record_raw_token_line(f"TOKEN::{_VALID_TOKEN}")
        result = validate_octave_content(tmp_path, content)
        assert result.valid, result.errors
        assert result.token == _VALID_TOKEN


class TestLexerTrailingGarbageRejected:
    @pytest.mark.unit
    def test_quoted_token_trailing_garbage_not_resolved(self, tmp_path: Path) -> None:
        """A trailing-garbage quoted TOKEN line does not resolve the clean token.

        ``TOKEN::"<valid>" garbage`` on disk must NOT make
        ``lookup_token_deterministic(<valid>)`` return True — the lexer is
        authoritative Gate A and must reject the malformed line, not match it.
        """
        decisions = tmp_path / ".hestai" / "decisions"
        decisions.mkdir(parents=True)
        (decisions / "malformed.oct.md").write_text(
            _decision_record_raw_token_line(f'TOKEN::"{_VALID_TOKEN}" EXTRA STUFF')
        )
        assert lookup_token_deterministic(tmp_path, _VALID_TOKEN) is False

    @pytest.mark.unit
    def test_bare_token_trailing_garbage_not_resolved(self, tmp_path: Path) -> None:
        """A trailing-garbage bare TOKEN line does not resolve the clean token."""
        decisions = tmp_path / ".hestai" / "decisions"
        decisions.mkdir(parents=True)
        (decisions / "malformed.oct.md").write_text(
            _decision_record_raw_token_line(f"TOKEN::{_VALID_TOKEN} EXTRA STUFF")
        )
        assert lookup_token_deterministic(tmp_path, _VALID_TOKEN) is False

    @pytest.mark.unit
    def test_clean_token_line_still_resolves(self, tmp_path: Path) -> None:
        """A clean quoted/bare TOKEN line still resolves (no regression)."""
        decisions = tmp_path / ".hestai" / "decisions"
        decisions.mkdir(parents=True)
        (decisions / "clean_quoted.oct.md").write_text(
            _decision_record_raw_token_line(f'TOKEN::"{_VALID_TOKEN}"')
        )
        assert lookup_token_deterministic(tmp_path, _VALID_TOKEN) is True


# ---------------------------------------------------------------------------
# ISSUE_REF shape validation (ADR-RFC-ARCH-004 §4.1 invariant #10)
#
# "ISSUE_REF shape — when present, parses as a GitHub URL or repo:<repo-id>#<n>."
# (ADR line 86: "GitHub issue URL or repo:<repo-id>#<n> shorthand. Optional on
#  PROPOSED/RATIFIED ...")
#
# ISSUE_REF is OPTIONAL: absence MUST remain valid. Only a PRESENT-but-malformed
# value is rejected, and it is collected alongside other errors (it does NOT
# early-return), mirroring the SUPERSEDED_BY collect-more-errors pattern.
# ---------------------------------------------------------------------------

# Valid §1.3 TOKEN used as the "wrong shape" injected into ISSUE_REF. It is a
# legal decision-TOKEN but NOT a legal ISSUE_REF — exactly the elevana-studio
# dogfood finding (a decision-TOKEN leaked into ISSUE_REF and Gate A passed it
# silently because ISSUE_REF was never validated). Referenced via a constant so
# secret scanners do not read the keyword+literal adjacency as a credential.
_DECISION_TOKEN_IN_ISSUE_REF = "HO-CONTEXT-MCP-TEST-20260513"
_VALID_ISSUE_REF_SHORTHAND = "repo:hestai-context-mcp#77"
_VALID_ISSUE_REF_URL = "https://github.com/elevanaltd/hestai-context-mcp/issues/53"
# A §1.3-valid TOKEN for the host DECISION_RECORD (kept distinct from the
# ISSUE_REF payload so a failure points unambiguously at ISSUE_REF).
_ISSUE_REF_HOST_TOKEN = "HO-CONTEXT-MCP-ISSUE-REF-HOST-20260613"


def _decision_record_with_issue_ref(token: str, issue_ref: str | None) -> str:
    """Build a well-formed DECISION_RECORD, optionally carrying an ISSUE_REF.

    When ``issue_ref`` is None the ISSUE_REF line is omitted entirely (the
    optional-field case). The TOKEN is quoted (already covered by the bare
    tests); the focus here is solely the ISSUE_REF shape.
    """
    issue_ref_line = f'  ISSUE_REF::"{issue_ref}"\n' if issue_ref is not None else ""
    return (
        "===DECISION_RECORD===\n"
        "META:\n"
        "  TYPE::DECISION_RECORD\n"
        '  VERSION::"1.0"\n'
        f'  TOKEN::"{token}"\n'
        "  STATUS::PROPOSED\n"
        "  TIER::OPERATIONAL\n"
        f"{issue_ref_line}"
        '  DECISION::"ISSUE_REF shape validation."\n'
        '  BECAUSE::"ADR-RFC-ARCH-004 §4.1 invariant #10."\n'
        '  AUTHORED_AT::"2026-06-13T00:00:00Z"\n'
        "===END===\n"
    )


class TestTypeCheckerIssueRefShape:
    @pytest.mark.unit
    def test_issue_ref_holding_decision_token_rejected(self, tmp_path: Path) -> None:
        """A decision-TOKEN in ISSUE_REF is rejected (the dogfood finding).

        ISSUE_REF::"HO-...-20260513" is a valid TOKEN but NOT a valid ISSUE_REF.
        """
        content = _decision_record_with_issue_ref(
            _ISSUE_REF_HOST_TOKEN, _DECISION_TOKEN_IN_ISSUE_REF
        )
        result = validate_octave_content(tmp_path, content)
        assert result.valid is False
        assert any("ISSUE_REF" in e for e in result.errors), result.errors
        # The bad value must be named in the error for operator diagnosis.
        assert any(_DECISION_TOKEN_IN_ISSUE_REF in e for e in result.errors), result.errors

    @pytest.mark.unit
    def test_issue_ref_repo_shorthand_accepted(self, tmp_path: Path) -> None:
        """ISSUE_REF::"repo:<repo-id>#<n>" passes the ISSUE_REF shape check."""
        content = _decision_record_with_issue_ref(_ISSUE_REF_HOST_TOKEN, _VALID_ISSUE_REF_SHORTHAND)
        result = validate_octave_content(tmp_path, content)
        assert result.valid, result.errors
        assert not any("ISSUE_REF" in e for e in result.errors), result.errors

    @pytest.mark.unit
    def test_issue_ref_github_url_accepted(self, tmp_path: Path) -> None:
        """ISSUE_REF::"https://github.com/<org>/<repo>/issues/<n>" passes."""
        content = _decision_record_with_issue_ref(_ISSUE_REF_HOST_TOKEN, _VALID_ISSUE_REF_URL)
        result = validate_octave_content(tmp_path, content)
        assert result.valid, result.errors
        assert not any("ISSUE_REF" in e for e in result.errors), result.errors

    @pytest.mark.unit
    def test_issue_ref_absent_is_valid(self, tmp_path: Path) -> None:
        """ISSUE_REF is OPTIONAL: a record with no ISSUE_REF field is valid."""
        content = _decision_record_with_issue_ref(_ISSUE_REF_HOST_TOKEN, None)
        result = validate_octave_content(tmp_path, content)
        assert result.valid, result.errors
        assert not any("ISSUE_REF" in e for e in result.errors), result.errors

    @pytest.mark.unit
    def test_real_ratified_record_with_issue_ref_still_validates(self, tmp_path: Path) -> None:
        """Regression: a real RATIFIED AGR with a valid shorthand ISSUE_REF validates.

        Mirrors the on-disk record
        .hestai/decisions/HO-AGR-SEMANTIC-REVIEWER-ANALYSIS-TIER-20260611.oct.md
        (ISSUE_REF::"repo:hestai-context-mcp#77"). Reproduced inline (TOKEN
        localised so the uniqueness check on tmp_path stays clean).
        """
        content = (
            "===DECISION_RECORD===\n"
            "META:\n"
            "  TYPE::DECISION_RECORD\n"
            '  VERSION::"1.0"\n'
            "  TOKEN::HO-AGR-SEMANTIC-REVIEWER-ANALYSIS-TIER-20260611\n"
            "  STATUS::RATIFIED\n"
            "  TIER::TACTICAL\n"
            '  AUTHORED_AT::"2026-06-11T00:00:00Z"\n'
            '  RATIFIED_BY::"human:operator"\n'
            '  RATIFIED_AT::"2026-06-11T00:00:00Z"\n'
            f'  ISSUE_REF::"{_VALID_ISSUE_REF_SHORTHAND}"\n'
            '  SCOPE::"hestai-context-mcp"\n'
            '  DECISION::"Scoped semantic reviewer at analysis tier."\n'
            '  BECAUSE::"Semantic second opinion catches what the human misses."\n'
            "===END===\n"
        )
        result = validate_octave_content(tmp_path, content)
        assert result.valid, result.errors


# ---------------------------------------------------------------------------
# ISSUE_REF trailing-garbage rejection (ADR-RFC-ARCH-004 §4.1 #10)
#
# _ISSUE_REF_RE end-anchors (\s*$) reject trailing garbage at the regex level,
# but that means _extract_issue_ref returns None for a malformed line, and check
# 5a (``if issue_ref is not None``) silently skips it.  A presence detector must
# close this bypass: if any ISSUE_REF:: line exists in content but strict
# extraction fails, Gate A must emit a named error.
# ---------------------------------------------------------------------------


def _decision_record_with_raw_issue_ref_line(token: str, raw_issue_ref_line: str) -> str:
    """Build a DECISION_RECORD with a caller-supplied raw ISSUE_REF field line.

    ``raw_issue_ref_line`` is the exact text of the ISSUE_REF field including
    any trailing garbage (e.g. ``ISSUE_REF::"repo:hestai-context-mcp#77" EXTRA``).
    The two-space indent is added here.
    """
    return (
        "===DECISION_RECORD===\n"
        "META:\n"
        "  TYPE::DECISION_RECORD\n"
        '  VERSION::"1.0"\n'
        f'  TOKEN::"{token}"\n'
        "  STATUS::PROPOSED\n"
        "  TIER::OPERATIONAL\n"
        f"  {raw_issue_ref_line}\n"
        '  DECISION::"ISSUE_REF trailing-garbage guard."\n'
        '  BECAUSE::"ADR-RFC-ARCH-004 §4.1 invariant #10."\n'
        '  AUTHORED_AT::"2026-06-13T00:00:00Z"\n'
        "===END===\n"
    )


# §1.3-valid TOKEN for the host DECISION_RECORD in trailing-garbage tests.
_ISSUE_REF_TRAILING_HOST_TOKEN = "HO-CONTEXT-MCP-ISSUE-REF-TRAILING-20260613"


class TestTypeCheckerIssueRefTrailingGarbageRejected:
    @pytest.mark.unit
    def test_issue_ref_trailing_garbage_quoted_rejected(self, tmp_path: Path) -> None:
        """ISSUE_REF::"repo:..#77" EXTRA must fail validation (quoted + trailing garbage).

        When a quoted ISSUE_REF line has trailing content the end-anchor causes
        _ISSUE_REF_RE to not match, _extract_issue_ref returns None, and check 5a
        is skipped -- the malformed line silently passes Gate A.  The presence
        detector must catch this and return valid=False with a named ISSUE_REF error.
        """
        raw = f'ISSUE_REF::"{_VALID_ISSUE_REF_SHORTHAND}" trailing-garbage'
        content = _decision_record_with_raw_issue_ref_line(
            _ISSUE_REF_TRAILING_HOST_TOKEN, raw
        )
        result = validate_octave_content(tmp_path, content)
        assert result.valid is False, "Expected invalid: quoted ISSUE_REF with trailing garbage"
        assert any("ISSUE_REF" in e for e in result.errors), result.errors

    @pytest.mark.unit
    def test_issue_ref_trailing_garbage_bare_rejected(self, tmp_path: Path) -> None:
        """ISSUE_REF::repo:..#77 EXTRA must fail validation (bare + trailing garbage).

        Same bypass as the quoted form: bare ISSUE_REF line with trailing content
        causes _ISSUE_REF_RE to not match, extraction returns None, check 5a
        skips.  The presence detector must emit a named ISSUE_REF error.
        """
        raw = f"ISSUE_REF::{_VALID_ISSUE_REF_SHORTHAND} trailing-garbage"
        content = _decision_record_with_raw_issue_ref_line(
            _ISSUE_REF_TRAILING_HOST_TOKEN, raw
        )
        result = validate_octave_content(tmp_path, content)
        assert result.valid is False, "Expected invalid: bare ISSUE_REF with trailing garbage"
        assert any("ISSUE_REF" in e for e in result.errors), result.errors
