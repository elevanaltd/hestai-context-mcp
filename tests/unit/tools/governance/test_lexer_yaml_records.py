"""PR-4 slice B5: the lexer's token existence checks see YAML records.

``declares_token(content, token)`` keeps its exact name/signature (a contract with
the S2 linker) and is true for a YAML record whose top-level front-matter
``token:`` matches. ``lookup_token_deterministic``'s filesystem fallback also
finds ``<token>.md`` records, with the same answers as for ``<token>.oct.md``.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from hestai_context_mcp.tools.governance import lexer
from hestai_context_mcp.tools.governance.lexer import declares_token, lookup_token_deterministic

from ._agr_fixtures import (
    decisions_dir,
    write_record,
    write_yaml_record,
    yaml_record_text,
)

pytestmark = pytest.mark.unit

TOKEN = "HO-LEXER-YAML-20261029"
LONGER = "HO-LEXER-YAML-EXTRA-20261029"


def test_declares_token_keeps_its_contract_signature() -> None:
    sig = inspect.signature(declares_token)
    assert list(sig.parameters) == ["content", "token"]
    assert sig.return_annotation in (bool, "bool")


def test_declares_token_true_for_yaml_front_matter_token() -> None:
    assert declares_token(yaml_record_text(token=TOKEN), TOKEN) is True


def test_declares_token_false_for_other_tokens_and_prefixes() -> None:
    text = yaml_record_text(token=LONGER)
    assert declares_token(text, TOKEN) is False
    assert declares_token(yaml_record_text(token=TOKEN), LONGER) is False
    assert declares_token(yaml_record_text(token=TOKEN), "HO-LEXER") is False


def _without_real_token(text: str) -> str:
    """Drop the record's own ``token:`` line so a scanner cannot short-circuit on it."""
    stripped = text.replace(f'token: "{TOKEN}"\n', "")
    assert stripped != text
    return stripped


def test_declares_token_ignores_the_markdown_body() -> None:
    body = f'token: "{LONGER}"\nTOKEN::{LONGER}\nID::{LONGER}\n---\ntoken: "{LONGER}"\n'
    text = yaml_record_text(token=TOKEN, body=body)
    assert declares_token(text, TOKEN) is True
    assert declares_token(text, LONGER) is False
    assert declares_token(_without_real_token(text), LONGER) is False


def test_declares_token_ignores_block_lines_of_a_topic_record() -> None:
    lines = [
        "current:",
        f'  token: "{LONGER}"',
        f'  R1: "see {LONGER}"',
        "rulings:",
        "  R1:",
        f'    token: "{LONGER}"',
        f"    TOKEN::{LONGER}",
        f'    rule: "token: \\"{LONGER}\\""',
    ]
    text = yaml_record_text(token=TOKEN, topic="t", extra_lines=lines)
    assert declares_token(text, TOKEN) is True
    assert declares_token(text, LONGER) is False
    assert declares_token(_without_real_token(text), LONGER) is False


@pytest.mark.parametrize(
    "line",
    [
        f"token: {LONGER}",  # unquoted
        f'  token: "{LONGER}"',  # indented
        f'token: "{LONGER}" junk',  # trailing garbage
        f'token: "{LONGER}" # comment',  # trailing comment
        f"TOKEN::{LONGER}",  # OCTAVE spelling inside the fences
        f"ID::{LONGER}",
        f'Token: "{LONGER}"',
    ],
)
def test_declares_token_requires_the_exact_yaml_token_line(line: str) -> None:
    text = f'---\ntype: "DECISION_RECORD"\n{line}\n---\nbody\n'
    assert declares_token(text, LONGER) is False


def test_declares_token_octave_record_ignores_yaml_spelling() -> None:
    octave = f'===DECISION_RECORD===\nMETA:\n  TOKEN::{TOKEN}\n  token: "{LONGER}"\n===END===\n'
    assert declares_token(octave, TOKEN) is True
    assert declares_token(octave, LONGER) is False


def test_declares_token_is_true_for_a_malformed_yaml_record_too() -> None:
    assert declares_token(yaml_record_text(token=TOKEN, extra_lines=["extra: bare"]), TOKEN)


def test_declares_token_octave_behaviour_unchanged() -> None:
    octave = f"===DECISION_RECORD===\nMETA:\n  TOKEN::{TOKEN}\n===END===\n"
    assert declares_token(octave, TOKEN) is True
    assert declares_token(octave, LONGER) is False


# --- filesystem fallback parity --------------------------------------------------


def _corpus(tmp_path: Path, *, yaml: bool, group: str | None = None) -> None:
    writer = write_yaml_record if yaml else write_record
    kwargs = {"group": group} if group else {}
    writer(tmp_path, token=TOKEN, **kwargs)


@pytest.mark.parametrize("group", [None, "topics"])
@pytest.mark.parametrize("probe", [TOKEN, LONGER, "HO-LEXER-YAML", "HO-NOPE-20261029"])
def test_lookup_resolves_md_and_oct_md_identically(
    tmp_path_factory: pytest.TempPathFactory, group: str | None, probe: str
) -> None:
    oct_dir = tmp_path_factory.mktemp("oct")
    yaml_dir = tmp_path_factory.mktemp("yaml")
    _corpus(oct_dir, yaml=False, group=group)
    _corpus(yaml_dir, yaml=True, group=group)
    assert lookup_token_deterministic(yaml_dir, probe) == lookup_token_deterministic(oct_dir, probe)
    assert lookup_token_deterministic(oct_dir, TOKEN) is True  # the oct side is a live control


def test_lookup_finds_a_yaml_record_by_token(tmp_path: Path) -> None:
    write_yaml_record(tmp_path, token=TOKEN)
    assert lookup_token_deterministic(tmp_path, TOKEN) is True
    assert lookup_token_deterministic(tmp_path, LONGER) is False


def test_lookup_finds_yaml_record_with_drifted_filename(tmp_path: Path) -> None:
    write_yaml_record(tmp_path, token=TOKEN, filename="renamed.md")
    assert lookup_token_deterministic(tmp_path, TOKEN) is True


def test_lookup_ignores_non_record_markdown(tmp_path: Path) -> None:
    root = decisions_dir(tmp_path)
    (root / "README.md").write_text(f"TOKEN::{TOKEN}\n", encoding="utf-8")
    (root / "notes.md").write_text(f'---\ntitle: "x"\ntoken: "{TOKEN}"\n---\n', encoding="utf-8")
    (root / f"{TOKEN}.md").write_text(f"TOKEN::{TOKEN}\n", encoding="utf-8")
    assert lookup_token_deterministic(tmp_path, TOKEN) is False


def test_lookup_ignores_a_token_only_present_in_a_yaml_body(tmp_path: Path) -> None:
    write_yaml_record(tmp_path, token=LONGER, body=f'token: "{TOKEN}"\nTOKEN::{TOKEN}\n')
    assert lookup_token_deterministic(tmp_path, TOKEN) is False
    assert lookup_token_deterministic(tmp_path, LONGER) is True


def test_lookup_with_a_stale_manifest_still_falls_back_to_yaml(tmp_path: Path) -> None:
    write_yaml_record(tmp_path, token=TOKEN)
    manifest = tmp_path / ".hestai" / "MANIFEST.md"
    manifest.write_text("| TOKEN/ID | path |\n| --- | --- |\n| HO-OTHER-20261029 | x |\n", "utf-8")
    assert lookup_token_deterministic(tmp_path, TOKEN) is True


def test_lexer_exports_unchanged() -> None:
    for name in ("declares_token", "lookup_token_deterministic", "assemble_context"):
        assert callable(getattr(lexer, name))
