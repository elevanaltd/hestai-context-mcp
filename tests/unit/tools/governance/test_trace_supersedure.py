"""RED suite — ``trace_supersedure`` MCP tool.

Contract: ADR-RFC-ARCH-004 §3.4 (return shape) + §3.1.1 (error envelope).
Pure read (PROD I5), structured return (PROD I4).

Return::

    {
      "ok": true,
      "chain": [{token, status, authored_at, superseded_by, path}, ...],
      "terminal_token": "<end token>",
      "terminal_status": "PROPOSED" | "RATIFIED" | "VOID"
    }

The chain starts at the requested token and follows SUPERSEDED_BY pointers to a
record whose SUPERSEDED_BY is null. A terminal token yields a single-entry
chain. Errors: TOKEN_NOT_FOUND, CHAIN_BROKEN, CHAIN_CYCLE_DETECTED (MUST fail
closed, not infinite-loop), WORKING_DIR_INVALID.

RED: ``tools.trace_supersedure`` does not exist yet — import raises
ModuleNotFoundError.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from ._agr_fixtures import (
    TOKEN_BROKEN,
    TOKEN_CYCLE_A,
    TOKEN_MID,
    TOKEN_MISSING,
    TOKEN_NEW,
    TOKEN_OLD,
    TOKEN_RATIFIED,
    snapshot_tree,
    write_broken_chain,
    write_cyclic_pair,
    write_record,
    write_supersession_chain,
)


def _trace_supersedure() -> Callable[..., dict]:
    """Lazily import the not-yet-existing tool (RED discipline).

    Import-inside-test keeps COLLECTION green and yields a per-test
    'missing implementation' failure. GREEN creates
    ``tools.trace_supersedure.trace_supersedure``.
    """
    from hestai_context_mcp.tools.trace_supersedure import trace_supersedure

    return trace_supersedure


class TestHappyPath:
    @pytest.mark.unit
    def test_full_chain_shape(self, tmp_path: Path) -> None:
        """§3.4: chain walks OLD->MID->NEW; terminal fields reflect the end."""
        trace_supersedure = _trace_supersedure()
        write_supersession_chain(tmp_path)
        result = trace_supersedure(str(tmp_path), TOKEN_OLD)
        assert result["ok"] is True

        chain = result["chain"]
        assert [e["token"] for e in chain] == [TOKEN_OLD, TOKEN_MID, TOKEN_NEW]

        # Per-entry shape (§3.4).
        first = chain[0]
        assert set(first.keys()) == {
            "token",
            "status",
            "authored_at",
            "superseded_by",
            "path",
        }
        assert first["superseded_by"] == TOKEN_MID
        assert first["path"] == f".hestai/decisions/{TOKEN_OLD}.oct.md"

        # Terminal: never SUPERSEDED; superseded_by null on the last entry.
        assert chain[-1]["superseded_by"] is None
        assert result["terminal_token"] == TOKEN_NEW
        assert result["terminal_status"] == "RATIFIED"

    @pytest.mark.unit
    def test_single_entry_chain_when_terminal(self, tmp_path: Path) -> None:
        """A record with no SUPERSEDED_BY yields a one-entry chain (§3.4)."""
        trace_supersedure = _trace_supersedure()
        write_record(tmp_path, token=TOKEN_RATIFIED, status="RATIFIED")
        result = trace_supersedure(str(tmp_path), TOKEN_RATIFIED)
        assert result["ok"] is True
        assert len(result["chain"]) == 1
        assert result["terminal_token"] == TOKEN_RATIFIED
        assert result["chain"][0]["superseded_by"] is None

    @pytest.mark.unit
    def test_mid_chain_start_truncates_to_remaining(self, tmp_path: Path) -> None:
        """Starting at a mid-chain token traces from there to the terminal."""
        trace_supersedure = _trace_supersedure()
        write_supersession_chain(tmp_path)
        result = trace_supersedure(str(tmp_path), TOKEN_MID)
        assert [e["token"] for e in result["chain"]] == [TOKEN_MID, TOKEN_NEW]
        assert result["terminal_token"] == TOKEN_NEW


class TestErrorEnvelope:
    def _assert_envelope(self, result: dict, code: str, category: str) -> None:
        assert result["ok"] is False
        err = result["error"]
        assert err["code"] == code
        assert err["category"] == category
        assert err["tool"] == "trace_supersedure"
        assert isinstance(err["message"], str) and err["message"]
        assert isinstance(err["context"], dict)
        assert err["contract_ref"].startswith("ADR-RFC-ARCH-004 §3")

    @pytest.mark.unit
    def test_token_not_found(self, tmp_path: Path) -> None:
        """A missing START token => TOKEN_NOT_FOUND (§3.4)."""
        trace_supersedure = _trace_supersedure()
        (tmp_path / ".hestai" / "decisions").mkdir(parents=True, exist_ok=True)
        result = trace_supersedure(str(tmp_path), TOKEN_MISSING)
        self._assert_envelope(result, "TOKEN_NOT_FOUND", "input_validation")

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "evil_token", ["../../../etc/passwd", "../secret", "..", "/etc/passwd"]
    )
    def test_traversal_token_is_not_found_no_escape(self, tmp_path: Path, evil_token: str) -> None:
        """P1 SECURITY: trace_supersedure does NOT pre-validate the token, so the
        path-traversal guard MUST live in discover_record. A traversal-shaped
        token yields the clean TOKEN_NOT_FOUND envelope, no exception, and no
        out-of-tree access.

        A real AGR is planted OUTSIDE the decisions tree; if the guard were
        missing, ``root / "../OUTSIDE.oct.md"`` could escape — here it must not
        resolve. ``Path.read_text`` is guarded to fail loudly on any escape.
        """
        trace_supersedure = _trace_supersedure()
        decisions = tmp_path / ".hestai" / "decisions"
        decisions.mkdir(parents=True, exist_ok=True)
        outside = tmp_path / ".hestai" / "OUTSIDE.oct.md"
        outside.write_text(
            "===DECISION_RECORD===\nMETA:\n  TYPE::DECISION_RECORD\n"
            "  TOKEN::HO-CONTEXT-MCP-OUTSIDE-20260101\n  STATUS::RATIFIED\n"
            '  TIER::STRATEGIC\n  AUTHORED_AT::"2026-01-01T00:00:00Z"\n'
            '  DECISION::"x"\n  BECAUSE::"y"\n===END===\n',
            encoding="utf-8",
        )

        decisions_resolved = decisions.resolve()
        real_read_text = Path.read_text

        def guarded_read_text(self: Path, *args: object, **kwargs: object) -> str:
            resolved = self.resolve()
            assert str(resolved).startswith(
                str(decisions_resolved)
            ), f"path escape — trace_supersedure read outside tree: {resolved}"
            return real_read_text(self, *args, **kwargs)  # type: ignore[arg-type]

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(Path, "read_text", guarded_read_text)
            result = trace_supersedure(str(tmp_path), evil_token)

        # Clean envelope, no exception, no escape.
        self._assert_envelope(result, "TOKEN_NOT_FOUND", "input_validation")

    @pytest.mark.unit
    def test_chain_broken_distinct_from_not_found(self, tmp_path: Path) -> None:
        """A mid-chain SUPERSEDED_BY pointing at a missing TOKEN => CHAIN_BROKEN.

        §3.4 keeps this DISTINCT from TOKEN_NOT_FOUND so consumers can tell
        missing-start from missing-middle. Context names both the broken-at
        token and the missing successor.
        """
        trace_supersedure = _trace_supersedure()
        write_broken_chain(tmp_path)
        result = trace_supersedure(str(tmp_path), TOKEN_BROKEN)
        self._assert_envelope(result, "CHAIN_BROKEN", "schema_violation")
        ctx = result["error"]["context"]
        assert ctx["broken_at_token"] == TOKEN_BROKEN
        assert ctx["missing_successor_token"] == TOKEN_MISSING

    @pytest.mark.unit
    def test_chain_cycle_detected_fails_closed(self, tmp_path: Path) -> None:
        """§3.4: a SUPERSEDED_BY cycle MUST fail closed, never infinite-loop.

        The two-record cycle A->B->A must terminate with CHAIN_CYCLE_DETECTED
        and name the revisited token. Loop-safety is enforced HARD: the call
        runs in a worker thread with a bounded join. If GREEN ever regresses
        into an unbounded walk, the join times out and the test FAILS loudly
        instead of hanging CI.
        """
        import threading

        trace_supersedure = _trace_supersedure()
        write_cyclic_pair(tmp_path)

        box: dict[str, dict] = {}

        def _run() -> None:
            box["result"] = trace_supersedure(str(tmp_path), TOKEN_CYCLE_A)

        worker = threading.Thread(target=_run, daemon=True)
        worker.start()
        worker.join(timeout=5.0)
        assert not worker.is_alive(), (
            "trace_supersedure did not terminate on a cyclic chain within 5s "
            "— it must fail closed (CHAIN_CYCLE_DETECTED), never infinite-loop."
        )

        result = box["result"]
        self._assert_envelope(result, "CHAIN_CYCLE_DETECTED", "schema_violation")
        assert "cycle_at_token" in result["error"]["context"]

    @pytest.mark.unit
    def test_working_dir_invalid(self, tmp_path: Path) -> None:
        """Non-existent working_dir => WORKING_DIR_INVALID."""
        trace_supersedure = _trace_supersedure()
        result = trace_supersedure(str(tmp_path / "absent"), TOKEN_OLD)
        self._assert_envelope(result, "WORKING_DIR_INVALID", "io_failure")


class TestPurity:
    @pytest.mark.unit
    def test_trace_is_pure_no_mutation(self, tmp_path: Path) -> None:
        """PROD I5: trace_supersedure performs zero writes/mutations."""
        trace_supersedure = _trace_supersedure()
        write_supersession_chain(tmp_path)
        before = snapshot_tree(tmp_path)
        trace_supersedure(str(tmp_path), TOKEN_OLD)
        after = snapshot_tree(tmp_path)
        assert before == after
