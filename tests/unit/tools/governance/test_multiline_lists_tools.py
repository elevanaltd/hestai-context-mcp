"""RED suite - multi-line list fields through the read tools and Gate A (issue #224).

* A wrapped edge field produces the derived edge in ``lookup_decision`` and
  ``trace_supersedure``, exactly as the same field written on one line does.
* An unterminated list makes the record unparseable: ``lookup_decision`` gives
  ``RECORD_PARSE_FAILED`` with the line and construct, ``list_decisions`` skips it with the
  same detail, ``trace_supersedure`` stops at it. Never a silent partial read.
* Gate A: a multi-line EDGE field is a WARNING (``valid`` stays True, so ``octave_write``
  output can still be amended); a single-line edge field gives none; an unterminated
  list is an error because the record could not be read back.
"""

from __future__ import annotations

from pathlib import Path

from hestai_context_mcp.tools.governance.type_checker import validate_octave_content
from hestai_context_mcp.tools.list_decisions import list_decisions
from hestai_context_mcp.tools.lookup_decision import lookup_decision
from hestai_context_mcp.tools.trace_supersedure import trace_supersedure

from ._agr_fixtures import TOKEN_NEW, TOKEN_OLD, write_record

_WRAPPED_SUCCESSOR = [f"  SUPERSEDED_BY::[\n    {TOKEN_NEW}\n  ]"]
_UNTERMINATED = ["  AFFECTS::[", "    A,", "    B", "  SCOPE::PROD"]


def _seed_wrapped_edge(root: Path, extra: list[str]) -> None:
    write_record(root, token=TOKEN_NEW, authored_at="2026-03-01T00:00:00Z")
    write_record(
        root,
        token=TOKEN_OLD,
        status="SUPERSEDED",
        authored_at="2026-01-01T00:00:00Z",
        extra_lines=extra,
    )


# --- 2. a wrapped edge field produces the derived edge ---------------------------------


def test_lookup_follows_a_wrapped_superseded_by(tmp_path: Path) -> None:
    _seed_wrapped_edge(tmp_path, _WRAPPED_SUCCESSOR)
    result = lookup_decision(str(tmp_path), TOKEN_OLD)
    assert result["ok"] is True, result
    assert [e["token"] for e in result["resolution_chain"]] == [TOKEN_OLD, TOKEN_NEW]
    assert result["resolution_chain"][0]["superseded_by"] == TOKEN_NEW
    assert result["resolution_chain_status"] == "complete"


def test_trace_follows_a_wrapped_superseded_by(tmp_path: Path) -> None:
    _seed_wrapped_edge(tmp_path, _WRAPPED_SUCCESSOR)
    result = trace_supersedure(str(tmp_path), TOKEN_OLD)
    assert result["ok"] is True, result
    assert [e["token"] for e in result["chain"]] == [TOKEN_OLD, TOKEN_NEW]
    assert result["terminal_token"] == TOKEN_NEW


def test_wrapped_and_single_line_edges_give_identical_chains(tmp_path: Path) -> None:
    wrapped, single = tmp_path / "wrapped", tmp_path / "single"
    _seed_wrapped_edge(wrapped, _WRAPPED_SUCCESSOR)
    _seed_wrapped_edge(single, [f"  SUPERSEDED_BY::[{TOKEN_NEW}]"])
    for tool in (lookup_decision, trace_supersedure):
        a, b = tool(str(wrapped), TOKEN_OLD), tool(str(single), TOKEN_OLD)
        a.get("record", {}).pop("path", None)
        b.get("record", {}).pop("path", None)
        assert a == b


def test_two_wrapped_successors_are_a_fork_not_a_pick(tmp_path: Path) -> None:
    write_record(tmp_path, token=TOKEN_NEW, authored_at="2026-03-01T00:00:00Z")
    write_record(tmp_path, token="HO-CUBIC-T-20260301", authored_at="2026-03-01T00:00:00Z")
    write_record(
        tmp_path,
        token=TOKEN_OLD,
        status="SUPERSEDED",
        authored_at="2026-01-01T00:00:00Z",
        extra_lines=["  SUPERSEDED_BY::[", f"    {TOKEN_NEW},", "    HO-CUBIC-T-20260301", "  ]"],
    )
    result = trace_supersedure(str(tmp_path), TOKEN_OLD)
    assert result["ok"] is False
    assert result["error"]["code"] == "CHAIN_FORK_DETECTED"


# --- 3. an unterminated list is rejected loudly -----------------------------------------


def test_lookup_reports_an_unterminated_list_with_line_and_construct(tmp_path: Path) -> None:
    path = write_record(tmp_path, token=TOKEN_OLD, extra_lines=_UNTERMINATED)
    lines = path.read_text(encoding="utf-8").splitlines()
    opened = lines.index("  AFFECTS::[") + 1
    result = lookup_decision(str(tmp_path), TOKEN_OLD)
    assert result["ok"] is False
    assert result["error"]["code"] == "RECORD_PARSE_FAILED"
    context = result["error"]["context"]
    assert context["line"] == opened
    assert context["construct"] == "unterminated_list"
    assert f"line {opened}: unterminated_list" in context["parse_error"]


def test_list_decisions_skips_an_unterminated_record_with_its_detail(tmp_path: Path) -> None:
    path = write_record(tmp_path, token=TOKEN_OLD, extra_lines=_UNTERMINATED)
    opened = path.read_text(encoding="utf-8").splitlines().index("  AFFECTS::[") + 1
    write_record(tmp_path, token=TOKEN_NEW, authored_at="2026-03-01T00:00:00Z")
    result = list_decisions(str(tmp_path))
    assert result["ok"] is True
    assert [r["token"] for r in result["records"]] == [TOKEN_NEW]
    assert len(result["skipped"]) == 1
    skipped = result["skipped"][0]
    assert skipped["line"] == opened
    assert skipped["construct"] == "unterminated_list"


def test_trace_stops_at_an_unterminated_record_mid_chain(tmp_path: Path) -> None:
    write_record(tmp_path, token=TOKEN_NEW, extra_lines=_UNTERMINATED)
    write_record(
        tmp_path,
        token=TOKEN_OLD,
        status="SUPERSEDED",
        authored_at="2026-01-01T00:00:00Z",
        superseded_by=TOKEN_NEW,
    )
    result = trace_supersedure(str(tmp_path), TOKEN_OLD)
    assert result["ok"] is False
    assert result["error"]["code"] == "RECORD_PARSE_FAILED"
    assert result["error"]["context"]["construct"] == "unterminated_list"


# --- 7. Gate A -----------------------------------------------------------------------------

_GATE_A_HEAD = (
    "===DECISION_RECORD===\n"
    "META:\n"
    "  TYPE::DECISION_RECORD\n"
    '  VERSION::"1.0"\n'
    "  TOKEN::HO-CUBIC-A-20260101\n"
    "  STATUS::PROPOSED\n"
    "  TIER::OPERATIONAL\n"
    '  AUTHORED_AT::"2026-01-01T00:00:00Z"\n'
    '  DECISION::"A binding decision sentence."\n'
    '  BECAUSE::"A one-sentence rationale."\n'
)


def _gate_a(tmp_path: Path, middle: str):  # type: ignore[no-untyped-def]
    return validate_octave_content(tmp_path, _GATE_A_HEAD + middle + "===END===\n")


def test_gate_a_warns_on_a_multi_line_edge_field_and_stays_valid(tmp_path: Path) -> None:
    for key in ("AMENDS", "EXTENDS", "SUPERSEDES"):
        result = _gate_a(
            tmp_path, f"  {key}::[\n    HO-CUBIC-T-20260301,\n    HO-ESCAPES-20261029\n  ]\n"
        )
        assert result.valid, (key, result.errors)
        assert any(key in w and "multi-line" in w for w in result.warnings), (key, result.warnings)


def test_gate_a_gives_no_warning_for_a_single_line_edge_field(tmp_path: Path) -> None:
    result = _gate_a(tmp_path, "  AMENDS::[HO-CUBIC-T-20260301,HO-ESCAPES-20261029]\n")
    assert result.valid, result.errors
    assert not any("multi-line" in w for w in result.warnings), result.warnings


def test_gate_a_gives_no_warning_for_a_multi_line_informational_list(tmp_path: Path) -> None:
    result = _gate_a(tmp_path, "  AFFECTS::[\n    submit_governance,\n    lookup_decision\n  ]\n")
    assert result.valid, result.errors
    assert not any("multi-line" in w for w in result.warnings), result.warnings


def test_gate_a_rejects_an_unterminated_list(tmp_path: Path) -> None:
    result = _gate_a(tmp_path, "  AFFECTS::[\n    A,\n  SCOPE::PROD\n")
    assert not result.valid
    assert any("unterminated_list" in e and "line 11" in e for e in result.errors), result.errors


def test_gate_a_warns_on_a_multi_line_superseded_by_and_stays_valid(tmp_path: Path) -> None:
    write_record(tmp_path, token=TOKEN_NEW, authored_at="2026-03-01T00:00:00Z")
    content = (
        _GATE_A_HEAD.replace("STATUS::PROPOSED", "STATUS::SUPERSEDED")
        + f"  SUPERSEDED_BY::[\n    {TOKEN_NEW}\n  ]\n===END===\n"
    )
    result = validate_octave_content(tmp_path, content)
    assert any("SUPERSEDED_BY" in w and "multi-line" in w for w in result.warnings), (
        result.errors,
        result.warnings,
    )
