"""ADR-0013 PSS StorageAdapter Protocol — verbatim from §PROTOCOL_SIGNATURES.

This module defines the storage boundary @runtime_checkable Protocol used by
hestai-context-mcp during clock_in (restore) and clock_out (publish).

CRS C1: signatures match BUILD-PLAN §PROTOCOL_SIGNATURES exactly. Any drift
requires CE re-consult per the B1→B2 arbitration record.

CRS C2: @runtime_checkable provides attribute-presence checks only — it does
NOT validate method signatures or parameter types at runtime. Implementations
must still satisfy the type contract; mypy strict is the binding type gate.

Concrete remote carriers (RemoteHTTP, S3, Git) are explicitly out of scope
for B1 per ADR-0013 R12 and B2_START_BLOCKER_003. Custom Git refs are
prohibited by R11 and the phantom-substrate evidence cited in the ADR.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from hestai_context_mcp.storage.types import (
    ArtifactRef,
    PortableArtifact,
    PortableMemoryArtifact,
    PortableNamespace,
    PublishAck,
    StorageCapabilities,
    TombstoneArtifact,
    WritePrecondition,
)


@runtime_checkable
class StorageAdapter(Protocol):
    """Storage boundary used by clock_in/clock_out for PSS artifacts.

    Adapters implement append-first writes with conditional/atomic create
    semantics. ``read_artifact`` returns the discriminated PortableArtifact
    union (RISK_002) so tombstones round-trip without a separate method.

    Note (CRS C2): runtime_checkable enables ``isinstance()`` attribute
    checks only; mypy strict + the explicit ``write_artifact``/
    ``write_tombstone`` split is the load-bearing type contract.
    """

    capabilities: StorageCapabilities

    def list_artifacts(
        self,
        namespace: PortableNamespace,
        after_id: str | None = None,
    ) -> list[ArtifactRef]:
        """List artifacts in deterministic monotonic order."""
        ...

    def read_artifact(self, ref: ArtifactRef) -> PortableArtifact:
        """Read the artifact identified by ref."""
        ...

    def write_artifact(
        self,
        ref: ArtifactRef,
        artifact: PortableMemoryArtifact,
        precondition: WritePrecondition,
    ) -> PublishAck:
        """Write a provenance-validated Portable Memory Artifact."""
        ...

    def write_tombstone(
        self,
        ref: ArtifactRef,
        tombstone: TombstoneArtifact,
        precondition: WritePrecondition,
    ) -> PublishAck:
        """Append a tombstone artifact without overwriting the target."""
        ...


__all__ = ["StorageAdapter"]
