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

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", [400, 404, 422])
    async def test_deterministic_non_200_status_is_not_retried(self, status: int):
        """Critical-engineer (#1186): a 4xx 'protocol surprise' is NOT the flaky
        malformed-body signature — it fails identically on every attempt, so the
        retry loop must NOT re-issue it. It raises the plain AIClientProtocolError
        base (not the retryable _MalformedBodyError subclass) and propagates on
        the first response.
        """
        from hestai_context_mcp.ports.ai_client import (
            AIClientProtocolError,
            CompletionRequest,
        )

        calls: list[httpx.Request] = []

        def handler(req: httpx.Request) -> httpx.Response:
            calls.append(req)
            return httpx.Response(status, json={"error": "client error"})

        sleep = _SleepSpy()
        client = _build_client_with_transport(
            handler, max_attempts=3, retry_backoff_seconds=0.0, sleep=sleep
        )
        with pytest.raises(AIClientProtocolError) as excinfo:
            async with client as c:
                await c.complete_text(CompletionRequest(system_prompt="s", user_prompt="u"))

        # Exactly one POST — no pointless re-issue of a deterministic failure.
        assert len(calls) == 1
        assert sleep.calls == []
        # Surfaces the unexpected-status message, not the generic exhaustion text.
        assert "unexpected HTTP status" in str(excinfo.value)
        assert "after" not in str(excinfo.value)  # not the exhaustion message


class TestAllMalformed200ShapesAreRetried:
    """Every malformed-200 BODY shape is the transient signature → retried.

    Pins the retry-eligible set precisely: non-JSON body, missing/empty
    ``choices``, non-object ``choices[0]``, non-object ``message``, and non-string
    ``content``. Each malformed-then-valid sequence must SUCCEED on the retry.
    """

    @staticmethod
    def _malformed_then_ok(first: httpx.Response):
        responses = [first, _ok_response("recovered")]
        calls: list[httpx.Request] = []

        def handler(req: httpx.Request) -> httpx.Response:
            calls.append(req)
            return responses[len(calls) - 1]

        return handler, calls

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "first_response",
        [
            httpx.Response(200, text="not-json-at-all"),
            httpx.Response(200, json={"no_choices": "here"}),
            httpx.Response(200, json={"choices": []}),
            httpx.Response(200, json={"choices": ["not-an-object"]}),
            httpx.Response(200, json={"choices": [{"message": "not-an-object"}]}),
            httpx.Response(200, json={"choices": [{"message": None}]}),
            # CRS (#1186): a truthy NON-LIST ``choices`` (dict/scalar) must NOT
            # leak a raw KeyError/TypeError past the port taxonomy — it is a
            # malformed body and must surface as the retryable _MalformedBodyError.
            httpx.Response(200, json={"choices": {"message": {"content": "x"}}}),
            httpx.Response(200, json={"choices": 1}),
            httpx.Response(200, json={"choices": True}),
            httpx.Response(
                200,
                json={"choices": [{"message": {"content": None}, "finish_reason": "stop"}]},
            ),
        ],
        ids=[
            "non_json_body",
            "missing_choices",
            "empty_choices",
            "choices0_not_object",
            "message_not_object",
            "message_null",
            "choices_dict_not_list",
            "choices_scalar_int",
            "choices_scalar_bool",
            "content_not_string",
        ],
    )
    async def test_malformed_200_shape_is_retried_then_succeeds(
        self, first_response: httpx.Response
    ):
        from hestai_context_mcp.ports.ai_client import CompletionRequest

        handler, calls = self._malformed_then_ok(first_response)
        sleep = _SleepSpy()
        client = _build_client_with_transport(
            handler, max_attempts=3, retry_backoff_seconds=0.0, sleep=sleep
        )
        async with client as c:
            out = await c.complete_text(CompletionRequest(system_prompt="s", user_prompt="u"))

        assert out.content == "recovered"
        assert len(calls) == 2  # retried exactly once, then succeeded
        assert len(sleep.calls) == 1

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "choices_value",
        [{"message": {"content": "x"}}, 1, True, "a-string"],
        ids=["dict", "int", "bool", "str"],
    )
    async def test_truthy_non_list_choices_surfaces_as_port_protocol_error(
        self, choices_value: object
    ):
        """CRS (#1186): a truthy non-list ``choices`` must surface through the port
        exception taxonomy (AIClientProtocolError), never as a raw KeyError /
        TypeError that bypasses every caller's ``except AIClientError`` fallback.
        With all attempts malformed it must raise the clearer exhaustion error.
        """
        from hestai_context_mcp.ports.ai_client import (
            AIClientProtocolError,
            CompletionRequest,
        )

        calls: list[httpx.Request] = []

        def handler(req: httpx.Request) -> httpx.Response:
            calls.append(req)
            return httpx.Response(200, json={"choices": choices_value})

        sleep = _SleepSpy()
        client = _build_client_with_transport(
            handler, max_attempts=2, retry_backoff_seconds=0.0, sleep=sleep
        )
        # Must be a port-taxonomy error, NOT a raw KeyError/TypeError.
        with pytest.raises(AIClientProtocolError):
            async with client as c:
                await c.complete_text(CompletionRequest(system_prompt="s", user_prompt="u"))
        # And it is the retryable signature: both attempts were issued.
        assert len(calls) == 2


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

    @pytest.mark.asyncio
    async def test_default_budget_tolerates_one_transient_malformed(self):
        """Behavioural proof the DEFAULT budget retries (MIP: >1 attempt).

        With no retry knobs supplied, a single malformed-then-valid sequence must
        still recover — pinning that the shipped default is >1 attempt without
        reaching into the private ``_max_attempts`` attribute.
        """
        from hestai_context_mcp.ports.ai_client import CompletionRequest

        responses = [_malformed_response(), _ok_response("default-recovered")]
        calls: list[httpx.Request] = []

        def handler(req: httpx.Request) -> httpx.Response:
            calls.append(req)
            return responses[len(calls) - 1]

        # Inject only the sleep spy so no real backoff elapses; attempts/backoff
        # use the shipped defaults.
        sleep = _SleepSpy()
        client = _build_client_with_transport(handler, sleep=sleep)
        async with client as c:
            out = await c.complete_text(CompletionRequest(system_prompt="s", user_prompt="u"))

        assert out.content == "default-recovered"
        assert len(calls) == 2

    @pytest.mark.asyncio
    async def test_max_attempts_one_disables_retry(self):
        """``max_attempts=1`` makes exactly one POST and never retries/sleeps."""
        from hestai_context_mcp.ports.ai_client import (
            AIClientProtocolError,
            CompletionRequest,
        )

        calls: list[httpx.Request] = []

        def handler(req: httpx.Request) -> httpx.Response:
            calls.append(req)
            return _malformed_response()

        sleep = _SleepSpy()
        client = _build_client_with_transport(handler, max_attempts=1, sleep=sleep)
        with pytest.raises(AIClientProtocolError):
            async with client as c:
                await c.complete_text(CompletionRequest(system_prompt="s", user_prompt="u"))

        assert len(calls) == 1
        assert sleep.calls == []

    @pytest.mark.asyncio
    async def test_max_attempts_zero_is_clamped_to_one_call(self):
        """A misconfigured ``max_attempts=0`` clamps to 1 — the request still fires.

        The clamp guarantees a bad config can never silently disable the call.
        """
        from hestai_context_mcp.ports.ai_client import (
            AIClientProtocolError,
            CompletionRequest,
        )

        calls: list[httpx.Request] = []

        def handler(req: httpx.Request) -> httpx.Response:
            calls.append(req)
            return _malformed_response()

        sleep = _SleepSpy()
        client = _build_client_with_transport(handler, max_attempts=0, sleep=sleep)
        with pytest.raises(AIClientProtocolError):
            async with client as c:
                await c.complete_text(CompletionRequest(system_prompt="s", user_prompt="u"))

        assert len(calls) == 1
        assert sleep.calls == []


class TestMisuseGuardIsNotRetried:
    @pytest.mark.asyncio
    async def test_complete_text_outside_async_with_raises_immediately(self):
        """Calling ``complete_text`` without entering ``async with`` is a misuse
        (programming error, not a transient flake) and must raise immediately —
        it must NOT be swallowed and re-issued by the retry loop.
        """
        from hestai_context_mcp.ports.ai_client import (
            AIClientProtocolError,
            CompletionRequest,
        )

        calls: list[httpx.Request] = []

        def handler(req: httpx.Request) -> httpx.Response:
            calls.append(req)
            return _ok_response("never-reached")

        sleep = _SleepSpy()
        client = _build_client_with_transport(handler, sleep=sleep)
        # NOTE: deliberately NOT using ``async with`` — the client is never opened.
        with pytest.raises(AIClientProtocolError, match="async-with"):
            await client.complete_text(CompletionRequest(system_prompt="s", user_prompt="u"))

        assert calls == []  # no POST ever issued
        assert sleep.calls == []  # not retried
