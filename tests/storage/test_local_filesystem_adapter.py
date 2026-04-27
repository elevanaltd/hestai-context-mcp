"""GROUP_006: LOCAL_FILESYSTEM_ADAPTER_CAPABILITIES — RED-first tests.

Asserts the LocalFilesystemAdapter contract per BUILD-PLAN
§TDD_TEST_LIST GROUP_006 (TEST_057..TEST_078).

Binding rulings exercised here:
- INVARIANT_003 (R6 + R10): write_artifact fails closed without complete
  redaction provenance.
- G4 (CIV): provenance guard MUST raise BEFORE any side-effecting filesystem
  write — partial files cannot exist.
- R9 / RISK_002: append-first monotonic IDs, deterministic list order,
  duplicate-id semantics (idempotent same-hash, fail conflicting-hash).
- R11: no shelling out to git, no custom Git refs.
- R12: no remote SDKs, no network imports.
- RISK_006: local carrier path layout mirrors the abstract ADR layout
  under .hestai/state/portable/pss/{ns}/{proj}/{ws}/{user}/artifacts/.
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


def _namespace_from(identity: Any) -> Any:
    from hestai_context_mcp.storage.types import PortableNamespace

    return PortableNamespace(
        project_id=identity.project_id,
        workspace_id=identity.workspace_id,
        user_id=identity.user_id,
        state_schema_version=identity.state_schema_version,
        carrier_namespace=identity.carrier_namespace,
    )


def _provenance(input_text: str = "i", output_text: str = "o") -> Any:
    from hestai_context_mcp.storage.provenance import build_provenance_or_raise

    return build_provenance_or_raise(
        input_text=input_text,
        output_text=output_text,
        redacted_credential_categories=(),
    )


def _payload_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _make_artifact(
    *,
    artifact_id: str = "art-001",
    sequence_id: int = 1,
    payload: dict[str, Any] | None = None,
    identity: Any | None = None,
    provenance: Any | None = None,
) -> Any:
    from hestai_context_mcp.storage.types import ArtifactKind, PortableMemoryArtifact

    payload = payload or {"k": "v"}
    identity = identity or _identity()
    provenance = provenance or _provenance()
    return PortableMemoryArtifact(
        artifact_id=artifact_id,
        artifact_kind=ArtifactKind.PORTABLE_MEMORY,
        identity=identity,
        schema_version=1,
        producer_version="1",
        minimum_reader_version=1,
        created_at=datetime.now(UTC),
        sequence_id=sequence_id,
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
        carrier_path="",  # filled by adapter on write; ignored on read
    )


@pytest.mark.unit
class TestLocalFilesystemAdapterImplementsProtocol:
    """TEST_057."""

    def test_local_filesystem_adapter_implements_storage_adapter_protocol(
        self, tmp_path: Path
    ) -> None:
        from hestai_context_mcp.storage.local_filesystem import LocalFilesystemAdapter
        from hestai_context_mcp.storage.protocol import StorageAdapter

        adapter = LocalFilesystemAdapter(working_dir=tmp_path)
        assert isinstance(adapter, StorageAdapter)


@pytest.mark.unit
class TestCapabilitiesMatrix:
    """TEST_058..TEST_061."""

    def _adapter(self, tmp_path: Path) -> Any:
        from hestai_context_mcp.storage.local_filesystem import LocalFilesystemAdapter

        return LocalFilesystemAdapter(working_dir=tmp_path)

    def test_local_filesystem_capabilities_meet_required_publication_matrix(
        self, tmp_path: Path
    ) -> None:
        a = self._adapter(tmp_path)
        caps = a.capabilities
        # Required for publication per ADR R2 capability matrix.
        assert caps.strong_list_consistency is True
        assert caps.atomic_compare_and_swap is True
        assert caps.conditional_writes is True
        assert caps.read_only is False

    def test_local_filesystem_encryption_capabilities_are_false_for_local_policy(
        self, tmp_path: Path
    ) -> None:
        a = self._adapter(tmp_path)
        # Local disk is outside this ADR; the adapter does not implement
        # at-rest/in-transit encryption itself.
        assert a.capabilities.encryption_at_rest is False
        assert a.capabilities.encryption_in_transit is False

    def test_local_filesystem_has_strong_list_consistency(self, tmp_path: Path) -> None:
        assert self._adapter(tmp_path).capabilities.strong_list_consistency is True

    def test_local_filesystem_conditional_writes_required(self, tmp_path: Path) -> None:
        assert self._adapter(tmp_path).capabilities.conditional_writes is True


@pytest.mark.unit
class TestPortableStateRoot:
    """TEST_062 + TEST_063 — root layout + unsafe namespace rejection."""

    def test_local_filesystem_uses_portable_state_root_only(self, tmp_path: Path) -> None:
        from hestai_context_mcp.storage.local_filesystem import LocalFilesystemAdapter

        adapter = LocalFilesystemAdapter(working_dir=tmp_path)
        assert adapter.portable_root == tmp_path / ".hestai" / "state" / "portable"
        # The adapter never writes outside portable_root.
        artifact = _make_artifact()
        ref = _make_ref_for(artifact)
        from hestai_context_mcp.storage.types import WritePrecondition

        adapter.write_artifact(ref, artifact, WritePrecondition())
        # All produced files live under portable_root.
        for path in tmp_path.rglob("*"):
            if path.is_file():
                assert adapter.portable_root in path.parents or path == adapter.portable_root

    def test_local_filesystem_rejects_unsafe_namespace_before_path_construction(
        self, tmp_path: Path
    ) -> None:
        from hestai_context_mcp.storage.identity import IdentityValidationError
        from hestai_context_mcp.storage.local_filesystem import LocalFilesystemAdapter
        from hestai_context_mcp.storage.types import PortableNamespace

        adapter = LocalFilesystemAdapter(working_dir=tmp_path)
        bad = PortableNamespace(
            project_id="../../etc",
            workspace_id="wt",
            user_id="alice",
            state_schema_version=1,
            carrier_namespace="personal",
        )
        with pytest.raises(IdentityValidationError):
            adapter.list_artifacts(bad)


@pytest.mark.unit
class TestWriteArtifact:
    """TEST_064..TEST_069 — write semantics."""

    def _adapter(self, tmp_path: Path) -> Any:
        from hestai_context_mcp.storage.local_filesystem import LocalFilesystemAdapter

        return LocalFilesystemAdapter(working_dir=tmp_path)

    def test_local_filesystem_write_creates_artifact_file(self, tmp_path: Path) -> None:
        from hestai_context_mcp.storage.types import WritePrecondition

        adapter = self._adapter(tmp_path)
        artifact = _make_artifact()
        ref = _make_ref_for(artifact)
        ack = adapter.write_artifact(ref, artifact, WritePrecondition())
        # An on-disk file exists under the artifacts subtree.
        artifact_files = list(
            (tmp_path / ".hestai" / "state" / "portable" / "pss").rglob("*.json")
        )
        assert artifact_files
        assert any(artifact.artifact_id in p.name for p in artifact_files)
        assert ack.artifact_id == artifact.artifact_id

    def test_local_filesystem_write_returns_publish_ack(self, tmp_path: Path) -> None:
        from hestai_context_mcp.storage.types import (
            PublishAck,
            PublishStatus,
            WritePrecondition,
        )

        adapter = self._adapter(tmp_path)
        artifact = _make_artifact()
        ref = _make_ref_for(artifact)
        ack = adapter.write_artifact(ref, artifact, WritePrecondition())
        assert isinstance(ack, PublishAck)
        assert ack.status == PublishStatus.PUBLISHED
        assert ack.identity == artifact.identity
        assert ack.sequence_id == artifact.sequence_id
        assert ack.carrier_namespace == artifact.identity.carrier_namespace

    def test_local_filesystem_write_fails_without_complete_redaction_provenance(
        self, tmp_path: Path
    ) -> None:
        """INVARIANT_003 — provenance gate fails closed (G4 atomic guard)."""
        from hestai_context_mcp.storage.provenance import ProvenanceIncompleteError
        from hestai_context_mcp.storage.types import (
            ArtifactKind,
            PortableMemoryArtifact,
            RedactionProvenance,
            WritePrecondition,
        )

        adapter = self._adapter(tmp_path)
        identity = _identity()
        # Provenance with empty engine_name simulates incomplete provenance.
        bad_provenance = RedactionProvenance(
            engine_name="",  # missing
            engine_version="1",
            ruleset_hash="x" * 64,
            input_artifact_hash="a" * 64,
            output_artifact_hash="b" * 64,
            redacted_at=datetime.now(UTC),
            classification_label="PORTABLE_MEMORY",
            redacted_credential_categories=(),
        )
        payload = {"k": "v"}
        artifact = PortableMemoryArtifact(
            artifact_id="bad-1",
            artifact_kind=ArtifactKind.PORTABLE_MEMORY,
            identity=identity,
            schema_version=1,
            producer_version="1",
            minimum_reader_version=1,
            created_at=datetime.now(UTC),
            sequence_id=1,
            parent_ids=(),
            redaction_provenance=bad_provenance,
            classification_label="PORTABLE_MEMORY",
            payload_hash=_payload_hash(payload),
            payload=payload,
        )
        ref = _make_ref_for(artifact)

        with pytest.raises(ProvenanceIncompleteError):
            adapter.write_artifact(ref, artifact, WritePrecondition())

        # G4 atomic-guard: NO partial file written under the pss subtree
        # (CE rework RISK_006: ADR-0013 abstract path).
        pss_dir = tmp_path / ".hestai" / "state" / "portable" / "pss"
        if pss_dir.exists():
            assert not list(pss_dir.rglob("*.json"))

    def test_local_filesystem_write_is_create_only_by_default(self, tmp_path: Path) -> None:
        from hestai_context_mcp.storage.types import WritePrecondition

        adapter = self._adapter(tmp_path)
        artifact = _make_artifact()
        ref = _make_ref_for(artifact)
        adapter.write_artifact(ref, artifact, WritePrecondition())
        # A second call with the SAME id but DIFFERENT payload (different
        # hash) must NOT overwrite — see TEST_069 for the exact behavior.
        # Default precondition is if_absent=True.
        assert WritePrecondition().if_absent is True

    def test_duplicate_artifact_id_same_hash_is_idempotent_duplicate_ack(
        self, tmp_path: Path
    ) -> None:
        from hestai_context_mcp.storage.types import PublishStatus, WritePrecondition

        adapter = self._adapter(tmp_path)
        artifact = _make_artifact()
        ref = _make_ref_for(artifact)
        adapter.write_artifact(ref, artifact, WritePrecondition())
        ack2 = adapter.write_artifact(ref, artifact, WritePrecondition())
        assert ack2.status == PublishStatus.DUPLICATE

    def test_duplicate_artifact_id_different_hash_fails_precondition(self, tmp_path: Path) -> None:
        from hestai_context_mcp.storage.types import PublishStatus, WritePrecondition

        adapter = self._adapter(tmp_path)
        artifact1 = _make_artifact(payload={"k": "v"})
        ref1 = _make_ref_for(artifact1)
        adapter.write_artifact(ref1, artifact1, WritePrecondition())

        # Same artifact_id, different payload (different hash) → FAILED.
        artifact2 = _make_artifact(payload={"k": "v2"})
        # rebuild ref with the *first* artifact_id + the *second* payload hash
        from hestai_context_mcp.storage.types import ArtifactRef

        ref2 = ArtifactRef(
            artifact_id=artifact1.artifact_id,
            identity=artifact2.identity,
            artifact_kind=artifact2.artifact_kind,
            sequence_id=artifact2.sequence_id,
            created_at=artifact2.created_at,
            payload_hash=artifact2.payload_hash,
            carrier_path="",
        )
        from hestai_context_mcp.storage.types import ArtifactKind, PortableMemoryArtifact

        # Force same artifact_id, different payload.
        conflicting = PortableMemoryArtifact(
            artifact_id=artifact1.artifact_id,
            artifact_kind=ArtifactKind.PORTABLE_MEMORY,
            identity=artifact2.identity,
            schema_version=1,
            producer_version="1",
            minimum_reader_version=1,
            created_at=artifact2.created_at,
            sequence_id=artifact2.sequence_id,
            parent_ids=(),
            redaction_provenance=artifact2.redaction_provenance,
            classification_label="PORTABLE_MEMORY",
            payload_hash=artifact2.payload_hash,
            payload=artifact2.payload,
        )
        ack = adapter.write_artifact(ref2, conflicting, WritePrecondition())
        assert ack.status == PublishStatus.FAILED
        assert ack.error_code is not None


@pytest.mark.unit
class TestListArtifacts:
    """TEST_070..TEST_071."""

    def test_list_artifacts_returns_monotonic_sequence_order(self, tmp_path: Path) -> None:
        from hestai_context_mcp.storage.local_filesystem import LocalFilesystemAdapter
        from hestai_context_mcp.storage.types import WritePrecondition

        adapter = LocalFilesystemAdapter(working_dir=tmp_path)
        # Insert in non-monotonic order.
        a3 = _make_artifact(artifact_id="art-3", sequence_id=3, payload={"i": 3})
        a1 = _make_artifact(artifact_id="art-1", sequence_id=1, payload={"i": 1})
        a2 = _make_artifact(artifact_id="art-2", sequence_id=2, payload={"i": 2})
        for art in (a3, a1, a2):
            adapter.write_artifact(_make_ref_for(art), art, WritePrecondition())

        refs = adapter.list_artifacts(_namespace_from(_identity()))
        seqs = [r.sequence_id for r in refs]
        assert seqs == sorted(seqs)
        assert seqs == [1, 2, 3]

    def test_list_artifacts_after_id_filters_exclusive(self, tmp_path: Path) -> None:
        from hestai_context_mcp.storage.local_filesystem import LocalFilesystemAdapter
        from hestai_context_mcp.storage.types import WritePrecondition

        adapter = LocalFilesystemAdapter(working_dir=tmp_path)
        a1 = _make_artifact(artifact_id="art-1", sequence_id=1, payload={"i": 1})
        a2 = _make_artifact(artifact_id="art-2", sequence_id=2, payload={"i": 2})
        a3 = _make_artifact(artifact_id="art-3", sequence_id=3, payload={"i": 3})
        for art in (a1, a2, a3):
            adapter.write_artifact(_make_ref_for(art), art, WritePrecondition())

        ns = _namespace_from(_identity())
        refs = adapter.list_artifacts(ns, after_id="art-1")
        ids = [r.artifact_id for r in refs]
        assert "art-1" not in ids
        assert ids == ["art-2", "art-3"]


@pytest.mark.unit
class TestReadArtifact:
    """TEST_072..TEST_073."""

    def test_read_artifact_validates_payload_hash(self, tmp_path: Path) -> None:
        from hestai_context_mcp.storage.local_filesystem import (
            LocalFilesystemAdapter,
            PayloadHashMismatchError,
        )
        from hestai_context_mcp.storage.types import WritePrecondition

        adapter = LocalFilesystemAdapter(working_dir=tmp_path)
        artifact = _make_artifact()
        ref = _make_ref_for(artifact)
        adapter.write_artifact(ref, artifact, WritePrecondition())

        # Tamper with the on-disk file.
        artifact_files = list(
            (tmp_path / ".hestai" / "state" / "portable" / "pss").rglob("*.json")
        )
        assert artifact_files
        target = artifact_files[0]
        raw = json.loads(target.read_text())
        raw["payload"] = {"tampered": True}
        target.write_text(json.dumps(raw))

        with pytest.raises(PayloadHashMismatchError):
            adapter.read_artifact(ref)

    def test_read_artifact_rejects_identity_mismatch(self, tmp_path: Path) -> None:
        from hestai_context_mcp.storage.identity import IdentityValidationError
        from hestai_context_mcp.storage.local_filesystem import LocalFilesystemAdapter
        from hestai_context_mcp.storage.types import (
            ArtifactRef,
            IdentityTuple,
            WritePrecondition,
        )

        adapter = LocalFilesystemAdapter(working_dir=tmp_path)
        artifact = _make_artifact()
        ref = _make_ref_for(artifact)
        adapter.write_artifact(ref, artifact, WritePrecondition())

        # Build a ref with a *different* identity pointing at the same path.
        wrong_identity = IdentityTuple(
            project_id="proj-OTHER",
            workspace_id="wt-build",
            user_id="alice",
            state_schema_version=1,
            carrier_namespace="personal",
        )
        bad_ref = ArtifactRef(
            artifact_id=ref.artifact_id,
            identity=wrong_identity,
            artifact_kind=ref.artifact_kind,
            sequence_id=ref.sequence_id,
            created_at=ref.created_at,
            payload_hash=ref.payload_hash,
            carrier_path=ref.carrier_path,
        )
        with pytest.raises((IdentityValidationError, FileNotFoundError)):
            adapter.read_artifact(bad_ref)


@pytest.mark.unit
class TestWriteTombstone:
    """TEST_074..TEST_076."""

    def _adapter(self, tmp_path: Path) -> Any:
        from hestai_context_mcp.storage.local_filesystem import LocalFilesystemAdapter

        return LocalFilesystemAdapter(working_dir=tmp_path)

    def _make_tombstone(self, *, target_artifact_id: str, sequence_id: int = 99) -> Any:
        from hestai_context_mcp.storage.types import ArtifactKind, TombstoneArtifact

        identity = _identity()
        return TombstoneArtifact(
            artifact_id=f"tomb-{target_artifact_id}",
            artifact_kind=ArtifactKind.TOMBSTONE,
            identity=identity,
            schema_version=1,
            producer_version="1",
            minimum_reader_version=1,
            created_at=datetime.now(UTC),
            sequence_id=sequence_id,
            parent_ids=(target_artifact_id,),
            target_artifact_id=target_artifact_id,
            reason="user-revoked",
            publisher_identity=identity,
            redaction_provenance=None,
            classification_label="PORTABLE_MEMORY",
            payload_hash=hashlib.sha256(target_artifact_id.encode()).hexdigest(),
        )

    def _ref_for_tombstone(self, tomb: Any) -> Any:
        from hestai_context_mcp.storage.types import ArtifactRef

        return ArtifactRef(
            artifact_id=tomb.artifact_id,
            identity=tomb.identity,
            artifact_kind=tomb.artifact_kind,
            sequence_id=tomb.sequence_id,
            created_at=tomb.created_at,
            payload_hash=tomb.payload_hash,
            carrier_path="",
        )

    def test_write_tombstone_appends_tombstone_file(self, tmp_path: Path) -> None:
        from hestai_context_mcp.storage.types import WritePrecondition

        adapter = self._adapter(tmp_path)
        # First seed a memory artifact to tombstone.
        artifact = _make_artifact(artifact_id="art-1", sequence_id=1)
        adapter.write_artifact(_make_ref_for(artifact), artifact, WritePrecondition())
        tomb = self._make_tombstone(target_artifact_id="art-1")
        ack = adapter.write_tombstone(self._ref_for_tombstone(tomb), tomb, WritePrecondition())
        assert ack.artifact_id == tomb.artifact_id
        # CE rework RISK_006: tombstones live under per-identity subtree at
        # portable/pss/{ns}/{proj}/{ws}/{user}/tombstones/{id}.json.
        pss_root = tmp_path / ".hestai" / "state" / "portable" / "pss"
        assert pss_root.exists()
        tombstones = [p for p in pss_root.rglob("*.json") if p.parent.name == "tombstones"]
        assert tombstones, f"no tombstone files found under {pss_root}"

    def test_write_tombstone_does_not_delete_target_artifact(self, tmp_path: Path) -> None:
        from hestai_context_mcp.storage.types import WritePrecondition

        adapter = self._adapter(tmp_path)
        artifact = _make_artifact(artifact_id="art-1", sequence_id=1)
        adapter.write_artifact(_make_ref_for(artifact), artifact, WritePrecondition())
        target_files = list(
            (tmp_path / ".hestai" / "state" / "portable" / "pss").rglob("*.json")
        )
        assert target_files
        target_file = target_files[0]
        before = target_file.read_text()

        tomb = self._make_tombstone(target_artifact_id="art-1")
        adapter.write_tombstone(self._ref_for_tombstone(tomb), tomb, WritePrecondition())
        assert target_file.exists()
        assert target_file.read_text() == before

    def test_write_tombstone_for_redaction_failure_requires_provenance(
        self, tmp_path: Path
    ) -> None:
        """If reason indicates post-hoc redaction failure, provenance is required."""
        from hestai_context_mcp.storage.local_filesystem import (
            TombstoneProvenanceRequiredError,
        )
        from hestai_context_mcp.storage.types import (
            ArtifactKind,
            TombstoneArtifact,
            WritePrecondition,
        )

        adapter = self._adapter(tmp_path)
        identity = _identity()
        bad_tomb = TombstoneArtifact(
            artifact_id="tomb-bad",
            artifact_kind=ArtifactKind.TOMBSTONE,
            identity=identity,
            schema_version=1,
            producer_version="1",
            minimum_reader_version=1,
            created_at=datetime.now(UTC),
            sequence_id=10,
            parent_ids=("art-x",),
            target_artifact_id="art-x",
            reason="redaction_failure",  # post-hoc redaction failure
            publisher_identity=identity,
            redaction_provenance=None,  # MISSING
            classification_label="PORTABLE_MEMORY",
            payload_hash="0" * 64,
        )
        from hestai_context_mcp.storage.types import ArtifactRef

        ref = ArtifactRef(
            artifact_id=bad_tomb.artifact_id,
            identity=bad_tomb.identity,
            artifact_kind=bad_tomb.artifact_kind,
            sequence_id=bad_tomb.sequence_id,
            created_at=bad_tomb.created_at,
            payload_hash=bad_tomb.payload_hash,
            carrier_path="",
        )
        with pytest.raises(TombstoneProvenanceRequiredError):
            adapter.write_tombstone(ref, bad_tomb, WritePrecondition())


@pytest.mark.unit
class TestAdapterSourceInvariants:
    """TEST_077..TEST_078 — module-level structural guards."""

    _SRC = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "hestai_context_mcp"
        / "storage"
        / "local_filesystem.py"
    )

    def test_adapter_never_shells_out_to_git(self) -> None:
        text = self._SRC.read_text()
        assert "subprocess" not in text or '"git"' not in text
        # No git CLI invocations of any kind.
        assert not re.search(r"\bsubprocess\.\w+\(.*\bgit\b", text)
        # No custom Git refs language.
        assert "refs/hestai" not in text

    def test_adapter_has_no_network_imports(self) -> None:
        text = self._SRC.read_text()
        forbidden = (
            "import requests",
            "import httpx",
            "import boto",
            "import urllib3",
            "from urllib3",
            "import aiohttp",
            "from boto",
            "from requests",
            "from httpx",
        )
        for token in forbidden:
            assert token not in text, f"local_filesystem.py imports forbidden module: {token}"
