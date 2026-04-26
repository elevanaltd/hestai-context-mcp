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
        from typing import Protocol, runtime_checkable

        from hestai_context_mcp.storage.protocol import StorageAdapter

        # @runtime_checkable Protocols expose _is_runtime_protocol = True.
        assert getattr(StorageAdapter, "_is_runtime_protocol", False) is True
        # Ensure it inherits from Protocol semantics — CRS C2: this is the
        # ONLY guarantee runtime_checkable provides (attribute-presence).
        assert issubclass(Protocol, type(Protocol))  # sanity
        assert StorageAdapter.__name__ == "StorageAdapter"
        # runtime_checkable is the imported decorator; presence asserted
        # by attribute on the protocol class itself.
        _ = runtime_checkable  # silence unused


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

    # Forbidden remote/Git tokens. Pattern words are anchored to import-like
    # boundaries OR appear as bare identifiers in code; comments mentioning
    # the *prohibition* are explicitly allowed.
    _REMOTE_TOKENS = (
        re.compile(r"\bRemoteHTTP\b"),
        re.compile(r"\bGitAdapter\b"),
        re.compile(r"\bS3Adapter\b"),
        re.compile(r"\brefs/hestai\b"),
    )

    def test_protocol_module_contains_no_remote_adapter_names(self) -> None:
        text = self._SRC.read_text()
        for pat in self._REMOTE_TOKENS[:3]:
            # Allow occurrences inside comment lines that announce the rule
            # (they MUST be inside lines starting with '#').
            for line in text.splitlines():
                if pat.search(line) and not line.lstrip().startswith("#"):
                    raise AssertionError(
                        f"protocol.py contains forbidden remote token /{pat.pattern}/: {line!r}"
                    )

    def test_protocol_module_contains_no_git_ref_storage_language(self) -> None:
        text = self._SRC.read_text()
        for line in text.splitlines():
            if self._REMOTE_TOKENS[3].search(line) and not line.lstrip().startswith("#"):
                raise AssertionError(
                    "protocol.py uses custom Git ref token outside a comment line"
                )

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
