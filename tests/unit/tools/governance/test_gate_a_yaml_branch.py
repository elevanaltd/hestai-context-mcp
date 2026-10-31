"""EPIC4 PR-5 phase 1B: the Gate A quoted-YAML branch and the ONE syntax seam.

``validate_record_content`` classifies the submitted content once
(``classify_record_text``) and dispatches: a YAML record is judged by the YAML
branch (reader rejection surfaced as structured errors, the syntax-independent
§4.1 invariants, TOKEN uniqueness across ``.oct.md`` and ``.md``, target
``{token}.md``); everything else goes to the unchanged OCTAVE branch (target
``{token}.oct.md``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from hestai_context_mcp.core.agent_readable_governance_parser import emit_yaml_record
from hestai_context_mcp.tools.governance.type_checker import (
    validate_octave_content,
    validate_record_content,
)

from ._agr_fixtures import decisions_dir, snapshot_tree, write_record, yaml_record_text

pytestmark = pytest.mark.unit

TOKEN = "HO-ESCAPES-20261029"
OLD_A = "HO-CUBIC-A-20260101"
OLD_T = "HO-CUBIC-T-20260301"

CORE: dict[str, str] = {
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


def _yaml(**overrides: Any) -> str:
    fields = {**CORE, **{k: v for k, v in overrides.items() if v is not None}}
    for key, value in overrides.items():
        if value is None:
            fields.pop(key, None)
    return emit_yaml_record(fields, None, None)


def _octave(token: str = TOKEN) -> str:
    return (
        "===DECISION_RECORD===\nMETA:\n  TYPE::DECISION_RECORD\n"
        f'  VERSION::"1.0"\n  TOKEN::{token}\n  STATUS::RATIFIED\n  TIER::STRATEGIC\n'
        '  AUTHORED_AT::"2026-10-29T00:00:00Z"\n  DECISION::"d"\n  BECAUSE::"b"\n'
        '  RATIFIED_BY::"human:operator"\n===END===\n'
    )


def _errors(tmp_path: Path, content: str) -> list[str]:
    result = validate_record_content(tmp_path, content)
    assert not result.valid, result
    return result.errors


def _has(errors: list[str], *needles: str) -> bool:
    return any(all(n in e for n in needles) for e in errors)


# --- the seam: dispatch and target path -------------------------------------


def test_valid_yaml_record_targets_dot_md(tmp_path: Path) -> None:
    result = validate_record_content(tmp_path, _yaml())
    assert result.valid, result.errors
    assert result.token == TOKEN
    assert result.card_type == "DECISION_RECORD"
    assert result.syntax == "yaml"
    assert result.target_path == tmp_path / ".hestai" / "decisions" / f"{TOKEN}.md"
    assert result.warnings == []


def test_octave_content_through_the_seam_equals_the_octave_gate(tmp_path: Path) -> None:
    content = _octave()
    via_seam = validate_record_content(tmp_path, content)
    direct = validate_octave_content(tmp_path, content)
    assert via_seam == direct
    assert via_seam.valid
    assert via_seam.syntax == "octave"
    assert via_seam.target_path == tmp_path / ".hestai" / "decisions" / f"{TOKEN}.oct.md"


def test_octave_gate_itself_still_refuses_yaml_content(tmp_path: Path) -> None:
    result = validate_octave_content(tmp_path, _yaml())
    assert not result.valid
    assert _has(result.errors, "No OCTAVE sentinel")


def test_gate_a_writes_nothing(tmp_path: Path) -> None:
    before = snapshot_tree(tmp_path)
    assert validate_record_content(tmp_path, _yaml()).valid
    assert snapshot_tree(tmp_path) == before


# --- the PR-4 reader's rejection surfaces as structured Gate A errors --------


@pytest.mark.parametrize(
    ("text", "line", "construct"),
    [
        (yaml_record_text(token=TOKEN, decision_literal="unquoted words"), 8, "unquoted_value"),
        (
            yaml_record_text(token=TOKEN, extra_lines=['scope: "a"', 'scope: "b"']),
            11,
            "duplicate_key",
        ),
        (yaml_record_text(token=TOKEN, decision_literal='"bad \\q escape"'), 8, "bad_escape"),
        (yaml_record_text(token=TOKEN, extra_lines=['  indented: "x"']), 10, "indentation"),
        (
            yaml_record_text(
                token=TOKEN, extra_lines=["current:", '  R1: "r"', '  status: "VOID"']
            ),
            12,
            "reserved_key_in_block",
        ),
        (
            '---\ntype: "DECISION_RECORD"\ntoken: "HO-ESCAPES-20261029"\n',
            3,
            "missing_closing_fence",
        ),
    ],
)
def test_reader_rejection_is_surfaced_with_line_and_construct(
    tmp_path: Path, text: str, line: int, construct: str
) -> None:
    result = validate_record_content(tmp_path, text)
    assert not result.valid
    assert result.target_path is None
    assert result.reject == {"line": line, "construct": construct}
    assert _has(result.errors, f"line {line}", construct)


def test_non_decision_record_yaml_is_rejected(tmp_path: Path) -> None:
    errors = _errors(tmp_path, _yaml().replace('"DECISION_RECORD"', '"BUILD_PLAN"', 1))
    assert _has(errors, "DECISION_RECORD")


def test_yaml_without_a_type_line_is_rejected(tmp_path: Path) -> None:
    text = "".join(ln for ln in _yaml().splitlines(True) if not ln.startswith("type:"))
    assert _has(_errors(tmp_path, text), "type")


# --- required fields and enums, same rules as the OCTAVE branch ---------------


@pytest.mark.parametrize(
    "missing", ["VERSION", "STATUS", "TIER", "DECISION", "BECAUSE", "AUTHORED_AT"]
)
def test_missing_required_field_is_named(tmp_path: Path, missing: str) -> None:
    text = "".join(
        ln for ln in _yaml().splitlines(True) if not ln.startswith(f"{missing.lower()}:")
    )
    assert _has(_errors(tmp_path, text), f"Required field '{missing}'")


def test_missing_token_is_rejected(tmp_path: Path) -> None:
    text = "".join(ln for ln in _yaml().splitlines(True) if not ln.startswith("token:"))
    assert _has(_errors(tmp_path, text), "token")


def test_invalid_token_format_is_rejected(tmp_path: Path) -> None:
    assert _has(_errors(tmp_path, _yaml().replace(TOKEN, "not-a-token")), "TOKEN", "format")


def test_status_enum(tmp_path: Path) -> None:
    assert _has(_errors(tmp_path, _yaml(STATUS="DONE")), "STATUS 'DONE'")
    assert validate_record_content(tmp_path, _yaml(STATUS="PROPOSED")).valid


def test_tier_enum(tmp_path: Path) -> None:
    assert _has(_errors(tmp_path, _yaml(TIER="HUGE")), "TIER 'HUGE'")


def test_version_shape(tmp_path: Path) -> None:
    assert _has(_errors(tmp_path, _yaml(VERSION="1.0.0")), "VERSION '1.0.0'")


def test_reserved_names_are_rejected(tmp_path: Path) -> None:
    errors = _errors(tmp_path, _yaml(DEPENDS_ON="x"))
    assert _has(errors, "Reserved field 'DEPENDS_ON'")


# --- syntax-independent §4.1 invariants --------------------------------------


def test_token_date_must_equal_authored_at_utc_date(tmp_path: Path) -> None:
    errors = _errors(tmp_path, _yaml(AUTHORED_AT="2026-10-30T00:00:00Z"))
    assert _has(errors, "TOKEN date suffix", "20261029")
    assert _has(_errors(tmp_path, _yaml(AUTHORED_AT="2026-10-29")), "full ISO-8601 timestamp")
    assert _has(_errors(tmp_path, _yaml(AUTHORED_AT="yesterday")), "not a parseable")
    assert validate_record_content(tmp_path, _yaml(AUTHORED_AT="2026-10-28T23:30:00-02:00")).valid


def test_ratification_provenance_is_a_warning_not_an_error(tmp_path: Path) -> None:
    result = validate_record_content(tmp_path, _yaml(RATIFIED_BY=None))
    assert result.valid
    assert _has(result.warnings, "RATIFIED_BY is absent", "#12")
    assert (
        validate_record_content(tmp_path, _yaml(RATIFIED_BY=None, STATUS="PROPOSED")).warnings == []
    )


@pytest.mark.parametrize(
    "ref",
    ["repo:hestai-context-mcp#220", "https://github.com/elevanaltd/hestai-context-mcp/issues/220"],
)
def test_issue_ref_valid_shapes(tmp_path: Path, ref: str) -> None:
    assert validate_record_content(tmp_path, _yaml(ISSUE_REF=ref)).valid


@pytest.mark.parametrize("ref", ["#220", "repo:x", "https://example.com/1", "see issue 220", ""])
def test_issue_ref_bad_shape(tmp_path: Path, ref: str) -> None:
    assert _has(_errors(tmp_path, _yaml(ISSUE_REF=ref)), "ISSUE_REF", "valid shape")


def test_human_adr_ref_token_form_and_path_form(tmp_path: Path) -> None:
    assert validate_record_content(tmp_path, _yaml(HUMAN_ADR_REF=OLD_A)).valid
    assert _has(_errors(tmp_path, _yaml(HUMAN_ADR_REF="docs/missing.md")), "HUMAN_ADR_REF")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "adr.md").write_text("x", encoding="utf-8")
    assert validate_record_content(tmp_path, _yaml(HUMAN_ADR_REF="docs/adr.md")).valid
    assert _has(_errors(tmp_path, _yaml(HUMAN_ADR_REF="../../etc/passwd")), "HUMAN_ADR_REF")


def test_reasoning_density(tmp_path: Path) -> None:
    long_text = " ".join(["word"] * 41)
    assert _has(_errors(tmp_path, _yaml(DECISION=long_text)), "DECISION value is 41 words")
    assert _has(_errors(tmp_path, _yaml(BECAUSE="a\nb")), "BECAUSE", "embedded newline")
    assert validate_record_content(tmp_path, _yaml(DECISION=" ".join(["word"] * 40))).valid


def test_superseded_by_iff_status_superseded(tmp_path: Path) -> None:
    write_record(tmp_path, token=OLD_A, authored_at="2026-01-01T00:00:00Z")
    assert _has(_errors(tmp_path, _yaml(STATUS="SUPERSEDED")), "SUPERSEDED_BY is absent")
    assert _has(_errors(tmp_path, _yaml(SUPERSEDED_BY=OLD_A)), "SUPERSEDED_BY is present")
    assert validate_record_content(tmp_path, _yaml(STATUS="SUPERSEDED", SUPERSEDED_BY=OLD_A)).valid


def test_superseded_by_target_must_exist(tmp_path: Path) -> None:
    errors = _errors(tmp_path, _yaml(STATUS="SUPERSEDED", SUPERSEDED_BY=OLD_T))
    assert _has(errors, f"SUPERSEDED_BY target '{OLD_T}' not found")


def test_supersedes_targets_must_exist(tmp_path: Path) -> None:
    write_record(tmp_path, token=OLD_A, authored_at="2026-01-01T00:00:00Z")
    content = emit_yaml_record(CORE, None, [OLD_A, OLD_T])
    errors = _errors(tmp_path, content)
    assert _has(errors, f"supersedes target '{OLD_T}' not found")
    assert not _has(errors, f"supersedes target '{OLD_A}'")
    ok = emit_yaml_record(CORE, None, [OLD_A])
    assert validate_record_content(tmp_path, ok).valid


# --- TOKEN uniqueness across both syntaxes (criterion 1) ----------------------


def test_yaml_token_already_an_octave_record_is_rejected(tmp_path: Path) -> None:
    write_record(tmp_path, token=TOKEN, authored_at="2026-10-29T00:00:00Z")
    assert _has(_errors(tmp_path, _yaml()), "already exists")


def test_yaml_token_already_a_yaml_record_is_rejected(tmp_path: Path) -> None:
    (decisions_dir(tmp_path) / f"{TOKEN}.md").write_text(_yaml(), encoding="utf-8")
    assert _has(_errors(tmp_path, _yaml()), "already exists")


def test_octave_token_already_a_yaml_record_is_rejected_through_the_seam(tmp_path: Path) -> None:
    (decisions_dir(tmp_path) / f"{TOKEN}.md").write_text(_yaml(), encoding="utf-8")
    assert _has(_errors(tmp_path, _octave()), "already exists")


def test_an_unparseable_file_at_the_target_path_is_never_overwritten(tmp_path: Path) -> None:
    for name in (f"{TOKEN}.md", f"{TOKEN}.oct.md"):
        stray = decisions_dir(tmp_path) / name
        stray.write_text("---\nnot a record\n", encoding="utf-8")
        assert _has(_errors(tmp_path, _yaml()), "already exists", name)
        stray.unlink()


def test_the_same_token_under_a_subgroup_still_collides(tmp_path: Path) -> None:
    group = decisions_dir(tmp_path) / "rfc-arch"
    group.mkdir()
    (group / f"{TOKEN}.oct.md").write_text("junk", encoding="utf-8")
    assert _has(_errors(tmp_path, _yaml()), "already exists")
