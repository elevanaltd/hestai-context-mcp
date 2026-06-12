"""RED suite — Agent-Readable Governance Record (AGR) parser.

Contract: ADR-RFC-ARCH-004 §1.2 (fields) / §1.1 (envelope). The parser is the
structured-extraction primitive the read tools build on: it turns one AGR
``.oct.md`` document's TEXT into a structured dict (PROD I4), mirroring
``core.north_star_parser`` exactly:

  * Pure function (PROD I5) — text in, dict out. No filesystem access, no
    side effects, DEBUG logging only on malformed input; never raises.
  * Regex-only (North Star §4 / PROD I3) — no OCTAVE AST parsing, no ``ast``
    import, no LLM. Deterministic for identical text.
  * Graceful on empty / None / whitespace / malformed — returns a stable
    empty-ish shape rather than raising.

This is RED: ``core.agent_readable_governance_parser`` does not exist yet, so
import raises ``ModuleNotFoundError`` (failure for the right reason — missing
implementation, not a collection error).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

# Non-secret governance identifier reused across the suite.
_TOKEN = "HO-CONTEXT-MCP-ADOPTS-AGR-DOGFOOD-20260611"


def _parse_decision_record() -> Callable[..., dict]:
    """Lazily import the not-yet-existing parser.

    RED-discipline (build-anti-patterns §5 / tdd-discipline): the import lives
    inside each test rather than at module top so COLLECTION succeeds and every
    test FAILS individually with a clear 'missing implementation' reason — not a
    single module-level collection error that masks the whole file. GREEN
    creates ``core.agent_readable_governance_parser.parse_decision_record`` and
    these resolve.
    """
    from hestai_context_mcp.core.agent_readable_governance_parser import (
        parse_decision_record,
    )

    return parse_decision_record


def _full_record(token: str = _TOKEN) -> str:
    """A complete RATIFIED DECISION_RECORD covering every schema field.

    Mirrors the real on-disk record
    ``.hestai/decisions/HO-CONTEXT-MCP-ADOPTS-AGR-DOGFOOD-20260611.oct.md``
    (bare canonical TOKEN per §1.1).
    """
    return (
        "===DECISION_RECORD===\n"
        "META:\n"
        "  TYPE::DECISION_RECORD\n"
        '  VERSION::"1.0"\n'
        f"  TOKEN::{token}\n"
        "  STATUS::RATIFIED\n"
        "  TIER::STRATEGIC\n"
        '  AUTHORED_AT::"2026-06-11T00:00:00Z"\n'
        '  RATIFIED_BY::"human:operator"\n'
        '  RATIFIED_AT::"2026-06-11T00:00:00Z"\n'
        '  ISSUE_REF::"repo:hestai-context-mcp#53"\n'
        '  HUMAN_ADR_REF::".hestai/decisions/rfc-arch/ADR-RFC-ARCH-004.md"\n'
        '  SCOPE::"hestai-context-mcp"\n'
        '  DECISION::"hestai-context-mcp dogfoods its own AGR standard."\n'
        '  BECAUSE::"This repository owns the AGR standard and validates it."\n'
        "===END===\n"
    )


class TestRequiredFieldExtraction:
    @pytest.mark.unit
    def test_extracts_all_required_fields(self) -> None:
        """Every §1.2 required field is surfaced verbatim from the text."""
        parse_decision_record = _parse_decision_record()
        rec = parse_decision_record(_full_record())

        assert rec["token"] == _TOKEN
        assert rec["type"] == "DECISION_RECORD"
        assert rec["version"] == "1.0"
        assert rec["status"] == "RATIFIED"
        assert rec["tier"] == "STRATEGIC"
        assert rec["decision"] == "hestai-context-mcp dogfoods its own AGR standard."
        assert rec["because"] == "This repository owns the AGR standard and validates it."
        assert rec["authored_at"] == "2026-06-11T00:00:00Z"

    @pytest.mark.unit
    def test_optional_fields_collected_in_fields_map(self) -> None:
        """Non-core present fields land in a ``fields`` sub-dict (§3.2 shape).

        The lookup_decision return packs all other present fields under
        ``record.fields``; the parser is the single source of that map.
        """
        parse_decision_record = _parse_decision_record()
        rec = parse_decision_record(_full_record())
        fields = rec["fields"]
        assert fields["RATIFIED_BY"] == "human:operator"
        assert fields["ISSUE_REF"] == "repo:hestai-context-mcp#53"
        assert fields["SCOPE"] == "hestai-context-mcp"
        # Core fields must NOT be duplicated into the fields map.
        assert "TOKEN" not in fields
        assert "DECISION" not in fields

    @pytest.mark.unit
    def test_bare_and_quoted_token_both_parse(self) -> None:
        """Quote-optional TOKEN per §1.1: bare canonical AND legacy quoted."""
        parse_decision_record = _parse_decision_record()
        bare = parse_decision_record(_full_record())
        quoted_text = _full_record().replace(f"TOKEN::{_TOKEN}", f'TOKEN::"{_TOKEN}"')
        quoted = parse_decision_record(quoted_text)
        assert bare["token"] == quoted["token"] == _TOKEN


class TestSupersededRecord:
    @pytest.mark.unit
    def test_superseded_by_is_surfaced(self) -> None:
        """A SUPERSEDED record exposes its successor TOKEN for chain walking."""
        successor = "HO-CONTEXT-MCP-ADOPTS-AGR-DOGFOOD-V2-20260612"
        text = (
            _full_record()
            .replace("  STATUS::RATIFIED\n", "  STATUS::SUPERSEDED\n")
            .replace("===END===\n", f"  SUPERSEDED_BY::{successor}\n===END===\n")
        )
        parse_decision_record = _parse_decision_record()
        rec = parse_decision_record(text)
        assert rec["status"] == "SUPERSEDED"
        assert rec["fields"]["SUPERSEDED_BY"] == successor


class TestGracefulDegradation:
    @pytest.mark.unit
    @pytest.mark.parametrize("bad", [None, "", "   ", "\n\t  \n"])
    def test_empty_or_none_returns_stable_empty_shape(self, bad: str | None) -> None:
        """Empty / None / whitespace yields a stable shape, never raises.

        Mirrors ``north_star_parser.extract_constraints`` graceful contract.
        The required keys are always present so consumers never special-case
        absence (PROD I4 consistent shape).
        """
        parse_decision_record = _parse_decision_record()
        rec = parse_decision_record(bad)
        for key in (
            "token",
            "type",
            "version",
            "status",
            "tier",
            "decision",
            "because",
            "authored_at",
            "fields",
        ):
            assert key in rec
        assert rec["fields"] == {}

    @pytest.mark.unit
    def test_malformed_octave_does_not_raise(self) -> None:
        """Garbage input returns a structured (empty) result, not an exception."""
        parse_decision_record = _parse_decision_record()
        rec = parse_decision_record("not octave at all :: %%% [[[")
        assert rec["token"] is None
        assert rec["fields"] == {}

    @pytest.mark.unit
    def test_missing_required_field_leaves_none_not_raise(self) -> None:
        """A record missing BECAUSE still parses; absent field is None."""
        text = _full_record().replace(
            '  BECAUSE::"This repository owns the AGR standard and validates it."\n',
            "",
        )
        parse_decision_record = _parse_decision_record()
        rec = parse_decision_record(text)
        assert rec["token"] == _TOKEN
        assert rec["because"] is None


class TestPurityAndRegexOnly:
    @pytest.mark.unit
    def test_parser_is_pure_no_filesystem_writes(self, tmp_path: Path) -> None:
        """Parsing must not create/modify any file (PROD I5 pure read)."""
        parse_decision_record = _parse_decision_record()
        before = sorted(p.name for p in tmp_path.iterdir())
        parse_decision_record(_full_record())
        after = sorted(p.name for p in tmp_path.iterdir())
        assert before == after == []

    @pytest.mark.unit
    def test_module_does_not_import_ast(self) -> None:
        """North Star §4 / PROD I3: regex-only — no OCTAVE AST parsing.

        The parser module MUST NOT pull in Python's ``ast`` module nor the
        octave-mcp grammar package (a proxy for 'no structured OCTAVE AST
        parsing in the read path').
        """
        import hestai_context_mcp.core.agent_readable_governance_parser as mod

        source = mod.__file__
        assert source is not None
        with open(source, encoding="utf-8") as fh:
            module_text = fh.read()
        assert "import ast" not in module_text
        assert "octave_mcp" not in module_text
