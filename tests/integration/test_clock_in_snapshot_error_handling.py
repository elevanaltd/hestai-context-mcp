"""Cubic rework cycle 2 — Finding #1 (P1, clock_in.py:449).

RED-first test: ``create_session_snapshot`` failure must be surfaced as
``portable_state.snapshot_error`` (PROD::I4 STRUCTURED_RETURN_SHAPES);
clock_in must NEVER raise even when snapshot write fails. This parallels
the A2 audit-on-skip pattern: local session creation already succeeded,
so portable-state snapshot failure is observable but not fatal.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest


def _identity_dict() -> dict[str, Any]:
    return {
        "project_id": "proj-A",
        "workspace_id": "wt-build",
        "user_id": "alice",
        "state_schema_version": 1,
        "carrier_namespace": "personal",
    }


def _write_identity_config(working_dir: Path) -> None:
    cfg_path = working_dir / ".hestai" / "state" / "portable" / "identity.json"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps(_identity_dict()))


@pytest.mark.integration
class TestClockInSnapshotWriteFailure:
    """Cubic P1 #1: snapshot construction must not break clock_in response shape."""

    def test_clock_in_surfaces_snapshot_error_when_create_snapshot_raises(
        self, tmp_path: Path
    ) -> None:
        """Patching ``create_session_snapshot`` to raise OSError must yield
        a structured ``portable_state.snapshot_error`` and a non-failing
        clock_in response (PROD::I4 STRUCTURED_RETURN_SHAPES)."""

        from hestai_context_mcp.tools.clock_in import clock_in

        _write_identity_config(tmp_path)

        def _raise(*args: Any, **kwargs: Any) -> Any:
            raise OSError("simulated disk-full on snapshot write")

        with (
            patch("hestai_context_mcp.tools.clock_in.get_current_branch", return_value="main"),
            patch(
                "hestai_context_mcp.storage.snapshots.create_session_snapshot",
                side_effect=_raise,
            ),
        ):
            result = clock_in(role="impl", working_dir=str(tmp_path), focus="task")

        # Top-level shape preserved (G2 backward-compat).
        assert "session_id" in result
        assert "portable_state" in result

        portable_state = result["portable_state"]
        # Restore did succeed up to (but not including) snapshot write.
        # Snapshot failure is observable via a dedicated structured field.
        assert "snapshot_error" in portable_state
        snapshot_error = portable_state["snapshot_error"]
        assert snapshot_error is not None
        assert snapshot_error["code"] == "snapshot_write_failed"
        assert "simulated disk-full" in snapshot_error["message"]
        # snapshot_path is None when the write fails (no half-written file).
        assert portable_state["snapshot_path"] is None
