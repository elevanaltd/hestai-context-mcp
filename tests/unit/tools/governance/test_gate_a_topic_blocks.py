"""RED suite — Gate A topic-block key-collision invariant (issue #203 S1).

The read parser keeps the FIRST match of each key, so a top-level reserved key
nested inside CURRENT / RULINGS could take over the record. Gate A rejects any
such line, naming the key and the block. A well-formed topic record passes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hestai_context_mcp.tools.governance.type_checker import validate_octave_content

_TOKEN = "TOPIC-CLIENT-ACCESS-20261015"


def _record(blocks: str = "") -> str:
    return (
        "===DECISION_RECORD===\n"
        "META:\n"
        "  TYPE::DECISION_RECORD\n"
        '  VERSION::"1.3"\n'
        f"  TOKEN::{_TOKEN}\n"
        "  TOPIC::client-access\n"
        "  STATUS::PROPOSED\n"
        "  TIER::OPERATIONAL\n"
        '  AUTHORED_AT::"2026-10-15T00:00:00Z"\n'
        '  DECISION::"Topic record: CURRENT rules rest on RULINGS entries"\n'
        '  BECAUSE::"One record per topic"\n'
        f"{blocks}"
        "===END===\n"
    )


_GOOD_BLOCKS = (
    "CURRENT:\n"
    '  R2::"Access is granted per project."\n'
    "RULINGS:\n"
    "  R2:\n"
    '    RULE::"Access is granted per project."\n'
    '    VERBATIM::"Access per project."\n'
    '    RULED::"Operator, 2026-10-15"\n'
    "    REPLACES::R1\n"
)


def test_topic_record_with_both_blocks_passes(tmp_path: Path) -> None:
    result = validate_octave_content(tmp_path, _record(_GOOD_BLOCKS))
    assert result.valid, result.errors


@pytest.mark.parametrize(
    "key",
    [
        "TOKEN",
        "ID",
        "TYPE",
        "STATUS",
        "TIER",
        "DECISION",
        "BECAUSE",
        "AUTHORED_AT",
        "SUPERSEDED_BY",
    ],
)
def test_reserved_key_inside_rulings_is_rejected(tmp_path: Path, key: str) -> None:
    blocks = _GOOD_BLOCKS.replace(
        '    RULED::"Operator, 2026-10-15"\n',
        f'    RULED::"Operator, 2026-10-15"\n    {key}::x\n',
    )
    result = validate_octave_content(tmp_path, _record(blocks))
    assert not result.valid
    joined = " ".join(result.errors)
    assert f"'{key}'" in joined and "RULINGS" in joined


def test_reserved_key_inside_current_is_rejected(tmp_path: Path) -> None:
    blocks = _GOOD_BLOCKS.replace("CURRENT:\n", "CURRENT:\n  STATUS::SUPERSEDED\n")
    result = validate_octave_content(tmp_path, _record(blocks))
    assert not result.valid
    joined = " ".join(result.errors)
    assert "'STATUS'" in joined and "CURRENT" in joined


def test_meta_level_reserved_keys_are_not_flagged(tmp_path: Path) -> None:
    """Top-level META keys are legitimate; only block-nested lines are checked."""
    result = validate_octave_content(tmp_path, _record())
    assert result.valid, result.errors


def test_reserved_key_after_block_end_is_not_a_block_line(tmp_path: Path) -> None:
    """A top-level line after the block closes is outside the block."""
    blocks = _GOOD_BLOCKS + 'RATIFIED_BY::"Operator"\n'
    result = validate_octave_content(tmp_path, _record(blocks))
    assert result.valid, result.errors
