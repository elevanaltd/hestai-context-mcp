"""Contract test: runtime-checkable conformance to the ``AIClient`` Protocol.

Prevents structural drift between the Protocol and its implementers. Any
concrete adapter or test stub purporting to be an ``AIClient`` MUST pass
``isinstance`` against the runtime-checkable Protocol.
"""

from __future__ import annotations

import httpx
import pytest

pytestmark = pytest.mark.contract


class TestProtocolConformance:
    def test_concrete_adapter_satisfies_protocol(self):
        from hestai_context_mcp.adapters.openai_compat_ai_client import (
            OpenAICompatAIClient,
        )
        from hestai_context_mcp.ports.ai_client import AIClient

        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"choices": []})

        client = OpenAICompatAIClient(
            api_key="k",
            base_url="https://openrouter.ai/api/v1",
            model="m",
            timeout_seconds=5,
            transport=httpx.MockTransport(handler),
        )
        assert isinstance(client, AIClient)

    def test_test_stub_satisfies_protocol(self):
        """Stubs used by other tests must track the Protocol (regression guard)."""
        from hestai_context_mcp.ports.ai_client import AIClient, CompletionRequest

        class _Stub:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return None

            async def complete_text(self, request: CompletionRequest) -> str:
                return "ok"

        assert isinstance(_Stub(), AIClient)

    def test_object_without_complete_text_is_not_ai_client(self):
        from hestai_context_mcp.ports.ai_client import AIClient

        class _NotClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return None

        assert isinstance(_NotClient(), AIClient) is False
