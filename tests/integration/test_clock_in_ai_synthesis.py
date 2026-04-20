"""Integration tests: ``clock_in`` + AI synthesis seam end-to-end.

Verifies the structured ``ai_synthesis`` field contract at the
``clock_in`` boundary:

- AI-success (stub AIClient) → ``response["ai_synthesis"]["source"] == "ai"``
- AI-failure (stub raising) → ``response["ai_synthesis"]["source"] == "fallback"``
- No credentials present → default factory yields no client → fallback

The injection point is the module-level factory
``hestai_context_mcp.core.synthesis.build_default_ai_client`` — the
narrowest seam that preserves ``clock_in``'s public signature. That seam
is already established by #4; issue #5 makes it call the factory rather
than hardcode ``None``.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.integration


def _valid_octave() -> str:
    return (
        "CONTEXT_FILES::[@x]\n"
        "FOCUS::integration\n"
        "PHASE::B1_FOUNDATION_COMPLETE\n"
        "BLOCKERS::[]\n"
        "TASKS::[wire-the-thing]\n"
        "FRESHNESS_WARNING::OK"
    )


class _Stub:
    def __init__(self, *, text: str = "", raises: BaseException | None = None) -> None:
        self._text = text
        self._raises = raises

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def complete_text(self, request: Any) -> str:
        if self._raises is not None:
            raise self._raises
        return self._text


class TestClockInAiSynthesisIntegration:
    @patch("hestai_context_mcp.tools.clock_in.get_current_branch", return_value="main")
    def test_ai_success_populates_source_ai(
        self, _mock_branch, tmp_path, monkeypatch: pytest.MonkeyPatch
    ):
        import hestai_context_mcp.core.synthesis as synth_mod
        from hestai_context_mcp.tools.clock_in import clock_in

        monkeypatch.setattr(
            synth_mod,
            "build_default_ai_client",
            lambda: _Stub(text=_valid_octave()),
            raising=True,
        )

        result = clock_in(
            role="implementation-lead",
            working_dir=str(tmp_path),
            focus="integration",
        )

        assert "ai_synthesis" in result
        assert result["ai_synthesis"]["source"] == "ai"
        assert "TASKS::" in result["ai_synthesis"]["synthesis"]

    @patch("hestai_context_mcp.tools.clock_in.get_current_branch", return_value="main")
    def test_ai_failure_collapses_to_fallback(
        self, _mock_branch, tmp_path, monkeypatch: pytest.MonkeyPatch
    ):
        import hestai_context_mcp.core.synthesis as synth_mod
        import hestai_context_mcp.ports.ai_client as port_mod
        from hestai_context_mcp.tools.clock_in import clock_in

        monkeypatch.setattr(
            synth_mod,
            "build_default_ai_client",
            lambda: _Stub(raises=port_mod.AIClientTransportError("net")),
            raising=True,
        )

        result = clock_in(
            role="implementation-lead",
            working_dir=str(tmp_path),
            focus="integration",
        )

        assert result["ai_synthesis"]["source"] == "fallback"
        assert "FRESHNESS_WARNING::AI_SYNTHESIS_UNAVAILABLE" in (
            result["ai_synthesis"]["synthesis"]
        )

    @patch("hestai_context_mcp.tools.clock_in.get_current_branch", return_value="main")
    def test_no_credentials_yields_fallback(
        self, _mock_branch, tmp_path, monkeypatch: pytest.MonkeyPatch
    ):
        """With env cleared and keyring empty, the default factory returns None."""
        # Clear env credentials
        for var in ("OPENAI_API_KEY", "OPENROUTER_API_KEY"):
            monkeypatch.delenv(var, raising=False)

        # Install an empty fake keyring so we don't touch the OS keyring
        import hestai_context_mcp.adapters.ai_config as cfg_mod

        class _EmptyKR:
            def get_password(self, *_a, **_kw):
                return None

            def set_password(self, *_a, **_kw):
                return None

            def delete_password(self, *_a, **_kw):
                return None

        monkeypatch.setattr(cfg_mod, "keyring", _EmptyKR(), raising=True)

        from hestai_context_mcp.tools.clock_in import clock_in

        result = clock_in(
            role="implementation-lead",
            working_dir=str(tmp_path),
            focus="integration",
        )

        assert result["ai_synthesis"]["source"] == "fallback"
