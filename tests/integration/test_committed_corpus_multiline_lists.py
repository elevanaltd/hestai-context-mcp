"""Issue #224: the committed corpus reads its wrapped lists in full, and nothing else changes.

* The decision records on main whose list fields ``octave_write`` wrapped over several
  lines read their lists in full (they used to read ``[``).
* A hestai-workbench record (``tests/fixtures``, content verbatim) reads its list in full.
* BYTE PARITY: for every committed record whose lists are single-line, the parser,
  ``lookup_decision`` and ``list_decisions`` return exactly what the pre-#224 reader
  returned. The pre-#224 reader is frozen below as ``_legacy_parse`` (the one-field-per-
  line loop, copied unchanged) and swapped in for the comparison.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest

from hestai_context_mcp.core import agent_readable_governance_parser as parser
from hestai_context_mcp.core.agent_readable_governance_parser import (
    DecisionRecord,
    annotate_lines,
    parse_decision_record,
    read_record,
)
from hestai_context_mcp.tools import lookup_decision as lookup_module
from hestai_context_mcp.tools.governance import agr_read
from hestai_context_mcp.tools.list_decisions import list_decisions
from hestai_context_mcp.tools.lookup_decision import lookup_decision

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[2]
DECISIONS = REPO_ROOT / ".hestai" / "decisions"
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "PROGRAMME-DIRECTION-RULINGS-20261025.oct.md"

_LEGACY_FIELD_RE = re.compile(r"^\s*([A-Z][A-Z0-9_]*)::(.*?)\s*$")
_OPEN_LIST_LINE_RE = re.compile(r"^\s*[A-Z][A-Z0-9_]*::\[\s*$")


def _legacy_parse(text: str | None) -> DecisionRecord:
    """The reader as it was before #224: one ``KEY::value`` per line, other lines skipped."""
    if not text or not text.strip():
        return parser._empty_record()  # noqa: SLF001
    if parser.is_yaml_front_matter(text):
        return parser.parse_decision_record(text)
    core: dict[str, str] = {}
    extra: dict[str, str] = {}
    for block, raw_line in annotate_lines(text):
        if block is not None:
            continue
        match = _LEGACY_FIELD_RE.match(raw_line)
        if not match:
            continue
        key, value = match.group(1), parser._strip_quotes(match.group(2))  # noqa: SLF001
        if key in parser._CORE_FIELDS:  # noqa: SLF001
            core.setdefault(key, value)
        else:
            extra.setdefault(key, value)
    return {
        "token": core.get("TOKEN"),
        "type": core.get("TYPE"),
        "version": core.get("VERSION"),
        "status": core.get("STATUS"),
        "tier": core.get("TIER"),
        "decision": core.get("DECISION"),
        "because": core.get("BECAUSE"),
        "authored_at": core.get("AUTHORED_AT"),
        "fields": extra,
    }


def _octave_records() -> list[Path]:
    return sorted(
        p
        for p in DECISIONS.rglob("*.oct.md")
        if p.read_text(encoding="utf-8").startswith("===DECISION_RECORD===")
    )


def _has_wrapped_list(path: Path) -> bool:
    return any(_OPEN_LIST_LINE_RE.match(line) for line in path.read_text("utf-8").splitlines())


def _token_of(path: Path) -> str:
    token = parse_decision_record(path.read_text(encoding="utf-8"))["token"]
    assert token is not None
    return token


SINGLE_LINE = [p for p in _octave_records() if not _has_wrapped_list(p)]
WRAPPED = [p for p in _octave_records() if _has_wrapped_list(p)]


def test_corpus_split_is_non_trivial() -> None:
    assert len(SINGLE_LINE) >= 10
    assert len(WRAPPED) >= 6


# --- 5. the affected records read their lists in full ----------------------------------

_EXPECTED_LISTS = {
    "EPIC4-RECORDS-YAML-BATCH-MERGE-AUTHORITY-20261025": (
        "RELATED_DECISIONS",
        "[HO-GOVERNANCE-AMEND-IN-PLACE-20260926]",
    ),
    "HO-AGR-SEMANTIC-REVIEWER-ABSTAIN-ON-FAILURE-20260724": (
        "AFFECTS",
        "[submit_governance,semantic_review,HESTAI_REVIEW_MAX_OUTPUT_TOKENS]",
    ),
    "HO-GOVERNANCE-IN-FLIGHT-TOKEN-AMENDMENT-20260921": (
        "AFFECTS",
        '[submit_governance,"tools/governance/linker.py","tools/governance/lexer.py",'
        '"tools/governance/type_checker.py"]',
    ),
    "HO-RCCAFP-RECORDING-IN-CONTEXT-MCP-20260927": (
        "AFFECTS",
        '["submit_rccafp_record","hestai-context-mcp tool surface","HestAI-MCP#445",'
        '"debate-hall-mcp#192","hestai-context-mcp#18"]',
    ),
    "HO-REVIEW-GATE-PIN-RELEASE-20261025": (
        "AFFECTS",
        '[".github/workflows/review-gate.yml","org ruleset 12626210",'
        '"hestai-context-mcp#170","hestai-workbench","elevana-studio","HestAI-MCP"]',
    ),
    "HO-SR-APPROVED-WORDING-FIXES-PENDING-20261015": (
        "AFFECTS",
        "[submit_review,review_formats.format_review_comment,"
        '"submit_governance Stage-5 verdict map","core/governance_reviewer.py",'
        '"hestai-context-mcp#201",HO-AGR-SEMANTIC-REVIEWER-ANALYSIS-TIER-20260611]',
    ),
    "HO-TOPIC-RECORDS-YAML-SYNTAX-20261029": (
        "AFFECTS",
        '["submit_governance append_ruling","lookup_decision current_state",'
        '"list_decisions topic filter","ADR-RFC-ARCH-004 topic-record section",'
        '"hestai-context-mcp#203","EPIC4 PR-4 ∧ PR-5"]',
    ),
}


@pytest.mark.parametrize("token", sorted(_EXPECTED_LISTS))
def test_affected_record_reads_its_list_in_full_through_lookup_decision(token: str) -> None:
    key, expected = _EXPECTED_LISTS[token]
    result = lookup_decision(str(REPO_ROOT), token)
    assert result["ok"] is True, result
    assert result["record"]["fields"][key] == expected


def test_no_committed_record_reads_a_bare_open_bracket() -> None:
    for path in _octave_records():
        fields = parse_decision_record(read_record(path).text)["fields"]
        assert [k for k, v in fields.items() if v.strip() == "["] == [], path.name


def test_every_committed_record_stays_parseable() -> None:
    result = list_decisions(str(REPO_ROOT))
    assert result["ok"] is True
    assert result["skipped"] == []


# --- 6. a hestai-workbench record --------------------------------------------------------


def test_workbench_record_fixture_reads_its_list_in_full() -> None:
    parsed = parse_decision_record(read_record(FIXTURE).text)
    assert parsed["token"] == "PROGRAMME-DIRECTION-RULINGS-20261025"
    assert parsed["fields"]["RELATED_DECISIONS"] == (
        "[HW-PROGRAMME-OPERATING-MODEL-20261025,"
        "CLEAR-AND-REANCHOR-CHECKPOINT-DESIGN-20261019,"
        "ANCHOR-V2-LIVING-PRESENCE-20260620]"
    )
    assert parsed["fields"]["RELATED_ISSUES"] == "hestai-workbench #609 ∧ #613 ∧ #596 ∧ #563"
    assert parsed["fields"]["STATUS_FINAL"] == "RATIFIED"


def test_workbench_record_fixture_is_looked_up_with_its_list(tmp_path: Path) -> None:
    store = tmp_path / ".hestai" / "decisions"
    store.mkdir(parents=True)
    shutil.copy(FIXTURE, store / FIXTURE.name)
    result = lookup_decision(str(tmp_path), "PROGRAMME-DIRECTION-RULINGS-20261025")
    assert result["ok"] is True, result
    assert result["record"]["fields"]["RELATED_DECISIONS"].startswith("[HW-PROGRAMME-")


# --- 8. byte parity ------------------------------------------------------------------------


@pytest.mark.parametrize("path", SINGLE_LINE, ids=lambda p: p.name)
def test_parser_output_is_identical_for_single_line_records(path: Path) -> None:
    text = read_record(path).text
    assert parse_decision_record(text) == _legacy_parse(text)


@pytest.mark.parametrize("path", WRAPPED, ids=lambda p: p.name)
def test_wrapped_records_differ_from_legacy_only_in_their_wrapped_lists(path: Path) -> None:
    text = read_record(path).text
    new, old = parse_decision_record(text), _legacy_parse(text)
    for core in ("token", "type", "version", "status", "tier", "decision", "because"):
        assert new[core] == old[core]  # type: ignore[literal-required]
    assert new["fields"].keys() == old["fields"].keys()
    for key, old_value in old["fields"].items():
        if old_value.strip() != "[":
            assert new["fields"][key] == old_value, key
        else:
            assert new["fields"][key].startswith("[") and new["fields"][key].endswith("]")
            assert new["fields"][key] != "["


def test_lookup_and_list_are_identical_to_the_legacy_reader_for_single_line_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tokens = [_token_of(p) for p in SINGLE_LINE]
    after_list = list_decisions(str(REPO_ROOT))
    after_lookup = {t: lookup_decision(str(REPO_ROOT), t) for t in tokens}

    monkeypatch.setattr(agr_read, "parse_decision_record", _legacy_parse)
    monkeypatch.setattr(lookup_module, "parse_decision_record", _legacy_parse)
    before_list = list_decisions(str(REPO_ROOT))
    before_lookup = {t: lookup_decision(str(REPO_ROOT), t) for t in tokens}

    assert after_lookup == before_lookup
    keep = set(tokens)
    assert [r for r in after_list["records"] if r["token"] in keep] == [
        r for r in before_list["records"] if r["token"] in keep
    ]
    assert after_list["skipped"] == before_list["skipped"] == []
    assert after_list["total"] == before_list["total"]
