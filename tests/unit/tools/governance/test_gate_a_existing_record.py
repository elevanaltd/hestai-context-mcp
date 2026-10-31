"""RED: Gate A ``existing_record`` keyword for the append_ruling path (#203 S2).

``validate_record_content(..., existing_record=True)`` lets a REWRITE of a record that
already exists pass Gate A: it skips ONLY the "already exists in the governance store"
check and its file-exists sibling. Every other check still runs. The keyword defaults
to False, so content mode keeps refusing an existing TOKEN; that it is reachable only
from the append path is pinned in ``test_submit_governance_append_ruling.py``.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any

import pytest

from hestai_context_mcp.core.agent_readable_governance_parser import emit_yaml_record
from hestai_context_mcp.tools.governance.type_checker import validate_record_content

pytestmark = pytest.mark.unit

TOKEN = "TOPIC-GATE-A-EXISTING-20261031"
CORE: dict[str, str] = {
    "TYPE": "DECISION_RECORD",
    "VERSION": "1.5",
    "TOKEN": TOKEN,
    "STATUS": "RATIFIED",
    "TIER": "TACTICAL",
    "AUTHORED_AT": "2026-10-31T00:00:00Z",
    "DECISION": "A binding decision sentence.",
    "BECAUSE": "A one-sentence rationale.",
    "RATIFIED_BY": "human:operator",
    "TOPIC": "gate-a-existing",
}


def _yaml(**overrides: Any) -> str:
    return emit_yaml_record({**CORE, **overrides}, None, None)


def _store(tmp_path: Path, name: str = f"{TOKEN}.md") -> Path:
    root = tmp_path / ".hestai" / "decisions" / "topics"
    root.mkdir(parents=True)
    path = root / name
    path.write_text(_yaml(), encoding="utf-8")
    return path


def _has(errors: list[str], *needles: str) -> bool:
    return any(all(n in e for n in needles) for e in errors)


def test_keyword_is_keyword_only_and_defaults_false() -> None:
    param = inspect.signature(validate_record_content).parameters["existing_record"]
    assert param.kind is inspect.Parameter.KEYWORD_ONLY
    assert param.default is False


def test_default_still_refuses_an_existing_token(tmp_path: Path) -> None:
    _store(tmp_path)
    result = validate_record_content(tmp_path, _yaml())
    assert not result.valid
    assert _has(result.errors, TOKEN, "already exists")


def test_default_still_refuses_an_unparseable_file_of_that_name(tmp_path: Path) -> None:
    path = _store(tmp_path)
    path.write_text("---\ntype: DECISION_RECORD\n---\n", encoding="utf-8")
    result = validate_record_content(tmp_path, _yaml())
    assert not result.valid
    assert _has(result.errors, "already exists", path.name)


def test_existing_record_admits_a_rewrite_of_the_existing_token(tmp_path: Path) -> None:
    _store(tmp_path)
    result = validate_record_content(tmp_path, _yaml(), existing_record=True)
    assert result.valid, result.errors
    assert result.canonical_content == _yaml()


def test_existing_record_skips_the_file_exists_sibling_too(tmp_path: Path) -> None:
    path = _store(tmp_path)
    path.write_text("---\ntype: DECISION_RECORD\n---\n", encoding="utf-8")
    result = validate_record_content(tmp_path, _yaml(), existing_record=True)
    assert result.valid, result.errors


@pytest.mark.parametrize(
    ("overrides", "needle"),
    [
        ({"STATUS": "DONE"}, "STATUS"),
        ({"TIER": "HIGH"}, "TIER"),
        ({"DECISION": " ".join(["word"] * 41)}, "DECISION"),
        ({"AUTHORED_AT": "2026-10-30T00:00:00Z"}, "AUTHORED_AT"),
        ({"ISSUE_REF": "not an issue ref"}, "ISSUE_REF"),
        ({"SUPERSEDED_BY": "HO-NOT-THERE-20260101", "STATUS": "SUPERSEDED"}, "not found"),
    ],
)
def test_existing_record_runs_every_other_check(
    tmp_path: Path, overrides: dict[str, str], needle: str
) -> None:
    _store(tmp_path)
    result = validate_record_content(tmp_path, _yaml(**overrides), existing_record=True)
    assert not result.valid
    assert _has(result.errors, needle), result.errors


def test_existing_record_still_rejects_a_reader_rejected_record(tmp_path: Path) -> None:
    _store(tmp_path)
    bad = _yaml().replace('tier: "TACTICAL"', "tier: TACTICAL")
    result = validate_record_content(tmp_path, bad, existing_record=True)
    assert not result.valid
    assert _has(result.errors, "unquoted_value")


def test_existing_record_does_not_relax_the_octave_branch(tmp_path: Path) -> None:
    root = tmp_path / ".hestai" / "decisions"
    root.mkdir(parents=True)
    octave = (
        "===DECISION_RECORD===\nMETA:\n  TYPE::DECISION_RECORD\n"
        f'  VERSION::"1.0"\n  TOKEN::{TOKEN}\n  STATUS::RATIFIED\n  TIER::STRATEGIC\n'
        '  AUTHORED_AT::"2026-10-31T00:00:00Z"\n  DECISION::"d"\n  BECAUSE::"b"\n'
        '  RATIFIED_BY::"human:operator"\n===END===\n'
    )
    (root / f"{TOKEN}.oct.md").write_text(octave, encoding="utf-8")
    result = validate_record_content(tmp_path, octave, existing_record=True)
    assert not result.valid
    assert _has(result.errors, TOKEN, "already exists")
