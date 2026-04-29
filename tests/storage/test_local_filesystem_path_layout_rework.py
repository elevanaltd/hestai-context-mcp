"""GROUP_017 — REWORK CYCLE RED tests for RISK_006 path layout drift.

Asserts the binding ruling from CE Stage C: the LocalFilesystemAdapter
on-disk path layout MUST match the ADR-0013 abstract path
``pss/{carrier_namespace}/{project_id}/{workspace_id}/{user_id}/artifacts/{artifact_id}``.

The current (pre-rework) layout was
``portable/artifacts/{ns}/{proj}/{ws}/{user}/v{schema_version}/{id}.json``
which violates the ruling on three counts:

- Top segment is ``portable/artifacts`` instead of ``pss``.
- The ``artifacts/`` segment lives at the top instead of the END.
- ``v{schema_version}`` is in the path; ADR-0013 binds schema_version as
  a field inside PortableMemoryArtifact and PortableNamespace, NOT as a
  path component (over-specification beyond the binding ruling).

After GREEN: every artifact write produces a file whose path relative to
the portable root matches::

    ^pss/[^/]+/[^/]+/[^/]+/[^/]+/artifacts/[^/]+\\.json$

The local portable root remains ``.hestai/state/portable/`` per the
BUILD-PLAN §FILE_LAYOUT NEW_FILE local_filesystem.py STRUCTURE rule
"Rooted under .hestai/state/portable for local carrier state."
"""

from __future__ import annotations

import hashlib
import json
import re
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


def _payload_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _make_artifact() -> Any:
    from hestai_context_mcp.storage.provenance import build_provenance_or_raise
    from hestai_context_mcp.storage.types import (
        ArtifactKind,
        PortableMemoryArtifact,
    )

    payload = {"k": "v"}
    provenance = build_provenance_or_raise(
        input_text="i", output_text="o", redacted_credential_categories=()
    )
    return PortableMemoryArtifact(
        artifact_id="art-rework-001",
        artifact_kind=ArtifactKind.PORTABLE_MEMORY,
        identity=_identity(),
        schema_version=1,
        producer_version="1",
        minimum_reader_version=1,
        created_at=datetime.now(UTC),
        sequence_id=1,
        parent_ids=(),
        redaction_provenance=provenance,
        classification_label="PORTABLE_MEMORY",
        payload_hash=_payload_hash(payload),
        payload=payload,
    )


def _make_ref_for(artifact: Any) -> Any:
    from hestai_context_mcp.storage.types import ArtifactRef

    return ArtifactRef(
        artifact_id=artifact.artifact_id,
        identity=artifact.identity,
        artifact_kind=artifact.artifact_kind,
        sequence_id=artifact.sequence_id,
        created_at=artifact.created_at,
        payload_hash=artifact.payload_hash,
        carrier_path="",
    )


# ADR-0013 abstract path regex (relative to the portable root).
_PSS_PATH_REGEX = re.compile(r"^pss/[^/]+/[^/]+/[^/]+/[^/]+/artifacts/[^/]+\.json$")


@pytest.mark.unit
class TestLocalFilesystemPssPathLayout:
    """BLOCKER 2 / RISK_006: path geometry must match ADR-0013 abstract path."""

    def test_write_artifact_produces_path_matching_pss_regex(self, tmp_path: Path) -> None:
        from hestai_context_mcp.storage.local_filesystem import LocalFilesystemAdapter
        from hestai_context_mcp.storage.types import WritePrecondition

        adapter = LocalFilesystemAdapter(working_dir=tmp_path)
        artifact = _make_artifact()
        ref = _make_ref_for(artifact)
        ack = adapter.write_artifact(ref, artifact, WritePrecondition())

        # Receipt must match the regex relative to the portable root.
        receipt = ack.durable_carrier_receipt
        assert receipt is not None, "PUBLISHED ack must carry a durable_carrier_receipt"
        portable_root = tmp_path / ".hestai" / "state" / "portable"
        relative = Path(receipt).resolve().relative_to(portable_root.resolve())
        assert _PSS_PATH_REGEX.match(str(relative)), (
            f"path {relative!r} does not match ADR-0013 abstract path regex "
            f"^pss/[^/]+/[^/]+/[^/]+/[^/]+/artifacts/[^/]+\\.json$"
        )

    def test_write_artifact_top_segment_is_pss_not_portable_artifacts(self, tmp_path: Path) -> None:
        from hestai_context_mcp.storage.local_filesystem import LocalFilesystemAdapter
        from hestai_context_mcp.storage.types import WritePrecondition

        adapter = LocalFilesystemAdapter(working_dir=tmp_path)
        artifact = _make_artifact()
        ref = _make_ref_for(artifact)
        adapter.write_artifact(ref, artifact, WritePrecondition())

        # New layout: pss/ exists; portable/artifacts/{ns}/... does NOT.
        assert (
            tmp_path / ".hestai" / "state" / "portable" / "pss"
        ).exists(), "ADR-0013 binding requires top segment 'pss' under portable root"
        # The legacy 'artifacts/' top-segment subtree at portable/artifacts/{ns}
        # must not be created. (Note: the END-position 'artifacts/' segment
        # under pss/{ns}/{proj}/{ws}/{user}/artifacts IS expected.)
        legacy_top = tmp_path / ".hestai" / "state" / "portable" / "artifacts"
        # If it exists, it MUST be empty — but the cleanest assertion is that
        # no JSON files are produced under the legacy top-level path.
        if legacy_top.exists():
            json_files = list(legacy_top.rglob("*.json"))
            assert json_files == [], (
                f"legacy top-level portable/artifacts/ must not contain artifact files; "
                f"found: {json_files}"
            )

    def test_write_artifact_does_not_include_v_schema_version_segment(self, tmp_path: Path) -> None:
        from hestai_context_mcp.storage.local_filesystem import LocalFilesystemAdapter
        from hestai_context_mcp.storage.types import WritePrecondition

        adapter = LocalFilesystemAdapter(working_dir=tmp_path)
        artifact = _make_artifact()
        ref = _make_ref_for(artifact)
        ack = adapter.write_artifact(ref, artifact, WritePrecondition())

        receipt = ack.durable_carrier_receipt
        assert receipt is not None
        # No segment named v1, v2, etc. The schema_version is a field on
        # PortableMemoryArtifact and PortableNamespace, not a path segment.
        rel_str = str(
            Path(receipt)
            .resolve()
            .relative_to((tmp_path / ".hestai" / "state" / "portable").resolve())
        )
        for part in Path(rel_str).parts:
            assert not re.match(r"^v\d+$", part), (
                f"path segment {part!r} matches v<int> shape; "
                "v{schema_version} is over-specification beyond ADR-0013 ruling"
            )

    def test_write_artifact_artifacts_segment_is_at_end_before_artifact_id(
        self, tmp_path: Path
    ) -> None:
        from hestai_context_mcp.storage.local_filesystem import LocalFilesystemAdapter
        from hestai_context_mcp.storage.types import WritePrecondition

        adapter = LocalFilesystemAdapter(working_dir=tmp_path)
        artifact = _make_artifact()
        ref = _make_ref_for(artifact)
        ack = adapter.write_artifact(ref, artifact, WritePrecondition())

        receipt = ack.durable_carrier_receipt
        assert receipt is not None
        rel = (
            Path(receipt)
            .resolve()
            .relative_to((tmp_path / ".hestai" / "state" / "portable").resolve())
        )
        parts = rel.parts
        # Expected: ('pss', ns, proj, ws, user, 'artifacts', '<id>.json')
        assert len(parts) == 7, (
            f"expected 7 path segments (pss, ns, proj, ws, user, artifacts, id.json); "
            f"got {len(parts)}: {parts}"
        )
        assert parts[0] == "pss"
        assert parts[-2] == "artifacts", (
            f"'artifacts' segment must be second-from-last (just before artifact id); "
            f"got parts={parts}"
        )
        assert parts[-1].endswith(".json")
