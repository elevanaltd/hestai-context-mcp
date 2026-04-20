"""Tests for the AI synthesis seam (``hestai_context_mcp.core.synthesis``).

The seam is provider-agnostic (PROD::I3): the module never imports any AI
SDK. Issue #4 lands the seam with a fallback-only implementation; issue #5
replaces ``synthesize_ai_context`` with a real provider call. These tests
lock the structural contract so that replacement cannot regress shape.
"""

from __future__ import annotations

import pytest

from hestai_context_mcp.core import synthesis as synthesis_mod
from hestai_context_mcp.core.synthesis import (
    AiSynthesisResult,
    build_fallback_synthesis,
    resolve_ai_synthesis,
    synthesize_ai_context,
)


class TestSynthesizeAiContextDefault:
    """``synthesize_ai_context`` is the seam for issue #5; default returns None."""

    def test_default_returns_none(self):
        """No provider wired yet → returns None (issue #5 replaces the body)."""
        assert (
            synthesize_ai_context(
                role="test-role",
                focus="test-focus",
                phase="B1_FOUNDATION_COMPLETE",
                context_summary="",
            )
            is None
        )


class TestBuildFallbackSynthesis:
    """Fallback synthesis must match the OCTAVE contract shape."""

    def test_returns_structured_dict(self):
        result = build_fallback_synthesis(
            role="implementation-lead",
            focus="fix-thing",
            phase="B1_FOUNDATION_COMPLETE",
        )
        assert isinstance(result, dict)
        assert set(result.keys()) == {"source", "synthesis"}
        assert result["source"] == "fallback"
        assert isinstance(result["synthesis"], str)

    def test_synthesis_contains_octave_markers(self):
        result = build_fallback_synthesis(
            role="test-role",
            focus="some-focus",
            phase="B1_FOUNDATION_COMPLETE",
        )
        s = result["synthesis"]
        assert "CONTEXT_FILES::" in s
        assert "FOCUS::some-focus" in s
        assert "PHASE::B1_FOUNDATION_COMPLETE" in s
        assert "BLOCKERS::" in s
        assert "TASKS::" in s
        assert "FRESHNESS_WARNING::" in s


class TestResolveAiSynthesis:
    """``resolve_ai_synthesis`` must ALWAYS return a populated result."""

    def test_falls_back_when_seam_returns_none(self, monkeypatch):
        monkeypatch.setattr(synthesis_mod, "synthesize_ai_context", lambda **_: None)
        result = resolve_ai_synthesis(
            role="r",
            focus="f",
            phase="B1_FOUNDATION_COMPLETE",
            context_summary="",
        )
        assert result["source"] == "fallback"
        assert "PHASE::B1_FOUNDATION_COMPLETE" in result["synthesis"]

    def test_returns_ai_result_when_seam_succeeds(self, monkeypatch):
        expected: AiSynthesisResult = {
            "source": "ai",
            "synthesis": "PHASE::B1_FOUNDATION_COMPLETE\nFOCUS::from-ai",
        }
        monkeypatch.setattr(
            synthesis_mod,
            "synthesize_ai_context",
            lambda **_: expected,
        )
        result = resolve_ai_synthesis(
            role="r",
            focus="f",
            phase="B1_FOUNDATION_COMPLETE",
            context_summary="",
        )
        assert result == expected

    def test_falls_back_when_seam_raises(self, monkeypatch):
        def raiser(**_):
            raise RuntimeError("provider offline")

        monkeypatch.setattr(synthesis_mod, "synthesize_ai_context", raiser)
        result = resolve_ai_synthesis(
            role="r",
            focus="f",
            phase="B1_FOUNDATION_COMPLETE",
            context_summary="",
        )
        assert result["source"] == "fallback"

    def test_falls_back_when_seam_returns_malformed_dict(self, monkeypatch):
        """Defensive: malformed dict from a future seam must not leak to caller."""
        monkeypatch.setattr(
            synthesis_mod,
            "synthesize_ai_context",
            lambda **_: {"wrong_key": "oops"},
        )
        result = resolve_ai_synthesis(
            role="r",
            focus="f",
            phase="B1_FOUNDATION_COMPLETE",
            context_summary="",
        )
        assert result["source"] == "fallback"

    @pytest.mark.parametrize(
        "bad_payload",
        [
            {"source": None, "synthesis": "text"},
            {"source": "ai", "synthesis": None},
            {"source": "ai", "synthesis": []},
            {"source": "ai", "synthesis": ""},
            {"source": "ai", "synthesis": "   "},
            {"source": "unknown", "synthesis": "text"},
            {"source": 42, "synthesis": "text"},
            ["source", "synthesis"],  # wrong container type entirely
            "source::synthesis",  # bare string
            42,  # bare scalar
        ],
        ids=[
            "source-is-None",
            "synthesis-is-None",
            "synthesis-is-list",
            "synthesis-is-empty-string",
            "synthesis-is-whitespace",
            "source-not-in-enum",
            "source-is-int",
            "result-is-list",
            "result-is-str",
            "result-is-int",
        ],
    )
    def test_falls_back_on_value_type_violations(self, monkeypatch, bad_payload):
        """CE gate: strict validation of value types, not just key presence.

        A future AIClient (issue #5) returning malformed values (wrong types,
        empty strings, or off-enum ``source`` values) must degrade to the
        deterministic fallback, not leak a broken shape to the Payload
        Compiler.
        """
        monkeypatch.setattr(
            synthesis_mod,
            "synthesize_ai_context",
            lambda **_: bad_payload,
        )
        result = resolve_ai_synthesis(
            role="r",
            focus="f",
            phase="B1_FOUNDATION_COMPLETE",
            context_summary="",
        )
        assert result["source"] == "fallback"
        assert isinstance(result["synthesis"], str)
        assert result["synthesis"].strip()

    def test_warns_on_seam_exception(self, monkeypatch, caplog):
        """Observability: seam exceptions must surface in logs (CE Q3)."""

        def raiser(**_):
            raise RuntimeError("provider timeout")

        monkeypatch.setattr(synthesis_mod, "synthesize_ai_context", raiser)
        with caplog.at_level("WARNING", logger="hestai_context_mcp.core.synthesis"):
            resolve_ai_synthesis(
                role="r",
                focus="f",
                phase="B1_FOUNDATION_COMPLETE",
                context_summary="",
            )
        assert any("AI synthesis seam raised" in rec.message for rec in caplog.records)

    def test_warns_on_seam_malformed_result(self, monkeypatch, caplog):
        """Observability: malformed seam payloads must surface in logs."""
        monkeypatch.setattr(
            synthesis_mod,
            "synthesize_ai_context",
            lambda **_: {"source": "ai", "synthesis": ""},
        )
        with caplog.at_level("WARNING", logger="hestai_context_mcp.core.synthesis"):
            resolve_ai_synthesis(
                role="r",
                focus="f",
                phase="B1_FOUNDATION_COMPLETE",
                context_summary="",
            )
        assert any("malformed payload" in rec.message for rec in caplog.records)


class TestProviderAgnosticImports:
    """PROD::I3 guard: the seam module must not import any AI provider SDK."""

    def test_no_provider_sdk_imports(self):
        import hestai_context_mcp.core.synthesis as mod

        source = pytest.importorskip("inspect").getsource(mod)
        forbidden = ("import anthropic", "import openai", "openrouter", "from openai")
        for token in forbidden:
            assert token not in source, f"PROD::I3 violation: found {token!r} in synthesis.py"
