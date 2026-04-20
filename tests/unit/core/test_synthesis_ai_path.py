"""AI-success-path and failure-mode tests for ``core.synthesis``.

Exercises the new behaviour introduced by issue #5:

- ``synthesize_ai_context`` calls the default AIClient factory, runs
  ``_validate_octave_synthesis`` on the returned text, and emits either
  ``{"source": "ai", "synthesis": <validated_text>}`` on success or
  ``None`` on any failure (letting ``resolve_ai_synthesis`` produce the
  deterministic fallback).

- Each port-layer exception collapses to ``None`` (→ fallback).
- Malformed OCTAVE (missing any of the 6 required fields) collapses to
  ``None`` (→ fallback).
- When no default AIClient is available (no key anywhere), the seam
  returns ``None`` without raising.

Dependency injection used here is the module-level factory
``build_default_ai_client``; tests monkeypatch it to return a stub
implementing the ``AIClient`` Protocol. This is the narrowest seam that
preserves #4's public surface.
"""

from __future__ import annotations

from typing import Any

import pytest

# --- Helpers -------------------------------------------------------------


def _valid_octave() -> str:
    """An OCTAVE blob containing all 6 required substring markers."""
    return (
        "CONTEXT_FILES::[@x]\n"
        "FOCUS::bar\n"
        "PHASE::B1_FOUNDATION_COMPLETE\n"
        "BLOCKERS::[]\n"
        "TASKS::[do-the-thing]\n"
        "FRESHNESS_WARNING::OK"
    )


class _StubClient:
    """Minimal async-context AIClient stub used by these tests."""

    def __init__(self, *, text: str = "", raises: BaseException | None = None) -> None:
        self._text = text
        self._raises = raises
        self.closed = False

    async def __aenter__(self) -> _StubClient:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        self.closed = True

    async def complete_text(self, request: Any) -> str:  # CompletionRequest
        if self._raises is not None:
            raise self._raises
        return self._text


@pytest.fixture
def patch_factory(monkeypatch: pytest.MonkeyPatch):
    """Patch ``synthesis.build_default_ai_client`` to return a supplied stub.

    Yields a setter ``set(stub_or_none)`` so each test can parameterise.
    """

    def _install(client_or_none):
        import hestai_context_mcp.core.synthesis as mod

        monkeypatch.setattr(
            mod,
            "build_default_ai_client",
            lambda: client_or_none,
            raising=True,
        )

    return _install


# --- Validator ------------------------------------------------------------


class TestValidateOctaveSynthesis:
    """Substring-level validator for the 6 required OCTAVE field markers."""

    def test_passes_when_all_fields_present(self):
        from hestai_context_mcp.core.synthesis import _validate_octave_synthesis

        assert _validate_octave_synthesis(_valid_octave()) is True

    @pytest.mark.parametrize(
        "missing",
        [
            "CONTEXT_FILES::",
            "FOCUS::",
            "PHASE::",
            "BLOCKERS::",
            "TASKS::",
            "FRESHNESS_WARNING::",
        ],
    )
    def test_fails_when_any_field_missing(self, missing: str):
        from hestai_context_mcp.core.synthesis import _validate_octave_synthesis

        text = _valid_octave().replace(missing, "X" + missing[1:])  # mangle marker
        assert _validate_octave_synthesis(text) is False

    def test_fallback_template_passes_its_own_validator(self):
        """Invariant: the deterministic fallback must satisfy the validator."""
        from hestai_context_mcp.core.synthesis import (
            _validate_octave_synthesis,
            build_fallback_synthesis,
        )

        result = build_fallback_synthesis(role="r", focus="f", phase="B1_FOUNDATION_COMPLETE")
        assert _validate_octave_synthesis(result["synthesis"]) is True


# --- synthesize_ai_context happy + failure modes ------------------------


class TestSynthesizeAiContextSuccess:
    def test_returns_ai_result_on_valid_octave(self, patch_factory):
        from hestai_context_mcp.core.synthesis import synthesize_ai_context

        patch_factory(_StubClient(text=_valid_octave()))
        result = synthesize_ai_context(
            role="r",
            focus="f",
            phase="B1_FOUNDATION_COMPLETE",
            context_summary="ctx",
        )
        assert result is not None
        assert result["source"] == "ai"
        assert result["synthesis"] == _valid_octave()


class TestSynthesizeAiContextFailureModes:
    def test_returns_none_when_factory_gives_no_client(self, patch_factory):
        from hestai_context_mcp.core.synthesis import synthesize_ai_context

        patch_factory(None)
        assert (
            synthesize_ai_context(
                role="r",
                focus="f",
                phase="B1_FOUNDATION_COMPLETE",
                context_summary="ctx",
            )
            is None
        )

    @pytest.mark.parametrize(
        "exc_name",
        ["AIClientAuthError", "AIClientTransportError", "AIClientProtocolError"],
    )
    def test_port_exceptions_collapse_to_none(self, patch_factory, exc_name: str):
        import hestai_context_mcp.ports.ai_client as port_mod

        from hestai_context_mcp.core.synthesis import synthesize_ai_context

        exc_cls = getattr(port_mod, exc_name)
        patch_factory(_StubClient(raises=exc_cls("boom")))

        assert (
            synthesize_ai_context(
                role="r",
                focus="f",
                phase="B1_FOUNDATION_COMPLETE",
                context_summary="ctx",
            )
            is None
        )

    def test_malformed_octave_collapses_to_none(self, patch_factory):
        """Missing TASKS:: field → validator rejects → fallback-trigger."""
        from hestai_context_mcp.core.synthesis import synthesize_ai_context

        bad = _valid_octave().replace("TASKS::", "TODOS::")
        patch_factory(_StubClient(text=bad))

        assert (
            synthesize_ai_context(
                role="r",
                focus="f",
                phase="B1_FOUNDATION_COMPLETE",
                context_summary="ctx",
            )
            is None
        )


class TestResolveAiSynthesisEndToEnd:
    """``resolve_ai_synthesis`` wrapper still enforces the #4 contract."""

    def test_ai_success_flows_through_wrapper(self, patch_factory):
        from hestai_context_mcp.core.synthesis import resolve_ai_synthesis

        patch_factory(_StubClient(text=_valid_octave()))
        res = resolve_ai_synthesis(
            role="r",
            focus="f",
            phase="B1_FOUNDATION_COMPLETE",
            context_summary="ctx",
        )
        assert res["source"] == "ai"
        assert "TASKS::" in res["synthesis"]

    def test_ai_auth_failure_collapses_to_fallback_via_wrapper(self, patch_factory):
        import hestai_context_mcp.ports.ai_client as port_mod

        from hestai_context_mcp.core.synthesis import resolve_ai_synthesis

        patch_factory(_StubClient(raises=port_mod.AIClientAuthError("no key")))
        res = resolve_ai_synthesis(
            role="r",
            focus="f",
            phase="B1_FOUNDATION_COMPLETE",
            context_summary="ctx",
        )
        assert res["source"] == "fallback"
        assert "FRESHNESS_WARNING::AI_SYNTHESIS_UNAVAILABLE" in res["synthesis"]
