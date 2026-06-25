"""Tests for the two-birds ``write_adr`` mode of submit_governance (#112).

ONE-INPUT design (operator-finalized): the agent's natural-language
``prose_input`` IS the ADR source. ``write_adr`` is a bool flag:

    submit_governance(working_dir, ..., prose_input=..., write_adr=True)

  * ``write_adr=False`` (default) -> AGR-only, current behaviour, byte-stable.
  * ``write_adr=True`` (prose mode) -> the linker ALSO dumb-writes the verbatim
    ``prose_input`` to ``docs/adr/<TOKEN>.md`` and the condensed AGR carries a
    deterministically-stamped ``HUMAN_ADR_REF::<TOKEN>`` (token-form #11).

``write_adr=True`` is PROSE-ONLY: with ``octave_content`` (or with no
``prose_input``) there is no natural prose to dump, so the tool returns a
structured error.

CI-safe: the prose intake composition (``run_intake_to_pr``) is stubbed exactly
as in ``test_submit_governance_prose.py`` -- NO AI call, fully deterministic.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

import hestai_context_mcp.tools.submit_governance as sg
from hestai_context_mcp.tools.submit_governance import submit_governance

_TOKEN = "HO-CONTEXT-MCP-TWOBIRDS-20260601"

_VALID_OCTAVE = (
    "===DECISION_RECORD===\n"
    "META:\n"
    "  TYPE::DECISION_RECORD\n"
    '  VERSION::"1.0"\n'
    f'  TOKEN::"{_TOKEN}"\n'
    "  STATUS::PROPOSED\n"
    "  TIER::OPERATIONAL\n"
    '  DECISION::"Two-birds decision."\n'
    '  BECAUSE::"Gate C end-to-end."\n'
    '  AUTHORED_AT::"2026-06-01T00:00:00Z"\n'
    "===END===\n"
)


@pytest.fixture
def stub_intake(monkeypatch: pytest.MonkeyPatch):
    """Patch the Stage 1+2+3+4 composition reached by the prose path.

    Mirrors ``test_submit_governance_prose.py`` so the two-birds API-layer tests
    never make an AI call. The stub captures the kwargs run_intake_to_pr is
    called with, so we can assert ``write_adr`` is forwarded.
    """

    def _install(result: dict[str, Any]) -> None:
        async def _fake(*args: Any, **kwargs: Any) -> dict[str, Any]:
            _install.captured = {"args": args, "kwargs": kwargs}  # type: ignore[attr-defined]
            return result

        monkeypatch.setattr(sg, "run_intake_to_pr", _fake, raising=True)

    _install.captured = None  # type: ignore[attr-defined]
    return _install


def _intake_ok(dry_run: bool = True) -> dict[str, Any]:
    return {
        "success": True,
        "token": _TOKEN,
        "card_type": "DECISION_RECORD",
        "target_path": f".hestai/decisions/{_TOKEN}.oct.md",
        "branch": f"governance/20260601-{_TOKEN.lower()}",
        "pr_url": None,
        "validation_errors": [],
        "octave_validation": None,
        "metrics": {"tokens": 42, "cost": 0.01, "model": "test-model"},
        "dry_run": dry_run,
    }


class TestWriteAdrIsProseOnly:
    def test_write_adr_with_octave_content_is_structured_error(self, tmp_path: Path) -> None:
        # RED #7: write_adr=True with octave_content -> structured error, no write.
        result = asyncio.run(
            submit_governance(
                working_dir=str(tmp_path),
                octave_content=_VALID_OCTAVE,
                write_adr=True,
                dry_run=True,
            )
        )
        assert result["success"] is False
        assert result["validation_errors"]
        joined = " ".join(result["validation_errors"]).lower()
        assert "prose_input" in joined and "adr" in joined

    def test_write_adr_with_no_prose_is_structured_error(self, tmp_path: Path) -> None:
        # RED #7: write_adr=True but neither input provided -> structured error.
        result = asyncio.run(
            submit_governance(
                working_dir=str(tmp_path),
                write_adr=True,
                dry_run=True,
            )
        )
        assert result["success"] is False
        assert result["validation_errors"]

    def test_error_path_includes_adr_target_path_none(self, tmp_path: Path) -> None:
        # F2 (P2) error-path return includes adr_target_path is None
        result = asyncio.run(
            submit_governance(
                working_dir=str(tmp_path),
                octave_content=_VALID_OCTAVE,
                write_adr=True,
                dry_run=True,
            )
        )
        assert result["success"] is False
        assert "adr_target_path" in result
        assert result["adr_target_path"] is None


class TestWriteAdrForwarding:
    def test_write_adr_true_forwarded_to_intake(self, tmp_path: Path, stub_intake) -> None:
        # RED: the prose path must forward write_adr + prose_input to the intake
        # composition so the linker can dual-write.
        stub_intake(_intake_ok())
        asyncio.run(
            submit_governance(
                working_dir=str(tmp_path),
                prose_input="A full ADR-grade decision narrative.",
                write_adr=True,
                dry_run=True,
            )
        )
        captured = stub_intake.captured
        assert captured is not None
        assert captured["kwargs"].get("write_adr") is True

    def test_write_adr_default_false_is_back_compat(self, tmp_path: Path, stub_intake) -> None:
        # RED #1: default (no write_adr) forwards write_adr=False -> AGR-only.
        stub_intake(_intake_ok())
        asyncio.run(
            submit_governance(
                working_dir=str(tmp_path),
                prose_input="record a decision",
                dry_run=True,
            )
        )
        captured = stub_intake.captured
        assert captured is not None
        assert captured["kwargs"].get("write_adr") is False
