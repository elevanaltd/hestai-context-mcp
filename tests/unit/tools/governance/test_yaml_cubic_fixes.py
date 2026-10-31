"""PR-4 bot-resolution fixes (cubic at 67ad39da): F1-F4, all against the loud-reject rulings."""

from __future__ import annotations

from pathlib import Path

import pytest

from hestai_context_mcp.core.agent_readable_governance_parser import (
    diagnose_yaml_record,
    has_yaml_decision_header,
)
from hestai_context_mcp.tools.governance import agr_read, manifest
from hestai_context_mcp.tools.list_decisions import list_decisions
from hestai_context_mcp.tools.lookup_decision import lookup_decision
from hestai_context_mcp.tools.trace_supersedure import trace_supersedure

from ._agr_fixtures import decisions_dir, write_record, write_yaml_record, yaml_record_text

pytestmark = pytest.mark.unit

A = "HO-CUBIC-A-20260101"
T = "HO-CUBIC-T-20260301"
OTHER = "HO-CUBIC-OTHER-20260401"


# --- F1: an invalid-token deriver derives no edge ------------------------------------


@pytest.mark.parametrize("bad_token", ["lowercase-bad", "HO-NO-DATE", "ho-cubic-20261029", "X"])
def test_f1_invalid_token_source_derives_no_edge(tmp_path: Path, bad_token: str) -> None:
    write_record(tmp_path, token=A)
    write_yaml_record(tmp_path, token=bad_token, filename="source.md", supersedes=A)
    assert agr_read.derive_supersession(tmp_path) == {}
    assert lookup_decision(str(tmp_path), A)["record"]["status"] == "RATIFIED"
    assert [e["token"] for e in trace_supersedure(str(tmp_path), A)["chain"]] == [A]


def test_f1_valid_token_source_still_derives(tmp_path: Path) -> None:
    write_record(tmp_path, token=A)
    write_yaml_record(tmp_path, token=T, supersedes=A)
    assert agr_read.derive_supersession(tmp_path) == {A: [T]}


# --- F2: a filename-matched malformed YAML candidate is reported, not "not found" ---------


def _write_text(tmp_path: Path, name: str, text: str) -> Path:
    path = decisions_dir(tmp_path) / name
    path.write_text(text, encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("old", "new", "construct"),
    [
        (f'token: "{T}"', f"token: {T}", "unquoted_value"),
        (f'token: "{T}"', f"token: '{T}'", "unquoted_value"),
        (f'token: "{T}"', f'token: "{T}" # note', "comment"),
        (f'token: "{T}"', f'token: "{T}" junk', "trailing_garbage"),
    ],
)
def test_f2_unextractable_token_scalar_is_reported_for_lookup_and_trace(
    tmp_path: Path, old: str, new: str, construct: str
) -> None:
    text = yaml_record_text(token=T).replace(old, new)
    assert new in text
    path = _write_text(tmp_path, f"{T}.md", text)
    line = text.split("\n").index(new) + 1
    rel = path.relative_to(tmp_path).as_posix()
    for result in (lookup_decision(str(tmp_path), T), trace_supersedure(str(tmp_path), T)):
        assert result["ok"] is False
        error = result["error"]
        assert error["code"] == "RECORD_PARSE_FAILED", error
        ctx = error["context"]
        assert (ctx["path"], ctx["line"], ctx["construct"]) == (rel, line, construct)


def test_f2_sub_grouped_file_is_reported_too(tmp_path: Path) -> None:
    text = yaml_record_text(token=T).replace(f'token: "{T}"', f"token: {T}")
    (decisions_dir(tmp_path) / "g").mkdir()
    _write_text(tmp_path, f"g/{T}.md", text)
    assert lookup_decision(str(tmp_path), T)["error"]["code"] == "RECORD_PARSE_FAILED"


def test_f2_parseable_record_with_mismatched_token_does_not_resolve_by_filename(
    tmp_path: Path,
) -> None:
    _write_text(tmp_path, f"{T}.md", yaml_record_text(token=OTHER))
    assert lookup_decision(str(tmp_path), T)["error"]["code"] == "TOKEN_NOT_FOUND"
    assert trace_supersedure(str(tmp_path), T)["error"]["code"] == "TOKEN_NOT_FOUND"
    assert lookup_decision(str(tmp_path), OTHER)["ok"] is True  # still found by content


def test_f2_malformed_record_with_a_quoted_mismatched_token_does_not_resolve_either(
    tmp_path: Path,
) -> None:
    _write_text(tmp_path, f"{T}.md", yaml_record_text(token=OTHER, extra_lines=["extra: bare"]))
    assert lookup_decision(str(tmp_path), T)["error"]["code"] == "TOKEN_NOT_FOUND"
    assert trace_supersedure(str(tmp_path), T)["error"]["code"] == "TOKEN_NOT_FOUND"


def test_f2_non_candidate_markdown_with_the_filename_stays_not_found(tmp_path: Path) -> None:
    _write_text(tmp_path, f"{T}.md", '---\ntype: "OTHER"\ntoken: x\n---\n')
    assert lookup_decision(str(tmp_path), T)["error"]["code"] == "TOKEN_NOT_FOUND"


# --- F3: the manifest does not index YAML-looking non-decision files ----------------------


def test_f3_yaml_looking_non_decision_oct_md_is_not_indexed(tmp_path: Path) -> None:
    root = decisions_dir(tmp_path)
    (root / "plan.oct.md").write_text(
        '---\ntype: "BUILD_PLAN"\ntoken: "HO-CUBIC-PLAN-20261029"\n---\n', encoding="utf-8"
    )
    (root / "notag.oct.md").write_text('---\ntoken: "HO-CUBIC-NOTYPE-20261029"\n---\n', "utf-8")
    write_yaml_record(tmp_path, token=T)
    table = manifest.build_manifest(tmp_path)
    assert "HO-CUBIC-PLAN-20261029" not in table and "HO-CUBIC-NOTYPE-20261029" not in table
    assert f"| {T} |" in table


def test_f3_extract_token_or_id_requires_the_decision_header_for_yaml() -> None:
    assert manifest._extract_token_or_id('---\ntype: "X"\ntoken: "HO-A-20261029"\n---\n') is None
    assert manifest._extract_token_or_id(yaml_record_text(token=T)) == T


# --- F4: type line with trailing comment / garbage / BOM is a loud candidate ---------------


@pytest.mark.parametrize(
    ("type_line", "construct"),
    [
        ('type: "DECISION_RECORD" # note', "comment"),
        ('type: "DECISION_RECORD" junk', "trailing_garbage"),
        ("type: DECISION_RECORD # note", "unquoted_value"),
        ("type: DECISION_RECORD extra", "unquoted_value"),
        ("type: 'DECISION_RECORD' # note", "unquoted_value"),
    ],
)
def test_f4_decorated_type_line_is_a_candidate_and_rejected_loudly(
    tmp_path: Path, type_line: str, construct: str
) -> None:
    text = yaml_record_text(token=T).replace('type: "DECISION_RECORD"', type_line)
    assert has_yaml_decision_header(text) is True
    assert agr_read.is_decision_record(text) is True
    assert diagnose_yaml_record(text) == {"line": 2, "construct": construct}
    path = _write_text(tmp_path, f"{T}.md", text)
    rel = path.relative_to(tmp_path).as_posix()
    error = lookup_decision(str(tmp_path), T)["error"]
    assert (error["code"], error["context"]["line"], error["context"]["construct"]) == (
        "RECORD_PARSE_FAILED",
        2,
        construct,
    )
    skipped = list_decisions(str(tmp_path))["skipped"]
    assert [(s["path"], s["line"], s["construct"]) for s in skipped] == [(rel, 2, construct)]


def test_f4_bom_before_the_fence_is_a_candidate_and_rejected_loudly(tmp_path: Path) -> None:
    text = "﻿" + yaml_record_text(token=T)
    assert has_yaml_decision_header(text) is True
    assert agr_read.is_decision_record(text) is True
    assert diagnose_yaml_record(text) == {"line": 1, "construct": "invalid_key"}
    path = _write_text(tmp_path, f"{T}.md", text)
    rel = path.relative_to(tmp_path).as_posix()
    error = lookup_decision(str(tmp_path), T)["error"]
    assert error["code"] == "RECORD_PARSE_FAILED"
    assert (error["context"]["line"], error["context"]["construct"]) == (1, "invalid_key")
    skipped = list_decisions(str(tmp_path))["skipped"]
    assert [(s["path"], s["line"], s["construct"]) for s in skipped] == [(rel, 1, "invalid_key")]


@pytest.mark.parametrize(
    "text",
    [
        '---\ntype: "OTHER" # DECISION_RECORD\n---\n',
        "---\ntype: DECISION_RECORD_X\n---\n",
        '---\ntype: "DECISION_RECORD_X"\n---\n',
        "---\ntype: DECISION_RECORDS\n---\n",
        '---\n  type: "DECISION_RECORD"\n---\n',
        '---\ntitle: x\n---\ntype: "DECISION_RECORD"\n',
        "﻿---\ntitle: x\n---\n",
        "﻿# README\ntype: DECISION_RECORD\n",
        "# README\n",
    ],
)
def test_f4_non_candidates_stay_invisible(text: str) -> None:
    assert has_yaml_decision_header(text) is False
    assert agr_read.is_decision_record(text) is False
