"""PR-4 rework slice C: derived-edge scope (C1), literal TAB (C2), trace never half-reads a
rejected YAML record (C3), and an unquoted ``type: DECISION_RECORD`` is loud, not invisible (C4).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hestai_context_mcp.core.agent_readable_governance_parser import (
    diagnose_yaml_record,
    has_yaml_decision_header,
)
from hestai_context_mcp.tools.governance import agr_read
from hestai_context_mcp.tools.list_decisions import list_decisions
from hestai_context_mcp.tools.lookup_decision import lookup_decision
from hestai_context_mcp.tools.trace_supersedure import trace_supersedure

from ._agr_fixtures import decisions_dir, write_record, write_yaml_record, yaml_record_text

pytestmark = pytest.mark.unit

A = "HO-SLICEC-A-20260101"
B = "HO-SLICEC-B-20260201"
C = "HO-SLICEC-C-20260301"
BAD = "HO-SLICEC-BAD-20260401"


# --- C1: derived edge scope -------------------------------------------------------


@pytest.mark.parametrize("source_status", ["PROPOSED", "VOID", "DRAFT", "WITHDRAWN"])
def test_only_ratified_or_superseded_sources_derive_edges(
    tmp_path: Path, source_status: str
) -> None:
    write_record(tmp_path, token=A)
    write_yaml_record(tmp_path, token=B, status=source_status, supersedes=A)
    assert agr_read.derive_supersession(tmp_path) == {}
    assert lookup_decision(str(tmp_path), A)["record"]["status"] == "RATIFIED"
    assert [e["token"] for e in trace_supersedure(str(tmp_path), A)["chain"]] == [A]
    assert [r["token"] for r in list_decisions(str(tmp_path), status="RATIFIED")["records"]] == [A]


@pytest.mark.parametrize("source_status", ["RATIFIED", "SUPERSEDED"])
def test_ratified_and_superseded_sources_derive_edges(tmp_path: Path, source_status: str) -> None:
    write_record(tmp_path, token=A)
    write_yaml_record(tmp_path, token=B, status=source_status, supersedes=A)
    assert agr_read.derive_supersession(tmp_path) == {A: [B]}


def test_a_superseded_source_still_retires_its_target(tmp_path: Path) -> None:
    """A <- B <- C: B is itself superseded (by C) yet B still retires A."""
    write_record(tmp_path, token=A)
    write_yaml_record(tmp_path, token=B, supersedes=A)
    write_yaml_record(tmp_path, token=C, supersedes=B)
    assert agr_read.derive_supersession(tmp_path) == {A: [B], B: [C]}
    assert lookup_decision(str(tmp_path), A)["record"]["status"] == "SUPERSEDED"
    assert [e["token"] for e in trace_supersedure(str(tmp_path), A)["chain"]] == [A, B, C]


def test_a_void_target_stays_void_but_the_edge_appears_in_chain_and_trace(tmp_path: Path) -> None:
    write_record(tmp_path, token=A, status="VOID")
    write_yaml_record(tmp_path, token=B, supersedes=A)
    looked_up = lookup_decision(str(tmp_path), A)
    assert looked_up["record"]["status"] == "VOID"
    assert looked_up["record"]["fields"]["SUPERSEDED_BY"] == B
    assert [e["token"] for e in looked_up["resolution_chain"]] == [A, B]
    traced = trace_supersedure(str(tmp_path), A)
    assert [(e["token"], e["status"], e["superseded_by"]) for e in traced["chain"]] == [
        (A, "VOID", B),
        (B, "RATIFIED", None),
    ]
    assert [r["token"] for r in list_decisions(str(tmp_path), status="VOID")["records"]] == [A]
    assert [r["token"] for r in list_decisions(str(tmp_path), status="SUPERSEDED")["records"]] == []


def test_a_yaml_void_target_also_stays_void(tmp_path: Path) -> None:
    write_yaml_record(tmp_path, token=A, status="VOID")
    write_yaml_record(tmp_path, token=B, supersedes=A)
    assert lookup_decision(str(tmp_path), A)["record"]["status"] == "VOID"


# --- C2: literal TAB ---------------------------------------------------------------


def test_a_real_tab_inside_a_quoted_value_is_a_control_character_reject(tmp_path: Path) -> None:
    tab = chr(9)
    line = f'extra: "a{tab}b"'
    text = yaml_record_text(token=A, extra_lines=[line])
    assert tab in line and "\\t" not in line
    reject = diagnose_yaml_record(text)
    assert reject == {"line": text.split("\n").index(line) + 1, "construct": "control_character"}
    path = decisions_dir(tmp_path) / f"{A}.md"
    path.write_text(text, encoding="utf-8")
    error = lookup_decision(str(tmp_path), A)["error"]
    assert (
        error["code"] == "RECORD_PARSE_FAILED"
        and error["context"]["construct"] == "control_character"
    )
    # the escaped spelling is the accepted one
    ok = yaml_record_text(token=A, extra_lines=['extra: "a\\tb"'])
    assert diagnose_yaml_record(ok) is None


# --- C3: trace never half-reads a rejected YAML record --------------------------------


def _unquoted_status_record(tmp_path: Path, token: str) -> Path:
    text = yaml_record_text(token=token).replace('status: "RATIFIED"', "status: RATIFIED")
    path = decisions_dir(tmp_path) / f"{token}.md"
    path.write_text(text, encoding="utf-8")
    return path


def test_trace_of_a_rejected_start_record_surfaces_the_structured_rejection(
    tmp_path: Path,
) -> None:
    path = _unquoted_status_record(tmp_path, BAD)
    line = path.read_text(encoding="utf-8").split("\n").index("status: RATIFIED") + 1
    looked_up = lookup_decision(str(tmp_path), BAD)["error"]
    traced = trace_supersedure(str(tmp_path), BAD)
    assert traced["ok"] is False
    error = traced["error"]
    assert error["code"] == "RECORD_PARSE_FAILED"
    assert error["tool"] == "trace_supersedure"
    for key in ("path", "line", "construct"):
        assert error["context"][key] == looked_up["context"][key]
    assert error["context"]["path"] == path.relative_to(tmp_path).as_posix()
    assert (error["context"]["line"], error["context"]["construct"]) == (line, "unquoted_value")
    assert error["context"]["chain"] == []


def test_trace_hitting_a_rejected_record_mid_chain_surfaces_it(tmp_path: Path) -> None:
    write_record(tmp_path, token=A, status="SUPERSEDED", superseded_by=BAD)
    path = write_yaml_record(tmp_path, token=BAD, extra_lines=["extra: |"])
    error = trace_supersedure(str(tmp_path), A)["error"]
    assert error["code"] == "RECORD_PARSE_FAILED"
    ctx = error["context"]
    assert ctx["token"] == BAD
    assert ctx["path"] == path.relative_to(tmp_path).as_posix()
    assert ctx["construct"] == "block_scalar"
    assert ctx["line"] == path.read_text(encoding="utf-8").split("\n").index("extra: |") + 1
    assert [e["token"] for e in ctx["chain"]] == [A]


def test_trace_hitting_an_incomplete_yaml_record_mid_chain_is_rejected_too(tmp_path: Path) -> None:
    write_record(tmp_path, token=A, status="SUPERSEDED", superseded_by=BAD)
    text = yaml_record_text(token=BAD).replace('because: "A one-sentence rationale."\n', "")
    (decisions_dir(tmp_path) / f"{BAD}.md").write_text(text, encoding="utf-8")
    error = trace_supersedure(str(tmp_path), A)["error"]
    assert error["code"] == "RECORD_PARSE_FAILED"
    assert error["context"]["token"] == BAD
    assert "construct" not in error["context"]


def test_lookup_reports_a_rejected_record_hit_by_its_resolution_walk(tmp_path: Path) -> None:
    write_record(tmp_path, token=A, status="SUPERSEDED", superseded_by=BAD)
    path = write_yaml_record(tmp_path, token=BAD, extra_lines=["extra: |"])
    result = lookup_decision(str(tmp_path), A)
    assert result["ok"] is True
    assert result["resolution_chain_status"] == "unparseable"
    assert result["rejected_at"] == {
        "token": BAD,
        "path": path.relative_to(tmp_path).as_posix(),
        "line": path.read_text(encoding="utf-8").split("\n").index("extra: |") + 1,
        "construct": "block_scalar",
    }
    assert [e["token"] for e in result["resolution_chain"]] == [A]


def test_a_healthy_trace_is_unchanged(tmp_path: Path) -> None:
    write_record(tmp_path, token=A, status="SUPERSEDED", superseded_by=B)
    write_yaml_record(tmp_path, token=B)
    result = trace_supersedure(str(tmp_path), A)
    assert result["ok"] is True and [e["token"] for e in result["chain"]] == [A, B]
    assert "rejected_at" not in lookup_decision(str(tmp_path), A)


# --- C4: unquoted type is a loud candidate, not invisible --------------------------------


@pytest.mark.parametrize("spelling", ["DECISION_RECORD", "'DECISION_RECORD'", '"DECISION_RECORD"'])
def test_type_decision_record_in_any_quoting_is_a_candidate(spelling: str) -> None:
    text = f'---\ntype: {spelling}\ntoken: "{A}"\n---\n'
    assert has_yaml_decision_header(text) is True


@pytest.mark.parametrize(
    "text",
    [
        '---\ntype: "OTHER"\ntoken: "' + A + '"\n---\n',
        "---\ntype: OTHER\n---\n",
        # (`type: DECISION_RECORD extra` moved to the F4 candidate tests below)
        "---\ntype: DECISION_RECORD_X\n---\n",
        "---\ntitle: DECISION_RECORD\n---\n",
        "---\n  type: DECISION_RECORD\n---\n",
        "---\nx: y\n---\ntype: DECISION_RECORD\n",
        "# README\ntype: DECISION_RECORD\n",
    ],
)
def test_other_front_matter_stays_invisible(text: str) -> None:
    assert has_yaml_decision_header(text) is False


def test_unquoted_type_is_rejected_loudly_by_lookup_and_list(tmp_path: Path) -> None:
    text = yaml_record_text(token=A).replace('type: "DECISION_RECORD"', "type: DECISION_RECORD")
    path = decisions_dir(tmp_path) / f"{A}.md"
    path.write_text(text, encoding="utf-8")
    rel = path.relative_to(tmp_path).as_posix()
    error = lookup_decision(str(tmp_path), A)["error"]
    assert error["code"] == "RECORD_PARSE_FAILED"
    assert (error["context"]["path"], error["context"]["line"], error["context"]["construct"]) == (
        rel,
        2,
        "unquoted_value",
    )
    skipped = list_decisions(str(tmp_path))["skipped"]
    assert [(s["path"], s["line"], s["construct"]) for s in skipped] == [(rel, 2, "unquoted_value")]
    assert trace_supersedure(str(tmp_path), A)["error"]["code"] == "RECORD_PARSE_FAILED"


def test_readmes_and_other_typed_markdown_stay_out_of_list_and_skipped(tmp_path: Path) -> None:
    root = decisions_dir(tmp_path)
    (root / "README.md").write_text("# Decisions\n", encoding="utf-8")
    (root / "other.md").write_text('---\ntype: "BUILD_PLAN"\n---\nbody\n', encoding="utf-8")
    (root / "bare-other.md").write_text("---\ntype: BUILD_PLAN\n---\nbody\n", encoding="utf-8")
    result = list_decisions(str(tmp_path))
    assert result["records"] == [] and result["skipped"] == []


# --- pre-review: a mid-chain record that becomes unreadable is an envelope, not a crash ---


def test_unreadable_mid_chain_record_returns_an_envelope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_record(tmp_path, token=A, status="SUPERSEDED", superseded_by=B)
    b_path = write_record(tmp_path, token=B)
    real_discover, real_read = agr_read.discover_record, Path.read_text

    def discover(working_dir: Path, token: str) -> Path | None:
        return b_path if token == B else real_discover(working_dir, token)

    def flaky_read(self: Path, *args: object, **kwargs: object) -> str:
        if self == b_path:
            raise PermissionError("unreadable")
        return real_read(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(agr_read, "discover_record", discover)
    monkeypatch.setattr(Path, "read_text", flaky_read)

    traced = trace_supersedure(str(tmp_path), A)
    assert traced["ok"] is False
    assert traced["error"]["code"] == "RECORD_PARSE_FAILED"
    assert traced["error"]["context"]["token"] == B
    assert traced["error"]["context"]["path"] == b_path.relative_to(tmp_path).as_posix()
    assert [e["token"] for e in traced["error"]["context"]["chain"]] == [A]

    looked_up = lookup_decision(str(tmp_path), A)
    assert looked_up["ok"] is True
    assert looked_up["resolution_chain_status"] == "unparseable"
    assert looked_up["rejected_at"]["token"] == B
