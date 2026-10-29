"""PR-4 slice A steps 3-4: discovery, manifest and the three read tools see YAML.

A quoted-YAML front-matter record (``<token>.md``) resolves through the SAME code
paths as an OCTAVE ``<token>.oct.md`` record and returns the SAME dict shape
(PROD I4). Reads stay side-effect free (PROD I5). Fixtures live in ``tmp_path``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hestai_context_mcp.tools.governance import agr_read, manifest
from hestai_context_mcp.tools.list_decisions import list_decisions
from hestai_context_mcp.tools.lookup_decision import lookup_decision
from hestai_context_mcp.tools.trace_supersedure import trace_supersedure

from ._agr_fixtures import (
    decisions_dir,
    snapshot_tree,
    write_record,
    write_yaml_record,
    yaml_record_text,
)

pytestmark = pytest.mark.unit

T_OCT = "HO-READER-OCTAVE-20261001"
T_YAML = "HO-READER-YAML-20261002"
T_OLD = "HO-READER-OLD-20261003"
T_NEW = "HO-READER-NEW-20261004"


# --- iter_record_paths / is_decision_record ----------------------------------


def test_iter_record_paths_yields_yaml_md_but_not_readmes(tmp_path: Path) -> None:
    write_record(tmp_path, token=T_OCT)
    yaml_path = write_yaml_record(tmp_path, token=T_YAML)
    root = decisions_dir(tmp_path)
    (root / "README.md").write_text("# Decisions\n", encoding="utf-8")
    (root / "front-matter-only.md").write_text('---\ntitle: "x"\n---\nbody\n', encoding="utf-8")
    paths = agr_read.iter_record_paths(tmp_path)
    assert yaml_path in paths
    assert root / f"{T_OCT}.oct.md" in paths
    assert root / "README.md" not in paths
    assert root / "front-matter-only.md" not in paths


def test_is_decision_record_recognises_yaml_header() -> None:
    assert agr_read.is_decision_record(yaml_record_text(token=T_YAML)) is True
    assert agr_read.is_decision_record('---\ntitle: "x"\n---\n') is False


def test_yaml_file_body_octave_lines_do_not_qualify() -> None:
    text = '---\ntitle: "x"\n---\nTYPE::DECISION_RECORD\n'
    assert agr_read.is_decision_record(text) is False


# --- discover_record ----------------------------------------------------------


def test_discover_record_resolves_token_dot_md(tmp_path: Path) -> None:
    path = write_yaml_record(tmp_path, token=T_YAML)
    assert agr_read.discover_record(tmp_path, T_YAML) == path


def test_discover_record_resolves_sub_grouped_yaml(tmp_path: Path) -> None:
    path = write_yaml_record(tmp_path, token=T_YAML, group="topics")
    assert agr_read.discover_record(tmp_path, T_YAML) == path


def test_discover_record_prefers_oct_md_over_md(tmp_path: Path) -> None:
    oct_path = write_record(tmp_path, token=T_YAML)
    write_yaml_record(tmp_path, token=T_YAML)
    assert agr_read.discover_record(tmp_path, T_YAML) == oct_path


def test_discover_record_content_scan_finds_drifted_yaml_filename(tmp_path: Path) -> None:
    path = write_yaml_record(tmp_path, token=T_YAML, filename="renamed.md")
    assert agr_read.discover_record(tmp_path, T_YAML) == path


def test_discover_record_ignores_non_record_md_with_token_filename(tmp_path: Path) -> None:
    (decisions_dir(tmp_path) / f"{T_YAML}.md").write_text("# not a record\n", encoding="utf-8")
    assert agr_read.discover_record(tmp_path, T_YAML) is None


def test_discover_record_ignores_body_token_of_yaml_file(tmp_path: Path) -> None:
    write_yaml_record(tmp_path, token=T_YAML, body=f"TOKEN::{T_OLD}\n")
    assert agr_read.discover_record(tmp_path, T_OLD) is None


def test_discover_record_finds_malformed_yaml_by_token(tmp_path: Path) -> None:
    path = write_yaml_record(tmp_path, token=T_YAML, extra_lines=["extra: bare"])
    assert agr_read.discover_record(tmp_path, T_YAML) == path


# --- manifest -----------------------------------------------------------------


def test_manifest_indexes_yaml_records_only(tmp_path: Path) -> None:
    write_record(tmp_path, token=T_OCT)
    write_yaml_record(tmp_path, token=T_YAML)
    (decisions_dir(tmp_path) / "README.md").write_text("# Decisions\n", encoding="utf-8")
    table = manifest.build_manifest(tmp_path)
    assert f"| {T_YAML} | .hestai/decisions/{T_YAML}.md |" in table
    assert f"| {T_OCT} | .hestai/decisions/{T_OCT}.oct.md |" in table
    assert "README" not in table


def test_manifest_extract_token_or_id_reads_yaml_front_matter() -> None:
    text = yaml_record_text(token=T_YAML, body=f"TOKEN::{T_OLD}\n")
    assert manifest._extract_token_or_id(text) == T_YAML


# --- tools: same dict shape ---------------------------------------------------


def _strip_path(record: dict[str, object]) -> dict[str, object]:
    return {k: v for k, v in record.items() if k != "path"}


def test_lookup_decision_yaml_equals_octave_shape(tmp_path: Path) -> None:
    kw = {"scope": "repo", "tier": "TACTICAL"}
    write_record(tmp_path, token=T_OCT, **kw)
    write_yaml_record(tmp_path, token=T_YAML, **kw)
    oct_result = lookup_decision(str(tmp_path), T_OCT)
    yaml_result = lookup_decision(str(tmp_path), T_YAML)
    assert oct_result["ok"] is True and yaml_result["ok"] is True
    assert set(yaml_result) == set(oct_result)
    assert set(yaml_result["record"]) == set(oct_result["record"])
    assert yaml_result["record"]["path"] == f".hestai/decisions/{T_YAML}.md"
    expected = _strip_path(oct_result["record"]) | {"token": T_YAML}
    assert _strip_path(yaml_result["record"]) == expected
    assert yaml_result["resolution_chain"] == []
    assert yaml_result["resolution_chain_status"] == oct_result["resolution_chain_status"]


def test_lookup_decision_yaml_topic_record_has_current_state_list(tmp_path: Path) -> None:
    write_yaml_record(
        tmp_path, token=T_YAML, topic="t", body="CURRENT:\n  R1:: smuggled from body\n"
    )
    record = lookup_decision(str(tmp_path), T_YAML)["record"]
    assert record["fields"]["TOPIC"] == "t"
    assert record["current_state"] == []


def test_lookup_decision_malformed_yaml_is_parse_failed_naming_both_syntaxes(
    tmp_path: Path,
) -> None:
    write_yaml_record(tmp_path, token=T_YAML, extra_lines=["extra: bare"])
    result = lookup_decision(str(tmp_path), T_YAML)
    assert result["ok"] is False
    assert result["error"]["code"] == "RECORD_PARSE_FAILED"
    parse_error = result["error"]["context"]["parse_error"]
    assert "OCTAVE" in parse_error and "YAML" in parse_error


# (slice-A test_lookup_decision_yaml_with_topic_block_header_is_rejected removed: superseded by
# the B3 ruling; see test_yaml_topic_blocks.py)


def test_list_decisions_includes_yaml_and_applies_filters(tmp_path: Path) -> None:
    write_record(tmp_path, token=T_OCT, authored_at="2026-06-01T00:00:00Z")
    write_yaml_record(tmp_path, token=T_YAML, authored_at="2026-07-01T00:00:00Z", scope="repo")
    (decisions_dir(tmp_path) / "README.md").write_text("# Decisions\n", encoding="utf-8")
    result = list_decisions(str(tmp_path))
    assert result["ok"] is True
    assert [r["token"] for r in result["records"]] == [T_YAML, T_OCT]
    assert result["skipped"] == []
    row = result["records"][0]
    assert set(row) == set(result["records"][1])
    assert row["path"] == f".hestai/decisions/{T_YAML}.md"
    assert [r["token"] for r in list_decisions(str(tmp_path), scope="repo")["records"]] == [T_YAML]


def test_list_decisions_skips_malformed_yaml_with_wording_naming_both(tmp_path: Path) -> None:
    write_yaml_record(tmp_path, token=T_YAML, extra_lines=["extra: bare"])
    result = list_decisions(str(tmp_path))
    assert result["records"] == []
    assert len(result["skipped"]) == 1
    skipped = result["skipped"][0]
    assert skipped["path"] == f".hestai/decisions/{T_YAML}.md"
    assert "OCTAVE" in skipped["parse_error"] and "YAML" in skipped["parse_error"]


def test_trace_supersedure_walks_a_mixed_syntax_chain(tmp_path: Path) -> None:
    write_yaml_record(tmp_path, token=T_OLD, status="SUPERSEDED", superseded_by=T_NEW)
    write_record(tmp_path, token=T_NEW)
    result = trace_supersedure(str(tmp_path), T_OLD)
    assert result["ok"] is True
    assert [e["token"] for e in result["chain"]] == [T_OLD, T_NEW]
    assert result["chain"][0]["path"] == f".hestai/decisions/{T_OLD}.md"
    assert result["chain"][0]["superseded_by"] == T_NEW
    assert result["terminal_token"] == T_NEW


def test_lookup_decision_yaml_superseded_has_resolution_chain(tmp_path: Path) -> None:
    write_yaml_record(tmp_path, token=T_OLD, status="SUPERSEDED", superseded_by=T_NEW)
    write_yaml_record(tmp_path, token=T_NEW)
    result = lookup_decision(str(tmp_path), T_OLD)
    assert [e["token"] for e in result["resolution_chain"]] == [T_OLD, T_NEW]
    assert result["resolution_chain_status"] == "complete"


def test_yaml_reads_are_side_effect_free(tmp_path: Path) -> None:
    write_yaml_record(tmp_path, token=T_OLD, status="SUPERSEDED", superseded_by=T_NEW)
    write_yaml_record(tmp_path, token=T_NEW)
    before = snapshot_tree(tmp_path)
    lookup_decision(str(tmp_path), T_OLD)
    list_decisions(str(tmp_path))
    trace_supersedure(str(tmp_path), T_OLD)
    assert snapshot_tree(tmp_path) == before
