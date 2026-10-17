"""RED suite — the lexer counts only top-level TOKEN/ID declarations (#203 S2 follow-up a).

``lookup_token_deterministic`` greps ``.hestai/decisions/**/*.oct.md`` for a
``TOKEN::<value>`` / ``ID::<value>`` line. A line nested inside a topic
record's ``CURRENT`` / ``RULINGS`` block is not a declaration (ADR-RFC-ARCH-004
v1.3 §1.7: block lines are not META), so it must not make a token "exist".
Gate A #14 already rejects such records on write; this closes the read side
for a file that reached the store anyway.
"""

from __future__ import annotations

from pathlib import Path

from hestai_context_mcp.tools.governance import lexer
from hestai_context_mcp.tools.governance.lexer import lookup_token_deterministic

_PHANTOM = "HO-PHANTOM-NESTED-20261017"

_RECORD_WITH_NESTED_TOKEN = f"""===DECISION_RECORD===
META:
  TYPE::DECISION_RECORD
  TOKEN::TOPIC-HOST-20261017
  TOPIC::host
RULINGS:
  R1:
    TOKEN::{_PHANTOM}
    ID::"{_PHANTOM}"
    RULE::"A rule."
===END===
"""


def _store(tmp_path: Path, text: str) -> Path:
    decisions = tmp_path / ".hestai" / "decisions"
    decisions.mkdir(parents=True)
    (decisions / "TOPIC-HOST-20261017.oct.md").write_text(text, encoding="utf-8")
    return tmp_path


def test_nested_token_in_rulings_is_not_a_declaration(tmp_path: Path) -> None:
    wd = _store(tmp_path, _RECORD_WITH_NESTED_TOKEN)
    assert lookup_token_deterministic(wd, _PHANTOM) is False


def test_top_level_token_of_the_same_record_still_resolves(tmp_path: Path) -> None:
    wd = _store(tmp_path, _RECORD_WITH_NESTED_TOKEN)
    assert lookup_token_deterministic(wd, "TOPIC-HOST-20261017") is True


def test_nested_token_in_current_is_not_a_declaration(tmp_path: Path) -> None:
    text = _RECORD_WITH_NESTED_TOKEN.replace("RULINGS:", f"CURRENT:\n  TOKEN::{_PHANTOM}\nRULINGS:")
    wd = _store(tmp_path, text)
    assert lookup_token_deterministic(wd, _PHANTOM) is False


def test_declares_token_is_block_aware() -> None:
    declares_token = lexer.declares_token
    assert declares_token(_RECORD_WITH_NESTED_TOKEN, "TOPIC-HOST-20261017") is True
    assert declares_token(_RECORD_WITH_NESTED_TOKEN, _PHANTOM) is False


def test_declares_token_keeps_exact_match_and_quote_optionality() -> None:
    declares_token = lexer.declares_token
    text = '===DECISION_RECORD===\nMETA:\n  TOKEN::"HO-FOO-BAR-20260101"\n===END===\n'
    assert declares_token(text, "HO-FOO-BAR-20260101") is True
    assert declares_token(text, "HO-FOO-20260101") is False
