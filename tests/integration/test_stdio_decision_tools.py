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

from tests.unit.tools.governance._agr_fixtures import (
    write_record,
    write_yaml_record,
    yaml_topic_lines,
)

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


# --- slice B: YAML topic blocks, supersedes edges, FORK over the real stdio transport ----

T_TOPIC = "HO-STDIO-TOPIC-20261005"
T_FROZEN = "HO-STDIO-FROZEN-20260101"
T_FROZEN_NEW = "HO-STDIO-SUCCESSOR-20261006"
T_FORK_EXPLICIT = "HO-STDIO-EXPLICIT-20260901"


async def test_yaml_topic_record_round_trip(client: Client, repo: Path) -> None:
    write_yaml_record(
        repo,
        token=T_TOPIC,
        topic="client-access",
        extra_lines=yaml_topic_lines(
            [("R2", "Access is granted per project.")],
            [{"id": "R2", "rule": "Access is granted per project.", "ruled": "Operator"}],
        ),
    )
    looked_up = await _call(client, "lookup_decision", working_dir=str(repo), token=T_TOPIC)
    assert looked_up["record"]["current_state"] == [
        {"id": "R2", "rule": "Access is granted per project."}
    ]
    assert looked_up["record"]["fields"] == {"TOPIC": "client-access"}
    listed = await _call(client, "list_decisions", working_dir=str(repo), topic="client-access")
    assert [r["token"] for r in listed["records"]] == [T_TOPIC]
    assert listed["records"][0]["topic"] == "client-access"


async def test_yaml_supersedes_marks_a_frozen_octave_record_and_trace_walks_it(
    client: Client, repo: Path
) -> None:
    frozen = write_record(repo, token=T_FROZEN, authored_at="2026-01-01T00:00:00Z")
    before = frozen.read_bytes()
    write_yaml_record(repo, token=T_FROZEN_NEW, supersedes=T_FROZEN)
    looked_up = await _call(client, "lookup_decision", working_dir=str(repo), token=T_FROZEN)
    assert looked_up["record"]["status"] == "SUPERSEDED"
    assert looked_up["record"]["fields"]["SUPERSEDED_BY"] == T_FROZEN_NEW
    assert looked_up["resolution_chain_status"] == "complete"
    traced = await _call(client, "trace_supersedure", working_dir=str(repo), token=T_FROZEN)
    assert [(e["token"], e["status"]) for e in traced["chain"]] == [
        (T_FROZEN, "SUPERSEDED"),
        (T_FROZEN_NEW, "RATIFIED"),
    ]
    assert traced["terminal_token"] == T_FROZEN_NEW
    assert frozen.read_bytes() == before


async def test_fork_is_reported_over_stdio_never_resolved(client: Client, repo: Path) -> None:
    write_record(repo, token=T_FROZEN, status="SUPERSEDED", superseded_by=T_FORK_EXPLICIT)
    write_record(repo, token=T_FORK_EXPLICIT)
    write_yaml_record(repo, token=T_FROZEN_NEW, supersedes=T_FROZEN)
    successors = sorted([T_FORK_EXPLICIT, T_FROZEN_NEW])
    looked_up = await _call(client, "lookup_decision", working_dir=str(repo), token=T_FROZEN)
    assert looked_up["resolution_chain_status"] == "forked"
    assert looked_up["successors"] == successors
    traced = await _call(client, "trace_supersedure", working_dir=str(repo), token=T_FROZEN)
    assert traced["ok"] is False
    assert traced["error"]["code"] == "CHAIN_FORK_DETECTED"
    assert traced["error"]["context"]["successors"] == successors


async def test_rejected_yaml_record_names_path_line_and_construct_over_stdio(
    client: Client, repo: Path
) -> None:
    bad = "HO-STDIO-REJECT-20261007"
    path = write_yaml_record(repo, token=bad, extra_lines=["extra: |"])
    looked_up = await _call(client, "lookup_decision", working_dir=str(repo), token=bad)
    context = looked_up["error"]["context"]
    assert context["path"] == path.relative_to(repo).as_posix()
    assert context["construct"] == "block_scalar"
    assert context["line"] == path.read_text(encoding="utf-8").split("\n").index("extra: |") + 1
    listed = await _call(client, "list_decisions", working_dir=str(repo))
    entry = next(s for s in listed["skipped"] if s["path"].endswith(f"{bad}.md"))
    assert (entry["line"], entry["construct"]) == (context["line"], "block_scalar")


async def test_c5_fork_shape_is_pinned_at_the_stdio_boundary(client: Client, repo: Path) -> None:
    """Slice C5: OCTAVE X-successor plus a RATIFIED YAML Y listing the record in ``supersedes:``.

    ``successors`` is documented as the sorted (lexicographic) list of both TOKENs.
    """
    x, y, frozen = "HO-STDIO-FORKZ-20260901", "HO-STDIO-FORKA-20261008", "HO-STDIO-FORKED-20260101"
    write_record(repo, token=frozen, status="SUPERSEDED", superseded_by=x)
    write_record(repo, token=x)
    write_yaml_record(repo, token=y, status="RATIFIED", supersedes=frozen)

    looked_up = await _call(client, "lookup_decision", working_dir=str(repo), token=frozen)
    assert looked_up["ok"] is True
    assert looked_up["resolution_chain_status"] == "forked"
    assert looked_up["successors"] == [y, x] == sorted([x, y])  # derived Y sorts BEFORE explicit X
    assert looked_up["record"]["status"] == "SUPERSEDED"
    (entry,) = looked_up["resolution_chain"]
    assert entry["token"] == frozen
    assert entry["superseded_by"] is None and entry["fork"] is True
    assert entry["successors"] == [y, x]

    traced = await _call(client, "trace_supersedure", working_dir=str(repo), token=frozen)
    assert traced["ok"] is False
    error = traced["error"]
    assert error["code"] == "CHAIN_FORK_DETECTED"
    assert error["tool"] == "trace_supersedure"
    assert error["context"]["fork_at_token"] == frozen
    assert error["context"]["successors"] == [y, x]
    assert [e["token"] for e in error["context"]["chain"]] == [frozen]
    assert error["context"]["chain"][0]["fork"] is True


async def test_c6_unparseable_shape_is_pinned_at_the_stdio_boundary(
    client: Client, repo: Path
) -> None:
    """Slice C6: a rejected YAML record mid-chain stops both walks with a structured shape.

    Chain: frozen OCTAVE ``old`` --(derived: RATIFIED YAML ``mid`` lists it in ``supersedes:``)-->
    ``mid`` --(explicit ``superseded_by``)--> ``bad`` (YAML with an unquoted ``status``).
    """
    old, mid, bad = "HO-STDIO-C6OLD-20260101", "HO-STDIO-C6MID-20261009", "HO-STDIO-C6BAD-20261010"
    old_path = write_record(repo, token=old)
    write_yaml_record(repo, token=mid, status="RATIFIED", supersedes=old, superseded_by=bad)
    bad_path = write_yaml_record(repo, token=bad)
    bad_path.write_text(
        bad_path.read_text(encoding="utf-8").replace('status: "RATIFIED"', "status: RATIFIED"),
        encoding="utf-8",
    )
    before = old_path.read_bytes()
    bad_rel = bad_path.relative_to(repo).as_posix()
    bad_line = bad_path.read_text(encoding="utf-8").split("\n").index("status: RATIFIED") + 1

    looked_up = await _call(client, "lookup_decision", working_dir=str(repo), token=old)
    assert looked_up["ok"] is True
    assert looked_up["record"]["status"] == "SUPERSEDED"
    assert looked_up["resolution_chain_status"] == "unparseable"
    assert looked_up["rejected_at"] == {
        "token": bad,
        "path": bad_rel,
        "line": bad_line,
        "construct": "unquoted_value",
    }
    assert [e["token"] for e in looked_up["resolution_chain"]] == [old, mid]

    traced = await _call(client, "trace_supersedure", working_dir=str(repo), token=old)
    assert traced["ok"] is False
    error = traced["error"]
    assert error["code"] == "RECORD_PARSE_FAILED"
    assert error["tool"] == "trace_supersedure"
    context = error["context"]
    assert context["token"] == bad
    assert context["path"] == bad_rel
    assert context["line"] == bad_line
    assert context["construct"] == "unquoted_value"
    assert isinstance(context["parse_error"], str) and "unquoted_value" in context["parse_error"]
    assert [e["token"] for e in context["chain"]] == [old, mid]
    assert old_path.read_bytes() == before
