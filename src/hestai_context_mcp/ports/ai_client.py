"""Provider-agnostic AI client port.

This module defines the :class:`AIClient` Protocol and its exception
taxonomy. It is the *contract* that the application layer (e.g.
:mod:`hestai_context_mcp.core.synthesis`) depends on; concrete
implementations live under :mod:`hestai_context_mcp.adapters`.

**Binding invariants** (PROD::I3 PROVIDER_AGNOSTIC_CONTEXT):
    * No provider SDK is imported here.
    * No vendor identifier appears in public types, signatures,
      docstrings, or constants. Vendor names may only appear in
      adapters.
    * ``tests/unit/test_source_invariants.py::TestNoProviderSdkInPorts``
      enforces this by source grep.

Design notes:
    * ``Protocol`` (not ``ABC``): duck-typed conformance with static
      enforcement via mypy and runtime enforcement via
      :func:`typing.runtime_checkable`. Test stubs need not register.
    * Single coroutine method ``complete_text``. Provider selection,
      tier selection, retries, and model resolution all live *below*
      this port, in the adapter/config layer.
    * Exception taxonomy is small and binary-categorical: auth (no
      retry), transport (transient), protocol (provider misbehaved).
      OCTAVE schema violations are caught by the application-layer
      validator, not raised here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

__all__ = [
    "CompletionRequest",
    "AIClient",
    "AIClientError",
    "AIClientAuthError",
    "AIClientTransportError",
    "AIClientProtocolError",
]


@dataclass(frozen=True)
class CompletionRequest:
    """Provider-agnostic completion request.

    Carries only what the application layer cares about: prompts and
    generation parameters. Tier, provider, and model selection live in
    the adapter's config layer so swapping providers never requires
    application code changes.
    """

    system_prompt: str
    user_prompt: str
    max_tokens: int = 1024
    temperature: float = 0.3
    timeout_seconds: int = 15


class AIClientError(Exception):
    """Base for all port-layer AI client failures."""


class AIClientAuthError(AIClientError):
    """No usable credential, or credential rejected (HTTP 401/403).

    Application layer treats this as a permanent condition — no retry,
    emit fallback immediately.
    """


class AIClientTransportError(AIClientError):
    """Network-level or transient server failure.

    Includes timeouts, connection resets, DNS failures, HTTP 5xx, and
    HTTP 429 (rate limit). Application layer treats this as a transient
    condition — emits fallback for this call, does not retry within the
    request.
    """


class AIClientProtocolError(AIClientError):
    """Provider responded but the response was unparseable or malformed.

    Distinct from OCTAVE schema violations of the response body: this
    covers provider-layer HTTP/JSON shape failures (non-JSON body,
    missing ``choices``, etc.). OCTAVE body validation is an
    application-layer concern.
    """


@runtime_checkable
class AIClient(Protocol):
    """Provider-agnostic text completion port.

    Intentionally a single method. Tiered configuration, retry chains,
    and provider selection live below this port so swapping providers
    never requires application code to change.

    Async-context-manager shape is required so adapters can manage
    transport lifetimes (e.g. pooled HTTP clients) deterministically
    from caller scope.
    """

    async def __aenter__(self) -> AIClient: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object | None,
    ) -> None: ...

    async def complete_text(self, request: CompletionRequest) -> str:
        """Return raw completion text for ``request``.

        Raises:
            AIClientAuthError: No credential / credential rejected.
            AIClientTransportError: Timeout / connection / 5xx / 429.
            AIClientProtocolError: Malformed provider response.
        """
        ...
