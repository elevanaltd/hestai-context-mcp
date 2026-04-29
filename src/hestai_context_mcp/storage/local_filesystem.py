"""ADR-0013 PSS LocalFilesystemAdapter — default B1 storage carrier.

Implements the StorageAdapter protocol against the local filesystem rooted
at ``{working_dir}/.hestai/state/portable/``. This is the only adapter that
ships in B1 per ADR-0013 R12 and the BUILD-PLAN scope discipline.

Binding rulings enforced here:

- INVARIANT_003 (R6 + R10) + G4: ``write_artifact`` validates redaction
  provenance via :func:`storage.provenance.validate_provenance_complete`
  BEFORE any filesystem write. Incomplete provenance raises
  ``ProvenanceIncompleteError`` with no on-disk side-effects.
- R2 + R9: writes are conditional create-only by default
  (``WritePrecondition.if_absent``). Same artifact_id with the same
  payload_hash returns ``PublishStatus.DUPLICATE`` (idempotent). Same
  artifact_id with a *different* payload_hash returns
  ``PublishStatus.FAILED`` and never overwrites.
- R3: ``PortableNamespace`` and ``IdentityTuple`` are validated through
  :func:`storage.identity.validate_identity_tuple` BEFORE path
  construction, preventing traversal/path-separator components from
  reaching the filesystem.
- R8: tombstones append into ``portable/tombstones/{namespace}`` and never
  delete the target artifact. Tombstones whose ``reason`` indicates
  post-hoc redaction failure require non-null
  ``redaction_provenance`` (validated complete).
- R11: no git CLI shell-out, no custom Git refs.
- R12: no network imports, no remote SDKs.

Local carrier path layout (RISK_006, post-CE-rework):

    .hestai/state/portable/
      pss/{carrier_namespace}/{project_id}/{workspace_id}/{user_id}/artifacts/{artifact_id}.json
      pss/{carrier_namespace}/{project_id}/{workspace_id}/{user_id}/tombstones/{artifact_id}.json
      tmp/                # atomic-write staging
      outbox/             # owned by storage.outbox (R7)
      snapshots/          # owned by storage.snapshots (R5)

CE Stage C ruling (RISK_006 APPROVE_MIRROR): the on-disk path MUST
match the ADR-0013 abstract path. The 'pss' top segment, the END-
position 'artifacts/' segment, and the absence of any v{schema_version}
segment are all binding. schema_version is a field inside the artifact
and namespace records — embedding it in the path is over-specification.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hestai_context_mcp.storage.identity import (
    validate_identity_tuple,
    validate_namespace_matches_identity,
)
from hestai_context_mcp.storage.provenance import validate_provenance_complete
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
    StorageCapabilities,
    TombstoneArtifact,
    WritePrecondition,
)

# Reasons that indicate post-hoc redaction failure — these tombstones MUST
# carry non-null redaction_provenance per ADR-0013 R8.
_REDACTION_FAILURE_REASONS: frozenset[str] = frozenset(
    {"redaction_failure", "post_hoc_redaction_failure"}
)

_LOCAL_CAPABILITIES = StorageCapabilities(
    strong_list_consistency=True,
    atomic_compare_and_swap=True,
    conditional_writes=True,
    advisory_locking=False,
    streaming_writes=False,
    encryption_at_rest=False,
    encryption_in_transit=False,
    hard_delete=False,
    read_only=False,
)


@dataclass(frozen=True, slots=True)
class PayloadHashMismatchError(Exception):
    """Raised when an on-disk artifact payload no longer matches its hash (R4)."""

    code: str
    message: str

    def __post_init__(self) -> None:  # pragma: no cover - exception side-effect
        Exception.__init__(self, self.message)


@dataclass(frozen=True, slots=True)
class TombstoneProvenanceRequiredError(Exception):
    """Raised when a redaction-failure tombstone lacks redaction_provenance (R8)."""

    code: str
    message: str

    def __post_init__(self) -> None:  # pragma: no cover - exception side-effect
        Exception.__init__(self, self.message)


def _serialize_identity(identity: IdentityTuple) -> dict[str, Any]:
    return {
        "project_id": identity.project_id,
        "workspace_id": identity.workspace_id,
        "user_id": identity.user_id,
        "state_schema_version": identity.state_schema_version,
        "carrier_namespace": identity.carrier_namespace,
    }


def _serialize_provenance(p: RedactionProvenance) -> dict[str, Any]:
    return {
        "engine_name": p.engine_name,
        "engine_version": p.engine_version,
        "ruleset_hash": p.ruleset_hash,
        "input_artifact_hash": p.input_artifact_hash,
        "output_artifact_hash": p.output_artifact_hash,
        "redacted_at": p.redacted_at.isoformat(),
        "classification_label": p.classification_label,
        "redacted_credential_categories": list(p.redacted_credential_categories),
    }


def _serialize_memory_artifact(artifact: PortableMemoryArtifact) -> dict[str, Any]:
    return {
        "artifact_id": artifact.artifact_id,
        "artifact_kind": artifact.artifact_kind.value,
        "identity": _serialize_identity(artifact.identity),
        "schema_version": artifact.schema_version,
        "producer_version": artifact.producer_version,
        "minimum_reader_version": artifact.minimum_reader_version,
        "created_at": artifact.created_at.isoformat(),
        "sequence_id": artifact.sequence_id,
        "parent_ids": list(artifact.parent_ids),
        "redaction_provenance": _serialize_provenance(artifact.redaction_provenance),
        "classification_label": artifact.classification_label,
        "payload_hash": artifact.payload_hash,
        "payload": dict(artifact.payload),
    }


def _serialize_tombstone(tomb: TombstoneArtifact) -> dict[str, Any]:
    return {
        "artifact_id": tomb.artifact_id,
        "artifact_kind": tomb.artifact_kind.value,
        "identity": _serialize_identity(tomb.identity),
        "schema_version": tomb.schema_version,
        "producer_version": tomb.producer_version,
        "minimum_reader_version": tomb.minimum_reader_version,
        "created_at": tomb.created_at.isoformat(),
        "sequence_id": tomb.sequence_id,
        "parent_ids": list(tomb.parent_ids),
        "target_artifact_id": tomb.target_artifact_id,
        "reason": tomb.reason,
        "publisher_identity": _serialize_identity(tomb.publisher_identity),
        "redaction_provenance": (
            _serialize_provenance(tomb.redaction_provenance)
            if tomb.redaction_provenance is not None
            else None
        ),
        "classification_label": tomb.classification_label,
        "payload_hash": tomb.payload_hash,
    }


def _parse_identity(raw: dict[str, Any]) -> IdentityTuple:
    return IdentityTuple(
        project_id=str(raw["project_id"]),
        workspace_id=str(raw["workspace_id"]),
        user_id=str(raw["user_id"]),
        state_schema_version=int(raw["state_schema_version"]),
        carrier_namespace=str(raw["carrier_namespace"]),
    )


def _parse_provenance(raw: dict[str, Any]) -> RedactionProvenance:
    redacted_at = raw["redacted_at"]
    if isinstance(redacted_at, str):
        redacted_at = datetime.fromisoformat(redacted_at)
    return RedactionProvenance(
        engine_name=str(raw["engine_name"]),
        engine_version=str(raw["engine_version"]),
        ruleset_hash=str(raw["ruleset_hash"]),
        input_artifact_hash=str(raw["input_artifact_hash"]),
        output_artifact_hash=str(raw["output_artifact_hash"]),
        redacted_at=redacted_at,
        classification_label="PORTABLE_MEMORY",
        redacted_credential_categories=tuple(raw.get("redacted_credential_categories", ())),
    )


def _parse_memory_artifact(raw: dict[str, Any]) -> PortableMemoryArtifact:
    created_at = raw["created_at"]
    if isinstance(created_at, str):
        created_at = datetime.fromisoformat(created_at)
    return PortableMemoryArtifact(
        artifact_id=str(raw["artifact_id"]),
        artifact_kind=ArtifactKind.PORTABLE_MEMORY,
        identity=_parse_identity(raw["identity"]),
        schema_version=int(raw["schema_version"]),
        producer_version=str(raw["producer_version"]),
        minimum_reader_version=int(raw["minimum_reader_version"]),
        created_at=created_at,
        sequence_id=int(raw["sequence_id"]),
        parent_ids=tuple(raw.get("parent_ids", ())),
        redaction_provenance=_parse_provenance(raw["redaction_provenance"]),
        classification_label="PORTABLE_MEMORY",
        payload_hash=str(raw["payload_hash"]),
        payload=dict(raw["payload"]),
    )


def _parse_tombstone(raw: dict[str, Any]) -> TombstoneArtifact:
    created_at = raw["created_at"]
    if isinstance(created_at, str):
        created_at = datetime.fromisoformat(created_at)
    prov_raw = raw.get("redaction_provenance")
    prov = _parse_provenance(prov_raw) if prov_raw is not None else None
    return TombstoneArtifact(
        artifact_id=str(raw["artifact_id"]),
        artifact_kind=ArtifactKind.TOMBSTONE,
        identity=_parse_identity(raw["identity"]),
        schema_version=int(raw["schema_version"]),
        producer_version=str(raw["producer_version"]),
        minimum_reader_version=int(raw["minimum_reader_version"]),
        created_at=created_at,
        sequence_id=int(raw["sequence_id"]),
        parent_ids=tuple(raw.get("parent_ids", ())),
        target_artifact_id=str(raw["target_artifact_id"]),
        reason=str(raw["reason"]),
        publisher_identity=_parse_identity(raw["publisher_identity"]),
        redaction_provenance=prov,
        classification_label="PORTABLE_MEMORY",
        payload_hash=str(raw["payload_hash"]),
    )


def _atomic_write_json(target: Path, data: dict[str, Any], *, tmp_root: Path) -> None:
    """Write ``data`` as JSON to ``target`` atomically.

    Writes to a temp file under ``tmp_root`` then renames into place. The
    temp directory is created on demand. Caller is responsible for ensuring
    ``target.parent`` exists.
    """

    tmp_root.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(tmp_root), suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, sort_keys=True, separators=(",", ":"))
        os.replace(tmp_name, target)
    except BaseException:
        # Cleanup partial tmp file on any error.
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise


class LocalFilesystemAdapter:
    """Default B1 LocalFilesystemAdapter implementation (StorageAdapter Protocol).

    Args:
        working_dir: Project root containing ``.hestai/state/`` (or its
            symlink). The adapter writes only under
            ``working_dir/.hestai/state/portable/``.
    """

    capabilities: StorageCapabilities

    def __init__(self, working_dir: str | Path) -> None:
        self._working_dir = Path(working_dir).resolve()
        self.capabilities = _LOCAL_CAPABILITIES

    @property
    def portable_root(self) -> Path:
        """Root path for all PSS local-carrier state."""

        return self._working_dir / ".hestai" / "state" / "portable"

    @staticmethod
    def is_local_only() -> bool:
        """Canonical structural marker: this adapter is local-only (B1, R12).

        Returns:
            ``True`` for ``LocalFilesystemAdapter``. The post-B2 quality
            gate chain uses this method to mechanically confirm that B1
            ships only the local carrier per B2_START_BLOCKER_003. Future
            non-local adapters MUST return ``False`` from their override
            so PSS lifecycle code can short-circuit appropriately when
            local-only constraints apply.
        """

        return True

    @property
    def _pss_root(self) -> Path:
        """Root for the ADR-0013 abstract-path layout: ``portable/pss/``."""

        return self.portable_root / "pss"

    @property
    def _tmp_root(self) -> Path:
        return self.portable_root / "tmp"

    def _namespace_dir(self, namespace: PortableNamespace, *, kind: ArtifactKind) -> Path:
        """Per-identity namespace dir for ``kind``.

        Layout (CE rework RISK_006 APPROVE_MIRROR — ADR-0013 abstract path)::

            pss/{ns}/{proj}/{ws}/{user}/artifacts
            pss/{ns}/{proj}/{ws}/{user}/tombstones

        The 'artifacts'/'tombstones' segment lives at the END so the
        identity-keyed subtree is shared and the kind segment terminates
        the directory. No ``v{schema_version}`` segment — schema_version
        is a field inside the artifact/namespace records.
        """

        # Validate identity-shaped fields before any path construction (R3).
        identity = IdentityTuple(
            project_id=namespace.project_id,
            workspace_id=namespace.workspace_id,
            user_id=namespace.user_id,
            state_schema_version=namespace.state_schema_version,
            carrier_namespace=namespace.carrier_namespace,
        )
        validate_identity_tuple(identity)

        leaf = "artifacts" if kind is ArtifactKind.PORTABLE_MEMORY else "tombstones"
        return (
            self._pss_root
            / namespace.carrier_namespace
            / namespace.project_id
            / namespace.workspace_id
            / namespace.user_id
            / leaf
        )

    def _artifact_path(self, ref: ArtifactRef) -> Path:
        # Validate identity before path construction (R3).
        validate_identity_tuple(ref.identity)
        kind = ref.artifact_kind
        leaf = "artifacts" if kind is ArtifactKind.PORTABLE_MEMORY else "tombstones"
        return (
            self._pss_root
            / ref.identity.carrier_namespace
            / ref.identity.project_id
            / ref.identity.workspace_id
            / ref.identity.user_id
            / leaf
            / f"{ref.artifact_id}.json"
        )

    # ---- StorageAdapter API ----------------------------------------------

    def list_artifacts(
        self,
        namespace: PortableNamespace,
        after_id: str | None = None,
    ) -> list[ArtifactRef]:
        """List artifacts in deterministic monotonic (sequence_id, artifact_id) order."""

        # Validate namespace before path construction (R3).
        ns_dir = self._namespace_dir(namespace, kind=ArtifactKind.PORTABLE_MEMORY)
        if not ns_dir.exists():
            return []

        refs: list[ArtifactRef] = []
        for json_path in ns_dir.glob("*.json"):
            try:
                raw = json.loads(json_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            artifact = _parse_memory_artifact(raw)
            if artifact.identity != IdentityTuple(
                project_id=namespace.project_id,
                workspace_id=namespace.workspace_id,
                user_id=namespace.user_id,
                state_schema_version=namespace.state_schema_version,
                carrier_namespace=namespace.carrier_namespace,
            ):
                continue
            refs.append(
                ArtifactRef(
                    artifact_id=artifact.artifact_id,
                    identity=artifact.identity,
                    artifact_kind=artifact.artifact_kind,
                    sequence_id=artifact.sequence_id,
                    created_at=artifact.created_at,
                    payload_hash=artifact.payload_hash,
                    carrier_path=str(json_path),
                )
            )

        refs.sort(key=lambda r: (r.sequence_id, r.artifact_id))
        if after_id is not None:
            # Cubic P1 #4: pagination MUST use the same key as the sort,
            # ``(sequence_id, artifact_id)``. Lexicographic comparison on
            # ``artifact_id`` alone breaks the cursor when artifact_ids do
            # not increase monotonically with sequence_ids (PROD::I1
            # SESSION_LIFECYCLE_INTEGRITY: restore-time listing depends on
            # a stable cursor). Locate the ref whose artifact_id == after_id
            # in the already-sorted list and slice everything after it.
            cursor_index: int | None = None
            for idx, ref in enumerate(refs):
                if ref.artifact_id == after_id:
                    cursor_index = idx
                    break
            if cursor_index is None:
                # Cursor does not match any known ref: return empty rather
                # than the full list, preserving fail-closed semantics.
                return []
            refs = refs[cursor_index + 1 :]
        return refs

    def read_artifact(self, ref: ArtifactRef) -> PortableArtifact:
        """Read the artifact identified by ``ref`` and validate payload_hash (R4)."""

        path = self._artifact_path(ref)
        if not path.exists():
            raise FileNotFoundError(f"Portable artifact not found: {path}")
        raw = json.loads(path.read_text(encoding="utf-8"))
        kind = raw.get("artifact_kind")
        if kind == ArtifactKind.PORTABLE_MEMORY.value:
            artifact = _parse_memory_artifact(raw)
            # Identity match check (R3).
            if artifact.identity != ref.identity:
                from hestai_context_mcp.storage.identity import IdentityValidationError

                raise IdentityValidationError(
                    code="ref_identity_mismatch",
                    message="ArtifactRef.identity does not match on-disk artifact identity",
                )
            # Payload hash validation (R4).
            recomputed = hashlib.sha256(
                json.dumps(artifact.payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            if recomputed != artifact.payload_hash:
                raise PayloadHashMismatchError(
                    code="payload_hash_mismatch",
                    message=(
                        f"on-disk payload hash {recomputed!r} does not match stored "
                        f"payload_hash {artifact.payload_hash!r}"
                    ),
                )
            return artifact
        if kind == ArtifactKind.TOMBSTONE.value:
            tomb = _parse_tombstone(raw)
            if tomb.identity != ref.identity:
                from hestai_context_mcp.storage.identity import IdentityValidationError

                raise IdentityValidationError(
                    code="ref_identity_mismatch",
                    message="ArtifactRef.identity does not match on-disk tombstone identity",
                )
            return tomb
        raise PayloadHashMismatchError(
            code="unknown_artifact_kind",
            message=f"unsupported artifact_kind {kind!r}",
        )

    def write_artifact(
        self,
        ref: ArtifactRef,
        artifact: PortableMemoryArtifact,
        precondition: WritePrecondition,
    ) -> PublishAck:
        """Write a provenance-validated PortableMemoryArtifact (G4 atomic guard)."""

        # G4: provenance gate runs BEFORE any filesystem side-effect.
        validate_provenance_complete(artifact.redaction_provenance)
        # R3: identity validation BEFORE path construction.
        validate_identity_tuple(artifact.identity)
        # NOTE_007: namespace == identity.
        validate_namespace_matches_identity(
            namespace=PortableNamespace(
                project_id=artifact.identity.project_id,
                workspace_id=artifact.identity.workspace_id,
                user_id=artifact.identity.user_id,
                state_schema_version=artifact.identity.state_schema_version,
                carrier_namespace=artifact.identity.carrier_namespace,
            ),
            identity=artifact.identity,
        )

        target = self._artifact_path(ref)
        target.parent.mkdir(parents=True, exist_ok=True)

        if target.exists() and precondition.if_absent:
            existing_raw = json.loads(target.read_text(encoding="utf-8"))
            existing_hash = str(existing_raw.get("payload_hash"))
            if existing_hash == artifact.payload_hash:
                return PublishAck(
                    artifact_id=artifact.artifact_id,
                    identity=artifact.identity,
                    carrier_namespace=artifact.identity.carrier_namespace,
                    sequence_id=artifact.sequence_id,
                    status=PublishStatus.DUPLICATE,
                    durable_carrier_receipt=str(target),
                    queued_path=None,
                    published_at=datetime.now(UTC),
                    error_code=None,
                    error_message=None,
                )
            return PublishAck(
                artifact_id=artifact.artifact_id,
                identity=artifact.identity,
                carrier_namespace=artifact.identity.carrier_namespace,
                sequence_id=artifact.sequence_id,
                status=PublishStatus.FAILED,
                durable_carrier_receipt=None,
                queued_path=None,
                published_at=None,
                error_code="precondition_conflicting_payload",
                error_message=(
                    f"artifact_id {artifact.artifact_id!r} already exists with a different "
                    "payload_hash; refusing to overwrite (R9 append-first)"
                ),
            )

        _atomic_write_json(target, _serialize_memory_artifact(artifact), tmp_root=self._tmp_root)
        return PublishAck(
            artifact_id=artifact.artifact_id,
            identity=artifact.identity,
            carrier_namespace=artifact.identity.carrier_namespace,
            sequence_id=artifact.sequence_id,
            status=PublishStatus.PUBLISHED,
            durable_carrier_receipt=str(target),
            queued_path=None,
            published_at=datetime.now(UTC),
            error_code=None,
            error_message=None,
        )

    def write_tombstone(
        self,
        ref: ArtifactRef,
        tombstone: TombstoneArtifact,
        precondition: WritePrecondition,
    ) -> PublishAck:
        """Append a tombstone artifact (R8)."""

        # If the reason represents post-hoc redaction failure, provenance is required.
        if tombstone.reason in _REDACTION_FAILURE_REASONS:
            if tombstone.redaction_provenance is None:
                raise TombstoneProvenanceRequiredError(
                    code="tombstone_provenance_required",
                    message=(
                        f"tombstone reason {tombstone.reason!r} indicates post-hoc redaction "
                        "failure; redaction_provenance is required"
                    ),
                )
            validate_provenance_complete(tombstone.redaction_provenance)

        # Identity validation BEFORE path construction (R3).
        validate_identity_tuple(tombstone.identity)
        validate_identity_tuple(tombstone.publisher_identity)

        target = self._artifact_path(ref)
        target.parent.mkdir(parents=True, exist_ok=True)

        if target.exists() and precondition.if_absent:
            return PublishAck(
                artifact_id=tombstone.artifact_id,
                identity=tombstone.identity,
                carrier_namespace=tombstone.identity.carrier_namespace,
                sequence_id=tombstone.sequence_id,
                status=PublishStatus.DUPLICATE,
                durable_carrier_receipt=str(target),
                queued_path=None,
                published_at=datetime.now(UTC),
                error_code=None,
                error_message=None,
            )

        _atomic_write_json(target, _serialize_tombstone(tombstone), tmp_root=self._tmp_root)
        return PublishAck(
            artifact_id=tombstone.artifact_id,
            identity=tombstone.identity,
            carrier_namespace=tombstone.identity.carrier_namespace,
            sequence_id=tombstone.sequence_id,
            status=PublishStatus.PUBLISHED,
            durable_carrier_receipt=str(target),
            queued_path=None,
            published_at=datetime.now(UTC),
            error_code=None,
            error_message=None,
        )


__all__ = [
    "LocalFilesystemAdapter",
    "PayloadHashMismatchError",
    "TombstoneProvenanceRequiredError",
]
