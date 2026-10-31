"""PR-4 cubic round 2: G1-G3 behaviour and G5/G6 fixture fidelity."""

from __future__ import annotations

from pathlib import Path

import pytest

from hestai_context_mcp.core.agent_readable_governance_parser import parse_decision_record
from hestai_context_mcp.tools.governance import agr_read, manifest
from hestai_context_mcp.tools.governance.lexer import declares_token
from hestai_context_mcp.tools.list_decisions import list_decisions
from hestai_context_mcp.tools.lookup_decision import lookup_decision
from hestai_context_mcp.tools.trace_supersedure import trace_supersedure

from ._agr_fixtures import decisions_dir, write_record, write_yaml_record, yaml_record_text

pytestmark = pytest.mark.unit

T = "HO-ROUND2-T-20261029"


# --- G1: declares_token needs the decision header ------------------------------------------


def test_g1_non_agr_front_matter_does_not_declare_a_token() -> None:
    text = f'---\ntype: "BUILD_PLAN"\ntoken: "{T}"\n---\nbody\n'
    assert declares_token(text, T) is False
    assert declares_token(f'---\ntoken: "{T}"\n---\n', T) is False


def test_g1_decision_record_front_matter_still_declares() -> None:
    assert declares_token(yaml_record_text(token=T), T) is True


# --- G2: only well-formed tokens are indexed ------------------------------------------------


@pytest.mark.parametrize("bad", ["HO-A|B-20261029", "lower-20261029", "HO-NODATE", "HO A-20261029"])
def test_g2_invalid_yaml_token_is_not_indexed(tmp_path: Path, bad: str) -> None:
    write_yaml_record(tmp_path, token=bad, filename="odd.md")
    write_yaml_record(tmp_path, token=T)
    table = manifest.build_manifest(tmp_path)
    assert bad not in table
    assert f"| {T} |" in table
    assert len([r for r in table.splitlines() if r.startswith("| ") and "---" not in r]) == 2


def test_g2_extract_token_or_id_rejects_a_pipe_token() -> None:
    assert manifest._extract_token_or_id(yaml_record_text(token="HO-A|B-20261029")) is None


# --- G3: `.md` resolves only YAML records ----------------------------------------------------


def test_g3_md_file_holding_an_octave_envelope_is_not_a_record(tmp_path: Path) -> None:
    octave = write_record(tmp_path, token=T)
    md = decisions_dir(tmp_path) / f"{T}.md"
    md.write_text(octave.read_text(encoding="utf-8"), encoding="utf-8")
    octave.unlink()
    assert agr_read.discover_record(tmp_path, T) is None
    assert lookup_decision(str(tmp_path), T)["error"]["code"] == "TOKEN_NOT_FOUND"
    assert trace_supersedure(str(tmp_path), T)["error"]["code"] == "TOKEN_NOT_FOUND"
    assert list_decisions(str(tmp_path))["records"] == []


def test_g3_octave_md_next_to_a_real_oct_md_resolves_the_oct_md(tmp_path: Path) -> None:
    octave = write_record(tmp_path, token=T)
    (decisions_dir(tmp_path) / f"{T}.md").write_text(octave.read_text("utf-8"), encoding="utf-8")
    assert agr_read.discover_record(tmp_path, T) == octave


def test_g3_yaml_md_still_resolves(tmp_path: Path) -> None:
    path = write_yaml_record(tmp_path, token=T)
    assert agr_read.discover_record(tmp_path, T) == path


# --- G5 / G6: fixtures are faithful ----------------------------------------------------------


def test_g5_fixture_round_trips_control_characters() -> None:
    value = 'tab\there\x00nul\x1funit\x7fdel "q" back\\slash 😀'
    text = yaml_record_text(token=T, decision=value)
    assert parse_decision_record(text)["decision"] == value


def test_g6_crlf_fixture_keeps_its_line_endings_on_disk(tmp_path: Path) -> None:
    path = write_yaml_record(tmp_path, token=T, eol="\r\n")
    raw = path.read_bytes()
    header = raw.split(b"---\r\n", 2)[1]
    assert b"\r\n" in raw and header.count(b"\n") == header.count(b"\r\n") > 3
    assert parse_decision_record(raw.decode("utf-8"))["token"] == T
    assert lookup_decision(str(tmp_path), T)["ok"] is True
