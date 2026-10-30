"""N1: a fence line is exactly ``---`` or ``---\\r``; repeated CR is not a fence."""

from __future__ import annotations

from pathlib import Path

import pytest

from hestai_context_mcp.core.agent_readable_governance_parser import (
    classify_record_text,
    diagnose_yaml_record,
    is_yaml_front_matter,
    parse_decision_record,
)
from hestai_context_mcp.tools.list_decisions import list_decisions
from hestai_context_mcp.tools.lookup_decision import lookup_decision

from ._agr_fixtures import decisions_dir, yaml_record_text

pytestmark = pytest.mark.unit

T = "HO-CUBIC-T-20260301"


def _file(tmp_path: Path, data: str) -> Path:
    path = decisions_dir(tmp_path) / f"{T}.md"
    path.write_bytes(data.encode("utf-8"))
    return path


@pytest.mark.parametrize("closing", ["---\r\r", "---\r ", "---\r\r\r", "---\r\t"])
def test_repeated_cr_or_padding_is_not_a_closing_fence(tmp_path: Path, closing: str) -> None:
    text = yaml_record_text(token=T, body="").replace("\n---\n", f"\n{closing}\n")
    reject = diagnose_yaml_record(text)
    assert reject is not None and reject["construct"] == "missing_closing_fence"
    assert parse_decision_record(text)["token"] is None
    path = _file(tmp_path, text)
    rel = path.relative_to(tmp_path).as_posix()
    result = lookup_decision(str(tmp_path), T)
    assert result["ok"] is False and result["error"]["code"] == "RECORD_PARSE_FAILED"
    assert result["error"]["context"]["construct"] == "missing_closing_fence"
    skipped = list_decisions(str(tmp_path))["skipped"]
    assert [(s["path"], s["construct"]) for s in skipped] == [(rel, "missing_closing_fence")]
    assert list_decisions(str(tmp_path))["records"] == []


def test_double_cr_fence_followed_by_a_real_fence_is_an_invalid_key_line() -> None:
    text = yaml_record_text(token=T, body="").replace("\n---\n", "\n---\r\r\n---\n")
    reject = diagnose_yaml_record(text)
    assert reject is not None and reject["construct"] == "invalid_key"


@pytest.mark.parametrize("eol", ["\n", "\r\n"])
def test_valid_closing_controls_still_parse(tmp_path: Path, eol: str) -> None:
    text = yaml_record_text(token=T, eol=eol)
    assert diagnose_yaml_record(text) is None
    _file(tmp_path, text)
    assert lookup_decision(str(tmp_path), T)["ok"] is True
    assert [r["token"] for r in list_decisions(str(tmp_path))["records"]] == [T]


# --- the opening fence had the same leak (rstrip("\r")) -----------------------------------------


@pytest.mark.parametrize("first", ["---\r\r", "---\r\r\r", "---\r "])
def test_repeated_cr_opening_line_is_not_front_matter(first: str) -> None:
    text = yaml_record_text(token=T).replace("---\n", f"{first}\n", 1)
    assert is_yaml_front_matter(text) is False
    assert classify_record_text(text).syntax == "octave"
    assert classify_record_text(text.encode("utf-8")).syntax == "octave"


@pytest.mark.parametrize("eol", ["\n", "\r\n"])
def test_valid_opening_controls_are_front_matter(eol: str) -> None:
    text = yaml_record_text(token=T, eol=eol)
    assert is_yaml_front_matter(text) is True
    assert classify_record_text(text).syntax == "yaml"
    assert classify_record_text(text.encode("utf-8")).syntax == "yaml"
