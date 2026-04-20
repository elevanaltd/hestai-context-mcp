"""Concrete-adapter tests for ``OpenAICompatAIClient``.

Mocks the transport layer via ``httpx.MockTransport`` (first-party; no
extra dev dependency) so that the test asserts the adapter maps provider
behaviours onto the port-layer exception taxonomy correctly:

  HTTP 401 / 403             → AIClientAuthError
  HTTP 5xx                   → AIClientTransportError
  httpx timeout / conn reset → AIClientTransportError
  Malformed JSON / missing   → AIClientProtocolError
       ``choices`` payload
  Success                    → returns raw text

PROD::I3 is locked at the port level (tests/unit/ports/...); these tests
verify the translation contract.
"""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest


def _build_client_with_transport(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    api_key: str = "test-key",
    base_url: str = "https://openrouter.ai/api/v1",
    model: str = "google/gemini-2.0-flash-lite",
    timeout: float = 5.0,
):
    """Create adapter with an injected ``httpx.MockTransport`` for tests."""
    from hestai_context_mcp.adapters.openai_compat_ai_client import (
        OpenAICompatAIClient,
    )

    transport = httpx.MockTransport(handler)
    return OpenAICompatAIClient(
        api_key=api_key,
        base_url=base_url,
        model=model,
        timeout_seconds=timeout,
        transport=transport,
    )


def _ok_response(text: str) -> httpx.Response:
    """Build a well-formed OpenAI-compat chat-completions response."""
    return httpx.Response(
        200,
        json={
            "choices": [
                {"message": {"content": text}, "index": 0, "finish_reason": "stop"},
            ],
        },
    )


class TestAdapterImplementsProtocol:
    def test_module_importable(self):
        import hestai_context_mcp.adapters.openai_compat_ai_client  # noqa: F401

    def test_adapter_satisfies_port_protocol(self):
        from hestai_context_mcp.ports.ai_client import AIClient

        client = _build_client_with_transport(lambda req: _ok_response("x"))
        assert isinstance(client, AIClient) is True


class TestSuccessPath:
    @pytest.mark.asyncio
    async def test_returns_text_on_200(self):
        from hestai_context_mcp.ports.ai_client import CompletionRequest

        calls: list[httpx.Request] = []

        def handler(req: httpx.Request) -> httpx.Response:
            calls.append(req)
            return _ok_response("synthesised-octave")

        client = _build_client_with_transport(handler)
        async with client as c:
            out = await c.complete_text(CompletionRequest(system_prompt="s", user_prompt="u"))
        assert out == "synthesised-octave"
        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_auth_header_sent(self):
        from hestai_context_mcp.ports.ai_client import CompletionRequest

        seen_headers: dict[str, str] = {}

        def handler(req: httpx.Request) -> httpx.Response:
            seen_headers.update({k.lower(): v for k, v in req.headers.items()})
            return _ok_response("x")

        client = _build_client_with_transport(handler, api_key="THE_KEY")
        async with client as c:
            await c.complete_text(CompletionRequest(system_prompt="", user_prompt=""))
        auth = seen_headers.get("authorization", "")
        assert auth == "Bearer THE_KEY"


class TestAuthErrorPath:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", [401, 403])
    async def test_auth_status_maps_to_auth_error(self, status: int):
        from hestai_context_mcp.ports.ai_client import AIClientAuthError, CompletionRequest

        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(status, json={"error": "bad key"})

        client = _build_client_with_transport(handler)
        with pytest.raises(AIClientAuthError):
            async with client as c:
                await c.complete_text(CompletionRequest(system_prompt="s", user_prompt="u"))


class TestTransportErrorPath:
    @pytest.mark.asyncio
    async def test_429_rate_limit_maps_to_transport_error(self):
        """TMG C4: HTTP 429 (Too Many Requests) is a transient condition.

        Per spec §6 all transient/server conditions collapse onto
        ``AIClientTransportError`` and application layer emits fallback.
        429 is not an auth failure (the key is valid; the quota is not),
        so it must NOT map to ``AIClientAuthError``.
        """
        from hestai_context_mcp.ports.ai_client import (
            AIClientTransportError,
            CompletionRequest,
        )

        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(429, json={"error": "rate limit"}, headers={"retry-after": "30"})

        client = _build_client_with_transport(handler)
        with pytest.raises(AIClientTransportError):
            async with client as c:
                await c.complete_text(CompletionRequest(system_prompt="s", user_prompt="u"))

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", [500, 502, 503, 504])
    async def test_server_5xx_maps_to_transport_error(self, status: int):
        from hestai_context_mcp.ports.ai_client import (
            AIClientTransportError,
            CompletionRequest,
        )

        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(status, json={"error": "boom"})

        client = _build_client_with_transport(handler)
        with pytest.raises(AIClientTransportError):
            async with client as c:
                await c.complete_text(CompletionRequest(system_prompt="s", user_prompt="u"))

    @pytest.mark.asyncio
    async def test_httpx_timeout_maps_to_transport_error(self):
        from hestai_context_mcp.ports.ai_client import (
            AIClientTransportError,
            CompletionRequest,
        )

        def handler(req: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("timed out", request=req)

        client = _build_client_with_transport(handler)
        with pytest.raises(AIClientTransportError):
            async with client as c:
                await c.complete_text(CompletionRequest(system_prompt="s", user_prompt="u"))

    @pytest.mark.asyncio
    async def test_httpx_connect_error_maps_to_transport_error(self):
        from hestai_context_mcp.ports.ai_client import (
            AIClientTransportError,
            CompletionRequest,
        )

        def handler(req: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused", request=req)

        client = _build_client_with_transport(handler)
        with pytest.raises(AIClientTransportError):
            async with client as c:
                await c.complete_text(CompletionRequest(system_prompt="s", user_prompt="u"))


class TestProtocolErrorPath:
    @pytest.mark.asyncio
    async def test_non_json_body_maps_to_protocol_error(self):
        from hestai_context_mcp.ports.ai_client import (
            AIClientProtocolError,
            CompletionRequest,
        )

        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="not-json-at-all")

        client = _build_client_with_transport(handler)
        with pytest.raises(AIClientProtocolError):
            async with client as c:
                await c.complete_text(CompletionRequest(system_prompt="s", user_prompt="u"))

    @pytest.mark.asyncio
    async def test_missing_choices_maps_to_protocol_error(self):
        from hestai_context_mcp.ports.ai_client import (
            AIClientProtocolError,
            CompletionRequest,
        )

        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"no_choices": "here"})

        client = _build_client_with_transport(handler)
        with pytest.raises(AIClientProtocolError):
            async with client as c:
                await c.complete_text(CompletionRequest(system_prompt="s", user_prompt="u"))

    @pytest.mark.asyncio
    async def test_empty_choices_maps_to_protocol_error(self):
        from hestai_context_mcp.ports.ai_client import (
            AIClientProtocolError,
            CompletionRequest,
        )

        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"choices": []})

        client = _build_client_with_transport(handler)
        with pytest.raises(AIClientProtocolError):
            async with client as c:
                await c.complete_text(CompletionRequest(system_prompt="s", user_prompt="u"))


class TestRequestShape:
    @pytest.mark.asyncio
    async def test_request_body_contains_prompts_and_model(self):
        from hestai_context_mcp.ports.ai_client import CompletionRequest

        seen: dict[str, object] = {}

        def handler(req: httpx.Request) -> httpx.Response:
            seen["body"] = json.loads(req.content.decode())
            return _ok_response("x")

        client = _build_client_with_transport(handler, model="google/gemini-2.0-flash-lite")
        async with client as c:
            await c.complete_text(
                CompletionRequest(
                    system_prompt="SYS",
                    user_prompt="USER",
                    max_tokens=42,
                    temperature=0.7,
                )
            )

        body = seen["body"]
        assert isinstance(body, dict)
        assert body["model"] == "google/gemini-2.0-flash-lite"
        # OpenAI-compat chat completions: messages=[{role, content}, ...]
        messages = body.get("messages", [])
        roles = {m.get("role"): m.get("content") for m in messages}
        assert roles.get("system") == "SYS"
        assert roles.get("user") == "USER"
        assert body.get("max_tokens") == 42
        assert body.get("temperature") == 0.7


class TestBuildDefaultFactory:
    """``build_default_ai_client`` is the single env-reading site."""

    def test_factory_exported(self):
        from hestai_context_mcp.adapters.openai_compat_ai_client import (
            build_default_ai_client,
        )

        assert callable(build_default_ai_client)

    def test_factory_returns_ai_client_when_key_present(self, monkeypatch: pytest.MonkeyPatch):
        # Ensure no keyring lookup taints this factory test:
        import hestai_context_mcp.adapters.ai_config as cfg
        from hestai_context_mcp.ports.ai_client import AIClient

        class _NoKR:
            def get_password(self, *_a, **_kw):
                return None

            def set_password(self, *_a, **_kw):
                return None

            def delete_password(self, *_a, **_kw):
                return None

        monkeypatch.setattr(cfg, "keyring", _NoKR(), raising=True)
        monkeypatch.setenv("OPENROUTER_API_KEY", "ENV_KEY")

        from hestai_context_mcp.adapters.openai_compat_ai_client import (
            build_default_ai_client,
        )

        client = build_default_ai_client()
        assert isinstance(client, AIClient)

    def test_factory_returns_none_when_no_key(self, monkeypatch: pytest.MonkeyPatch):
        import hestai_context_mcp.adapters.ai_config as cfg

        class _NoKR:
            def get_password(self, *_a, **_kw):
                return None

            def set_password(self, *_a, **_kw):
                return None

            def delete_password(self, *_a, **_kw):
                return None

        monkeypatch.setattr(cfg, "keyring", _NoKR(), raising=True)
        for var in ("OPENAI_API_KEY", "OPENROUTER_API_KEY"):
            monkeypatch.delenv(var, raising=False)

        from hestai_context_mcp.adapters.openai_compat_ai_client import (
            build_default_ai_client,
        )

        client = build_default_ai_client()
        assert client is None
