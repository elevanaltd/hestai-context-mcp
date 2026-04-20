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

import json
import logging
from types import TracebackType
from typing import cast

import httpx

from hestai_context_mcp.adapters import ai_config
from hestai_context_mcp.ports.ai_client import (
    AIClient,
    AIClientAuthError,
    AIClientProtocolError,
    AIClientTransportError,
    CompletionRequest,
)

logger = logging.getLogger(__name__)

__all__ = [
    "OpenAICompatAIClient",
    "build_default_ai_client",
]


class OpenAICompatAIClient:
    """Concrete :class:`AIClient` over HTTP using the OpenAI chat-completions shape."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: float = 15.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout_seconds = float(timeout_seconds)
        # A test-only transport (``httpx.MockTransport``) may be
        # injected; otherwise the real network transport is used.
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

    async def complete_text(self, request: CompletionRequest) -> str:
        """Execute a chat completion call and return the raw text content."""
        if self._client is None:
            # Guarded by the async-context-manager contract; defensive
            # here so misuse fails predictably rather than with a
            # ``NoneType`` attribute error.
            raise AIClientProtocolError("OpenAICompatAIClient used outside an async-with block")
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": request.user_prompt},
            ],
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
        }
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

    def _interpret_response(self, response: httpx.Response) -> str:
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
            # Unknown non-2xx: treat as protocol-level surprise.
            raise AIClientProtocolError(f"unexpected HTTP status from provider: {status}")
        try:
            body = response.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise AIClientProtocolError(f"provider returned non-JSON body: {exc}") from exc
        choices = body.get("choices") if isinstance(body, dict) else None
        if not choices:
            raise AIClientProtocolError("provider response missing or empty 'choices' array")
        first = choices[0]
        if not isinstance(first, dict):
            raise AIClientProtocolError("provider response 'choices[0]' is not an object")
        message = first.get("message")
        if not isinstance(message, dict):
            raise AIClientProtocolError("provider response 'choices[0].message' is not an object")
        content = message.get("content")
        if not isinstance(content, str):
            raise AIClientProtocolError(
                "provider response 'choices[0].message.content' is not a string"
            )
        return content


def build_default_ai_client() -> AIClient | None:
    """Build the default :class:`AIClient` from configuration.

    Reads provider, model, and API key via :mod:`ai_config`. Returns
    ``None`` when no credential is available — callers should treat
    ``None`` as "no AI synthesis possible; use the deterministic
    fallback".

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
    model = ai_config.resolve_model()
    # Structural Protocol conformance: the concrete class satisfies the
    # ``AIClient`` runtime_checkable Protocol but mypy cannot see this
    # without an explicit cast (no nominal inheritance).
    return cast(
        AIClient,
        OpenAICompatAIClient(api_key=api_key, base_url=base_url, model=model),
    )
