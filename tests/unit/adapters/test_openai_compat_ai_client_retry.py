"""Bounded-retry tests for ``OpenAICompatAIClient.complete_text`` (issue #1186).

A real provider intermittently returns a 200-OK body whose
``choices[0].message.content`` is not a string (a transient malformed-response
signature). The SAME prose input that fails on one call compiles on the next, so
the adapter must retry the *narrow* transient-malformed-response case a bounded
number of times before surfacing a clearer, actionable error.

PLACEMENT (operator-ratified): the retry lives in the adapter (``complete_text``),
below the ``AIClient`` port — honouring the port invariant that "retries ... live
below this port, in the adapter/config layer" (``ports/ai_client.py``). Callers
(``core/intake_compiler``) stay unchanged.

SCOPE GUARDRAILS asserted here:
    * RETRY only on ``AIClientProtocolError`` from a malformed 200-OK body.
    * NO retry on ``AIClientAuthError`` (permanent), ``AIClientTransportError``
      (port says "do not retry within the request"), or
      ``AIClientTruncationError`` (re-issue would re-truncate and burn budget).
    * Backoff is injected so tests never block on real wall-clock seconds.
    * No spend leakage: a malformed body carries no usage, so a successful retry
      reports only the *winning* response's usage.

Transport is injected via ``httpx.MockTransport`` (first-party; no network).
"""

from __future__ import annotations

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
    **adapter_kwargs: object,
):
    """Create the adapter with an injected ``httpx.MockTransport``.

    ``adapter_kwargs`` forwards retry-tuning knobs (``max_attempts``,
    ``retry_backoff_seconds``, ``sleep``) so tests stay deterministic and fast.
    """
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
        **adapter_kwargs,
    )


def _malformed_response() -> httpx.Response:
    """A 200-OK body whose ``content`` is not a string (the #1186 signature)."""
    return httpx.Response(
        200,
        json={
            "choices": [
                {"message": {"content": None}, "index": 0, "finish_reason": "stop"},
            ],
        },
    )


def _ok_response(text: str, **usage: int) -> httpx.Response:
    body: dict[str, object] = {
        "choices": [
            {"message": {"content": text}, "index": 0, "finish_reason": "stop"},
        ],
    }
    if usage:
        body["usage"] = usage
    return httpx.Response(200, json=body)


class _SleepSpy:
    """Records backoff durations without sleeping for real."""

    def __init__(self) -> None:
        self.calls: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


class TestRetrySucceedsAfterTransientMalformed:
    @pytest.mark.asyncio
    async def test_malformed_twice_then_valid_returns_content(self):
        """Two malformed 200-OK bodies then a valid one → ultimately SUCCEEDS."""
        from hestai_context_mcp.ports.ai_client import CompletionRequest

        responses = [
            _malformed_response(),
            _malformed_response(),
            _ok_response("recovered-octave", prompt_tokens=5, completion_tokens=7, total_tokens=12),
        ]
        calls: list[httpx.Request] = []

        def handler(req: httpx.Request) -> httpx.Response:
            calls.append(req)
            return responses[len(calls) - 1]

        sleep = _SleepSpy()
        client = _build_client_with_transport(
            handler, max_attempts=3, retry_backoff_seconds=0.01, sleep=sleep
        )
        async with client as c:
            out = await c.complete_text(CompletionRequest(system_prompt="s", user_prompt="u"))

        # Retry proved: three transport calls, final valid content returned.
        assert out.content == "recovered-octave"
        assert len(calls) == 3
        # No spend leakage: usage reflects only the WINNING response.
        assert out.total_tokens == 12
        assert out.prompt_tokens == 5
        assert out.completion_tokens == 7
        # Backoff was applied between attempts (two gaps), never after success.
        assert sleep.calls == [0.01, 0.01]

    @pytest.mark.asyncio
    async def test_malformed_once_then_valid_retries_exactly_once(self):
        from hestai_context_mcp.ports.ai_client import CompletionRequest

        responses = [_malformed_response(), _ok_response("ok")]
        calls: list[httpx.Request] = []

        def handler(req: httpx.Request) -> httpx.Response:
            calls.append(req)
            return responses[len(calls) - 1]

        sleep = _SleepSpy()
        client = _build_client_with_transport(
            handler, max_attempts=3, retry_backoff_seconds=0.0, sleep=sleep
        )
        async with client as c:
            out = await c.complete_text(CompletionRequest(system_prompt="s", user_prompt="u"))

        assert out.content == "ok"
        assert len(calls) == 2
        assert len(sleep.calls) == 1


class TestRetryExhaustion:
    @pytest.mark.asyncio
    async def test_all_malformed_raises_clearer_error_after_exhaustion(self):
        """Every attempt malformed → AIClientProtocolError with an ACTIONABLE msg."""
        from hestai_context_mcp.ports.ai_client import (
            AIClientProtocolError,
            CompletionRequest,
        )

        calls: list[httpx.Request] = []

        def handler(req: httpx.Request) -> httpx.Response:
            calls.append(req)
            return _malformed_response()

        sleep = _SleepSpy()
        client = _build_client_with_transport(
            handler, max_attempts=3, retry_backoff_seconds=0.0, sleep=sleep
        )
        with pytest.raises(AIClientProtocolError) as excinfo:
            async with client as c:
                await c.complete_text(CompletionRequest(system_prompt="s", user_prompt="u"))

        # Exhausted all attempts.
        assert len(calls) == 3
        msg = str(excinfo.value)
        # The clearer message must be actionable, mention the attempt count, and
        # NOT be the raw low-level "is not a string" string.
        assert "3 attempt" in msg
        assert "octave_content" in msg
        assert "is not a string" not in msg
        # Underlying detail is preserved on the exception chain.
        assert excinfo.value.__cause__ is not None
        assert "is not a string" in str(excinfo.value.__cause__)
        # Slept once per inter-attempt gap (2 gaps for 3 attempts).
        assert len(sleep.calls) == 2


class TestNoRetryOnPermanentOrDistinctErrors:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", [401, 403])
    async def test_auth_error_is_not_retried(self, status: int):
        from hestai_context_mcp.ports.ai_client import (
            AIClientAuthError,
            CompletionRequest,
        )

        calls: list[httpx.Request] = []

        def handler(req: httpx.Request) -> httpx.Response:
            calls.append(req)
            return httpx.Response(status, json={"error": "bad key"})

        sleep = _SleepSpy()
        client = _build_client_with_transport(
            handler, max_attempts=3, retry_backoff_seconds=0.0, sleep=sleep
        )
        with pytest.raises(AIClientAuthError):
            async with client as c:
                await c.complete_text(CompletionRequest(system_prompt="s", user_prompt="u"))

        assert len(calls) == 1  # immediate, no retry
        assert sleep.calls == []

    @pytest.mark.asyncio
    async def test_truncation_error_is_not_retried(self):
        from hestai_context_mcp.ports.ai_client import (
            AIClientTruncationError,
            CompletionRequest,
        )

        calls: list[httpx.Request] = []

        def handler(req: httpx.Request) -> httpx.Response:
            calls.append(req)
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
                    },
                },
            )

        sleep = _SleepSpy()
        client = _build_client_with_transport(
            handler, max_attempts=3, retry_backoff_seconds=0.0, sleep=sleep
        )
        with pytest.raises(AIClientTruncationError) as excinfo:
            async with client as c:
                await c.complete_text(CompletionRequest(system_prompt="s", user_prompt="u"))

        assert len(calls) == 1  # re-issue would re-truncate and burn budget
        assert sleep.calls == []
        # Real tokens preserved through the (unretried) error.
        assert excinfo.value.consumed_tokens == 8200

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", [429, 500, 503])
    async def test_transport_error_is_not_retried_within_request(self, status: int):
        """Port contract: transport failures are not retried within the request."""
        from hestai_context_mcp.ports.ai_client import (
            AIClientTransportError,
            CompletionRequest,
        )

        calls: list[httpx.Request] = []

        def handler(req: httpx.Request) -> httpx.Response:
            calls.append(req)
            return httpx.Response(status, json={"error": "boom"})

        sleep = _SleepSpy()
        client = _build_client_with_transport(
            handler, max_attempts=3, retry_backoff_seconds=0.0, sleep=sleep
        )
        with pytest.raises(AIClientTransportError):
            async with client as c:
                await c.complete_text(CompletionRequest(system_prompt="s", user_prompt="u"))

        assert len(calls) == 1
        assert sleep.calls == []

    @pytest.mark.asyncio
    async def test_network_exception_is_not_retried_within_request(self):
        from hestai_context_mcp.ports.ai_client import (
            AIClientTransportError,
            CompletionRequest,
        )

        calls: list[httpx.Request] = []

        def handler(req: httpx.Request) -> httpx.Response:
            calls.append(req)
            raise httpx.ConnectError("refused", request=req)

        sleep = _SleepSpy()
        client = _build_client_with_transport(
            handler, max_attempts=3, retry_backoff_seconds=0.0, sleep=sleep
        )
        with pytest.raises(AIClientTransportError):
            async with client as c:
                await c.complete_text(CompletionRequest(system_prompt="s", user_prompt="u"))

        assert len(calls) == 1
        assert sleep.calls == []


class TestRetryDefaultsAndBackCompat:
    @pytest.mark.asyncio
    async def test_success_on_first_attempt_never_sleeps(self):
        """The happy path is unchanged: one call, no backoff."""
        from hestai_context_mcp.ports.ai_client import CompletionRequest

        calls: list[httpx.Request] = []

        def handler(req: httpx.Request) -> httpx.Response:
            calls.append(req)
            return _ok_response("first-try")

        sleep = _SleepSpy()
        client = _build_client_with_transport(handler, sleep=sleep)
        async with client as c:
            out = await c.complete_text(CompletionRequest(system_prompt="s", user_prompt="u"))

        assert out.content == "first-try"
        assert len(calls) == 1
        assert sleep.calls == []

    def test_default_max_attempts_is_bounded_and_small(self):
        """A sensible bounded default exists (MIP): >1 to retry, but small."""
        client = _build_client_with_transport(lambda req: _ok_response("x"))
        assert 2 <= client._max_attempts <= 3
