"""J1: a MANIFEST.md hit for a YAML ``.md`` record is trusted only if the file still parses."""

from __future__ import annotations

from pathlib import Path

import pytest

from hestai_context_mcp.tools.governance import manifest
from hestai_context_mcp.tools.governance.lexer import lookup_token_deterministic

from ._agr_fixtures import decisions_dir, write_record, write_yaml_record, yaml_record_text

pytestmark = pytest.mark.unit

T = "HO-CUBIC-T-20260301"
A = "HO-CUBIC-A-20260101"


def _manifest(tmp_path: Path, token: str, rel: str) -> None:
    path = tmp_path / ".hestai" / "MANIFEST.md"
    path.write_text(f"| TOKEN/ID | path |\n| --- | --- |\n| {token} | {rel} |\n", encoding="utf-8")


def test_stale_manifest_row_for_a_rejected_yaml_record_does_not_satisfy_the_check(
    tmp_path: Path,
) -> None:
    write_yaml_record(tmp_path, token=T)
    _manifest(tmp_path, T, f".hestai/decisions/{T}.md")
    assert lookup_token_deterministic(tmp_path, T) is True  # valid at manifest time
    text = yaml_record_text(token=T).replace('status: "RATIFIED"', "status: RATIFIED")
    (decisions_dir(tmp_path) / f"{T}.md").write_text(text, encoding="utf-8")  # now rejected
    assert lookup_token_deterministic(tmp_path, T) is False


def test_stale_manifest_row_for_a_deleted_yaml_record_does_not_satisfy_the_check(
    tmp_path: Path,
) -> None:
    path = write_yaml_record(tmp_path, token=T)
    _manifest(tmp_path, T, f".hestai/decisions/{T}.md")
    path.unlink()
    assert lookup_token_deterministic(tmp_path, T) is False


def test_valid_yaml_manifest_hit_still_satisfies_the_check(tmp_path: Path) -> None:
    write_yaml_record(tmp_path, token=T)
    manifest.write_manifest(tmp_path)
    assert f"| {T} |" in (tmp_path / ".hestai" / "MANIFEST.md").read_text(encoding="utf-8")
    assert lookup_token_deterministic(tmp_path, T) is True


def test_valid_yaml_hit_in_a_manifest_row_with_a_different_path_falls_back_correctly(
    tmp_path: Path,
) -> None:
    write_yaml_record(tmp_path, token=T)
    _manifest(tmp_path, T, ".hestai/decisions/elsewhere.md")  # row path gone, file still on disk
    assert lookup_token_deterministic(tmp_path, T) is True  # filesystem fallback finds it


def test_octave_manifest_hit_is_unchanged_even_if_the_file_is_gone(tmp_path: Path) -> None:
    path = write_record(tmp_path, token=A)
    _manifest(tmp_path, A, f".hestai/decisions/{A}.oct.md")
    path.unlink()
    assert lookup_token_deterministic(tmp_path, A) is True  # pre-existing behaviour
    assert lookup_token_deterministic(tmp_path, T) is False
