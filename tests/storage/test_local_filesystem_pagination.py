"""Cubic rework cycle 2 — Finding #4 (P1, local_filesystem.py:414).

RED-first test: ``list_artifacts(after_id=...)`` must paginate by the
same key as the sort, ``(sequence_id, artifact_id)``. Filtering by
lexicographic ``r.artifact_id > after_id`` returns wrong results when
artifact_ids do not increase monotonically with sequence_ids. PROD::I1
SESSION_LIFECYCLE_INTEGRITY relies on a correct cursor for restore-time
listing.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest


def _identity() -> Any:
    from hestai_context_mcp.storage.types import IdentityTuple

    return IdentityTuple(
        project_id="proj-A",
        workspace_id="wt-build",
        user_id="alice",
        state_schema_version=1,
        carrier_namespace="personal",
    )


def _namespace() -> Any:
    from hestai_context_mcp.storage.types import PortableNamespace

    identity = _identity()
    return PortableNamespace(
        project_id=identity.project_id,
        workspace_id=identity.workspace_id,
        user_id=identity.user_id,
        state_schema_version=identity.state_schema_version,
        carrier_namespace=identity.carrier_namespace,
    )


def _provenance() -> Any:
    from hestai_context_mcp.storage.provenance import build_provenance_or_raise

    return build_provenance_or_raise(
        input_text="i", output_text="o", redacted_credential_categories=()
    )


def _payload_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _seed(adapter: Any, artifact_id: str, sequence_id: int) -> None:
    from hestai_context_mcp.storage.types import (
        ArtifactKind,
        ArtifactRef,
        PortableMemoryArtifact,
        WritePrecondition,
    )

    payload = {"id": artifact_id, "seq": sequence_id}
    artifact = PortableMemoryArtifact(
        artifact_id=artifact_id,
        artifact_kind=ArtifactKind.PORTABLE_MEMORY,
        identity=_identity(),
        schema_version=1,
        producer_version="1",
        minimum_reader_version=1,
        created_at=datetime.now(UTC),
        sequence_id=sequence_id,
        parent_ids=(),
        redaction_provenance=_provenance(),
        classification_label="PORTABLE_MEMORY",
        payload_hash=_payload_hash(payload),
        payload=payload,
    )
    ref = ArtifactRef(
        artifact_id=artifact.artifact_id,
        identity=artifact.identity,
        artifact_kind=artifact.artifact_kind,
        sequence_id=artifact.sequence_id,
        created_at=artifact.created_at,
        payload_hash=artifact.payload_hash,
        carrier_path="",
    )
    adapter.write_artifact(ref, artifact, WritePrecondition())


@pytest.mark.unit
class TestListArtifactsPaginationCursorTuple:
    """Cubic P1 #4: paginate by (sequence_id, artifact_id), not lex of id."""

    def test_pagination_returns_correct_tail_when_id_lex_differs_from_sort(
        self, tmp_path: Path
    ) -> None:
        """Construct artifacts where lex order on artifact_id alone differs
        from the canonical (sequence_id, artifact_id) sort, then assert
        ``after_id`` returns the correct tail."""

        from hestai_context_mcp.storage.local_filesystem import LocalFilesystemAdapter

        adapter = LocalFilesystemAdapter(working_dir=tmp_path)
        ns = _namespace()

        # Sequence 1 has the lex-greatest id; sequence 2 has the lex-least.
        # Canonical sort: A(seq=1, id="zzz"), B(seq=2, id="aaa")
        # Lexicographic sort of ids only: B, A — different!
        _seed(adapter, artifact_id="zzz", sequence_id=1)
        _seed(adapter, artifact_id="aaa", sequence_id=2)

        full = adapter.list_artifacts(ns)
        assert [r.artifact_id for r in full] == ["zzz", "aaa"], (
            "sort must be (sequence_id, artifact_id); got " f"{[r.artifact_id for r in full]}"
        )

        # Cursor at first ref: tail must contain the second ref.
        tail = adapter.list_artifacts(ns, after_id="zzz")
        assert [r.artifact_id for r in tail] == ["aaa"], (
            "pagination must use sort key, not lex of artifact_id alone; "
            f"got {[r.artifact_id for r in tail]}"
        )

    def test_pagination_returns_empty_after_last_ref(self, tmp_path: Path) -> None:
        """Cursor at the last ref returns an empty tail regardless of id-lex order."""

        from hestai_context_mcp.storage.local_filesystem import LocalFilesystemAdapter

        adapter = LocalFilesystemAdapter(working_dir=tmp_path)
        ns = _namespace()
        _seed(adapter, artifact_id="zzz", sequence_id=1)
        _seed(adapter, artifact_id="aaa", sequence_id=2)

        # ``aaa`` is the last in the canonical (seq, id) sort.
        tail = adapter.list_artifacts(ns, after_id="aaa")
        assert tail == []
