"""EPIC4 PR-5 phase 1C (RED): submit_governance CONTENT mode accepts a quoted-YAML record.

The record arrives in the existing ``octave_content`` parameter (the tool signature is
unchanged). The Gate A syntax seam (``type_checker.validate_record_content``) decides
the syntax; a YAML record is written to ``.hestai/decisions/{token}.md``, never
reaches the OCTAVE Gate B validator, and a rejected record returns the reader's
line/construct as structured ``validation_errors``. PROSE mode stays OCTAVE and never
touches the YAML seam.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from hestai_context_mcp.core import agent_readable_governance_parser as _parser
from hestai_context_mcp.core.agent_readable_governance_parser import (
    emit_yaml_record,
)
from hestai_context_mcp.tools import submit_governance as sg

from .governance._agr_fixtures import snapshot_tree, write_record, yaml_record_text

pytestmark = pytest.mark.unit


def canonicalize_yaml_record(raw: str | bytes) -> str:
    """Late-bound so a missing implementation fails the test, not collection of the suite."""
    return _parser.canonicalize_yaml_record(raw)  # type: ignore[attr-defined,no-any-return]


TOKEN = "HO-ESCAPES-20261029"
OCTAVE_TOKEN = "HO-CONTEXT-MCP-NEWREC-20260601"

CORE = {
    "TYPE": "DECISION_RECORD",
    "VERSION": "1.4",
    "TOKEN": TOKEN,
    "STATUS": "RATIFIED",
    "TIER": "STRATEGIC",
    "AUTHORED_AT": "2026-10-29T00:00:00Z",
    "DECISION": "A binding decision sentence.",
    "BECAUSE": "A one-sentence rationale.",
    "RATIFIED_BY": "human:operator",
}

OCTAVE_RECORD = f"""\
===DECISION_RECORD===
META:
  TYPE::DECISION_RECORD
  VERSION::"1.0"
  TOKEN::{OCTAVE_TOKEN}
  STATUS::PROPOSED
  TIER::OPERATIONAL
  DECISION::"d"
  BECAUSE::"b"
  AUTHORED_AT::"2026-06-01T00:00:00Z"
===END===
"""


def _submit(tmp_path: Path, content: str, **kwargs: Any) -> dict[str, Any]:
    return asyncio.run(
        sg.submit_governance(
            working_dir=str(tmp_path),
            octave_content=content,
            dry_run=kwargs.pop("dry_run", True),
            review=False,
            **kwargs,
        )
    )


@pytest.fixture()
def no_gate_b(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Gate B (the OCTAVE validator) must never VALIDATE a YAML record (returns ``.validate``)."""
    validator = MagicMock()
    validator.validate.side_effect = AssertionError("Gate B ran on a YAML record")
    monkeypatch.setattr(sg, "get_octave_validator", lambda: validator)
    return validator.validate  # type: ignore[no-any-return]


def test_valid_yaml_record_is_accepted_and_targets_dot_md(
    tmp_path: Path, no_gate_b: MagicMock
) -> None:
    before = snapshot_tree(tmp_path)
    result = _submit(tmp_path, emit_yaml_record(CORE, None, None))
    assert result["success"] is True, result["validation_errors"]
    assert result["token"] == TOKEN
    assert result["card_type"] == "DECISION_RECORD"
    assert result["target_path"] == f".hestai/decisions/{TOKEN}.md"
    assert result["validation_errors"] == []
    assert result["dry_run"] is True
    no_gate_b.assert_not_called()
    assert snapshot_tree(tmp_path) == before  # dry_run writes nothing


def test_yaml_result_has_the_same_i4_keys_as_an_octave_result(tmp_path: Path) -> None:
    yaml_result = _submit(tmp_path, emit_yaml_record(CORE, None, None))
    octave_result = _submit(tmp_path, OCTAVE_RECORD)
    assert octave_result["success"] is True
    assert yaml_result["success"] is True
    assert set(yaml_result) == set(octave_result)
    # Gate B is skipped for YAML but its fields stay in the result shape.
    assert "octave_validation" in yaml_result
    assert "real_validation_available" in yaml_result


def test_octave_content_still_targets_dot_oct_md(tmp_path: Path) -> None:
    result = _submit(tmp_path, OCTAVE_RECORD)
    assert result["success"] is True
    assert result["target_path"] == f".hestai/decisions/{OCTAVE_TOKEN}.oct.md"


@pytest.mark.parametrize(
    ("text", "construct"),
    [
        (yaml_record_text(token=TOKEN, decision_literal="unquoted words"), "unquoted_value"),
        (yaml_record_text(token=TOKEN, extra_lines=['scope: "a"', 'scope: "b"']), "duplicate_key"),
        (yaml_record_text(token=TOKEN, decision_literal='"bad \\q"'), "bad_escape"),
    ],
)
def test_invalid_yaml_is_rejected_with_line_and_construct(
    tmp_path: Path, no_gate_b: MagicMock, text: str, construct: str
) -> None:
    result = _submit(tmp_path, text)
    assert result["success"] is False
    assert result["target_path"] is None
    assert result["pr_url"] is None
    assert any("line" in e and construct in e for e in result["validation_errors"]), result
    no_gate_b.assert_not_called()


def test_gate_a_invariants_apply_to_a_yaml_record(tmp_path: Path) -> None:
    result = _submit(tmp_path, emit_yaml_record({**CORE, "STATUS": "DONE"}, None, None))
    assert result["success"] is False
    assert any("STATUS 'DONE'" in e for e in result["validation_errors"])


def test_yaml_token_already_an_octave_record_is_rejected(tmp_path: Path) -> None:
    write_record(tmp_path, token=TOKEN, authored_at="2026-10-29T00:00:00Z")
    result = _submit(tmp_path, emit_yaml_record(CORE, None, None))
    assert result["success"] is False
    assert any("already exists" in e for e in result["validation_errors"])


def test_a_rejected_yaml_record_never_reaches_the_linker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    linker = MagicMock(side_effect=AssertionError("linker ran"))
    monkeypatch.setattr(sg, "run_linker", linker)
    result = _submit(
        tmp_path, yaml_record_text(token=TOKEN, decision_literal="unquoted words"), dry_run=False
    )
    assert result["success"] is False
    assert any("line 8" in e and "unquoted_value" in e for e in result["validation_errors"])
    linker.assert_not_called()


def _noncanonical() -> str:
    return yaml_record_text(
        token=TOKEN,
        authored_at="2026-10-29T00:00:00Z",
        scope="repo",
        body="# Body\r\nverbatim\r\n",
        eol="\r\n",
    )


def _stub_linker(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    linker = MagicMock(
        return_value={
            "token": TOKEN,
            "card_type": "DECISION_RECORD",
            "target_path": f".hestai/decisions/{TOKEN}.md",
            "branch": "b",
            "pr_url": "https://github.com/elevanaltd/hestai-context-mcp/pull/1",
            "error": None,
        }
    )
    monkeypatch.setattr(sg, "run_linker", linker)
    return linker


def test_the_linker_is_handed_the_canonical_bytes_not_the_submitted_ones(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ruling (C): parse, then write the canonical front matter + the verbatim body."""
    submitted = _noncanonical()
    linker = _stub_linker(monkeypatch)
    result = _submit(tmp_path, submitted, dry_run=False)
    assert result["success"] is True
    kwargs = linker.call_args.kwargs
    canonical = canonicalize_yaml_record(submitted)
    assert canonical != submitted
    assert kwargs["octave_content"] == canonical
    assert kwargs["octave_content"].endswith("---\n# Body\r\nverbatim\r\n")
    assert kwargs["validation"].syntax == "yaml"
    assert kwargs["validation"].canonical_content == canonical
    assert kwargs["validation"].target_path == tmp_path / ".hestai" / "decisions" / f"{TOKEN}.md"


def test_octave_content_is_handed_to_the_linker_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    linker = _stub_linker(monkeypatch)
    _submit(tmp_path, OCTAVE_RECORD, dry_run=False)
    assert linker.call_args.kwargs["octave_content"] == OCTAVE_RECORD


def test_stage5_review_runs_unchanged_on_the_yaml_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Decided: Stage-5 is not skipped for YAML; it reviews the text that was written."""
    _stub_linker(monkeypatch)
    review = AsyncMock(return_value={"posted": False})
    monkeypatch.setattr(sg, "_run_semantic_review", review)
    submitted = _noncanonical()
    result = asyncio.run(
        sg.submit_governance(
            working_dir=str(tmp_path), octave_content=submitted, dry_run=False, review=True
        )
    )
    assert result["success"] is True
    review.assert_awaited_once()
    assert review.await_args.args[0] == canonicalize_yaml_record(submitted)


# --- PIN (passes today): prose mode is unchanged and still OCTAVE -----------------


def test_prose_mode_still_uses_the_octave_pipeline_and_never_the_yaml_seam(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pipeline = AsyncMock(return_value={"success": True, "octave": OCTAVE_RECORD})
    monkeypatch.setattr(sg, "run_intake_to_pr", pipeline)
    seam = MagicMock(side_effect=AssertionError("prose mode touched the YAML seam"))
    monkeypatch.setattr(sg, "validate_record_content", seam)
    result = asyncio.run(
        sg.submit_governance(working_dir=str(tmp_path), prose_input="decide x", review=False)
    )
    assert result["success"] is True
    pipeline.assert_awaited_once()
    seam.assert_not_called()


def test_a_yaml_validation_without_canonical_bytes_is_a_structured_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Guard, not assert: a validator that cannot supply canonical bytes must not crash the tool."""
    from hestai_context_mcp.tools.governance.type_checker import ValidationResult

    broken = ValidationResult(
        valid=True,
        token=TOKEN,
        card_type="DECISION_RECORD",
        target_path=tmp_path / ".hestai" / "decisions" / f"{TOKEN}.md",
        syntax="octave",
        canonical_content=None,
    )
    monkeypatch.setattr(sg, "validate_record_content", lambda wd, content: broken)
    linker = MagicMock(side_effect=AssertionError("linker ran"))
    monkeypatch.setattr(sg, "run_linker", linker)
    result = _submit(tmp_path, emit_yaml_record(CORE, None, None), dry_run=False)
    assert result["success"] is False
    assert any("canonical" in e for e in result["validation_errors"])
    linker.assert_not_called()


@pytest.mark.parametrize("available", [True, False])
def test_yaml_reports_the_actual_octave_validator_availability(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, available: bool
) -> None:
    """Gate B is skipped for YAML, but the availability signal is the real one (F3)."""
    from hestai_context_mcp.ports.octave_validator import UnavailableOctaveValidator

    validator = MagicMock() if available else UnavailableOctaveValidator()
    if available:
        validator.validate.side_effect = AssertionError("Gate B ran on a YAML record")
    monkeypatch.setattr(sg, "get_octave_validator", lambda: validator)
    result = _submit(tmp_path, emit_yaml_record(CORE, None, None))
    assert result["success"] is True
    assert result["real_validation_available"] is available
    assert result["octave_validation"] is None
