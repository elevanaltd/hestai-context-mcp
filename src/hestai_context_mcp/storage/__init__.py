"""Portable Session State (PSS) storage package — ADR-0013 B1 foundation.

Re-exports the stable type and protocol contract for ADR-0013 Portable
Session State. Concrete adapters (currently only LocalFilesystemAdapter)
land alongside; remote carriers are explicitly out of scope per R12 and
the B2_START_BLOCKERS in the B1 BUILD-PLAN.

Per CRS C1 the signatures here MUST match BUILD-PLAN §PROTOCOL_SIGNATURES
verbatim. Any drift requires CE re-consult per the B1→B2 arbitration record.
"""

from __future__ import annotations

from hestai_context_mcp.storage.local_filesystem import LocalFilesystemAdapter
from hestai_context_mcp.storage.protocol import StorageAdapter
from hestai_context_mcp.storage.types import (
    ArtifactKind,
    ArtifactRef,
    IdentityTuple,
    PortableArtifact,
    PortableMemoryArtifact,
    PortableNamespace,
    PublishAck,
    PublishStatus,
    RedactionProvenance,
    StateClassification,
    StorageCapabilities,
    TombstoneArtifact,
    WritePrecondition,
)

__all__ = [
    "ArtifactKind",
    "ArtifactRef",
    "IdentityTuple",
    "LocalFilesystemAdapter",
    "PortableArtifact",
    "PortableMemoryArtifact",
    "PortableNamespace",
    "PublishAck",
    "PublishStatus",
    "RedactionProvenance",
    "StateClassification",
    "StorageAdapter",
    "StorageCapabilities",
    "TombstoneArtifact",
    "WritePrecondition",
]
