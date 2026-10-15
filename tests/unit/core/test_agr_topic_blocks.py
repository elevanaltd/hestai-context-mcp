"""RED suite — topic-record CURRENT / RULINGS block collection (issue #203 S1).

ADR-RFC-ARCH-004 v1.3 §1.2/§1.7: a topic record carries an optional ``TOPIC``
META field plus two top-level blocks. ``CURRENT`` lists the one-line rules in
force (``R2::"<rule>"``); ``RULINGS`` holds one nested entry per ruling with
``RULE`` / ``VERBATIM`` / ``RULED`` and an optional ``REPLACES``.

The collector is regex-only (North Star §4), pure (PROD I5), and additive:
``parse_decision_record`` keeps its nine keys unchanged.
"""

from __future__ import annotations

from hestai_context_mcp.core.agent_readable_governance_parser import (
    collect_topic_blocks,
    parse_decision_record,
)

_TOPIC_RECORD = """===DECISION_RECORD===
META:
  TYPE::DECISION_RECORD
  VERSION::"1.3"
  TOKEN::TOPIC-CLIENT-ACCESS-20261015
  TOPIC::client-access
  STATUS::RATIFIED
  TIER::OPERATIONAL
  AUTHORED_AT::"2026-10-15T00:00:00Z"
  DECISION::"Topic record: rules in CURRENT rest on RULINGS entries"
  BECAUSE::"One record per topic"
CURRENT:
  R2::"Access is granted per project."
  R3::"Offboarding revokes access within 24h."
RULINGS:
  R2:
    RULE::"Access is granted per project."
    VERBATIM::"Access per project, not per client."
    RULED::"Operator, 2026-10-15"
    REPLACES::R1
  R3:
    RULE::"Offboarding revokes access within 24h."
    VERBATIM::"Revoke within a day."
    RULED::"Operator, 2026-10-15"
===END===
"""


def test_collects_current_block_in_order() -> None:
    blocks = collect_topic_blocks(_TOPIC_RECORD)
    assert blocks["current"] == [
        {"id": "R2", "rule": "Access is granted per project."},
        {"id": "R3", "rule": "Offboarding revokes access within 24h."},
    ]


def test_collects_rulings_block_in_order_with_optional_replaces() -> None:
    blocks = collect_topic_blocks(_TOPIC_RECORD)
    assert blocks["rulings"] == [
        {
            "id": "R2",
            "rule": "Access is granted per project.",
            "verbatim": "Access per project, not per client.",
            "ruled": "Operator, 2026-10-15",
            "replaces": "R1",
        },
        {
            "id": "R3",
            "rule": "Offboarding revokes access within 24h.",
            "verbatim": "Revoke within a day.",
            "ruled": "Operator, 2026-10-15",
            "replaces": None,
        },
    ]


def test_record_without_blocks_yields_empty_lists() -> None:
    text = _TOPIC_RECORD.split("CURRENT:")[0] + "===END===\n"
    assert collect_topic_blocks(text) == {"current": [], "rulings": []}


def test_empty_and_none_input_are_graceful() -> None:
    assert collect_topic_blocks(None) == {"current": [], "rulings": []}
    assert collect_topic_blocks("") == {"current": [], "rulings": []}


def test_existing_parse_keys_unchanged() -> None:
    parsed = parse_decision_record(_TOPIC_RECORD)
    assert set(parsed) == {
        "token",
        "type",
        "version",
        "status",
        "tier",
        "decision",
        "because",
        "authored_at",
        "fields",
    }
    assert parsed["fields"]["TOPIC"] == "client-access"


def test_block_lines_do_not_leak_into_fields() -> None:
    """Nested RULE/VERBATIM/R2 lines must not become META ``fields``."""
    fields = parse_decision_record(_TOPIC_RECORD)["fields"]
    for leaked in ("R2", "R3", "RULE", "VERBATIM", "RULED", "REPLACES"):
        assert leaked not in fields


def test_nested_topic_key_cannot_hijack_meta_topic() -> None:
    text = _TOPIC_RECORD.replace(
        '    RULED::"Operator, 2026-10-15"\n    REPLACES::R1',
        '    RULED::"Operator, 2026-10-15"\n    TOPIC::evil\n    REPLACES::R1',
    )
    assert parse_decision_record(text)["fields"]["TOPIC"] == "client-access"


def test_block_ends_at_next_top_level_line() -> None:
    text = _TOPIC_RECORD.replace("===END===", 'TRAILER::"after"\n===END===')
    parsed = parse_decision_record(text)
    assert parsed["fields"]["TRAILER"] == "after"
    assert collect_topic_blocks(text)["rulings"][-1]["id"] == "R3"
