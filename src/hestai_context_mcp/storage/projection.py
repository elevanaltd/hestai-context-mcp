"""ADR-0013 PSS deterministic projection builder — R3, R8, R9, R10.

Pure projection over already-loaded Portable Memory Artifacts and
TombstoneArtifacts. Produces a JSON-compatible read model that
``clock_in`` writes into the named session snapshot.

Binding rulings enforced here:

- R3: all artifacts must share the same identity tuple as the projection
  caller; mismatch raises ``IdentityValidationError`` (no silent
  contamination from forks/clones).
- R8 + A3: tombstones are applied BEFORE merge, so the resulting
  ``artifact_refs`` never contains a tombstoned artifact. Tombstones
  themselves are recorded under ``tombstoned_artifact_ids`` so the
  projection round-trips through clock_in -> snapshot -> get_context
  without losing revocation evidence.
- R9: same artifact_id + same payload_hash is idempotent; same
  artifact_id + different payload_hash raises ``ProjectionError``.
- R10 / INVARIANT_004: deterministic — same inputs produce identical
  output. INVARIANT_005: structured failure, never silent empty.

This module performs no filesystem I/O and never imports adapters.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from hestai_context_mcp.storage.identity import (
    IdentityValidationError,
    validate_identity_tuple,
)
from hestai_context_mcp.storage.types import (
    IdentityTuple,
    PortableMemoryArtifact,
    TombstoneArtifact,
)


@dataclass(frozen=True, slots=True)
class ProjectionError(Exception):
    """Structured projection failure (R9 conflicts, R10 fail-closed)."""

    code: str
    message: str

    def __post_init__(self) -> None:  # pragma: no cover - exception side-effect
        Exception.__init__(self, self.message)


def _identity_dict(identity: IdentityTuple) -> dict[str, Any]:
    return {
        "project_id": identity.project_id,
        "workspace_id": identity.workspace_id,
        "user_id": identity.user_id,
        "state_schema_version": identity.state_schema_version,
        "carrier_namespace": identity.carrier_namespace,
    }


def build_projection(
    *,
    identity: IdentityTuple,
    artifacts: tuple[PortableMemoryArtifact, ...],
    tombstones: tuple[TombstoneArtifact, ...],
) -> dict[str, Any]:
    """Build a deterministic projection over ``artifacts`` minus ``tombstones``.

    Args:
        identity: Snapshot identity tuple.
        artifacts: Portable memory artifacts to merge.
        tombstones: Tombstone artifacts whose targets must be excluded.

    Returns:
        ``{"identity": <id>, "tombstoned_artifact_ids": [...],
        "artifact_refs": [{"artifact_id": ..., "sequence_id": ...,
        "payload_hash": ..., "payload": {...}}, ...]}``.

    Raises:
        IdentityValidationError: when ``identity`` is invalid or any
            artifact / tombstone disagrees with ``identity``.
        ProjectionError: when same artifact_id has conflicting payload
            hashes (R9).
    """

    validate_identity_tuple(identity)

    # R3: identity match for every input.
    for a in artifacts:
        if a.identity != identity:
            raise IdentityValidationError(
                code="projection_artifact_identity_mismatch",
                message=(
                    f"artifact {a.artifact_id!r} identity {a.identity!r} does not match "
                    f"projection identity {identity!r}"
                ),
            )
    for t in tombstones:
        if t.identity != identity:
            raise IdentityValidationError(
                code="projection_tombstone_identity_mismatch",
                message=(
                    f"tombstone {t.artifact_id!r} identity does not match projection identity"
                ),
            )

    # R8: tombstoned target ids are excluded BEFORE merge.
    tombstoned_ids = sorted({t.target_artifact_id for t in tombstones})
    tombstoned_set = set(tombstoned_ids)

    # R9: deduplicate same artifact_id; conflicting hashes raise.
    by_id: dict[str, PortableMemoryArtifact] = {}
    for a in artifacts:
        if a.artifact_id in tombstoned_set:
            continue
        prior = by_id.get(a.artifact_id)
        if prior is None:
            by_id[a.artifact_id] = a
            continue
        if prior.payload_hash != a.payload_hash:
            raise ProjectionError(
                code="conflicting_artifact_payload",
                message=(
                    f"artifact_id {a.artifact_id!r} has conflicting payload_hash "
                    f"{prior.payload_hash!r} vs {a.payload_hash!r}"
                ),
            )
        # Same id + same hash: idempotent — keep first.

    ordered = sorted(by_id.values(), key=lambda a: (a.sequence_id, a.artifact_id))
    artifact_refs: list[dict[str, Any]] = [
        {
            "artifact_id": a.artifact_id,
            "sequence_id": a.sequence_id,
            "payload_hash": a.payload_hash,
            "payload": dict(a.payload),
        }
        for a in ordered
    ]

    return {
        "identity": _identity_dict(identity),
        "tombstoned_artifact_ids": tombstoned_ids,
        "artifact_refs": artifact_refs,
    }


__all__ = ["ProjectionError", "build_projection"]
