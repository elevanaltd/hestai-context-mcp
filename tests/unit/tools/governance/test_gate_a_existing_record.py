"""Gate A ``existing_record`` for the append_ruling path (#203 S2).

``validate_record_content(..., existing_record=<path>)`` lets a REWRITE of the YAML
record at ``<path>`` pass Gate A. It relaxes ONLY the §4.1 #4 uniqueness check, and only
as far as that one file: the rewrite is accepted when the sole store match for the TOKEN
is ``<path>`` itself. Any other match (an ``.oct.md`` twin, a second ``.md``, any other
same-name file) still raises the duplicate error (HC design fix, PR #234 round 1). Every
other check still runs. The keyword defaults to None, so content mode keeps refusing an
existing TOKEN; that it is reachable only from the append path is pinned in
``test_submit_governance_append_ruling.py``.
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
OCTAVE_TWIN = (
    "===DECISION_RECORD===\nMETA:\n  TYPE::DECISION_RECORD\n"
    f'  VERSION::"1.0"\n  TOKEN::{TOKEN}\n  STATUS::RATIFIED\n  TIER::STRATEGIC\n'
    '  AUTHORED_AT::"2026-10-31T00:00:00Z"\n  DECISION::"d"\n  BECAUSE::"b"\n'
    '  RATIFIED_BY::"human:operator"\n===END===\n'
)


def _yaml(**overrides: Any) -> str:
    return emit_yaml_record({**CORE, **overrides}, None, None)


def _store(tmp_path: Path, rel: str = f"topics/{TOKEN}.md", text: str | None = None) -> Path:
    path = tmp_path / ".hestai" / "decisions" / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_yaml() if text is None else text, encoding="utf-8")
    return path


def _has(errors: list[str], *needles: str) -> bool:
    return any(all(n in e for n in needles) for e in errors)


def test_keyword_is_keyword_only_and_defaults_none() -> None:
    param = inspect.signature(validate_record_content).parameters["existing_record"]
    assert param.kind is inspect.Parameter.KEYWORD_ONLY
    assert param.default is None


def test_default_still_refuses_an_existing_token(tmp_path: Path) -> None:
    _store(tmp_path)
    result = validate_record_content(tmp_path, _yaml())
    assert not result.valid
    assert _has(result.errors, TOKEN, "already exists")


def test_default_still_refuses_an_unparseable_file_of_that_name(tmp_path: Path) -> None:
    path = _store(tmp_path, text="---\ntype: DECISION_RECORD\n---\n")
    result = validate_record_content(tmp_path, _yaml())
    assert not result.valid
    assert _has(result.errors, "already exists", path.name)


def test_existing_record_admits_a_rewrite_of_that_one_file(tmp_path: Path) -> None:
    path = _store(tmp_path)
    result = validate_record_content(tmp_path, _yaml(), existing_record=path)
    assert result.valid, result.errors
    assert result.canonical_content == _yaml()


def test_existing_record_admits_a_rewrite_at_a_drifted_file_name(tmp_path: Path) -> None:
    path = _store(tmp_path, rel="topics/odd-name.md")
    result = validate_record_content(tmp_path, _yaml(), existing_record=path)
    assert result.valid, result.errors


def test_existing_record_admits_an_unreadable_file_at_that_path(tmp_path: Path) -> None:
    path = _store(tmp_path, text="---\ntype: DECISION_RECORD\n---\n")
    result = validate_record_content(tmp_path, _yaml(), existing_record=path)
    assert result.valid, result.errors


def test_an_octave_twin_still_raises_the_duplicate_error(tmp_path: Path) -> None:
    path = _store(tmp_path)
    twin = _store(tmp_path, rel=f"{TOKEN}.oct.md", text=OCTAVE_TWIN)
    result = validate_record_content(tmp_path, _yaml(), existing_record=path)
    assert not result.valid
    assert _has(result.errors, TOKEN, "already exists", twin.name)


def test_an_octave_twin_under_another_name_still_raises(tmp_path: Path) -> None:
    path = _store(tmp_path)
    twin = _store(tmp_path, rel="legacy/elsewhere.oct.md", text=OCTAVE_TWIN)
    result = validate_record_content(tmp_path, _yaml(), existing_record=path)
    assert not result.valid
    assert _has(result.errors, "already exists", twin.name)


def test_a_second_yaml_record_with_the_token_still_raises(tmp_path: Path) -> None:
    path = _store(tmp_path)
    copy = _store(tmp_path, rel="copy.md")
    result = validate_record_content(tmp_path, _yaml(), existing_record=path)
    assert not result.valid
    assert _has(result.errors, "already exists", copy.name)


def test_a_same_name_file_elsewhere_still_raises(tmp_path: Path) -> None:
    path = _store(tmp_path, rel="topics/odd-name.md")
    stray = _store(tmp_path, rel=f"{TOKEN}.md", text="---\ntype: DECISION_RECORD\n---\n")
    result = validate_record_content(tmp_path, _yaml(), existing_record=path)
    assert not result.valid
    assert _has(result.errors, "already exists", stray.name)


def test_existing_record_must_name_a_yaml_md_path(tmp_path: Path) -> None:
    twin = _store(tmp_path, rel=f"{TOKEN}.oct.md", text=OCTAVE_TWIN)
    result = validate_record_content(tmp_path, _yaml(), existing_record=twin)
    assert not result.valid
    assert _has(result.errors, "existing_record", ".md")


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
    path = _store(tmp_path)
    result = validate_record_content(tmp_path, _yaml(**overrides), existing_record=path)
    assert not result.valid
    assert _has(result.errors, needle), result.errors


def test_existing_record_still_rejects_a_reader_rejected_record(tmp_path: Path) -> None:
    path = _store(tmp_path)
    bad = _yaml().replace('tier: "TACTICAL"', "tier: TACTICAL")
    result = validate_record_content(tmp_path, bad, existing_record=path)
    assert not result.valid
    assert _has(result.errors, "unquoted_value")


def test_existing_record_does_not_relax_the_octave_branch(tmp_path: Path) -> None:
    twin = _store(tmp_path, rel=f"{TOKEN}.oct.md", text=OCTAVE_TWIN)
    result = validate_record_content(tmp_path, OCTAVE_TWIN, existing_record=twin)
    assert not result.valid
    assert _has(result.errors, TOKEN, "already exists")
