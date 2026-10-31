"""L1: assemble_context honours strict extension/syntax pairing and never leaks surrogates."""

from __future__ import annotations

from pathlib import Path

import pytest

from hestai_context_mcp.tools.governance.lexer import assemble_context

from ._agr_fixtures import decisions_dir, write_record, yaml_record_text

pytestmark = pytest.mark.unit

T = "HO-CUBIC-T-20260301"
A = "HO-CUBIC-A-20260101"


def test_yaml_looking_oct_md_with_invalid_bytes_contributes_nothing(tmp_path: Path) -> None:
    raw = yaml_record_text(token=T, extra_lines=['extra: "PLACEHOLDER"']).encode("utf-8")
    (decisions_dir(tmp_path) / f"{T}.oct.md").write_bytes(
        raw.replace(b"PLACEHOLDER", b"bad\xffbyte")
    )
    out = assemble_context(tmp_path)
    assert out == ""
    assert not any(0xD800 <= ord(c) <= 0xDFFF for c in out)
    out.encode("utf-8")  # must be encodable: no lone surrogates


def test_valid_yaml_in_oct_md_is_also_not_assembled(tmp_path: Path) -> None:
    (decisions_dir(tmp_path) / f"{T}.oct.md").write_text(yaml_record_text(token=T), "utf-8")
    assert assemble_context(tmp_path) == ""


def test_octave_content_is_still_assembled_with_replace_semantics(tmp_path: Path) -> None:
    path = write_record(tmp_path, token=A)
    path.write_bytes(path.read_bytes().replace(b"A binding", b"A bin\xffding"))
    out = assemble_context(tmp_path)
    assert f"TOKEN::{A}" in out and "A bin" + chr(0xFFFD) + "ding" in out
    out.encode("utf-8")


def test_yaml_oct_md_does_not_displace_octave_records(tmp_path: Path) -> None:
    (decisions_dir(tmp_path) / f"{T}.oct.md").write_bytes(b'---\ntype: "X"\nv: "\xff"\n---\n')
    write_record(tmp_path, token=A)
    out = assemble_context(tmp_path)
    assert f"TOKEN::{A}" in out and "�" not in out
