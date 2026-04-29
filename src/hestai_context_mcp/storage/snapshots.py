"""ADR-0013 PSS named-session snapshots — R5 + R10 implementation.

Owns ``.hestai/state/portable/snapshots/{session_id}/`` with two files:

- ``context-projection.json``: derived read-model payload for ``get_context``.
- ``metadata.json``: identity tuple, artifact refs (sequence_id +
  artifact_id + payload_hash), created_at.

Binding rulings enforced here:

- R5: snapshots are written by ``clock_in`` only. ``read_session_snapshot``
  is a pure read — no directory creation, no mutation. The snapshot is
  the *frozen* view that ``get_context`` should see for the session,
  preventing intra-session context drift.
- R3: artifact refs whose identity differs from the snapshot identity are
  refused at write time (``IdentityValidationError``).
- R10: snapshot does not drift mid-session — projection bytes on disk
  are the only source of truth for that session.
- Path traversal: ``session_id`` is validated to be a non-empty token free
  of path separators, traversal sequences, and control characters.

PROD::I5: ``read_session_snapshot`` performs zero writes. Tools using it
in ``get_context`` must not call any other adapter API.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hestai_context_mcp.storage.identity import (
    IdentityValidationError,
    validate_identity_tuple,
)
from hestai_context_mcp.storage.types import (
    ArtifactRef,
    IdentityTuple,
    JsonObject,
    StateClassification,
)

#: Snapshots are derived projection state per ADR-0013 R1.
SNAPSHOT_CLASSIFICATION: StateClassification = StateClassification.DERIVED_PROJECTION

_PATH_TRAVERSAL_TOKENS: tuple[str, ...] = ("/", "\\", "..")
_CONTROL_CHARS: tuple[str, ...] = ("\n", "\r", "\t", "\x00")


@dataclass(frozen=True, slots=True)
class SnapshotIdValidationError(ValueError):
    """Session-id failed structural validation (path traversal / blank)."""

    code: str
    message: str

    def __post_init__(self) -> None:  # pragma: no cover - exception side-effect
        Exception.__init__(self, self.message)


@dataclass(frozen=True, slots=True)
class SnapshotNotFoundError(Exception):
    """Snapshot directory or files missing for the requested session_id."""

    code: str
    message: str
    session_id: str

    def __post_init__(self) -> None:  # pragma: no cover - exception side-effect
        Exception.__init__(self, self.message)


def _validate_session_id(session_id: str) -> str:
    if not isinstance(session_id, str) or not session_id or not session_id.strip():
        raise SnapshotIdValidationError(
            code="blank_session_id",
            message="session_id must be a non-blank string",
        )
    for token in _PATH_TRAVERSAL_TOKENS:
        if token in session_id:
            raise SnapshotIdValidationError(
                code="path_traversal_session_id",
                message=f"session_id must not contain {token!r}",
            )
    for ctrl in _CONTROL_CHARS:
        if ctrl in session_id:
            raise SnapshotIdValidationError(
                code="control_char_session_id",
                message="session_id must not contain control characters",
            )
    return session_id


def _snapshot_dir(working_dir: Path, session_id: str) -> Path:
    return Path(working_dir).resolve() / ".hestai" / "state" / "portable" / "snapshots" / session_id


def _serialize_ref(ref: ArtifactRef) -> dict[str, Any]:
    return {
        "artifact_id": ref.artifact_id,
        "identity": {
            "project_id": ref.identity.project_id,
            "workspace_id": ref.identity.workspace_id,
            "user_id": ref.identity.user_id,
            "state_schema_version": ref.identity.state_schema_version,
            "carrier_namespace": ref.identity.carrier_namespace,
        },
        "artifact_kind": ref.artifact_kind.value,
        "sequence_id": ref.sequence_id,
        "created_at": ref.created_at.isoformat(),
        "payload_hash": ref.payload_hash,
        "carrier_path": ref.carrier_path,
    }


def _serialize_identity(identity: IdentityTuple) -> dict[str, Any]:
    return {
        "project_id": identity.project_id,
        "workspace_id": identity.workspace_id,
        "user_id": identity.user_id,
        "state_schema_version": identity.state_schema_version,
        "carrier_namespace": identity.carrier_namespace,
    }


def _atomic_write_json(target: Path, data: dict[str, Any]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(target.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, sort_keys=True, separators=(",", ":"))
        os.replace(tmp_name, target)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise


def create_session_snapshot(
    *,
    working_dir: str | Path,
    session_id: str,
    identity: IdentityTuple,
    artifact_refs: tuple[ArtifactRef, ...],
    projection_payload: JsonObject,
) -> Path:
    """Write a frozen context projection for ``session_id``.

    Args:
        working_dir: Project root.
        session_id: Logical session identifier (validated structurally).
        identity: PSS identity tuple bound to this snapshot.
        artifact_refs: Artifact refs included in the projection. All refs
            must share ``identity`` (R3).
        projection_payload: JSON-compatible read-model payload.

    Returns:
        Final path of ``context-projection.json``.

    Raises:
        SnapshotIdValidationError: when ``session_id`` is structurally invalid.
        IdentityValidationError: when ``identity`` is invalid or any ref
            disagrees with ``identity``.
    """

    sid = _validate_session_id(session_id)
    validate_identity_tuple(identity)

    for ref in artifact_refs:
        if ref.identity != identity:
            raise IdentityValidationError(
                code="snapshot_artifact_identity_mismatch",
                message=(
                    f"artifact_ref {ref.artifact_id!r} identity does not match "
                    "snapshot identity (R3)"
                ),
            )

    target_dir = _snapshot_dir(Path(working_dir), sid)
    projection_path = target_dir / "context-projection.json"
    metadata_path = target_dir / "metadata.json"

    _atomic_write_json(projection_path, dict(projection_payload))
    metadata: dict[str, Any] = {
        "session_id": sid,
        "identity": _serialize_identity(identity),
        "artifact_refs": [_serialize_ref(r) for r in artifact_refs],
        "created_at": datetime.now(UTC).isoformat(),
        "classification_label": SNAPSHOT_CLASSIFICATION.value,
    }
    _atomic_write_json(metadata_path, metadata)
    return projection_path


def read_session_snapshot(
    *,
    working_dir: str | Path,
    session_id: str,
) -> dict[str, Any]:
    """Read the named snapshot for ``session_id`` as a pure local read.

    Returns:
        ``{"projection": <projection-json>, "metadata": <metadata-json>}``.

    Raises:
        SnapshotIdValidationError: when ``session_id`` is structurally invalid.
        SnapshotNotFoundError: when the snapshot does not exist.
    """

    sid = _validate_session_id(session_id)
    target_dir = _snapshot_dir(Path(working_dir), sid)
    projection_path = target_dir / "context-projection.json"
    metadata_path = target_dir / "metadata.json"

    if not projection_path.exists() or not metadata_path.exists():
        raise SnapshotNotFoundError(
            code="snapshot_not_found",
            message=f"snapshot for session_id={sid!r} not found at {target_dir}",
            session_id=sid,
        )

    return {
        "projection": json.loads(projection_path.read_text(encoding="utf-8")),
        "metadata": json.loads(metadata_path.read_text(encoding="utf-8")),
    }


__all__ = [
    "SNAPSHOT_CLASSIFICATION",
    "SnapshotIdValidationError",
    "SnapshotNotFoundError",
    "create_session_snapshot",
    "read_session_snapshot",
]
