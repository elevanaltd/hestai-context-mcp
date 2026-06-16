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
    provider_payload: dict | None = None,
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
        provider_payload=provider_payload,
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

    def test_transport_parameter_is_async_base_transport(self):
        """Cubic P2: ``transport`` must be typed ``httpx.AsyncBaseTransport``.

        The underlying ``httpx.AsyncClient`` only accepts an async transport
        at runtime. Typing the parameter as the *sync* base class
        (``httpx.BaseTransport``) allowed mypy to accept mis-injected
        synchronous transports that would fail at await time.
        """
        import inspect as _inspect

        from hestai_context_mcp.adapters.openai_compat_ai_client import (
            OpenAICompatAIClient,
        )

        sig = _inspect.signature(OpenAICompatAIClient.__init__)
        transport_param = sig.parameters.get("transport")
        assert transport_param is not None, "expected `transport` keyword on __init__"
        # Annotation may be a type or a string (depending on
        # ``from __future__ import annotations`` state of the module).
        ann = transport_param.annotation
        ann_str = ann if isinstance(ann, str) else getattr(ann, "__name__", str(ann))
        assert (
            "AsyncBaseTransport" in ann_str
        ), f"transport annotation must reference AsyncBaseTransport, got {ann!r}"
        assert "BaseTransport" in ann_str  # sanity — keeps the prefix intact
        # And the sync BaseTransport MUST NOT be the sole qualifier:
        assert (
            ann_str.strip().rstrip("| None").rstrip() != "httpx.BaseTransport"
        ), "transport must not be typed as sync httpx.BaseTransport"

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
        # Issue #98: complete_text now returns a CompletionResult, not a bare str.
        assert out.content == "synthesised-octave"
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


class TestSuccessUsageAccounting:
    """Issue #98: the success path reports the provider's real usage and cost."""

    @pytest.mark.asyncio
    async def test_request_opts_into_usage_accounting(self):
        """The outgoing body asks the provider to include real usage/cost."""
        from hestai_context_mcp.ports.ai_client import CompletionRequest

        seen: dict[str, object] = {}

        def handler(req: httpx.Request) -> httpx.Response:
            seen["body"] = json.loads(req.content.decode())
            return _ok_response("x")

        client = _build_client_with_transport(handler)
        async with client as c:
            await c.complete_text(CompletionRequest(system_prompt="s", user_prompt="u"))

        body = seen["body"]
        assert isinstance(body, dict)
        assert body.get("usage") == {"include": True}

    @pytest.mark.asyncio
    async def test_success_returns_real_usage_and_cost(self):
        from hestai_context_mcp.ports.ai_client import CompletionRequest

        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {"message": {"content": "octave"}, "index": 0, "finish_reason": "stop"},
                    ],
                    "usage": {
                        "prompt_tokens": 6900,
                        "completion_tokens": 3100,
                        "total_tokens": 10000,
                        "cost": 0.0043,
                    },
                },
            )

        client = _build_client_with_transport(handler)
        async with client as c:
            out = await c.complete_text(CompletionRequest(system_prompt="s", user_prompt="u"))
        assert out.content == "octave"
        assert out.prompt_tokens == 6900
        assert out.completion_tokens == 3100
        assert out.total_tokens == 10000
        assert out.cost == 0.0043

    @pytest.mark.asyncio
    async def test_success_cost_none_when_provider_omits_it(self):
        from hestai_context_mcp.ports.ai_client import CompletionRequest

        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {"message": {"content": "octave"}, "index": 0, "finish_reason": "stop"},
                    ],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
                },
            )

        client = _build_client_with_transport(handler)
        async with client as c:
            out = await c.complete_text(CompletionRequest(system_prompt="s", user_prompt="u"))
        assert out.total_tokens == 30
        assert out.cost is None

    @pytest.mark.asyncio
    async def test_success_with_no_usage_block_has_none_usage_and_cost(self):
        from hestai_context_mcp.ports.ai_client import CompletionRequest

        client = _build_client_with_transport(lambda req: _ok_response("octave"))
        async with client as c:
            out = await c.complete_text(CompletionRequest(system_prompt="s", user_prompt="u"))
        assert out.content == "octave"
        assert out.prompt_tokens is None
        assert out.completion_tokens is None
        assert out.total_tokens is None
        assert out.cost is None

    @pytest.mark.asyncio
    async def test_negative_cost_is_treated_as_absent(self):
        """A negative cost is invalid telemetry (mirrors issue #97 token clamp)."""
        from hestai_context_mcp.ports.ai_client import CompletionRequest

        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {"message": {"content": "octave"}, "index": 0, "finish_reason": "stop"},
                    ],
                    "usage": {"total_tokens": 30, "cost": -0.5},
                },
            )

        client = _build_client_with_transport(handler)
        async with client as c:
            out = await c.complete_text(CompletionRequest(system_prompt="s", user_prompt="u"))
        assert out.cost is None


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
    async def test_408_request_timeout_maps_to_transport_error(self):
        """CE ``ce-issue5-20260420-1``: HTTP 408 is a transient condition.

        Prior behaviour collapsed any non-2xx-non-auth-non-5xx status
        into ``AIClientProtocolError``; 408 specifically must map to
        ``AIClientTransportError`` so the application layer treats the
        server-side timeout identically to a client-side timeout.
        """
        from hestai_context_mcp.ports.ai_client import (
            AIClientTransportError,
            CompletionRequest,
        )

        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(408, json={"error": "request timeout"})

        client = _build_client_with_transport(handler)
        with pytest.raises(AIClientTransportError):
            async with client as c:
                await c.complete_text(CompletionRequest(system_prompt="s", user_prompt="u"))

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


class TestProviderPayloadRouting:
    """Issue #96: a generic provider_payload is merged into the outgoing JSON.

    The adapter is provider-agnostic about *what* the payload says — it only
    knows how to attach it to the wire request. The OpenRouter-specific routing
    preference (preferred upstream order, allow_fallbacks) is sourced from
    config (ai_config), not hardcoded here, so there is no magic model-name
    branch in the adapter.
    """

    @pytest.mark.asyncio
    async def test_provider_payload_merged_into_request_body(self):
        from hestai_context_mcp.ports.ai_client import CompletionRequest

        seen: dict[str, object] = {}

        def handler(req: httpx.Request) -> httpx.Response:
            seen["body"] = json.loads(req.content.decode())
            return _ok_response("x")

        payload = {"provider": {"order": ["MiniMax"], "allow_fallbacks": True}}
        client = _build_client_with_transport(handler, provider_payload=payload)
        async with client as c:
            await c.complete_text(CompletionRequest(system_prompt="s", user_prompt="u"))

        body = seen["body"]
        assert isinstance(body, dict)
        assert body["provider"] == {"order": ["MiniMax"], "allow_fallbacks": True}
        # The core completion fields remain intact alongside the merged payload.
        assert body["model"]
        assert body["messages"]

    @pytest.mark.asyncio
    async def test_no_provider_payload_means_no_provider_key(self):
        from hestai_context_mcp.ports.ai_client import CompletionRequest

        seen: dict[str, object] = {}

        def handler(req: httpx.Request) -> httpx.Response:
            seen["body"] = json.loads(req.content.decode())
            return _ok_response("x")

        client = _build_client_with_transport(handler, provider_payload=None)
        async with client as c:
            await c.complete_text(CompletionRequest(system_prompt="s", user_prompt="u"))

        body = seen["body"]
        assert isinstance(body, dict)
        assert "provider" not in body

    @pytest.mark.asyncio
    async def test_provider_payload_does_not_overwrite_core_fields(self):
        """A payload key colliding with a reserved field must not clobber it."""
        from hestai_context_mcp.ports.ai_client import CompletionRequest

        seen: dict[str, object] = {}

        def handler(req: httpx.Request) -> httpx.Response:
            seen["body"] = json.loads(req.content.decode())
            return _ok_response("x")

        # A malicious/misconfigured payload attempting to override the model.
        payload = {"model": "evil/override", "provider": {"order": ["MiniMax"]}}
        client = _build_client_with_transport(
            handler, model="google/gemini-2.0-flash-lite", provider_payload=payload
        )
        async with client as c:
            await c.complete_text(CompletionRequest(system_prompt="s", user_prompt="u"))

        body = seen["body"]
        assert isinstance(body, dict)
        assert body["model"] == "google/gemini-2.0-flash-lite"
        assert body["provider"] == {"order": ["MiniMax"]}


class TestTruncationPath:
    """Issue #96: finish_reason='length' is budget exhaustion, not malformed.

    A reasoning model routed onto an upstream that hits the output cap returns
    a well-formed envelope with ``finish_reason='length'`` and (often) a null
    ``content``. The adapter must inspect ``finish_reason``/``usage`` BEFORE the
    ``isinstance(content, str)`` check and raise ``AIClientTruncationError``
    carrying the real tokens consumed — never collapse the spend onto a generic
    ``AIClientProtocolError`` (which would lose the cost telemetry).
    """

    @pytest.mark.asyncio
    async def test_length_with_null_content_raises_truncation_with_usage(self):
        from hestai_context_mcp.ports.ai_client import (
            AIClientTruncationError,
            CompletionRequest,
        )

        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {"message": {"content": None}, "index": 0, "finish_reason": "length"},
                    ],
                    "usage": {
                        "prompt_tokens": 200,
                        "completion_tokens": 8000,
                        "total_tokens": 8200,
                        "cost": 0.0142,
                    },
                },
            )

        client = _build_client_with_transport(handler)
        with pytest.raises(AIClientTruncationError) as excinfo:
            async with client as c:
                await c.complete_text(CompletionRequest(system_prompt="s", user_prompt="u"))
        exc = excinfo.value
        assert exc.consumed_tokens == 8200
        assert exc.prompt_tokens == 200
        assert exc.completion_tokens == 8000
        # Issue #98: the real cost is threaded into the truncation error.
        assert exc.cost == 0.0142

    @pytest.mark.asyncio
    async def test_length_takes_precedence_over_content_type_check(self):
        """finish_reason='length' wins even when content IS a (partial) string.

        Truncation must be detected from the stop condition, not inferred from a
        null body; a partial string with finish_reason='length' is still a
        truncated, untrustworthy result.
        """
        from hestai_context_mcp.ports.ai_client import (
            AIClientTruncationError,
            CompletionRequest,
        )

        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {"content": "partial text"},
                            "index": 0,
                            "finish_reason": "length",
                        },
                    ],
                    "usage": {"total_tokens": 8000},
                },
            )

        client = _build_client_with_transport(handler)
        with pytest.raises(AIClientTruncationError) as excinfo:
            async with client as c:
                await c.complete_text(CompletionRequest(system_prompt="s", user_prompt="u"))
        assert excinfo.value.consumed_tokens == 8000

    @pytest.mark.asyncio
    async def test_length_without_usage_raises_truncation_zero_tokens(self):
        """No usage block → still a truncation, consumed_tokens degrades to 0.

        Better to surface the truncation (and not retry) than to mislabel it as
        a protocol error; the cost telemetry is simply unavailable.
        """
        from hestai_context_mcp.ports.ai_client import (
            AIClientTruncationError,
            CompletionRequest,
        )

        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {"message": {"content": None}, "index": 0, "finish_reason": "length"},
                    ],
                },
            )

        client = _build_client_with_transport(handler)
        with pytest.raises(AIClientTruncationError) as excinfo:
            async with client as c:
                await c.complete_text(CompletionRequest(system_prompt="s", user_prompt="u"))
        assert excinfo.value.consumed_tokens == 0

    @pytest.mark.asyncio
    async def test_negative_usage_counts_do_not_produce_negative_tokens(self):
        """A malformed usage block with negative counts must not bill negatively.

        Issue #97 (cubic P2): negative ``prompt_tokens``/``completion_tokens`` are
        invalid telemetry — they must be treated as absent (clamped to 0), never
        flow through to a negative ``consumed_tokens`` / negative cost record. The
        accuracy this PR introduces must not be undone by a misbehaving provider.
        """
        from hestai_context_mcp.ports.ai_client import (
            AIClientTruncationError,
            CompletionRequest,
        )

        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {"message": {"content": None}, "index": 0, "finish_reason": "length"},
                    ],
                    # Negative split with no total → reconstruction must clamp.
                    "usage": {"prompt_tokens": -100, "completion_tokens": -8000},
                },
            )

        client = _build_client_with_transport(handler)
        with pytest.raises(AIClientTruncationError) as excinfo:
            async with client as c:
                await c.complete_text(CompletionRequest(system_prompt="s", user_prompt="u"))
        exc = excinfo.value
        assert exc.consumed_tokens >= 0
        assert exc.consumed_tokens == 0
        # Negative split values are invalid → reported as absent (None), not negative.
        assert exc.prompt_tokens is None
        assert exc.completion_tokens is None

    @pytest.mark.asyncio
    async def test_negative_total_tokens_is_clamped_to_zero(self):
        """A negative ``total_tokens`` is invalid and must clamp to 0, not bill."""
        from hestai_context_mcp.ports.ai_client import (
            AIClientTruncationError,
            CompletionRequest,
        )

        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {"message": {"content": None}, "index": 0, "finish_reason": "length"},
                    ],
                    "usage": {"total_tokens": -8000},
                },
            )

        client = _build_client_with_transport(handler)
        with pytest.raises(AIClientTruncationError) as excinfo:
            async with client as c:
                await c.complete_text(CompletionRequest(system_prompt="s", user_prompt="u"))
        assert excinfo.value.consumed_tokens == 0

    @pytest.mark.asyncio
    async def test_null_content_without_length_still_protocol_error(self):
        """A null content with a *non*-length stop reason stays a protocol error.

        Only ``finish_reason='length'`` is reclassified; genuinely malformed
        shapes (null content on a 'stop') keep the existing protocol-error path.
        """
        from hestai_context_mcp.ports.ai_client import (
            AIClientProtocolError,
            CompletionRequest,
        )

        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {"message": {"content": None}, "index": 0, "finish_reason": "stop"},
                    ],
                },
            )

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

    def test_factory_wires_config_sourced_provider_payload(self, monkeypatch: pytest.MonkeyPatch):
        """Issue #96: the factory injects the routing pin from ai_config.

        The vendor-specific routing preference is resolved in ``ai_config``
        (config-sourced, not a magic model-name branch) and threaded into the
        adapter constructor as the generic ``provider_payload``.
        """
        import hestai_context_mcp.adapters.ai_config as cfg
        import hestai_context_mcp.adapters.openai_compat_ai_client as adapter_mod

        class _NoKR:
            def get_password(self, *_a, **_kw):
                return None

            def set_password(self, *_a, **_kw):
                return None

            def delete_password(self, *_a, **_kw):
                return None

        monkeypatch.setattr(cfg, "keyring", _NoKR(), raising=True)
        monkeypatch.setenv("OPENROUTER_API_KEY", "ENV_KEY")

        sentinel = {"provider": {"order": ["MiniMax"], "allow_fallbacks": True}}
        monkeypatch.setattr(cfg, "resolve_provider_payload", lambda _provider: sentinel)

        captured: dict[str, object] = {}
        real_cls = adapter_mod.OpenAICompatAIClient

        def _capturing_ctor(**kwargs):
            captured.update(kwargs)
            return real_cls(**kwargs)

        monkeypatch.setattr(adapter_mod, "OpenAICompatAIClient", _capturing_ctor)
        client = adapter_mod.build_default_ai_client()
        assert client is not None
        assert captured.get("provider_payload") == sentinel

    def test_factory_raises_typeerror_if_complete_text_is_sync(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """CRS gemini follow-up: production guard for non-coroutine complete_text.

        ``runtime_checkable`` Protocol does not enforce ``async def`` —
        the factory must therefore reject any client whose
        ``complete_text`` is synchronous, otherwise the bug surfaces
        only at the first ``await`` (a TypeError deep inside the
        synthesis path).
        """
        import hestai_context_mcp.adapters.ai_config as cfg
        import hestai_context_mcp.adapters.openai_compat_ai_client as adapter_mod

        class _NoKR:
            def get_password(self, *_a, **_kw):
                return None

            def set_password(self, *_a, **_kw):
                return None

            def delete_password(self, *_a, **_kw):
                return None

        monkeypatch.setattr(cfg, "keyring", _NoKR(), raising=True)
        monkeypatch.setenv("OPENROUTER_API_KEY", "ENV_KEY")

        # Substitute a broken constructor that returns an instance whose
        # ``complete_text`` is sync — simulates a future regression where
        # someone forgets the ``async`` keyword.
        class _BrokenClient:
            def __init__(self, **_kw):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return None

            def complete_text(self, request):  # SYNC — the regression
                return "nope"

        monkeypatch.setattr(adapter_mod, "OpenAICompatAIClient", _BrokenClient)
        with pytest.raises(TypeError, match="async def"):
            adapter_mod.build_default_ai_client()


class TestBuildDefaultFactoryTierAware:
    """Issue #77: ``build_default_ai_client(tier=...)`` selects the tier model.

    The factory remains the single env-reading site; passing ``tier`` makes
    it resolve the model via ``ai_config.resolve_model(tier)``. The default
    (no ``tier`` arg) stays back-compatible with the pre-#77 behaviour.
    """

    @staticmethod
    def _no_keyring(monkeypatch: pytest.MonkeyPatch) -> None:
        import hestai_context_mcp.adapters.ai_config as cfg

        class _NoKR:
            def get_password(self, *_a, **_kw):
                return None

            def set_password(self, *_a, **_kw):
                return None

            def delete_password(self, *_a, **_kw):
                return None

        monkeypatch.setattr(cfg, "keyring", _NoKR(), raising=True)

    def test_analysis_tier_builds_client_with_analysis_model(self, monkeypatch: pytest.MonkeyPatch):
        self._no_keyring(monkeypatch)
        monkeypatch.setenv("OPENROUTER_API_KEY", "ENV_KEY")
        monkeypatch.setenv("HESTAI_AI_MODEL", "base/model")
        monkeypatch.setenv("HESTAI_AI_MODEL_ANALYSIS", "analysis/model")

        from hestai_context_mcp.adapters.openai_compat_ai_client import (
            OpenAICompatAIClient,
            build_default_ai_client,
        )

        client = build_default_ai_client(tier="analysis")
        assert isinstance(client, OpenAICompatAIClient)
        # The constructed adapter carries the analysis-tier model.
        assert client._model == "analysis/model"

    def test_default_tier_backcompat(self, monkeypatch: pytest.MonkeyPatch):
        self._no_keyring(monkeypatch)
        monkeypatch.setenv("OPENROUTER_API_KEY", "ENV_KEY")
        monkeypatch.setenv("HESTAI_AI_MODEL", "base/model")
        monkeypatch.setenv("HESTAI_AI_MODEL_ANALYSIS", "analysis/model")

        from hestai_context_mcp.adapters.openai_compat_ai_client import (
            OpenAICompatAIClient,
            build_default_ai_client,
        )

        # No tier arg -> default tier -> HESTAI_AI_MODEL (not the analysis var).
        client = build_default_ai_client()
        assert isinstance(client, OpenAICompatAIClient)
        assert client._model == "base/model"
