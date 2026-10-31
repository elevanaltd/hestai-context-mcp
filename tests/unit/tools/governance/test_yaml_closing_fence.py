"""M1: the closing fence is exactly ``---`` (optional CR), like the opening fence."""

from __future__ import annotations

from pathlib import Path

import pytest

from hestai_context_mcp.core.agent_readable_governance_parser import (
    collect_topic_blocks,
    diagnose_yaml_record,
    parse_decision_record,
)
from hestai_context_mcp.tools.list_decisions import list_decisions
from hestai_context_mcp.tools.lookup_decision import lookup_decision

from ._agr_fixtures import decisions_dir, yaml_record_text, yaml_topic_lines

pytestmark = pytest.mark.unit

T = "HO-CUBIC-T-20260301"


def _write(tmp_path: Path, text: str) -> Path:
    path = decisions_dir(tmp_path) / f"{T}.md"
    path.write_text(text, encoding="utf-8", newline="")
    return path


@pytest.mark.parametrize("closing", ["---   ", "--- ", "---\t", "---  \r"])
def test_closing_fence_with_trailing_whitespace_is_not_a_fence(
    tmp_path: Path, closing: str
) -> None:
    text = yaml_record_text(token=T, body="").replace("\n---\n", f"\n{closing}\n")
    assert closing in text
    last = max(i for i, ln in enumerate(text.split("\n")) if ln.strip())
    reject = diagnose_yaml_record(text)
    assert reject == {"line": last + 1, "construct": "missing_closing_fence"}
    assert parse_decision_record(text)["token"] is None
    path = _write(tmp_path, text)
    rel = path.relative_to(tmp_path).as_posix()
    error = lookup_decision(str(tmp_path), T)["error"]
    assert error["code"] == "RECORD_PARSE_FAILED"
    assert error["context"]["construct"] == "missing_closing_fence"
    skipped = list_decisions(str(tmp_path))["skipped"]
    assert [(s["path"], s["construct"]) for s in skipped] == [(rel, "missing_closing_fence")]
    assert list_decisions(str(tmp_path))["records"] == []


def test_padded_fence_followed_by_a_real_one_is_an_invalid_key_line(tmp_path: Path) -> None:
    text = yaml_record_text(token=T, body="").replace("\n---\n", "\n---   \n---\n")
    reject = diagnose_yaml_record(text)
    assert reject is not None and reject["construct"] == "invalid_key"
    assert reject["line"] == text.split("\n").index("---   ") + 1
    _write(tmp_path, text)
    assert lookup_decision(str(tmp_path), T)["error"]["context"]["construct"] == "invalid_key"


def test_padded_fence_does_not_close_a_topic_block_scan() -> None:
    lines = [*yaml_topic_lines([("R1", "one")])]
    text = yaml_record_text(token=T, topic="t", extra_lines=lines, body="").replace(
        "\n---\n", "\n---   \n"
    )
    assert collect_topic_blocks(text)["current"] == [{"id": "R1", "rule": "one"}]


@pytest.mark.parametrize("eol", ["\n", "\r\n"])
def test_exact_closing_fence_still_works(tmp_path: Path, eol: str) -> None:
    text = yaml_record_text(token=T, eol=eol)
    assert diagnose_yaml_record(text) is None
    _write(tmp_path, text)
    assert lookup_decision(str(tmp_path), T)["ok"] is True
    assert [r["token"] for r in list_decisions(str(tmp_path))["records"]] == [T]
