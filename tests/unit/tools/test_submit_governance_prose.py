"""Tests for the prose_input MODE of submit_governance (RFC #53 Gate C, T5).

The CONTRACT RULING: prose intake is a new MODE of submit_governance (a
``prose_input`` parameter), NOT a new tool. Signature:

    submit_governance(working_dir, octave_content=None, prose_input=None,
                      dry_run=False) -> dict

Guard: EXACTLY ONE of octave_content / prose_input must be non-None.
When prose_input is set, Stage 1+2 produce the OCTAVE, then the call REJOINS
the existing octave_content tail (Stage 3 + Stage 4).

Back-compat: the octave_content path must behave byte-identically to post-#70
main (the baseline INCLUDES the OctaveValidator seam).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

import hestai_context_mcp.tools.submit_governance as sg
from hestai_context_mcp.tools.submit_governance import submit_governance

_VALID_OCTAVE = (
    "===DECISION_RECORD===\n"
    "META:\n"
    "  TYPE::DECISION_RECORD\n"
    '  VERSION::"1.0"\n'
    '  TOKEN::"HO-CONTEXT-MCP-PROSE-20260601"\n'
    "  STATUS::PROPOSED\n"
    "  TIER::OPERATIONAL\n"
    '  DECISION::"Prose-authored decision."\n'
    '  BECAUSE::"Gate C end-to-end."\n'
    '  AUTHORED_AT::"2026-06-01T00:00:00Z"\n'
    "===END===\n"
)


# ---------------------------------------------------------------------------
# EXACTLY-ONE-OF guard
# ---------------------------------------------------------------------------


class TestExactlyOneOfGuard:
    def test_both_none_is_failure(self, tmp_path: Path) -> None:
        result = asyncio.run(submit_governance(working_dir=str(tmp_path), dry_run=True))
        assert result["success"] is False
        assert result["validation_errors"]
        # I4: all defined fields present.
        for key in ("token", "card_type", "target_path", "branch", "pr_url", "dry_run"):
            assert key in result

    def test_both_set_is_failure(self, tmp_path: Path) -> None:
        result = asyncio.run(
            submit_governance(
                working_dir=str(tmp_path),
                octave_content=_VALID_OCTAVE,
                prose_input="record a decision",
                dry_run=True,
            )
        )
        assert result["success"] is False
        assert result["validation_errors"]


# ---------------------------------------------------------------------------
# Prose mode (Stage 1+2 -> rejoin tail)
# ---------------------------------------------------------------------------


@pytest.fixture
def stub_intake(monkeypatch: pytest.MonkeyPatch):
    """Patch the Stage 1+2+3+4 composition reached by the prose path."""

    def _install(result: dict[str, Any]) -> None:
        async def _fake(*args: Any, **kwargs: Any) -> dict[str, Any]:
            _install.captured = {"args": args, "kwargs": kwargs}  # type: ignore[attr-defined]
            return result

        monkeypatch.setattr(sg, "run_intake_to_pr", _fake, raising=True)

    _install.captured = None  # type: ignore[attr-defined]
    return _install


def _intake_ok() -> dict[str, Any]:
    return {
        "success": True,
        "token": "HO-CONTEXT-MCP-PROSE-20260601",
        "card_type": "DECISION_RECORD",
        "target_path": ".hestai/decisions/HO-CONTEXT-MCP-PROSE-20260601.oct.md",
        "branch": "governance/20260601-ho-context-mcp-prose-20260601",
        "pr_url": None,
        "validation_errors": [],
        "octave_validation": None,
        "metrics": {"tokens": 42, "cost": 0.01, "model": "test-model"},
        "dry_run": True,
    }


class TestProseMode:
    def test_prose_runs_intake_and_returns_metrics(self, tmp_path: Path, stub_intake) -> None:
        stub_intake(_intake_ok())
        result = asyncio.run(
            submit_governance(
                working_dir=str(tmp_path),
                prose_input="record a prose decision",
                dry_run=True,
            )
        )
        assert result["success"] is True
        assert result["token"] == "HO-CONTEXT-MCP-PROSE-20260601"
        assert result["card_type"] == "DECISION_RECORD"
        assert result["metrics"]["model"] == "test-model"
        assert result["dry_run"] is True

    def test_prose_path_forwards_dry_run(self, tmp_path: Path, stub_intake) -> None:
        stub_intake(_intake_ok())
        asyncio.run(
            submit_governance(
                working_dir=str(tmp_path),
                prose_input="x",
                dry_run=False,
            )
        )
        captured = stub_intake.captured
        assert captured is not None
        assert captured["kwargs"].get("dry_run") is False

    def test_prose_invalid_working_dir_is_structured_failure(self, stub_intake) -> None:
        stub_intake(_intake_ok())
        result = asyncio.run(
            submit_governance(
                working_dir="/nonexistent/path/xyz",
                prose_input="record a decision",
                dry_run=True,
            )
        )
        assert result["success"] is False
        assert result["validation_errors"]


# ---------------------------------------------------------------------------
# Back-compat: octave_content path byte-stable vs post-#70 main
# ---------------------------------------------------------------------------


class TestOctaveContentBackCompat:
    """The octave_content path must keep its EXACT post-#70 return shape."""

    _POST_70_KEYS = {
        "success",
        "token",
        "card_type",
        "target_path",
        "branch",
        "pr_url",
        "validation_errors",
        "octave_validation",
        "dry_run",
    }

    def test_octave_content_dry_run_success_shape_unchanged(self, tmp_path: Path) -> None:
        result = asyncio.run(
            submit_governance(
                working_dir=str(tmp_path),
                octave_content=_VALID_OCTAVE,
                dry_run=True,
            )
        )
        # Byte-stable shape: EXACTLY the post-#70 keys, no extra "metrics" key.
        assert set(result.keys()) == self._POST_70_KEYS
        assert result["success"] is True
        assert result["token"] == "HO-CONTEXT-MCP-PROSE-20260601"
        assert result["card_type"] == "DECISION_RECORD"

    def test_octave_content_failure_shape_unchanged(self, tmp_path: Path) -> None:
        result = asyncio.run(
            submit_governance(
                working_dir=str(tmp_path),
                octave_content="not valid octave",
                dry_run=True,
            )
        )
        assert set(result.keys()) == self._POST_70_KEYS
        assert result["success"] is False
        assert result["validation_errors"]

    def test_octave_content_does_not_invoke_intake(self, tmp_path: Path, monkeypatch) -> None:
        # The octave_content path must NOT touch the prose intake pipeline.
        called = {"hit": False}

        async def _boom(*args: Any, **kwargs: Any) -> dict[str, Any]:
            called["hit"] = True
            return {}

        monkeypatch.setattr(sg, "run_intake_to_pr", _boom, raising=True)
        asyncio.run(
            submit_governance(
                working_dir=str(tmp_path),
                octave_content=_VALID_OCTAVE,
                dry_run=True,
            )
        )
        assert called["hit"] is False
