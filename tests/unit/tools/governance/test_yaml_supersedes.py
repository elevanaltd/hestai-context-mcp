"""PR-4 slice B4 (+ addendum): ``supersedes:`` edges derived at read time, with FORK detection.

* ``supersedes:`` is one double-quoted, comma-separated list of TOKENS only; prose
  is a loud reject. ``supersedes_note:`` is ignored by edge logic.
* A record named in a YAML record's ``supersedes`` READS as SUPERSEDED (OR rule:
  an OCTAVE ``SUPERSEDED_BY`` or a derived edge), with ``superseded_by`` / the chain
  entry reflecting the deriving record. The target file is NEVER touched.
* Two DIFFERENT successors for one record (a fork) are reported, never silently
  picked: ``resolution_chain_status == "forked"`` + ``successors`` on lookup, a
  ``CHAIN_FORK_DETECTED`` envelope on trace. The same successor from both sources
  is not a fork.
* Only a YAML ``supersedes:`` derives edges; legacy OCTAVE prose ``SUPERSEDES`` does not.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hestai_context_mcp.core.agent_readable_governance_parser import (
    TOKEN_FORMAT_PATTERN,
    YamlSyntaxError,
    diagnose_yaml_record,
    parse_decision_record,
    parse_supersedes_list,
)
from hestai_context_mcp.tools.governance import agr_read
from hestai_context_mcp.tools.governance.type_checker import _TOKEN_FORMAT_RE
from hestai_context_mcp.tools.list_decisions import list_decisions
from hestai_context_mcp.tools.lookup_decision import lookup_decision
from hestai_context_mcp.tools.trace_supersedure import trace_supersedure

from ._agr_fixtures import snapshot_tree, write_record, write_yaml_record, yaml_record_text

pytestmark = pytest.mark.unit

OLD = "HO-SUPERSEDES-OLD-20260101"
OLD2 = "HO-SUPERSEDES-OLD-20260102"
NEW = "HO-SUPERSEDES-NEW-20261001"
NEW2 = "HO-SUPERSEDES-NEW-20261002"
EXPLICIT = "HO-SUPERSEDES-EXPLICIT-20260901"


def test_token_pattern_is_the_gate_a_pattern() -> None:
    assert _TOKEN_FORMAT_RE.pattern == TOKEN_FORMAT_PATTERN


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (OLD, [OLD]),
        (f"{OLD},{OLD2}", [OLD, OLD2]),
        (f"{OLD}, {OLD2}", [OLD, OLD2]),
        (f"  {OLD}  ,  {OLD2}  ", [OLD, OLD2]),
    ],
)
def test_parse_supersedes_list_accepts_token_lists(value: str, expected: list[str]) -> None:
    assert parse_supersedes_list(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "",
        "   ",
        "supersedes the old access rule",
        f"{OLD} and {OLD2}",
        f"{OLD};{OLD2}",
        f"{OLD},,{OLD2}",
        f"{OLD},",
        ",".join([OLD, "not-a-token"]),
        OLD.lower(),
        f"{OLD}-extra words",
        "HO-SHORT-1",
        f"{OLD}, {OLD}",  # duplicate entry: one record must not look like two successors
    ],
)
def test_parse_supersedes_list_rejects_prose_and_bad_entries(value: str) -> None:
    with pytest.raises(YamlSyntaxError) as info:
        parse_supersedes_list(value)
    assert info.value.construct == "invalid_supersedes"


def test_record_with_supersedes_parses_and_keeps_raw_value_in_fields() -> None:
    text = yaml_record_text(token=NEW, supersedes=f"{OLD}, {OLD2}")
    parsed = parse_decision_record(text)
    assert parsed["fields"] == {"SUPERSEDES": f"{OLD}, {OLD2}"}
    assert diagnose_yaml_record(text) is None


def test_self_supersedes_is_a_loud_reject() -> None:
    text = yaml_record_text(token=NEW, supersedes=NEW)
    reject = diagnose_yaml_record(text)
    assert reject == {
        "line": text.split("\n").index(f'supersedes: "{NEW}"') + 1,
        "construct": "invalid_supersedes",
    }


def test_record_with_prose_supersedes_is_a_loud_reject() -> None:
    text = yaml_record_text(token=NEW, supersedes="replaces the old thing")
    reject = diagnose_yaml_record(text)
    assert reject == {
        "line": text.split("\n").index('supersedes: "replaces the old thing"') + 1,
        "construct": "invalid_supersedes",
    }
    assert parse_decision_record(text)["token"] is None


def test_supersedes_note_is_free_text_and_creates_no_edge(tmp_path: Path) -> None:
    write_record(tmp_path, token=OLD)
    write_yaml_record(
        tmp_path,
        token=NEW,
        extra_lines=[f'supersedes_note: "this supersedes {OLD} in spirit; see also {OLD2}"'],
    )
    assert agr_read.derive_supersession(tmp_path) == {}
    assert lookup_decision(str(tmp_path), OLD)["record"]["status"] == "RATIFIED"


# --- derived reverse edge ------------------------------------------------------


def _frozen_old_and_new(tmp_path: Path) -> Path:
    old_path = write_record(tmp_path, token=OLD, status="RATIFIED")
    write_yaml_record(tmp_path, token=NEW, supersedes=OLD)
    return old_path


def test_derive_supersession_maps_target_to_sorted_deriving_tokens(tmp_path: Path) -> None:
    write_record(tmp_path, token=OLD)
    write_yaml_record(tmp_path, token=NEW2, supersedes=f"{OLD},{OLD2}")
    write_yaml_record(tmp_path, token=NEW, supersedes=OLD)
    assert agr_read.derive_supersession(tmp_path) == {OLD: [NEW, NEW2], OLD2: [NEW2]}


def test_octave_target_reads_superseded_and_file_is_untouched(tmp_path: Path) -> None:
    old_path = _frozen_old_and_new(tmp_path)
    before_bytes = old_path.read_bytes()
    before_mtime = old_path.stat().st_mtime_ns
    result = lookup_decision(str(tmp_path), OLD)
    assert result["ok"] is True
    assert result["record"]["status"] == "SUPERSEDED"
    assert result["record"]["fields"]["SUPERSEDED_BY"] == NEW
    assert [e["token"] for e in result["resolution_chain"]] == [OLD, NEW]
    assert result["resolution_chain"][0]["superseded_by"] == NEW
    assert result["resolution_chain"][0]["status"] == "SUPERSEDED"
    assert result["resolution_chain_status"] == "complete"
    assert "successors" not in result
    assert old_path.read_bytes() == before_bytes
    assert old_path.stat().st_mtime_ns == before_mtime
    assert b"SUPERSEDED" not in before_bytes


def test_trace_supersedure_follows_the_derived_edge(tmp_path: Path) -> None:
    _frozen_old_and_new(tmp_path)
    result = trace_supersedure(str(tmp_path), OLD)
    assert result["ok"] is True
    assert [(e["token"], e["status"], e["superseded_by"]) for e in result["chain"]] == [
        (OLD, "SUPERSEDED", NEW),
        (NEW, "RATIFIED", None),
    ]
    assert result["terminal_token"] == NEW
    assert result["terminal_status"] == "RATIFIED"


def test_list_decisions_rows_and_status_filter_use_derived_status(tmp_path: Path) -> None:
    _frozen_old_and_new(tmp_path)
    rows = {r["token"]: r["status"] for r in list_decisions(str(tmp_path))["records"]}
    assert rows == {OLD: "SUPERSEDED", NEW: "RATIFIED"}
    superseded = list_decisions(str(tmp_path), status="SUPERSEDED")["records"]
    assert [r["token"] for r in superseded] == [OLD]
    assert [r["token"] for r in list_decisions(str(tmp_path), status="RATIFIED")["records"]] == [
        NEW
    ]


def test_multi_target_supersedes_marks_every_target(tmp_path: Path) -> None:
    write_record(tmp_path, token=OLD)
    write_yaml_record(tmp_path, token=OLD2)
    write_yaml_record(tmp_path, token=NEW, supersedes=f"{OLD}, {OLD2}")
    for target in (OLD, OLD2):
        record = lookup_decision(str(tmp_path), target)["record"]
        assert record["status"] == "SUPERSEDED" and record["fields"]["SUPERSEDED_BY"] == NEW


def test_yaml_target_superseded_by_yaml(tmp_path: Path) -> None:
    write_yaml_record(tmp_path, token=OLD)
    write_yaml_record(tmp_path, token=NEW, supersedes=OLD)
    assert [e["token"] for e in trace_supersedure(str(tmp_path), OLD)["chain"]] == [OLD, NEW]


def test_chain_walks_a_mixed_three_hop_chain(tmp_path: Path) -> None:
    write_record(tmp_path, token=OLD, status="SUPERSEDED", superseded_by=EXPLICIT)
    write_record(tmp_path, token=OLD2)
    write_yaml_record(tmp_path, token=EXPLICIT, supersedes=OLD2)
    write_yaml_record(tmp_path, token=NEW, supersedes=EXPLICIT)
    result = trace_supersedure(str(tmp_path), OLD)
    assert [e["token"] for e in result["chain"]] == [OLD, EXPLICIT, NEW]
    assert result["terminal_token"] == NEW
    # two consecutive derived hops, and derived SUPERSEDED_BY merges into existing fields
    assert [e["token"] for e in trace_supersedure(str(tmp_path), OLD2)["chain"]] == [
        OLD2,
        EXPLICIT,
        NEW,
    ]
    assert lookup_decision(str(tmp_path), EXPLICIT)["record"]["fields"] == {
        "SUPERSEDES": OLD2,
        "SUPERSEDED_BY": NEW,
    }


def test_or_rule_octave_superseded_by_alone_still_marks_superseded(tmp_path: Path) -> None:
    write_record(tmp_path, token=OLD, status="SUPERSEDED", superseded_by=NEW)
    write_record(tmp_path, token=NEW)
    assert lookup_decision(str(tmp_path), OLD)["record"]["status"] == "SUPERSEDED"
    assert [e["token"] for e in trace_supersedure(str(tmp_path), OLD)["chain"]] == [OLD, NEW]


def test_same_successor_from_both_sources_is_not_a_fork(tmp_path: Path) -> None:
    write_record(tmp_path, token=OLD, status="SUPERSEDED", superseded_by=NEW)
    write_yaml_record(tmp_path, token=NEW, supersedes=OLD)
    result = lookup_decision(str(tmp_path), OLD)
    assert result["resolution_chain_status"] == "complete"
    assert "successors" not in result
    traced = trace_supersedure(str(tmp_path), OLD)
    assert traced["ok"] is True
    assert [e["token"] for e in traced["chain"]] == [OLD, NEW]


def test_derived_status_is_unconditional_across_proposed_and_void_targets(tmp_path: Path) -> None:
    write_record(tmp_path, token=OLD, status="PROPOSED")
    write_yaml_record(tmp_path, token=OLD2, status="VOID")
    write_yaml_record(tmp_path, token=NEW, supersedes=f"{OLD},{OLD2}")
    rows = {r["token"]: r["status"] for r in list_decisions(str(tmp_path))["records"]}
    assert rows == {OLD: "SUPERSEDED", OLD2: "SUPERSEDED", NEW: "RATIFIED"}
    assert list_decisions(str(tmp_path), status="PROPOSED")["records"] == []


def test_void_deriving_record_still_derives_and_reports_its_own_terminal_status(
    tmp_path: Path,
) -> None:
    write_record(tmp_path, token=OLD)
    write_yaml_record(tmp_path, token=NEW, status="VOID", supersedes=OLD)
    result = trace_supersedure(str(tmp_path), OLD)
    assert [e["token"] for e in result["chain"]] == [OLD, NEW]
    assert result["terminal_status"] == "VOID"


# --- FORK ----------------------------------------------------------------------


def _fork_corpus(tmp_path: Path) -> None:
    write_record(tmp_path, token=OLD, status="SUPERSEDED", superseded_by=EXPLICIT)
    write_record(tmp_path, token=EXPLICIT)
    write_yaml_record(tmp_path, token=NEW, supersedes=OLD)


def test_fork_explicit_vs_derived_is_reported_by_lookup(tmp_path: Path) -> None:
    _fork_corpus(tmp_path)
    result = lookup_decision(str(tmp_path), OLD)
    assert result["ok"] is True
    assert result["resolution_chain_status"] == "forked"
    assert result["successors"] == sorted([EXPLICIT, NEW])
    assert result["record"]["status"] == "SUPERSEDED"
    assert (
        result["record"]["fields"]["SUPERSEDED_BY"] == EXPLICIT
    )  # the file's own value, unaltered
    (entry,) = result["resolution_chain"]
    assert entry["token"] == OLD
    assert entry["superseded_by"] is None
    assert entry["fork"] is True
    assert entry["successors"] == sorted([EXPLICIT, NEW])


def test_fork_explicit_vs_derived_is_reported_by_trace(tmp_path: Path) -> None:
    _fork_corpus(tmp_path)
    result = trace_supersedure(str(tmp_path), OLD)
    assert result["ok"] is False
    error = result["error"]
    assert error["code"] == "CHAIN_FORK_DETECTED"
    assert error["category"] == "schema_violation"
    assert error["context"]["fork_at_token"] == OLD
    assert error["context"]["successors"] == sorted([EXPLICIT, NEW])
    assert [e["token"] for e in error["context"]["chain"]] == [OLD]


def test_fork_two_yaml_successors(tmp_path: Path) -> None:
    write_record(tmp_path, token=OLD)
    write_yaml_record(tmp_path, token=NEW, supersedes=OLD)
    write_yaml_record(tmp_path, token=NEW2, supersedes=OLD)
    result = lookup_decision(str(tmp_path), OLD)
    assert result["resolution_chain_status"] == "forked"
    assert result["successors"] == [NEW, NEW2]
    assert result["record"]["status"] == "SUPERSEDED"
    assert "SUPERSEDED_BY" not in result["record"]["fields"]  # never picks one successor
    (entry,) = result["resolution_chain"]
    assert (entry["status"], entry["superseded_by"], entry["fork"]) == ("SUPERSEDED", None, True)
    assert entry["successors"] == [NEW, NEW2]
    assert trace_supersedure(str(tmp_path), OLD)["error"]["code"] == "CHAIN_FORK_DETECTED"
    assert [r["token"] for r in list_decisions(str(tmp_path), status="SUPERSEDED")["records"]] == [
        OLD
    ]
    assert [r["token"] for r in list_decisions(str(tmp_path), status="RATIFIED")["records"]] == [
        NEW,
        NEW2,
    ]


def test_fork_mid_chain_reports_the_chain_so_far(tmp_path: Path) -> None:
    write_record(tmp_path, token=OLD2, status="SUPERSEDED", superseded_by=OLD)
    _fork_corpus(tmp_path)
    error = trace_supersedure(str(tmp_path), OLD2)["error"]
    assert error["code"] == "CHAIN_FORK_DETECTED"
    assert error["context"]["fork_at_token"] == OLD
    assert [e["token"] for e in error["context"]["chain"]] == [OLD2, OLD]
    result = lookup_decision(str(tmp_path), OLD2)
    assert result["resolution_chain_status"] == "forked"
    assert result["successors"] == sorted([EXPLICIT, NEW])
    first, second = result["resolution_chain"]
    assert first["superseded_by"] == OLD and "fork" not in first
    assert second["token"] == OLD and second["fork"] is True


def test_forked_record_still_lists_as_superseded(tmp_path: Path) -> None:
    _fork_corpus(tmp_path)
    statuses = {r["token"]: r["status"] for r in list_decisions(str(tmp_path))["records"]}
    assert statuses[OLD] == "SUPERSEDED"


# --- non-edges and edge cases ---------------------------------------------------


def test_legacy_octave_prose_supersedes_produces_no_edge(tmp_path: Path) -> None:
    write_record(tmp_path, token=OLD)
    write_record(tmp_path, token=NEW, extra_lines=[f'  SUPERSEDES::"{OLD}"'])
    assert agr_read.derive_supersession(tmp_path) == {}
    assert lookup_decision(str(tmp_path), OLD)["record"]["status"] == "RATIFIED"


def test_unparseable_yaml_record_derives_no_edges(tmp_path: Path) -> None:
    write_record(tmp_path, token=OLD)
    write_yaml_record(tmp_path, token=NEW, supersedes=OLD, extra_lines=["extra: bare"])
    assert agr_read.derive_supersession(tmp_path) == {}
    assert lookup_decision(str(tmp_path), OLD)["record"]["status"] == "RATIFIED"


def test_supersedes_naming_a_missing_record_is_harmless(tmp_path: Path) -> None:
    write_yaml_record(tmp_path, token=NEW, supersedes=OLD)
    assert lookup_decision(str(tmp_path), NEW)["ok"] is True
    assert trace_supersedure(str(tmp_path), NEW)["ok"] is True


def test_mutual_supersedes_is_a_cycle(tmp_path: Path) -> None:
    write_yaml_record(tmp_path, token=OLD, supersedes=NEW)
    write_yaml_record(tmp_path, token=NEW, supersedes=OLD)
    error = trace_supersedure(str(tmp_path), OLD)["error"]
    assert error["code"] == "CHAIN_CYCLE_DETECTED"
    assert lookup_decision(str(tmp_path), OLD)["resolution_chain_status"] == "cyclic"


def test_broken_explicit_link_still_reports_broken(tmp_path: Path) -> None:
    write_record(
        tmp_path, token=OLD, status="SUPERSEDED", superseded_by="HO-SUPERSEDES-GONE-20260303"
    )
    assert trace_supersedure(str(tmp_path), OLD)["error"]["code"] == "CHAIN_BROKEN"


def test_corpus_without_yaml_has_no_derived_edges(tmp_path: Path) -> None:
    write_record(tmp_path, token=OLD, status="SUPERSEDED", superseded_by=NEW)
    write_record(tmp_path, token=NEW)
    assert agr_read.derive_supersession(tmp_path) == {}
    assert agr_read.derive_supersession(tmp_path / "missing") == {}


def test_supersession_reads_are_side_effect_free(tmp_path: Path) -> None:
    _fork_corpus(tmp_path)
    before = snapshot_tree(tmp_path)
    lookup_decision(str(tmp_path), OLD)
    list_decisions(str(tmp_path))
    trace_supersedure(str(tmp_path), OLD)
    agr_read.derive_supersession(tmp_path)
    assert snapshot_tree(tmp_path) == before
