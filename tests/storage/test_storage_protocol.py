"""GROUP_002: PROTOCOL — RED-first tests for storage/protocol.py.

Asserts the StorageAdapter @runtime_checkable Protocol contract per
BUILD-PLAN §PROTOCOL_SIGNATURES, including source-invariants TEST_019
(no remote adapter names) and TEST_020 (no Git ref language).

Binding rulings exercised here:
- CRS C1: signatures verbatim — pinned method names + parameter types.
- CRS C2: ``@runtime_checkable`` is attribute-presence only — tests do
  NOT rely on Protocol for full type/method validation; they assert
  attribute presence and signature shape via inspect/get_type_hints.
- B2_START_BLOCKER_003: no remote adapters, no Git refs.

R-trace: see BUILD-PLAN §TDD_TEST_LIST GROUP_002_PROTOCOL.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path
from typing import get_type_hints

import pytest


@pytest.mark.unit
class TestStorageAdapterProtocolRuntimeCheckable:
    """TEST_013: StorageAdapter Protocol exists and is @runtime_checkable."""

    def test_storage_adapter_protocol_is_runtime_checkable(self) -> None:
        from hestai_context_mcp.storage.protocol import StorageAdapter

        # @runtime_checkable Protocols expose _is_runtime_protocol = True
        # and _is_protocol = True (Python 3.11+ typing internals).
        assert getattr(StorageAdapter, "_is_runtime_protocol", False) is True
        assert getattr(StorageAdapter, "_is_protocol", False) is True
        # CRS C2 caveat: runtime_checkable provides attribute-presence
        # checks ONLY — not method/parameter type validation.
        assert StorageAdapter.__name__ == "StorageAdapter"


@pytest.mark.unit
class TestStorageAdapterRequiresCapabilities:
    """TEST_014: StorageAdapter declares ``capabilities`` attribute."""

    def test_storage_adapter_protocol_requires_capabilities_attribute(self) -> None:
        from hestai_context_mcp.storage.protocol import StorageAdapter

        hints = get_type_hints(StorageAdapter)
        assert "capabilities" in hints
        # The annotation must be StorageCapabilities.
        from hestai_context_mcp.storage.types import StorageCapabilities

        assert hints["capabilities"] is StorageCapabilities


@pytest.mark.unit
class TestListArtifactsSignature:
    """TEST_015: list_artifacts(namespace, after_id=None) -> list[ArtifactRef]."""

    def test_storage_adapter_protocol_lists_artifacts_by_namespace(self) -> None:
        from hestai_context_mcp.storage.protocol import StorageAdapter
        from hestai_context_mcp.storage.types import ArtifactRef, PortableNamespace

        sig = inspect.signature(StorageAdapter.list_artifacts)
        params = sig.parameters
        assert "namespace" in params
        assert "after_id" in params
        # default None preserves the signature freedom for fresh-list reads.
        assert params["after_id"].default is None
        hints = get_type_hints(StorageAdapter.list_artifacts)
        assert hints["namespace"] is PortableNamespace
        # str | None
        assert hints["after_id"] == str | None
        assert hints["return"] == list[ArtifactRef]


@pytest.mark.unit
class TestReadArtifactSignature:
    """TEST_016: read_artifact returns PortableArtifact union (RISK_002)."""

    def test_storage_adapter_protocol_reads_portable_artifact_union(self) -> None:
        from hestai_context_mcp.storage.protocol import StorageAdapter
        from hestai_context_mcp.storage.types import (
            ArtifactRef,
            PortableMemoryArtifact,
            TombstoneArtifact,
        )

        sig = inspect.signature(StorageAdapter.read_artifact)
        assert "ref" in sig.parameters
        hints = get_type_hints(StorageAdapter.read_artifact)
        assert hints["ref"] is ArtifactRef
        # Return type is the discriminated union — RISK_002 (no separate
        # read_tombstone). Accept both runtime alias forms.
        rt = hints["return"]
        # PortableArtifact alias resolves to a Union at runtime.
        assert PortableMemoryArtifact in getattr(rt, "__args__", (rt,)) or rt == (
            PortableMemoryArtifact | TombstoneArtifact
        )
        assert TombstoneArtifact in getattr(rt, "__args__", (rt,)) or rt == (
            PortableMemoryArtifact | TombstoneArtifact
        )


@pytest.mark.unit
class TestWriteArtifactSignature:
    """TEST_017: write_artifact requires precondition + provenance gate."""

    def test_storage_adapter_protocol_writes_memory_artifact_with_precondition(self) -> None:
        from hestai_context_mcp.storage.protocol import StorageAdapter
        from hestai_context_mcp.storage.types import (
            ArtifactRef,
            PortableMemoryArtifact,
            PublishAck,
            WritePrecondition,
        )

        sig = inspect.signature(StorageAdapter.write_artifact)
        assert {"ref", "artifact", "precondition"}.issubset(sig.parameters)
        hints = get_type_hints(StorageAdapter.write_artifact)
        assert hints["ref"] is ArtifactRef
        assert hints["artifact"] is PortableMemoryArtifact
        assert hints["precondition"] is WritePrecondition
        assert hints["return"] is PublishAck


@pytest.mark.unit
class TestWriteTombstoneSignature:
    """TEST_018: write_tombstone appends without overwrite."""

    def test_storage_adapter_protocol_writes_tombstone_with_precondition(self) -> None:
        from hestai_context_mcp.storage.protocol import StorageAdapter
        from hestai_context_mcp.storage.types import (
            ArtifactRef,
            PublishAck,
            TombstoneArtifact,
            WritePrecondition,
        )

        sig = inspect.signature(StorageAdapter.write_tombstone)
        assert {"ref", "tombstone", "precondition"}.issubset(sig.parameters)
        hints = get_type_hints(StorageAdapter.write_tombstone)
        assert hints["ref"] is ArtifactRef
        assert hints["tombstone"] is TombstoneArtifact
        assert hints["precondition"] is WritePrecondition
        assert hints["return"] is PublishAck


@pytest.mark.unit
class TestProtocolModuleSourceInvariants:
    """TEST_019/TEST_020 + TEST_165 (G1): protocol module is provider-neutral."""

    _SRC = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "hestai_context_mcp"
        / "storage"
        / "protocol.py"
    )

    # Forbidden remote-adapter usage tokens — anchored to identifier-like
    # constructs (import, from-import, class definition, function call, or
    # attribute access). Narrative prose in module docstrings citing the
    # *prohibition* is permitted (the ADR explicitly enumerates these names
    # as out-of-scope).
    _REMOTE_USAGE_PATTERNS = (
        re.compile(r"\b(?:import|from)\s+\S*RemoteHTTP\b"),
        re.compile(r"\b(?:import|from)\s+\S*GitAdapter\b"),
        re.compile(r"\b(?:import|from)\s+\S*S3Adapter\b"),
        re.compile(r"\bclass\s+(?:RemoteHTTP|GitAdapter|S3Adapter)\b"),
        re.compile(r"\b(?:RemoteHTTP|GitAdapter|S3Adapter)\s*\("),  # call sites
        re.compile(r"\.(?:RemoteHTTP|GitAdapter|S3Adapter)\b"),  # attr access
    )

    _GIT_REF_USAGE_PATTERN = re.compile(r"['\"]refs/hestai")

    def test_protocol_module_contains_no_remote_adapter_names(self) -> None:
        text = self._SRC.read_text()
        for pat in self._REMOTE_USAGE_PATTERNS:
            assert not pat.search(
                text
            ), f"protocol.py uses forbidden remote-adapter pattern /{pat.pattern}/"

    def test_protocol_module_contains_no_git_ref_storage_language(self) -> None:
        text = self._SRC.read_text()
        # Forbid string literals embedding refs/hestai (which would imply
        # the module uses Git refs as a storage carrier — R11 violation).
        assert not self._GIT_REF_USAGE_PATTERN.search(
            text
        ), "protocol.py contains a 'refs/hestai' string literal — R11 violation"

    def test_protocol_module_imports_only_typing_and_storage_types(self) -> None:
        text = self._SRC.read_text()
        forbidden = (
            "import requests",
            "import httpx",
            "import boto",
            "import git",
            "from git ",
            "import keyring",
        )
        for token in forbidden:
            assert token not in text, f"protocol.py imports forbidden module: {token}"
