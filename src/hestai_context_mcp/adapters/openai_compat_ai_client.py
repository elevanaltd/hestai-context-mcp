"""OpenAI-compatible HTTP adapter for the :class:`AIClient` port.

Speaks the OpenAI Chat Completions protocol over an injected
``httpx.AsyncClient``. Works against any provider exposing the same
endpoint shape (e.g. OpenAI, OpenRouter). Provider-selection and
credential resolution live in :mod:`ai_config`; this module is the
single place that knows the wire protocol.

Responsibilities:
    * Implement the :class:`AIClient` Protocol.
    * Translate ``httpx`` exceptions and HTTP status codes into the
      port-layer exception taxonomy
      (:class:`AIClientAuthError`, :class:`AIClientTransportError`,
      :class:`AIClientProtocolError`).
    * Nothing else. Validation of response *bodies* (OCTAVE schema,
      content policy, etc.) is an application-layer concern.

Design notes:
    * The async context manager wraps the underlying ``httpx``
      client's lifecycle. Callers are expected to ``async with`` the
      adapter (the Protocol signature requires it).
    * A ``transport`` keyword is accepted to support test injection
      via ``httpx.MockTransport``. Production callers leave it
      defaulted.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from types import TracebackType
from typing import cast

import httpx

from hestai_context_mcp.adapters import ai_config
from hestai_context_mcp.ports.ai_client import (
    AIClient,
    AIClientAuthError,
    AIClientProtocolError,
    AIClientTransportError,
    AIClientTruncationError,
    CompletionRequest,
    CompletionResult,
)

logger = logging.getLogger(__name__)

__all__ = [
    "OpenAICompatAIClient",
    "build_default_ai_client",
]

# Issue #1186: bounded retry for the transient malformed-response signature.
# Some providers intermittently return a 200-OK body whose
# ``choices[0].message.content`` is not a string (or whose ``choices`` shape is
# otherwise malformed) for an input that compiles fine on the very next call.
# A small bounded retry below the port turns that flake into a success without
# changing any caller. Kept minimal (MIP): a sensible hardcoded default rather
# than a new env knob — the values are constructor-overridable for tests.
_DEFAULT_MAX_ATTEMPTS = 3
_DEFAULT_RETRY_BACKOFF_SECONDS = 0.5


class _MalformedBodyError(AIClientProtocolError):
    """Adapter-private marker: a 200-OK response whose BODY shape is malformed.

    Issue #1186: this is the *transient* protocol failure worth retrying — the
    provider returned HTTP 200 but the JSON envelope was unparseable or shaped
    wrong (non-JSON body, missing/empty ``choices``, non-object ``choices[0]`` /
    ``message``, or non-string ``content``). The SAME input typically compiles on
    the next attempt, so the retry loop re-issues ONLY this subclass.

    Deliberately a *subclass* of :class:`AIClientProtocolError` so callers and
    the port contract are unchanged (it still surfaces as a protocol error). A
    *deterministic* protocol surprise — an unexpected non-200 status such as 400
    / 404 / 422 — keeps raising the plain ``AIClientProtocolError`` base, which
    the retry loop does NOT catch: re-issuing a 4xx would burn latency/budget for
    a guaranteed-identical failure (critical-engineer review, #1186).
    """


@dataclass(frozen=True)
class _Usage:
    """Adapter-internal parsed view of a provider ``usage`` block.

    Distinct from the port's :class:`CompletionResult`: this is a transient
    parse result used to build both the success result and the truncation error.
    """

    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    cost: float | None = None


def _coerce_non_negative_int(value: object) -> int | None:
    """Return ``value`` if it is a non-negative, non-bool int, else ``None``.

    Issue #97: a negative count is invalid telemetry — treat it as absent so it
    can never bill negative tokens.
    """
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _coerce_non_negative_float(value: object) -> float | None:
    """Return ``value`` as a non-negative float, else ``None``.

    Accepts int or float (but not bool). A negative or non-numeric cost is
    invalid telemetry and degrades to ``None`` so the caller falls back to its
    labelled estimate rather than reporting a bogus actual (issue #98).
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and value >= 0:
        return float(value)
    return None


class OpenAICompatAIClient:
    """Concrete :class:`AIClient` over HTTP using the OpenAI chat-completions shape."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: float = 15.0,
        transport: httpx.AsyncBaseTransport | None = None,
        provider_payload: dict[str, object] | None = None,
        max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
        retry_backoff_seconds: float = _DEFAULT_RETRY_BACKOFF_SECONDS,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout_seconds = float(timeout_seconds)
        # Issue #1186: bounded retry for the transient malformed-response
        # signature. ``max_attempts`` is the TOTAL number of POSTs (clamped to a
        # floor of 1 so a misconfiguration can never disable the request). The
        # backoff between attempts and the sleep coroutine are injectable so the
        # retry loop is deterministic and instant under test (no real seconds).
        self._max_attempts = max(1, int(max_attempts))
        self._retry_backoff_seconds = max(0.0, float(retry_backoff_seconds))
        self._sleep: Callable[[float], Awaitable[None]] = sleep or asyncio.sleep
        # Issue #96: a generic, opaque payload merged into every outgoing
        # /chat/completions body (e.g. OpenRouter ``provider`` routing
        # preferences). The adapter is agnostic about its contents; the
        # vendor-specific shape is sourced from config (see
        # ``build_default_ai_client``), keeping any provider/model magic-string
        # branch out of this wire-protocol layer. Reserved completion keys
        # (model/messages/max_tokens/temperature) are never overridden.
        self._provider_payload = provider_payload
        # A test-only transport (``httpx.MockTransport`` is acceptable
        # because it implements ``AsyncBaseTransport`` for async clients)
        # may be injected; otherwise the real network transport is used.
        # Cubic-dev-ai P2: typing the parameter as the *async* base
        # transport prevents mypy from accepting a sync transport that
        # would crash at the first ``await`` against ``AsyncClient``.
        self._transport = transport
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> OpenAICompatAIClient:
        kwargs: dict[str, object] = {
            "base_url": self._base_url,
            "timeout": self._timeout_seconds,
            "headers": {
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
        }
        if self._transport is not None:
            kwargs["transport"] = self._transport
        self._client = httpx.AsyncClient(**kwargs)  # type: ignore[arg-type]
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def complete_text(self, request: CompletionRequest) -> CompletionResult:
        """Execute a chat completion call and return content + real usage/cost.

        Issue #1186: a transient malformed 200-OK body (``_MalformedBodyError``
        — e.g. non-JSON body, missing/empty ``choices``, or ``content`` not a
        string) is retried up to ``max_attempts`` total POSTs with a small
        backoff. The retry is deliberately NARROW: only ``_MalformedBodyError``
        (the malformed-200-body subclass of ``AIClientProtocolError``) re-issues
        the call. ``AIClientAuthError`` (permanent), ``AIClientTransportError``
        (the port contract says "do not retry within the request"),
        ``AIClientTruncationError`` (a re-issue would re-truncate and burn
        budget), AND a deterministic non-200 protocol surprise (the plain
        ``AIClientProtocolError`` base, e.g. 400/404/422 — fails identically
        every time) all propagate immediately on the first occurrence. On
        exhaustion a clearer, actionable ``AIClientProtocolError`` is raised,
        preserving the underlying detail on the exception chain.
        """
        if self._client is None:
            # Guarded by the async-context-manager contract; defensive here so
            # misuse fails predictably (and is NOT swallowed by the retry loop —
            # this is a programming error, not a transient provider flake).
            raise AIClientProtocolError("OpenAICompatAIClient used outside an async-with block")
        last_protocol_error: _MalformedBodyError | None = None
        for attempt in range(1, self._max_attempts + 1):
            try:
                return await self._attempt_completion(request)
            except _MalformedBodyError as exc:
                # Transient malformed 200-OK body: retry the whole call until the
                # budget is exhausted. Auth, transport, truncation, AND a
                # deterministic non-200 protocol surprise (plain
                # AIClientProtocolError, e.g. 400/404/422) are NOT caught here, so
                # they propagate immediately without a pointless re-issue.
                last_protocol_error = exc
                if attempt < self._max_attempts:
                    logger.warning(
                        "provider returned a malformed response (attempt %d/%d): %s; retrying",
                        attempt,
                        self._max_attempts,
                        exc,
                    )
                    await self._sleep(self._retry_backoff_seconds)
        # Exhausted every attempt on the malformed-response signature. Surface a
        # clearer, actionable error while preserving the low-level cause.
        raise AIClientProtocolError(
            f"provider returned an unparseable response after {self._max_attempts} attempts; "
            "retry later or resubmit in octave_content mode"
        ) from last_protocol_error

    async def _attempt_completion(self, request: CompletionRequest) -> CompletionResult:
        """Single POST + response interpretation (one attempt of the retry loop).

        ``complete_text`` has already verified the async-context-manager contract
        (``self._client`` is open) before entering the retry loop, so the guard
        below is purely a type-narrowing assertion for mypy — it is never the
        live failure path.
        """
        assert self._client is not None  # narrowed by complete_text's guard
        payload: dict[str, object] = {}
        if self._provider_payload:
            # Merge the opaque config-sourced payload first so the reserved
            # completion fields below always win (a misconfigured payload must
            # never redirect the model or clobber the messages).
            payload.update(self._provider_payload)
        payload.update(
            {
                "model": self._model,
                "messages": [
                    {"role": "system", "content": request.system_prompt},
                    {"role": "user", "content": request.user_prompt},
                ],
                "max_tokens": request.max_tokens,
                "temperature": request.temperature,
            }
        )
        timeout = httpx.Timeout(float(request.timeout_seconds))
        try:
            response = await self._client.post(
                "/chat/completions",
                json=payload,
                timeout=timeout,
            )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            # TimeoutException covers read/connect/write/pool timeouts;
            # NetworkError covers ConnectError / ReadError / WriteError
            # / ProtocolError / RemoteProtocolError. All transient.
            raise AIClientTransportError(f"transport failure: {exc}") from exc
        except httpx.HTTPError as exc:
            # Any remaining httpx error (e.g. ``DecodeError``) is
            # transient from the caller's perspective.
            raise AIClientTransportError(f"http error: {exc}") from exc

        return self._interpret_response(response)

    def _interpret_response(self, response: httpx.Response) -> CompletionResult:
        status = response.status_code
        if status in (401, 403):
            # Do NOT include the response body — it may contain the key
            # or a hint that is sensitive.
            raise AIClientAuthError(f"provider rejected credential (HTTP {status})")
        # 408 (Request Timeout), 429 (Too Many Requests), and all 5xx
        # are transient conditions the application must retry via the
        # next request (not within this one). CE review
        # ``ce-issue5-20260420-1`` explicitly flagged 408.
        if status in (408, 429) or 500 <= status < 600:
            raise AIClientTransportError(f"provider returned HTTP {status}")
        if status != 200:
            # Unknown non-2xx (e.g. 400/404/422): a DETERMINISTIC protocol
            # surprise, NOT the transient malformed-body signature. Raise the
            # plain base so the #1186 retry loop does NOT re-issue it — a 4xx will
            # fail identically on every attempt (critical-engineer review).
            raise AIClientProtocolError(f"unexpected HTTP status from provider: {status}")
        # --- Everything below is a 200-OK whose BODY shape is malformed: the
        # transient signature the #1186 retry loop re-issues (_MalformedBodyError).
        try:
            body = response.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise _MalformedBodyError(f"provider returned non-JSON body: {exc}") from exc
        choices = body.get("choices") if isinstance(body, dict) else None
        # Validate the CONTAINER type before indexing: a truthy non-list value
        # (e.g. a dict or scalar) would otherwise raise a raw KeyError/TypeError
        # that escapes the port exception taxonomy and bypasses both this retry
        # loop and every caller's ``except AIClientError`` fallback (CRS, #1186).
        if not isinstance(choices, list) or not choices:
            raise _MalformedBodyError("provider response missing or empty 'choices' array")
        first = choices[0]
        if not isinstance(first, dict):
            raise _MalformedBodyError("provider response 'choices[0]' is not an object")
        message = first.get("message")
        if not isinstance(message, dict):
            raise _MalformedBodyError("provider response 'choices[0].message' is not an object")
        # Issue #96: inspect the stop condition BEFORE the content type-check.
        # ``finish_reason == "length"`` means the generation hit the output-token
        # cap (budget exhaustion) — a well-formed envelope whose body is
        # incomplete or null. This is a distinct, actionable condition, not a
        # malformed response, so it must surface as ``AIClientTruncationError``
        # carrying the real tokens billed. We deliberately do NOT fall back to
        # ``reasoning``/``reasoning_content``: surfacing chain-of-thought as a
        # compiled artifact is a safety hazard for governance content.
        usage = self._extract_usage(body)
        finish_reason = first.get("finish_reason")
        if finish_reason == "length":
            raise AIClientTruncationError(
                "provider truncated output at the token cap (finish_reason='length')",
                consumed_tokens=usage.total_tokens or 0,
                prompt_tokens=usage.prompt_tokens,
                completion_tokens=usage.completion_tokens,
                cost=usage.cost,
            )
        content = message.get("content")
        if not isinstance(content, str):
            raise _MalformedBodyError(
                "provider response 'choices[0].message.content' is not a string"
            )
        # Issue #98: return the provider's real usage + cost alongside content so
        # the application layer reports accurate metrics, not local estimates.
        return CompletionResult(
            content=content,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            total_tokens=usage.total_tokens,
            cost=usage.cost,
        )

    @staticmethod
    def _extract_usage(body: object) -> _Usage:
        """Pull real token counts and cost from an OpenAI-compat ``usage`` block.

        Returns a :class:`_Usage` carrying ``total_tokens`` / ``prompt_tokens`` /
        ``completion_tokens`` (``None`` when absent) and the real ``cost``
        (``None`` when the provider reports none). Missing or malformed numeric
        fields degrade to ``None`` rather than masking a truncation or billing a
        bogus figure. ``total_tokens`` is reconstructed from the split when the
        provider omits it but supplies the parts.
        """
        usage = body.get("usage") if isinstance(body, dict) else None
        if not isinstance(usage, dict):
            return _Usage()

        prompt_tokens = _coerce_non_negative_int(usage.get("prompt_tokens"))
        completion_tokens = _coerce_non_negative_int(usage.get("completion_tokens"))
        total = _coerce_non_negative_int(usage.get("total_tokens"))
        if total is None and (prompt_tokens is not None or completion_tokens is not None):
            # Reconstruct the total from the split when the provider omits it but
            # supplies at least one part. If nothing is reported, leave it None.
            total = (prompt_tokens or 0) + (completion_tokens or 0)
        cost = _coerce_non_negative_float(usage.get("cost"))
        return _Usage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total,
            cost=cost,
        )


def build_default_ai_client(
    *, tier: str = "default", working_dir: str | None = None
) -> AIClient | None:
    """Build the default :class:`AIClient` from configuration.

    Reads provider, model, and API key via :mod:`ai_config`. Returns
    ``None`` when no credential is available — callers should treat
    ``None`` as "no AI synthesis possible; use the deterministic
    fallback".

    Args:
        tier: Model tier to resolve (issue #77). One of ``"default"``,
            ``"analysis"``, ``"critical"``. The default keeps the
            pre-#77 behaviour (the synthesis tier). Tier only selects the
            *model identifier*; provider and credential resolution are
            unchanged.
        working_dir: Optional caller project root (issue #106). Forwarded
            to :func:`ai_config.resolve_model` so a caller repo that sets
            ``PER_REPO_OVERRIDE`` in its ``.env`` selects its own model;
            ``None`` keeps centralized (process-env) resolution.

    This is the *single* env-reading site for AI client construction.
    Any other code reading ``HESTAI_AI_*`` or ``*_API_KEY`` is a
    layering violation.
    """
    provider = ai_config.resolve_provider()
    api_key = ai_config.resolve_api_key(provider=provider)
    if not api_key:
        return None
    try:
        base_url = ai_config.get_provider_base_url(provider)
    except ValueError:
        # Misconfigured provider identifier — fail closed.
        logger.warning("Unknown HESTAI_AI_PROVIDER %r; cannot build AIClient", provider)
        return None
    model = ai_config.resolve_model(tier, working_dir=working_dir)
    # Issue #96: config-sourced upstream-routing pin (None for providers that
    # take no routing preference). Resolved here, in the composition root, so
    # the wire-protocol adapter stays free of any provider/model magic-string
    # branch (PROD::I3 keeps vendor knowledge in adapters/config).
    provider_payload = ai_config.resolve_provider_payload(provider)
    client = OpenAICompatAIClient(
        api_key=api_key,
        base_url=base_url,
        model=model,
        provider_payload=provider_payload,
    )
    # Construction-time guard (CRS gemini follow-up
    # ``crs_review_pr9_followup_ceeaa71``): ``runtime_checkable`` Protocol
    # only checks attribute *presence*, so a future adapter that defined
    # ``complete_text`` as ``def`` rather than ``async def`` would pass
    # ``isinstance(c, AIClient)`` and then crash at the first ``await``
    # with ``TypeError: object str can't be used in 'await' expression``.
    # Fail closed at construction so the bug surfaces before any I/O.
    if not inspect.iscoroutinefunction(client.complete_text):
        raise TypeError(
            "AIClient implementation must define `complete_text` as `async def`; "
            f"got a non-coroutine function on {type(client).__name__}"
        )
    # Structural Protocol conformance: the concrete class satisfies the
    # ``AIClient`` runtime_checkable Protocol but mypy cannot see this
    # without an explicit cast (no nominal inheritance).
    return cast(AIClient, client)
