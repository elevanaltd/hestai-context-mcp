"""G3 strict pairing, `.oct.md` side: a `.oct.md` file is a record only as OCTAVE.

YAML front matter inside `<token>.oct.md` is out of spec (ADR §1.1, ruling (a)): it is
not resolved, not listed, not indexed, and does not declare a token.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hestai_context_mcp.tools.governance import agr_read, manifest
from hestai_context_mcp.tools.governance.lexer import lookup_token_deterministic
from hestai_context_mcp.tools.list_decisions import list_decisions
from hestai_context_mcp.tools.lookup_decision import lookup_decision
from hestai_context_mcp.tools.trace_supersedure import trace_supersedure

from ._agr_fixtures import decisions_dir, write_record, write_yaml_record

pytestmark = pytest.mark.unit

T = "HO-OCTONLY-T-20261029"
U = "HO-OCTONLY-U-20261030"


def _yaml_in_oct(tmp_path: Path, token: str = T) -> Path:
    return write_yaml_record(tmp_path, token=token, filename=f"{token}.oct.md")


def test_yaml_front_matter_in_oct_md_is_not_resolved(tmp_path: Path) -> None:
    _yaml_in_oct(tmp_path)
    assert agr_read.discover_record(tmp_path, T) is None
    assert lookup_decision(str(tmp_path), T)["error"]["code"] == "TOKEN_NOT_FOUND"
    assert trace_supersedure(str(tmp_path), T)["error"]["code"] == "TOKEN_NOT_FOUND"


def test_yaml_front_matter_in_drifted_oct_md_is_not_resolved(tmp_path: Path) -> None:
    write_yaml_record(tmp_path, token=T, filename="renamed.oct.md")
    assert agr_read.discover_record(tmp_path, T) is None


def test_yaml_front_matter_in_oct_md_is_not_listed_or_skipped(tmp_path: Path) -> None:
    path = _yaml_in_oct(tmp_path)
    assert path not in agr_read.iter_record_paths(tmp_path)
    result = list_decisions(str(tmp_path))
    assert result["records"] == [] and result["skipped"] == []


def test_yaml_in_oct_md_is_not_indexed_and_does_not_declare(tmp_path: Path) -> None:
    _yaml_in_oct(tmp_path)
    assert f"| {T} |" not in manifest.build_manifest(tmp_path)
    assert lookup_token_deterministic(tmp_path, T) is False


def test_yaml_in_oct_md_derives_no_supersedes_edge(tmp_path: Path) -> None:
    write_record(tmp_path, token=U)
    write_yaml_record(tmp_path, token=T, supersedes=U, filename=f"{T}.oct.md")
    assert agr_read.derive_supersession(tmp_path) == {}
    assert lookup_decision(str(tmp_path), U)["record"]["status"] == "RATIFIED"


def test_the_same_yaml_as_dot_md_still_works(tmp_path: Path) -> None:
    path = write_yaml_record(tmp_path, token=T)
    assert agr_read.discover_record(tmp_path, T) == path
    assert lookup_token_deterministic(tmp_path, T) is True
    assert f"| {T} |" in manifest.build_manifest(tmp_path)


def test_octave_oct_md_records_are_unaffected(tmp_path: Path) -> None:
    path = write_record(tmp_path, token=T)
    write_record(tmp_path, token=U, group="g")
    assert agr_read.discover_record(tmp_path, T) == path
    assert lookup_decision(str(tmp_path), T)["ok"] is True
    assert sorted(r["token"] for r in list_decisions(str(tmp_path))["records"]) == [T, U]
    assert lookup_token_deterministic(tmp_path, U) is True
    assert f"| {T} |" in manifest.build_manifest(tmp_path)


def test_non_decision_octave_oct_md_files_are_still_silently_out_of_scope(tmp_path: Path) -> None:
    (decisions_dir(tmp_path) / "plan.oct.md").write_text("===BUILD_PLAN===\n===END===\n", "utf-8")
    result = list_decisions(str(tmp_path))
    assert result["records"] == [] and result["skipped"] == []
