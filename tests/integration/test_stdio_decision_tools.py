"""PR-4 slice A step 5: stdio round-trip of the AGR read tools over BOTH syntaxes.

Spawns the REAL server (``python -m hestai_context_mcp``) over stdio against a
temp repo holding one OCTAVE and one quoted-YAML DECISION_RECORD, calls
``lookup_decision`` / ``list_decisions`` / ``trace_supersedure`` through an MCP
client, and asserts the structured results (PROD I4) for both records.
"""

from __future__ import annotations

import sys
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client
from fastmcp.client.transports import StdioTransport

from tests.unit.tools.governance._agr_fixtures import write_record, write_yaml_record

pytestmark = pytest.mark.integration

T_OCT = "HO-STDIO-OCTAVE-20261001"
T_YAML = "HO-STDIO-YAML-20261002"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    write_record(
        tmp_path,
        token=T_OCT,
        status="SUPERSEDED",
        authored_at="2026-10-01T00:00:00Z",
        superseded_by=T_YAML,
    )
    write_yaml_record(tmp_path, token=T_YAML, authored_at="2026-10-02T00:00:00Z", scope="repo")
    return tmp_path


@pytest.fixture
async def client(tmp_path: Path) -> AsyncIterator[Client]:
    transport = StdioTransport(
        command=sys.executable,
        args=["-m", "hestai_context_mcp"],
        cwd=str(tmp_path),
        keep_alive=False,
    )
    async with Client(transport) as session:
        yield session


async def _call(client: Client, tool: str, **args: Any) -> dict[str, Any]:
    result = await client.call_tool(tool, args)
    assert result.is_error is False
    assert isinstance(result.structured_content, dict)
    return result.structured_content


async def test_server_exposes_the_three_read_tools(client: Client) -> None:
    names = {tool.name for tool in await client.list_tools()}
    assert {"lookup_decision", "list_decisions", "trace_supersedure"} <= names


async def test_lookup_decision_round_trip_for_both_syntaxes(client: Client, repo: Path) -> None:
    oct_result = await _call(client, "lookup_decision", working_dir=str(repo), token=T_OCT)
    yaml_result = await _call(client, "lookup_decision", working_dir=str(repo), token=T_YAML)
    assert oct_result["ok"] is True and yaml_result["ok"] is True
    assert oct_result["record"]["path"] == f".hestai/decisions/{T_OCT}.oct.md"
    assert yaml_result["record"]["path"] == f".hestai/decisions/{T_YAML}.md"
    assert set(oct_result["record"]) == set(yaml_result["record"])
    assert yaml_result["record"]["token"] == T_YAML
    assert yaml_result["record"]["type"] == "DECISION_RECORD"
    assert yaml_result["record"]["fields"] == {"SCOPE": "repo"}
    assert [e["token"] for e in oct_result["resolution_chain"]] == [T_OCT, T_YAML]
    assert oct_result["resolution_chain_status"] == "complete"


async def test_list_decisions_round_trip_for_both_syntaxes(client: Client, repo: Path) -> None:
    result = await _call(client, "list_decisions", working_dir=str(repo))
    assert result["ok"] is True
    assert result["total"] == 2
    assert result["skipped"] == []
    assert [r["token"] for r in result["records"]] == [T_YAML, T_OCT]
    assert {r["path"] for r in result["records"]} == {
        f".hestai/decisions/{T_OCT}.oct.md",
        f".hestai/decisions/{T_YAML}.md",
    }


async def test_trace_supersedure_round_trip_across_syntaxes(client: Client, repo: Path) -> None:
    result = await _call(client, "trace_supersedure", working_dir=str(repo), token=T_OCT)
    assert result["ok"] is True
    assert [e["token"] for e in result["chain"]] == [T_OCT, T_YAML]
    assert result["terminal_token"] == T_YAML
    assert result["terminal_status"] == "RATIFIED"
    yaml_only = await _call(client, "trace_supersedure", working_dir=str(repo), token=T_YAML)
    assert [e["token"] for e in yaml_only["chain"]] == [T_YAML]


async def test_malformed_yaml_record_round_trips_as_structured_envelope(
    client: Client, repo: Path
) -> None:
    bad = "HO-STDIO-BAD-20261003"
    write_yaml_record(repo, token=bad, extra_lines=["extra: bare"])
    looked_up = await _call(client, "lookup_decision", working_dir=str(repo), token=bad)
    assert looked_up["ok"] is False
    assert looked_up["error"]["code"] == "RECORD_PARSE_FAILED"
    listed = await _call(client, "list_decisions", working_dir=str(repo))
    assert [s["path"] for s in listed["skipped"]] == [f".hestai/decisions/{bad}.md"]
