"""PR-4 slice B: the committed ``.hestai/decisions`` corpus reads exactly as before.

The repo's own corpus is frozen OCTAVE (no YAML decision records, no ``supersedes:``
edges), so the read-time supersession overlay must be inert: every record's status
from ``lookup_decision`` and ``list_decisions`` equals the ``STATUS::`` written in
its file. (The cross-commit comparison against d8e2c6fc is the one-off command in
the slice report; this test pins the invariant that makes it hold.)
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from hestai_context_mcp.core.agent_readable_governance_parser import has_yaml_decision_header
from hestai_context_mcp.tools.governance import agr_read
from hestai_context_mcp.tools.list_decisions import list_decisions
from hestai_context_mcp.tools.lookup_decision import lookup_decision

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[2]
DECISIONS = REPO_ROOT / ".hestai" / "decisions"
_TOKEN_RE = re.compile(r"(?m)^\s*TOKEN::\"?([^\"\s]+)\"?\s*$")
_STATUS_RE = re.compile(r"(?m)^\s*STATUS::\"?([A-Z]+)\"?\s*$")


def _file_statuses() -> dict[str, str]:
    statuses: dict[str, str] = {}
    for path in sorted(DECISIONS.rglob("*.oct.md")):
        text = path.read_text(encoding="utf-8")
        if not text.startswith("===DECISION_RECORD==="):
            continue
        token, status = _TOKEN_RE.search(text), _STATUS_RE.search(text)
        if token and status:
            statuses[token.group(1)] = status.group(1)
    return statuses


def test_committed_corpus_has_no_yaml_decision_records_or_derived_edges() -> None:
    yaml_records = [
        p
        for p in DECISIONS.rglob("*.md")
        if not p.name.endswith(".oct.md")
        and has_yaml_decision_header(p.read_text(encoding="utf-8", errors="replace"))
    ]
    assert yaml_records == []
    assert agr_read.derive_supersession(REPO_ROOT) == {}


def test_corpus_is_non_trivial() -> None:
    assert len(_file_statuses()) >= 10


def test_list_decisions_statuses_equal_file_statuses() -> None:
    expected = _file_statuses()
    result = list_decisions(str(REPO_ROOT))
    assert result["ok"] is True
    listed = {r["token"]: r["status"] for r in result["records"]}
    assert result["skipped"] == []
    assert listed == expected


@pytest.mark.parametrize("token", sorted(_file_statuses()))
def test_lookup_decision_status_equals_file_status(token: str) -> None:
    result = lookup_decision(str(REPO_ROOT), token)
    assert result["ok"] is True, result
    assert result["record"]["status"] == _file_statuses()[token]
