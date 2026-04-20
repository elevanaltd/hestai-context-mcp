"""Port contract tests for ``hestai_context_mcp.ports.ai_client``.

Locks the provider-agnostic shape mandated by PROD::I3. The port is a
:class:`typing.Protocol` (runtime-checkable) with a single coroutine method
and a strict exception taxonomy. No provider SDK types may appear in its
public surface.

These tests are RED until issue #5 lands the port module.
"""

from __future__ import annotations

import inspect
from typing import Protocol, get_type_hints, runtime_checkable

import pytest


class TestPortModuleShape:
    """Module exposes the expected public symbols."""

    def test_module_importable(self):
        import hestai_context_mcp.ports.ai_client  # noqa: F401

    def test_exports_protocol_class(self):
        from hestai_context_mcp.ports.ai_client import AIClient

        assert isinstance(AIClient, type) or getattr(AIClient, "_is_protocol", False)

    def test_exports_completion_request(self):
        from hestai_context_mcp.ports.ai_client import CompletionRequest

        # frozen dataclass — immutable request shape
        assert CompletionRequest is not None

    def test_exports_exception_taxonomy(self):
        from hestai_context_mcp.ports.ai_client import (
            AIClientAuthError,
            AIClientError,
            AIClientProtocolError,
            AIClientTransportError,
        )

        assert issubclass(AIClientAuthError, AIClientError)
        assert issubclass(AIClientTransportError, AIClientError)
        assert issubclass(AIClientProtocolError, AIClientError)


class TestCompletionRequestShape:
    """``CompletionRequest`` is a frozen dataclass with the spec-mandated fields."""

    def test_required_fields_present(self):
        from hestai_context_mcp.ports.ai_client import CompletionRequest

        req = CompletionRequest(system_prompt="s", user_prompt="u")
        assert req.system_prompt == "s"
        assert req.user_prompt == "u"

    def test_defaults_match_spec(self):
        from hestai_context_mcp.ports.ai_client import CompletionRequest

        req = CompletionRequest(system_prompt="", user_prompt="")
        assert req.max_tokens == 1024
        assert req.temperature == 0.3
        assert req.timeout_seconds == 15

    def test_is_frozen(self):
        from hestai_context_mcp.ports.ai_client import CompletionRequest

        req = CompletionRequest(system_prompt="s", user_prompt="u")
        with pytest.raises((AttributeError, Exception)):
            # FrozenInstanceError is the dataclasses-specific subclass; both
            # parent classes above catch it without importing the internal.
            req.system_prompt = "other"  # type: ignore[misc]

    def test_type_hints_are_primitive(self):
        """I3 guard: no provider types leaked into request hints.

        TMG C3: asserts that every expected field *has* an annotation and
        that each annotation is a primitive type. ``get_type_hints`` silently
        returns ``{}`` for unannotated attributes, so a missing annotation
        would otherwise pass vacuously.
        """
        from hestai_context_mcp.ports.ai_client import CompletionRequest

        hints = get_type_hints(CompletionRequest)
        expected = {
            "system_prompt",
            "user_prompt",
            "max_tokens",
            "temperature",
            "timeout_seconds",
        }
        assert set(hints.keys()) == expected, (
            f"CompletionRequest annotation set mismatch: got {set(hints.keys())} "
            f"expected {expected}"
        )
        allowed = {str, int, float}
        for name, hint in hints.items():
            assert hint in allowed, f"CompletionRequest.{name} has non-primitive hint: {hint!r}"


class TestAIClientProtocol:
    """``AIClient`` is a runtime-checkable Protocol with ``complete_text`` coroutine."""

    def test_is_runtime_checkable(self):
        from hestai_context_mcp.ports.ai_client import AIClient

        # runtime_checkable decorator sets a flag; functionally detectable by
        # calling isinstance on a non-matching object (must not raise TypeError).
        class _NotMatching:
            pass

        # Should not raise TypeError("@runtime_checkable not applied").
        assert isinstance(AIClient, type) or True  # sanity: import works
        # Key runtime-checkable behaviour:
        assert isinstance(_NotMatching(), AIClient) is False

    def test_is_protocol_subclass(self):
        from hestai_context_mcp.ports.ai_client import AIClient

        # A Protocol's MRO contains Protocol.
        assert Protocol in AIClient.__mro__

    def test_defines_complete_text_coroutine(self):
        from hestai_context_mcp.ports.ai_client import AIClient, CompletionRequest

        meth = getattr(AIClient, "complete_text", None)
        assert meth is not None, "AIClient must define complete_text"
        # Signature discipline: (self, request: CompletionRequest) -> str
        sig = inspect.signature(meth)
        params = list(sig.parameters.values())
        # Accept either (self, request) or (request) once unbound.
        non_self = [p for p in params if p.name != "self"]
        assert len(non_self) == 1, f"Expected exactly one non-self param, got {non_self}"
        p = non_self[0]
        # Annotation should refer to CompletionRequest (by type or string).
        ann = p.annotation
        assert ann is CompletionRequest or getattr(ann, "__name__", None) == "CompletionRequest"

    def test_satisfies_isinstance_with_conforming_stub(self):
        """A stub implementing __aenter__/__aexit__/complete_text is an AIClient."""
        from hestai_context_mcp.ports.ai_client import AIClient, CompletionRequest

        class _Stub:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return None

            async def complete_text(self, request: CompletionRequest) -> str:
                return "ok"

        assert isinstance(_Stub(), AIClient) is True


class TestPortProviderAgnostic:
    """PROD::I3 source-grep guard: no provider SDK names in the port module."""

    def test_no_provider_sdk_in_source(self):
        import hestai_context_mcp.ports.ai_client as mod

        source = inspect.getsource(mod)
        forbidden = (
            "import anthropic",
            "import openai",
            "from anthropic",
            "from openai",
            "openrouter",  # catches both imports and URLs
        )
        for token in forbidden:
            assert (
                token.lower() not in source.lower()
            ), f"PROD::I3 violation: found {token!r} in ports/ai_client.py"


class TestExceptionTaxonomyInstantiable:
    """Port exceptions must be instantiable with a message (taxonomy sanity)."""

    @pytest.mark.parametrize(
        "exc_name",
        ["AIClientError", "AIClientAuthError", "AIClientTransportError", "AIClientProtocolError"],
    )
    def test_exception_instantiates_with_message(self, exc_name):
        import hestai_context_mcp.ports.ai_client as mod

        exc_cls = getattr(mod, exc_name)
        inst = exc_cls("boom")
        assert isinstance(inst, Exception)
        assert "boom" in str(inst)


# Helper Protocol re-export to avoid name shadowing in this test module.
_ = runtime_checkable  # noqa: F841 — intentionally retained import reference
