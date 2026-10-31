"""Gate rework round 1: H1 strict UTF-8 for YAML, H2 lexer/manifest count parseable YAML only,
H3 a YAML deriver must be the file its token resolves to. Fixture tokens are reused literals."""

from __future__ import annotations

from pathlib import Path

import pytest

from hestai_context_mcp.core.agent_readable_governance_parser import (
    decode_record_bytes,
    diagnose_yaml_record,
    parse_decision_record,
)
from hestai_context_mcp.tools.governance import agr_read, manifest
from hestai_context_mcp.tools.governance.lexer import declares_token, lookup_token_deterministic
from hestai_context_mcp.tools.list_decisions import list_decisions
from hestai_context_mcp.tools.lookup_decision import lookup_decision
from hestai_context_mcp.tools.trace_supersedure import trace_supersedure

from ._agr_fixtures import decisions_dir, write_record, write_yaml_record, yaml_record_text

pytestmark = pytest.mark.unit

A = "HO-CUBIC-A-20260101"
T = "HO-CUBIC-T-20260301"


# --- H1 ------------------------------------------------------------------------------------


def _bad_utf8_record(tmp_path: Path, *, where: str = "fence") -> tuple[Path, int]:
    text = yaml_record_text(
        token=T, extra_lines=['extra: "PLACEHOLDER"'] if where == "fence" else None
    )
    body = text.encode("utf-8")
    if where == "fence":
        body = body.replace(b"PLACEHOLDER", b"bad\xffbyte")
    else:
        body = body + b"trailing \xff bytes in the markdown body\n"
    path = decisions_dir(tmp_path) / f"{T}.md"
    path.write_bytes(body)
    line = next((i + 1 for i, ln in enumerate(body.split(b"\n")) if b"\xff" in ln), 0)
    return path, line


def test_h1_decode_record_bytes_is_strict_only_for_yaml() -> None:
    assert decode_record_bytes(b'---\nx: "a\xffb"\n---\n') != ""
    assert diagnose_yaml_record(decode_record_bytes(b'---\nx: "a\xffb"\n---\n')) == {
        "line": 2,
        "construct": "invalid_utf8",
    }
    octave = decode_record_bytes(b'===DECISION_RECORD===\nMETA:\n  X::"a\xffb"\n')
    assert "�" in octave  # OCTAVE keeps errors="replace"


def test_h1_invalid_utf8_inside_the_fences_is_a_loud_reject(tmp_path: Path) -> None:
    path, line = _bad_utf8_record(tmp_path)
    rel = path.relative_to(tmp_path).as_posix()
    for result in (lookup_decision(str(tmp_path), T), trace_supersedure(str(tmp_path), T)):
        assert result["ok"] is False
        ctx = result["error"]["context"]
        assert result["error"]["code"] == "RECORD_PARSE_FAILED"
        assert (ctx["path"], ctx["line"], ctx["construct"]) == (rel, line, "invalid_utf8")
    skipped = list_decisions(str(tmp_path))["skipped"]
    assert [(s["path"], s["line"], s["construct"]) for s in skipped] == [
        (rel, line, "invalid_utf8")
    ]
    assert list_decisions(str(tmp_path))["records"] == []


def test_h1_invalid_utf8_in_the_markdown_body_is_ignored(tmp_path: Path) -> None:
    _bad_utf8_record(tmp_path, where="body")
    assert lookup_decision(str(tmp_path), T)["ok"] is True
    assert [r["token"] for r in list_decisions(str(tmp_path))["records"]] == [T]


def test_h1_octave_records_keep_replace_semantics(tmp_path: Path) -> None:
    path = write_record(tmp_path, token=T)
    path.write_bytes(path.read_bytes().replace(b"A binding decision", b"A bin\xffding decision"))
    result = lookup_decision(str(tmp_path), T)
    assert result["ok"] is True
    assert "�" in result["record"]["decision"]


def test_h1_mid_chain_invalid_utf8_stops_the_walk(tmp_path: Path) -> None:
    write_record(tmp_path, token=A, status="SUPERSEDED", superseded_by=T)
    path, line = _bad_utf8_record(tmp_path)
    error = trace_supersedure(str(tmp_path), A)["error"]
    assert error["code"] == "RECORD_PARSE_FAILED"
    assert (error["context"]["line"], error["context"]["construct"]) == (line, "invalid_utf8")


# --- H2 ------------------------------------------------------------------------------------


def _rejected_yaml(tmp_path: Path) -> None:
    text = yaml_record_text(token=T).replace('status: "RATIFIED"', "status: RATIFIED")
    (decisions_dir(tmp_path) / f"{T}.md").write_text(text, encoding="utf-8")


def test_h2_rejected_yaml_does_not_satisfy_the_target_check(tmp_path: Path) -> None:
    _rejected_yaml(tmp_path)
    assert lookup_token_deterministic(tmp_path, T) is False
    assert f"| {T} |" not in manifest.build_manifest(tmp_path)


def test_h2_valid_yaml_does_satisfy_it(tmp_path: Path) -> None:
    write_yaml_record(tmp_path, token=T)
    assert lookup_token_deterministic(tmp_path, T) is True
    assert f"| {T} |" in manifest.build_manifest(tmp_path)


def test_h2_incomplete_yaml_does_not_satisfy_it(tmp_path: Path) -> None:
    text = yaml_record_text(token=T).replace('because: "A one-sentence rationale."\n', "")
    (decisions_dir(tmp_path) / f"{T}.md").write_text(text, encoding="utf-8")
    assert lookup_token_deterministic(tmp_path, T) is False


def test_h2_declares_token_stays_a_pure_declaration_check() -> None:
    text = yaml_record_text(token=T).replace('status: "RATIFIED"', "status: RATIFIED")
    assert declares_token(text, T) is True


def test_h2_octave_lexer_behaviour_unchanged(tmp_path: Path) -> None:
    write_record(tmp_path, token=T)
    assert lookup_token_deterministic(tmp_path, T) is True
    assert f"| {T} |" in manifest.build_manifest(tmp_path)


# --- H3 ------------------------------------------------------------------------------------


def test_h3_duplicate_token_deriver_derives_no_edge(tmp_path: Path) -> None:
    write_record(tmp_path, token=A)
    write_record(tmp_path, token=T)  # T.oct.md wins discovery
    write_yaml_record(tmp_path, token=T, filename="duplicate.md", supersedes=A)
    assert agr_read.derive_supersession(tmp_path) == {}
    assert lookup_decision(str(tmp_path), A)["record"]["status"] == "RATIFIED"
    assert [e["token"] for e in trace_supersedure(str(tmp_path), A)["chain"]] == [A]


def test_h3_normal_deriver_keeps_its_edge(tmp_path: Path) -> None:
    write_record(tmp_path, token=A)
    write_yaml_record(tmp_path, token=T, supersedes=A)
    assert agr_read.derive_supersession(tmp_path) == {A: [T]}


def test_h3_renamed_but_unique_yaml_deriver_keeps_its_edge(tmp_path: Path) -> None:
    write_record(tmp_path, token=A)
    write_yaml_record(tmp_path, token=T, filename="renamed.md", supersedes=A)
    assert agr_read.derive_supersession(tmp_path) == {A: [T]}


def test_parse_of_invalid_bytes_text_does_not_raise() -> None:
    assert parse_decision_record(decode_record_bytes(b'---\nx: "\xff"\n---\n'))["token"] is None
