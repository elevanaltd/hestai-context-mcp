"""Gate A §4.1 invariant enforcement — issue #88 (silent-pass gap closure).

ADR-RFC-ARCH-004 §4.1 enumerates 12 invariants the AGR validator MUST enforce.
Before #88 the write-side Gate A (``type_checker.validate_octave_content``)
enforced only a subset, so ``submit_governance`` ACCEPTED and EMITTED records
that the read layer (``agr_read.record_is_parseable`` +
``agent_readable_governance_parser``) then correctly REJECTED as unparseable —
the write tool produced records its own read tools could not parse.

This module adds one test class per remaining unenforced invariant, asserting
BOTH the rejection AND an actionable, field-named error message at the correct
§4.2 severity:

  #1-residual  VERSION two-segment shape (§1.5; reject 3-segment "1.0.0")  -> error
  #2          Required fields present (TYPE/VERSION/TOKEN/STATUS/TIER/
              DECISION/BECAUSE/AUTHORED_AT)                                -> error
  #3-residual TOKEN YYYYMMDD suffix == UTC date of AUTHORED_AT             -> error
  #5          STATUS enum                                                  -> error
  #6          TIER enum                                                    -> error
  #7          Reserved names DEPENDS_ON/CONFLICTS_WITH/ARCHIVED_AT         -> error
  #9          SUPERSEDED_BY present IFF STATUS == SUPERSEDED               -> error
  #11         HUMAN_ADR_REF resolves under the repository                  -> error
  #12         Ratification provenance (STATUS!=PROPOSED ∧ RATIFIED_BY
              absent)                                                      -> WARNING

Plus a write/read PARITY proof: a record that the read parser rejects is now
rejected by Gate A too.

Regex-only (North Star §4 / PROD I3); structured ``ValidationResult`` errors,
never raised (PROD I4). Mirrors the established #10 ISSUE_REF precedent
(dc30ac9 RED / 782621d GREEN) and the bare-canonical test style.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hestai_context_mcp.core.agent_readable_governance_parser import (
    parse_decision_record,
)
from hestai_context_mcp.tools.governance.agr_read import (
    is_decision_record,
    record_is_parseable,
)
from hestai_context_mcp.tools.governance.type_checker import validate_octave_content

# A canonical, fully-valid DECISION_RECORD. Helpers below mutate ONE axis at a
# time so each test isolates a single invariant. TOKEN date suffix matches
# AUTHORED_AT's UTC date (20260619) so #3-residual stays clean unless mutated.
_VALID_TOKEN = "HO-CONTEXT-MCP-GATE-A-88-20260619"
_VALID_AUTHORED_AT = "2026-06-19T00:00:00Z"


def _record(
    *,
    token: str = _VALID_TOKEN,
    version: str | None = "1.0",
    type_field: str | None = "DECISION_RECORD",
    status: str | None = "PROPOSED",
    tier: str | None = "OPERATIONAL",
    decision: str | None = "A binding decision sentence.",
    because: str | None = "A one-sentence rationale.",
    authored_at: str | None = _VALID_AUTHORED_AT,
    extra_lines: str = "",
) -> str:
    """Build a DECISION_RECORD; any field set to None is OMITTED entirely.

    ``extra_lines`` is injected verbatim into the META block (already indented
    by the caller) for fields like SUPERSEDED_BY / RATIFIED_BY / HUMAN_ADR_REF /
    reserved names.
    """
    lines = ["===DECISION_RECORD===", "META:"]
    if type_field is not None:
        lines.append(f"  TYPE::{type_field}")
    if version is not None:
        lines.append(f'  VERSION::"{version}"')
    if token is not None:
        lines.append(f"  TOKEN::{token}")
    if status is not None:
        lines.append(f"  STATUS::{status}")
    if tier is not None:
        lines.append(f"  TIER::{tier}")
    if decision is not None:
        lines.append(f'  DECISION::"{decision}"')
    if because is not None:
        lines.append(f'  BECAUSE::"{because}"')
    if authored_at is not None:
        lines.append(f'  AUTHORED_AT::"{authored_at}"')
    if extra_lines:
        lines.append(extra_lines.rstrip("\n"))
    lines.append("===END===")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Invariant #2 — Required fields present (error)
# ---------------------------------------------------------------------------


class TestRequiredFieldsPresent:
    @pytest.mark.unit
    @pytest.mark.parametrize(
        ("omit_kwarg", "field_name"),
        [
            ({"status": None}, "STATUS"),
            ({"tier": None}, "TIER"),
            ({"decision": None}, "DECISION"),
            ({"because": None}, "BECAUSE"),
            ({"authored_at": None}, "AUTHORED_AT"),
            ({"version": None}, "VERSION"),
        ],
    )
    def test_missing_required_field_rejected(
        self, tmp_path: Path, omit_kwarg: dict[str, None], field_name: str
    ) -> None:
        """A DECISION_RECORD missing any §1.2 required field is rejected by Gate A.

        This is the core silent-pass class: today a record with only TYPE+TOKEN
        passes Gate A but the read parser marks it unparseable.
        """
        content = _record(**omit_kwarg)  # type: ignore[arg-type]
        result = validate_octave_content(tmp_path, content)
        assert result.valid is False, f"missing {field_name} must reject"
        # Operator UX: the missing field must be NAMED in the error.
        assert any(field_name in e for e in result.errors), result.errors

    @pytest.mark.unit
    def test_only_type_and_token_rejected(self, tmp_path: Path) -> None:
        """The exact #88 repro: TYPE+TOKEN only passes today; must now reject."""
        content = (
            "===DECISION_RECORD===\n"
            "META:\n"
            "  TYPE::DECISION_RECORD\n"
            f"  TOKEN::{_VALID_TOKEN}\n"
            "===END===\n"
        )
        result = validate_octave_content(tmp_path, content)
        assert result.valid is False
        # At minimum STATUS, TIER, DECISION, BECAUSE, AUTHORED_AT named.
        for field_name in ("STATUS", "TIER", "DECISION", "BECAUSE", "AUTHORED_AT"):
            assert any(field_name in e for e in result.errors), (field_name, result.errors)

    @pytest.mark.unit
    def test_all_required_fields_present_valid(self, tmp_path: Path) -> None:
        """Regression: a fully-formed record still validates."""
        result = validate_octave_content(tmp_path, _record())
        assert result.valid, result.errors


# ---------------------------------------------------------------------------
# Invariant #1-residual — VERSION two-segment shape (§1.5) (error)
# ---------------------------------------------------------------------------


class TestVersionShape:
    @pytest.mark.unit
    def test_three_segment_version_rejected(self, tmp_path: Path) -> None:
        """VERSION "1.0.0" (3-segment) is rejected: §1.5 is MAJOR.MINOR only."""
        result = validate_octave_content(tmp_path, _record(version="1.0.0"))
        assert result.valid is False
        assert any("VERSION" in e for e in result.errors), result.errors
        assert any("1.0.0" in e for e in result.errors), result.errors

    @pytest.mark.unit
    def test_non_numeric_version_rejected(self, tmp_path: Path) -> None:
        """VERSION "v1" is rejected — must be a parseable MAJOR.MINOR string."""
        result = validate_octave_content(tmp_path, _record(version="v1"))
        assert result.valid is False
        assert any("VERSION" in e for e in result.errors), result.errors

    @pytest.mark.unit
    def test_two_segment_version_accepted(self, tmp_path: Path) -> None:
        """VERSION "1.0" (and future "1.1") is accepted."""
        assert validate_octave_content(tmp_path, _record(version="1.0")).valid
        assert validate_octave_content(tmp_path, _record(version="1.1")).valid


# ---------------------------------------------------------------------------
# Invariant #3-residual — TOKEN date suffix == UTC date of AUTHORED_AT (error)
# ---------------------------------------------------------------------------


class TestTokenDateConsistency:
    @pytest.mark.unit
    def test_token_date_mismatch_rejected(self, tmp_path: Path) -> None:
        """TOKEN suffix 20260619 with AUTHORED_AT 2026-06-18 is a hard error (§1.3)."""
        content = _record(
            token="HO-CONTEXT-MCP-GATE-A-88-20260619",
            authored_at="2026-06-18T23:59:59Z",
        )
        result = validate_octave_content(tmp_path, content)
        assert result.valid is False
        assert any("AUTHORED_AT" in e or "date" in e.lower() for e in result.errors), result.errors
        assert any("20260619" in e for e in result.errors), result.errors

    @pytest.mark.unit
    def test_token_date_match_accepted(self, tmp_path: Path) -> None:
        """TOKEN suffix equal to AUTHORED_AT UTC date validates."""
        content = _record(
            token="HO-CONTEXT-MCP-GATE-A-88-20260619",
            authored_at="2026-06-19T12:34:56Z",
        )
        assert validate_octave_content(tmp_path, content).valid

    @pytest.mark.unit
    def test_token_date_utc_boundary_uses_date_portion(self, tmp_path: Path) -> None:
        """The check is on the UTC DATE portion only (time-of-day irrelevant)."""
        content = _record(
            token="HO-CONTEXT-MCP-GATE-A-88-20260619",
            authored_at="2026-06-19T00:00:00Z",
        )
        assert validate_octave_content(tmp_path, content).valid


# ---------------------------------------------------------------------------
# Invariant #5 — STATUS enum (error)
# ---------------------------------------------------------------------------


class TestStatusEnum:
    @pytest.mark.unit
    @pytest.mark.parametrize("status", ["PROPOSED", "RATIFIED", "SUPERSEDED", "VOID"])
    def test_valid_status_accepted(self, tmp_path: Path, status: str) -> None:
        # SUPERSEDED requires SUPERSEDED_BY (#9); supply it so this isolates #5.
        extra = ""
        if status == "SUPERSEDED":
            # Point at an existing token: seed it on disk.
            target = "HO-CONTEXT-MCP-SUCCESSOR-20260619"
            decisions = tmp_path / ".hestai" / "decisions"
            decisions.mkdir(parents=True, exist_ok=True)
            (decisions / f"{target}.oct.md").write_text(_record(token=target), encoding="utf-8")
            extra = f'  SUPERSEDED_BY::"{target}"'
        result = validate_octave_content(tmp_path, _record(status=status, extra_lines=extra))
        assert result.valid, result.errors

    @pytest.mark.unit
    def test_invalid_status_rejected(self, tmp_path: Path) -> None:
        """STATUS::DRAFT is not in the §1.4 enum and must reject, naming the value."""
        result = validate_octave_content(tmp_path, _record(status="DRAFT"))
        assert result.valid is False
        assert any("STATUS" in e for e in result.errors), result.errors
        assert any("DRAFT" in e for e in result.errors), result.errors

    @pytest.mark.unit
    def test_lowercase_status_rejected(self, tmp_path: Path) -> None:
        """Enum is case-sensitive: 'proposed' is not 'PROPOSED'."""
        result = validate_octave_content(tmp_path, _record(status="proposed"))
        assert result.valid is False
        assert any("STATUS" in e for e in result.errors), result.errors


# ---------------------------------------------------------------------------
# Invariant #6 — TIER enum (error)
# ---------------------------------------------------------------------------


class TestTierEnum:
    @pytest.mark.unit
    @pytest.mark.parametrize("tier", ["STRATEGIC", "TACTICAL", "OPERATIONAL"])
    def test_valid_tier_accepted(self, tmp_path: Path, tier: str) -> None:
        assert validate_octave_content(tmp_path, _record(tier=tier)).valid

    @pytest.mark.unit
    def test_invalid_tier_rejected(self, tmp_path: Path) -> None:
        """TIER::HIGH is not in the §1.2 enum and must reject, naming the value."""
        result = validate_octave_content(tmp_path, _record(tier="HIGH"))
        assert result.valid is False
        assert any("TIER" in e for e in result.errors), result.errors
        assert any("HIGH" in e for e in result.errors), result.errors


# ---------------------------------------------------------------------------
# Invariant #7 — Reserved names MUST NOT appear in v1.x (error)
# ---------------------------------------------------------------------------


class TestReservedNames:
    @pytest.mark.unit
    @pytest.mark.parametrize("reserved", ["DEPENDS_ON", "CONFLICTS_WITH", "ARCHIVED_AT"])
    def test_reserved_field_rejected(self, tmp_path: Path, reserved: str) -> None:
        """A v1.x record carrying a reserved field name is rejected (§1.2)."""
        result = validate_octave_content(tmp_path, _record(extra_lines=f'  {reserved}::"whatever"'))
        assert result.valid is False
        assert any(reserved in e for e in result.errors), result.errors

    @pytest.mark.unit
    def test_no_reserved_field_accepted(self, tmp_path: Path) -> None:
        """Regression: a clean record (no reserved names) validates."""
        assert validate_octave_content(tmp_path, _record()).valid


# ---------------------------------------------------------------------------
# Invariant #9 — SUPERSEDED_BY present IFF STATUS == SUPERSEDED (error)
# ---------------------------------------------------------------------------


class TestSupersededByIff:
    def _seed_successor(self, tmp_path: Path) -> str:
        target = "HO-CONTEXT-MCP-SUCCESSOR-20260619"
        decisions = tmp_path / ".hestai" / "decisions"
        decisions.mkdir(parents=True, exist_ok=True)
        (decisions / f"{target}.oct.md").write_text(_record(token=target), encoding="utf-8")
        return target

    @pytest.mark.unit
    def test_superseded_without_superseded_by_rejected(self, tmp_path: Path) -> None:
        """STATUS::SUPERSEDED with NO SUPERSEDED_BY is a hard error (#9)."""
        result = validate_octave_content(tmp_path, _record(status="SUPERSEDED"))
        assert result.valid is False
        assert any("SUPERSEDED_BY" in e for e in result.errors), result.errors

    @pytest.mark.unit
    def test_superseded_by_on_non_superseded_rejected(self, tmp_path: Path) -> None:
        """SUPERSEDED_BY present while STATUS != SUPERSEDED is a hard error (#9)."""
        target = self._seed_successor(tmp_path)
        result = validate_octave_content(
            tmp_path,
            _record(status="RATIFIED", extra_lines=f'  SUPERSEDED_BY::"{target}"'),
        )
        assert result.valid is False
        assert any("SUPERSEDED_BY" in e for e in result.errors), result.errors

    @pytest.mark.unit
    def test_superseded_with_superseded_by_accepted(self, tmp_path: Path) -> None:
        """The matched case (SUPERSEDED ∧ SUPERSEDED_BY present) validates."""
        target = self._seed_successor(tmp_path)
        result = validate_octave_content(
            tmp_path,
            _record(status="SUPERSEDED", extra_lines=f'  SUPERSEDED_BY::"{target}"'),
        )
        assert result.valid, result.errors


# ---------------------------------------------------------------------------
# Invariant #11 — HUMAN_ADR_REF resolves under the repository (error)
# ---------------------------------------------------------------------------


class TestHumanAdrRefResolution:
    @pytest.mark.unit
    def test_unresolvable_human_adr_ref_rejected(self, tmp_path: Path) -> None:
        """HUMAN_ADR_REF pointing at a non-existent path is a hard error (#11)."""
        result = validate_octave_content(
            tmp_path,
            _record(extra_lines='  HUMAN_ADR_REF::"docs/adr/does-not-exist.md"'),
        )
        assert result.valid is False
        assert any("HUMAN_ADR_REF" in e for e in result.errors), result.errors

    @pytest.mark.unit
    def test_resolvable_human_adr_ref_accepted(self, tmp_path: Path) -> None:
        """HUMAN_ADR_REF resolving under the repo validates."""
        adr_dir = tmp_path / "docs" / "adr"
        adr_dir.mkdir(parents=True)
        (adr_dir / "0001-real.md").write_text("# real adr\n", encoding="utf-8")
        result = validate_octave_content(
            tmp_path, _record(extra_lines='  HUMAN_ADR_REF::"docs/adr/0001-real.md"')
        )
        assert result.valid, result.errors

    @pytest.mark.unit
    def test_human_adr_ref_traversal_rejected(self, tmp_path: Path) -> None:
        """A HUMAN_ADR_REF escaping the repo root is rejected (does not resolve under repo)."""
        result = validate_octave_content(
            tmp_path, _record(extra_lines='  HUMAN_ADR_REF::"../../../etc/passwd"')
        )
        assert result.valid is False
        assert any("HUMAN_ADR_REF" in e for e in result.errors), result.errors

    @pytest.mark.unit
    def test_human_adr_ref_absent_accepted(self, tmp_path: Path) -> None:
        """HUMAN_ADR_REF is OPTIONAL: absence validates."""
        assert validate_octave_content(tmp_path, _record()).valid


# ---------------------------------------------------------------------------
# Invariant #12 — Ratification provenance: WARNING (not error) per §4.2
# ---------------------------------------------------------------------------


class TestRatificationProvenanceWarning:
    @pytest.mark.unit
    def test_ratified_without_ratified_by_warns_not_errors(self, tmp_path: Path) -> None:
        """STATUS=RATIFIED ∧ RATIFIED_BY absent => WARNING, record still valid (#12)."""
        result = validate_octave_content(tmp_path, _record(status="RATIFIED"))
        # §4.2: this is a WARNING, NOT an error. The record must remain valid.
        assert result.valid, result.errors
        assert any("RATIFIED_BY" in w for w in result.warnings), result.warnings

    @pytest.mark.unit
    def test_proposed_without_ratified_by_no_warning(self, tmp_path: Path) -> None:
        """PROPOSED records need no RATIFIED_BY: no warning emitted (#12)."""
        result = validate_octave_content(tmp_path, _record(status="PROPOSED"))
        assert result.valid, result.errors
        assert not any("RATIFIED_BY" in w for w in result.warnings), result.warnings

    @pytest.mark.unit
    def test_ratified_with_ratified_by_no_warning(self, tmp_path: Path) -> None:
        """RATIFIED with RATIFIED_BY present: clean, no warning (#12)."""
        result = validate_octave_content(
            tmp_path,
            _record(status="RATIFIED", extra_lines='  RATIFIED_BY::"human:operator"'),
        )
        assert result.valid, result.errors
        assert not any("RATIFIED_BY" in w for w in result.warnings), result.warnings


# ---------------------------------------------------------------------------
# WRITE/READ PARITY PROOF (issue #88 core requirement)
# ---------------------------------------------------------------------------


class TestWriteReadParity:
    """A record the READ parser rejects must now be rejected by Gate A (write).

    Before #88 these records passed Gate A (write side) but
    ``record_is_parseable`` returned False (read side) — the write tool emitted
    records its own read tools could not parse. This proves the gap is closed.
    """

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "content",
        [
            # Only TYPE + TOKEN — missing 5 required fields.
            (
                "===DECISION_RECORD===\n"
                "META:\n"
                "  TYPE::DECISION_RECORD\n"
                f"  TOKEN::{_VALID_TOKEN}\n"
                "===END===\n"
            ),
            # Missing AUTHORED_AT only.
            _record(authored_at=None),
            # Missing STATUS only.
            _record(status=None),
        ],
    )
    def test_read_unparseable_record_now_fails_gate_a(self, tmp_path: Path, content: str) -> None:
        # Precondition: the read side considers this an AGR but unparseable.
        assert is_decision_record(content) is True
        assert record_is_parseable(parse_decision_record(content)) is False
        # The parity claim: Gate A (write) now ALSO rejects it.
        result = validate_octave_content(tmp_path, content)
        assert result.valid is False, "Gate A must reject what the read parser rejects"

    @pytest.mark.unit
    def test_read_parseable_record_passes_gate_a(self, tmp_path: Path) -> None:
        """Converse: a read-parseable record still passes Gate A (no over-rejection)."""
        content = _record()
        assert record_is_parseable(parse_decision_record(content)) is True
        assert validate_octave_content(tmp_path, content).valid, "no over-rejection"


# ---------------------------------------------------------------------------
# Review rework (T3 CE/CIV): #9 must honour the CANONICAL BARE SUPERSEDED_BY
# form. ADR-RFC-ARCH-004 §13.1 ratified bare TOKEN edge references as canonical;
# the §4.1 #9 iff check must therefore see a bare ``SUPERSEDED_BY::TOKEN`` exactly
# as it sees the legacy quoted form, mirroring lineage.py's quote-optional regex.
# ---------------------------------------------------------------------------


class TestSupersededByBareCanonical:
    def _seed_successor(self, tmp_path: Path) -> str:
        target = "HO-CONTEXT-MCP-SUCCESSOR-20260619"
        decisions = tmp_path / ".hestai" / "decisions"
        decisions.mkdir(parents=True, exist_ok=True)
        (decisions / f"{target}.oct.md").write_text(_record(token=target), encoding="utf-8")
        return target

    @pytest.mark.unit
    def test_superseded_with_bare_superseded_by_accepted(self, tmp_path: Path) -> None:
        """SUPERSEDED + BARE SUPERSEDED_BV::TOKEN satisfies #9 (canonical form)."""
        target = self._seed_successor(tmp_path)
        result = validate_octave_content(
            tmp_path,
            _record(status="SUPERSEDED", extra_lines=f"  SUPERSEDED_BY::{target}"),
        )
        assert result.valid, result.errors

    @pytest.mark.unit
    def test_bare_superseded_by_on_non_superseded_rejected(self, tmp_path: Path) -> None:
        """A BARE SUPERSEDED_BY on a RATIFIED record must still trip #9."""
        target = self._seed_successor(tmp_path)
        result = validate_octave_content(
            tmp_path,
            _record(status="RATIFIED", extra_lines=f"  SUPERSEDED_BY::{target}"),
        )
        assert result.valid is False
        assert any("SUPERSEDED_BY" in e for e in result.errors), result.errors


# ---------------------------------------------------------------------------
# Review rework (T3 CIV): #3 TOKEN-date consistency MUST use the UTC date, not a
# lexical leading-date capture. §1.3 says the suffix equals the *UTC date portion*
# of AUTHORED_AT — an offset timestamp must be normalised to UTC before
# comparison, and a non-timestamp AUTHORED_AT must not silently pass #3.
# ---------------------------------------------------------------------------


class TestTokenDateUtcNormalisation:
    @pytest.mark.unit
    def test_offset_timestamp_normalised_to_utc_accepted(self, tmp_path: Path) -> None:
        """2026-06-18T23:30-02:00 is UTC date 2026-06-19 → token 20260619 valid."""
        content = _record(
            token="HO-CONTEXT-MCP-GATE-A-88-20260619",
            authored_at="2026-06-18T23:30:00-02:00",
        )
        result = validate_octave_content(tmp_path, content)
        assert result.valid, result.errors

    @pytest.mark.unit
    def test_offset_timestamp_normalised_to_utc_mismatch_rejected(self, tmp_path: Path) -> None:
        """Same instant: token 20260618 disagrees with UTC date 20260619 → reject."""
        content = _record(
            token="HO-CONTEXT-MCP-GATE-A-88-20260618",
            authored_at="2026-06-18T23:30:00-02:00",
        )
        result = validate_octave_content(tmp_path, content)
        assert result.valid is False
        assert any("AUTHORED_AT" in e or "date" in e.lower() for e in result.errors), result.errors

    @pytest.mark.unit
    def test_positive_offset_normalised_to_utc(self, tmp_path: Path) -> None:
        """2026-06-19T01:00+03:00 is UTC date 2026-06-18 → token 20260618 valid."""
        content = _record(
            token="HO-CONTEXT-MCP-GATE-A-88-20260618",
            authored_at="2026-06-19T01:00:00+03:00",
        )
        result = validate_octave_content(tmp_path, content)
        assert result.valid, result.errors

    @pytest.mark.unit
    def test_unparseable_authored_at_rejected(self, tmp_path: Path) -> None:
        """A non-timestamp AUTHORED_AT must NOT silently pass the #3 date check."""
        content = _record(
            token="HO-CONTEXT-MCP-GATE-A-88-20260619",
            authored_at="not-a-timestamp",
        )
        result = validate_octave_content(tmp_path, content)
        assert result.valid is False
        assert any("AUTHORED_AT" in e for e in result.errors), result.errors

    @pytest.mark.unit
    def test_plain_utc_z_still_accepted(self, tmp_path: Path) -> None:
        """Regression: the common Z-suffixed UTC form still validates."""
        content = _record(
            token="HO-CONTEXT-MCP-GATE-A-88-20260619",
            authored_at="2026-06-19T00:00:00Z",
        )
        assert validate_octave_content(tmp_path, content).valid
