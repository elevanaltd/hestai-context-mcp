"""RED suite — topic-record read side (issue #203 S1).

* ``list_decisions(topic=)`` filters on the free META ``TOPIC`` field (same
  pattern as SCOPE) and returns ``topic`` (or ``None``) on every row.
* ``lookup_decision`` adds ``current_state: [{id, rule}]`` when the record has
  a TOPIC; the key is ``None`` otherwise. All existing keys are unchanged.
"""

from __future__ import annotations

from pathlib import Path

from hestai_context_mcp.tools.list_decisions import list_decisions
from hestai_context_mcp.tools.lookup_decision import lookup_decision

from ._agr_fixtures import write_record

_TOPIC_TOKEN = "TOPIC-CLIENT-ACCESS-20261015"
_PLAIN_TOKEN = "HO-CONTEXT-MCP-PLAIN-20261014"
_OTHER_TOKEN = "TOPIC-OTHER-20261016"

_BLOCKS = [
    "CURRENT:",
    '  R2::"Access is granted per project."',
    '  R3::"Offboarding revokes access within 24h."',
    "RULINGS:",
    "  R2:",
    '    RULE::"Access is granted per project."',
    '    VERBATIM::"Access per project."',
    '    RULED::"Operator, 2026-10-15"',
]


def _seed(tmp_path: Path) -> None:
    write_record(
        tmp_path,
        token=_TOPIC_TOKEN,
        authored_at="2026-10-15T00:00:00Z",
        extra_lines=["  TOPIC::client-access", *_BLOCKS],
    )
    write_record(
        tmp_path,
        token=_OTHER_TOKEN,
        authored_at="2026-10-16T00:00:00Z",
        extra_lines=["  TOPIC::other-topic"],
    )
    write_record(tmp_path, token=_PLAIN_TOKEN, authored_at="2026-10-14T00:00:00Z")


def test_list_topic_filter_returns_only_matching(tmp_path: Path) -> None:
    _seed(tmp_path)
    result = list_decisions(str(tmp_path), topic="client-access")
    assert result["ok"] is True
    assert [r["token"] for r in result["records"]] == [_TOPIC_TOKEN]
    assert result["records"][0]["topic"] == "client-access"


def test_list_without_topic_returns_all_topic_key_only_on_topic_rows(tmp_path: Path) -> None:
    _seed(tmp_path)
    result = list_decisions(str(tmp_path))
    by_token = {r["token"]: r.get("topic") for r in result["records"]}
    plain = next(r for r in result["records"] if r["token"] == _PLAIN_TOKEN)
    assert "topic" not in plain  # pre-v1.3 row shape preserved
    assert by_token == {
        _TOPIC_TOKEN: "client-access",
        _OTHER_TOKEN: "other-topic",
        _PLAIN_TOKEN: None,
    }


def test_list_unknown_topic_returns_empty(tmp_path: Path) -> None:
    _seed(tmp_path)
    result = list_decisions(str(tmp_path), topic="nope")
    assert result["ok"] is True
    assert result["records"] == []
    assert result["total"] == 0


def test_lookup_topic_record_has_current_state(tmp_path: Path) -> None:
    _seed(tmp_path)
    result = lookup_decision(str(tmp_path), _TOPIC_TOKEN)
    assert result["ok"] is True
    assert result["record"]["current_state"] == [
        {"id": "R2", "rule": "Access is granted per project."},
        {"id": "R3", "rule": "Offboarding revokes access within 24h."},
    ]
    # Existing keys intact.
    for key in ("token", "type", "version", "status", "tier", "decision", "because"):
        assert key in result["record"]
    assert result["record"]["fields"]["TOPIC"] == "client-access"


def test_lookup_non_topic_record_current_state_is_none(tmp_path: Path) -> None:
    _seed(tmp_path)
    result = lookup_decision(str(tmp_path), _PLAIN_TOKEN)
    assert result["ok"] is True
    assert result["record"]["current_state"] is None


def test_lookup_topic_without_current_block_gives_empty_list(tmp_path: Path) -> None:
    _seed(tmp_path)
    result = lookup_decision(str(tmp_path), _OTHER_TOKEN)
    assert result["record"]["current_state"] == []


# --- CE rework round 1: read failures return the §3.1.1 envelope ------------


def test_lookup_file_vanishes_after_discovery_returns_envelope(tmp_path: Path, monkeypatch) -> None:
    from hestai_context_mcp.tools.governance import agr_read

    _seed(tmp_path)
    real = agr_read.discover_record

    def discover_then_delete(working: Path, token: str):
        found = real(working, token)
        if found is not None:
            found.unlink()
        return found

    monkeypatch.setattr(agr_read, "discover_record", discover_then_delete)
    result = lookup_decision(str(tmp_path), _TOPIC_TOKEN)
    assert result["ok"] is False
    assert result["error"]["code"] == "RECORD_PARSE_FAILED"
    assert result["error"]["context"]["token"] == _TOPIC_TOKEN


def test_lookup_read_oserror_returns_envelope(tmp_path: Path, monkeypatch) -> None:
    _seed(tmp_path)
    real = Path.read_text

    def flaky(self: Path, *args, **kwargs):
        if self.name == f"{_TOPIC_TOKEN}.oct.md":
            raise PermissionError("denied")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", flaky)
    result = lookup_decision(str(tmp_path), _TOPIC_TOKEN)
    assert result["ok"] is False
    assert result["error"]["code"] == "RECORD_PARSE_FAILED"


def test_lookup_reads_record_file_once(tmp_path: Path, monkeypatch) -> None:
    _seed(tmp_path)
    real = Path.read_text
    calls: list[str] = []

    def counting(self: Path, *args, **kwargs):
        if self.name == f"{_TOPIC_TOKEN}.oct.md":
            calls.append(self.name)
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counting)
    result = lookup_decision(str(tmp_path), _TOPIC_TOKEN)
    assert result["ok"] is True
    assert len(calls) == 1
