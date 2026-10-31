"""Rework round 3: K3 BOM+YAML never falls into OCTAVE scanning, K4 exact fence line,
K1 BOM-prefixed OCTAVE detection equals base, K5 resolve() inside the guarded block."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from hestai_context_mcp.core.agent_readable_governance_parser import (
    classify_record_text,
    decode_record_bytes,
    diagnose_yaml_record,
    is_yaml_front_matter,
    parse_decision_record,
)
from hestai_context_mcp.tools.governance import agr_read
from hestai_context_mcp.tools.governance.lexer import lookup_token_deterministic
from hestai_context_mcp.tools.list_decisions import list_decisions
from hestai_context_mcp.tools.lookup_decision import lookup_decision

from ._agr_fixtures import decisions_dir, yaml_record_text

pytestmark = pytest.mark.unit

T = "HO-CUBIC-T-20260301"
A = "HO-CUBIC-A-20260101"
BOM = "﻿"

OCTAVE_FULL = (
    '===DECISION_RECORD===\nMETA:\n  TYPE::DECISION_RECORD\n  VERSION::"1.0"\n'
    f"  TOKEN::{A}\n  STATUS::RATIFIED\n  TIER::STRATEGIC\n"
    '  AUTHORED_AT::"2026-06-01T00:00:00Z"\n  DECISION::"d"\n  BECAUSE::"b"\n===END===\n'
)


# --- K3 ---------------------------------------------------------------------------------------


def test_k3_bom_yaml_header_with_a_full_octave_body_is_rejected_not_ok(tmp_path: Path) -> None:
    text = BOM + yaml_record_text(token=T, body=OCTAVE_FULL)
    parsed = parse_decision_record(text)
    assert parsed["token"] is None and parsed["fields"] == {}
    path = decisions_dir(tmp_path) / f"{T}.md"
    path.write_text(text, encoding="utf-8")
    result = lookup_decision(str(tmp_path), T)
    assert result["ok"] is False
    assert result["error"]["code"] == "RECORD_PARSE_FAILED"
    assert (result["error"]["context"]["line"], result["error"]["context"]["construct"]) == (
        1,
        "invalid_key",
    )
    listed = list_decisions(str(tmp_path))
    assert listed["records"] == [] and listed["skipped"][0]["construct"] == "invalid_key"


def test_k3_octave_body_token_is_not_read_from_a_bom_yaml_file(tmp_path: Path) -> None:
    (decisions_dir(tmp_path) / f"{T}.md").write_text(
        BOM + yaml_record_text(token=T, body=OCTAVE_FULL), encoding="utf-8"
    )
    assert lookup_decision(str(tmp_path), A)["error"]["code"] == "TOKEN_NOT_FOUND"


# --- K4 ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("first", ["---not-front-matter", "----", "--- x", "---:", "-- -"])
def test_k4_only_a_complete_fence_line_is_front_matter(first: str) -> None:
    assert is_yaml_front_matter(f"{first}\nbody\n") is False


@pytest.mark.parametrize("first", ["---", "---\r"])
def test_k4_complete_fence_line_variants_are_front_matter(first: str) -> None:
    assert is_yaml_front_matter(f"{first}\nx: y\n") is True


@pytest.mark.parametrize("first", ["---not-front-matter", "----"])
def test_k4_non_fence_input_keeps_replace_semantics(first: str) -> None:
    assert "�" in decode_record_bytes(first.encode() + b"\nbad \xff byte\n")


def test_k4_real_fence_keeps_strict_decoding() -> None:
    decoded = decode_record_bytes(b'---\nx: "bad \xff"\n---\n')
    assert "�" not in decoded and any(0xD800 <= ord(c) <= 0xDFFF for c in decoded)


def test_k4_bom_then_a_real_fence_is_strict_and_bom_then_prefix_is_not() -> None:
    assert "�" not in decode_record_bytes(BOM.encode() + b'---\nx: "\xff"\n---\n')
    assert "�" in decode_record_bytes(BOM.encode() + b"---nope\n\xff\n")


# --- K1: BOM-prefixed non-YAML content behaves exactly as base (d8e2c6fc) ---------------------
# Base: is_decision_record = sentinel-anchored-at-start OR a line-anchored TYPE::DECISION_RECORD.
# A leading BOM defeats the \A sentinel but not the (?m) TYPE line.


def test_k1_bom_prefixed_octave_with_a_type_line_is_a_decision_record_as_at_base() -> None:
    assert agr_read.is_decision_record(BOM + OCTAVE_FULL) is True


def test_k1_bom_prefixed_octave_with_only_the_sentinel_is_not_as_at_base() -> None:
    only_sentinel = BOM + "===DECISION_RECORD===\nMETA:\n  TOKEN::" + A + "\n===END===\n"
    assert agr_read.is_decision_record(only_sentinel) is False


def test_k1_bom_prefixed_non_yaml_markdown_is_not_a_record() -> None:
    assert agr_read.is_decision_record(BOM + "# README\n") is False


def test_k1_bom_prefixed_fence_without_a_decision_type_behaves_like_the_unprefixed_file() -> None:
    body = "---\ntitle: x\n---\nTYPE::DECISION_RECORD\n"
    assert agr_read.is_decision_record(BOM + body) is agr_read.is_decision_record(body) is False


def test_k1_bom_yaml_candidate_is_still_a_candidate() -> None:
    assert agr_read.is_decision_record(BOM + yaml_record_text(token=T)) is True


# --- K5 ---------------------------------------------------------------------------------------


def test_k5_symlink_loop_manifest_path_falls_back_instead_of_raising(tmp_path: Path) -> None:
    hestai = tmp_path / ".hestai"
    hestai.mkdir()
    loop_a, loop_b = hestai / "loop_a", hestai / "loop_b"
    os.symlink(loop_b, loop_a)
    os.symlink(loop_a, loop_b)
    (hestai / "MANIFEST.md").write_text(
        f"| TOKEN/ID | path |\n| --- | --- |\n| {T} | .hestai/loop_a/x.md |\n", encoding="utf-8"
    )
    assert lookup_token_deterministic(tmp_path, T) is False  # no raise; filesystem finds nothing


def test_k5_loop_row_still_falls_back_to_a_real_yaml_record(tmp_path: Path) -> None:
    from ._agr_fixtures import write_yaml_record

    write_yaml_record(tmp_path, token=T)
    hestai = tmp_path / ".hestai"
    os.symlink(hestai / "loop_b", hestai / "loop_a")
    os.symlink(hestai / "loop_a", hestai / "loop_b")
    (hestai / "MANIFEST.md").write_text(
        f"| TOKEN/ID | path |\n| --- | --- |\n| {T} | .hestai/loop_a/x.md |\n", encoding="utf-8"
    )
    assert lookup_token_deterministic(tmp_path, T) is True


# --- the single entry step ----------------------------------------------------------------------

YAML_TEXT = yaml_record_text(token=T, scope="repo")
OCTAVE_TEXT = OCTAVE_FULL


def _variant(text: str, *, bom: bool, crlf: bool) -> bytes:
    body = text.replace("\n", "\r\n") if crlf else text
    return ((BOM if bom else "") + body).encode("utf-8")


@pytest.mark.parametrize("crlf", [False, True])
@pytest.mark.parametrize("bom", [False, True])
@pytest.mark.parametrize(("syntax", "text"), [("octave", OCTAVE_TEXT), ("yaml", YAML_TEXT)])
def test_entry_step_classifies_every_variant_alike(
    syntax: str, text: str, bom: bool, crlf: bool
) -> None:
    for raw in (_variant(text, bom=bom, crlf=crlf), _variant(text, bom=bom, crlf=crlf).decode()):
        record = classify_record_text(raw)
        assert record.syntax == syntax
        parsed = parse_decision_record(record.text)
        reference = parse_decision_record(text)
        if syntax == "yaml" and bom:
            # a BOM is not part of the YAML record grammar: loud reject, never parsed as OCTAVE
            assert record.diagnostic == {"line": 1, "construct": "invalid_key"}
            assert parsed["token"] is None
        else:
            assert record.diagnostic is None
            assert parsed == reference
        assert "\r\n" not in record.text or syntax == "octave"


def test_entry_step_decodes_octave_with_replace_and_yaml_strictly() -> None:
    octave = classify_record_text(b'===X===\nA::"b\xffc"\n')
    assert octave.syntax == "octave" and "\ufffd" in octave.text and octave.diagnostic is None
    yaml = classify_record_text(b'---\ntype: "DECISION_RECORD"\nx: "b\xffc"\n---\n')
    assert yaml.syntax == "yaml" and yaml.diagnostic == {"line": 3, "construct": "invalid_utf8"}
    body_only = classify_record_text(b'---\ntype: "DECISION_RECORD"\n---\nbody \xff\n')
    assert body_only.diagnostic is None


def test_entry_step_never_lets_a_yaml_candidate_fall_into_octave_parsing() -> None:
    text = BOM + yaml_record_text(token=T, body=OCTAVE_FULL)
    assert classify_record_text(text).syntax == "yaml"
    assert parse_decision_record(text)["token"] is None
    assert diagnose_yaml_record(text) == {"line": 1, "construct": "invalid_key"}
