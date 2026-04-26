"""GROUP_007: OUTBOX — RED-first tests for storage/outbox.py.

Asserts the Durable Outbound Queue contract per BUILD-PLAN
§TDD_TEST_LIST GROUP_007 (TEST_079..TEST_088) and ADR-0013 R7.

Binding rulings exercised here:
- RISK_008 + G7: B1 implements queue creation + status only — no retry
  orchestration. Drain/retry tools are deferred until a future ADR.
- A2 (CIV): clock_out emits a structured ``portable_publication`` status
  record even when publish is skipped (e.g., no transcript / provenance
  unavailable). The outbox surface here exposes
  ``unpublished_memory_exists`` so the clock_out integration can route
  status without re-implementing queue scanning.
- R7: queue path is ``.hestai/state/portable/outbox/{artifact_id}.json``.
- R10: parse errors surface as structured errors, not silent skips.
- get_context purity: no outbox file is created/modified by reads
  (TEST_088).
"""

from __future__ import annotations

import json
import time
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


def _failed_ack(artifact_id: str = "art-1") -> Any:
    from hestai_context_mcp.storage.types import PublishAck, PublishStatus

    identity = _identity()
    return PublishAck(
        artifact_id=artifact_id,
        identity=identity,
        carrier_namespace=identity.carrier_namespace,
        sequence_id=1,
        status=PublishStatus.FAILED,
        durable_carrier_receipt=None,
        queued_path=None,
        published_at=None,
        error_code="adapter_io_error",
        error_message="simulated failure",
    )


@pytest.mark.unit
class TestOutboxRoot:
    """TEST_079."""

    def test_outbox_root_is_hestai_state_portable_outbox(self, tmp_path: Path) -> None:
        from hestai_context_mcp.storage.outbox import OutboxStore

        store = OutboxStore(working_dir=tmp_path)
        assert store.root == tmp_path / ".hestai" / "state" / "portable" / "outbox"


@pytest.mark.unit
class TestEnqueue:
    """TEST_080..TEST_082."""

    def test_enqueue_unpublished_artifact_writes_json_by_artifact_id(self, tmp_path: Path) -> None:
        from hestai_context_mcp.storage.outbox import OutboxStore

        store = OutboxStore(working_dir=tmp_path)
        ack = _failed_ack(artifact_id="art-42")
        path = store.enqueue(
            ack=ack,
            error_code="adapter_io_error",
            error_message="simulated failure",
        )
        assert path.name == "art-42.json"
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["artifact_id"] == "art-42"

    def test_enqueue_uses_atomic_replace(self, tmp_path: Path) -> None:
        """Atomic replace: a tmp staging directory is used and the final file
        is the only one in place after enqueue.
        """
        from hestai_context_mcp.storage.outbox import OutboxStore

        store = OutboxStore(working_dir=tmp_path)
        ack = _failed_ack(artifact_id="art-1")
        path = store.enqueue(ack=ack, error_code="x", error_message="y")
        # No leftover .tmp file in the outbox dir.
        assert path.exists()
        leftovers = [p for p in store.root.iterdir() if p.suffix == ".tmp"]
        assert leftovers == []

    def test_outbox_entry_contains_artifact_ack_error_and_retry_metadata(
        self, tmp_path: Path
    ) -> None:
        from hestai_context_mcp.storage.outbox import OutboxStore

        store = OutboxStore(working_dir=tmp_path)
        ack = _failed_ack(artifact_id="art-77")
        path = store.enqueue(
            ack=ack,
            error_code="adapter_io_error",
            error_message="simulated failure",
        )
        data = json.loads(path.read_text(encoding="utf-8"))
        for k in (
            "artifact_id",
            "identity",
            "carrier_namespace",
            "sequence_id",
            "status",
            "error_code",
            "error_message",
            "enqueued_at",
            "retry_count",
        ):
            assert k in data, f"missing key {k!r}"
        # B1 status-only: retry_count starts at 0 and is never advanced
        # automatically (RISK_008 + G7).
        assert data["retry_count"] == 0


@pytest.mark.unit
class TestStatus:
    """TEST_083..TEST_084."""

    def test_outbox_status_true_when_entries_exist(self, tmp_path: Path) -> None:
        from hestai_context_mcp.storage.outbox import OutboxStore

        store = OutboxStore(working_dir=tmp_path)
        store.enqueue(ack=_failed_ack("a-1"), error_code="x", error_message="y")
        assert store.unpublished_memory_exists() is True

    def test_outbox_status_false_when_empty(self, tmp_path: Path) -> None:
        from hestai_context_mcp.storage.outbox import OutboxStore

        store = OutboxStore(working_dir=tmp_path)
        assert store.unpublished_memory_exists() is False


@pytest.mark.unit
class TestList:
    """TEST_085..TEST_086."""

    def test_list_outbox_entries_is_deterministic(self, tmp_path: Path) -> None:
        from hestai_context_mcp.storage.outbox import OutboxStore

        store = OutboxStore(working_dir=tmp_path)
        store.enqueue(ack=_failed_ack("a-3"), error_code="x", error_message="y")
        store.enqueue(ack=_failed_ack("a-1"), error_code="x", error_message="y")
        store.enqueue(ack=_failed_ack("a-2"), error_code="x", error_message="y")
        ids = [e["artifact_id"] for e in store.list_entries()]
        assert ids == ["a-1", "a-2", "a-3"]

    def test_outbox_unknown_entry_parse_error_is_structured(self, tmp_path: Path) -> None:
        from hestai_context_mcp.storage.outbox import OutboxParseError, OutboxStore

        store = OutboxStore(working_dir=tmp_path)
        store.root.mkdir(parents=True, exist_ok=True)
        bad = store.root / "broken.json"
        bad.write_text("{not-json")
        with pytest.raises(OutboxParseError):
            store.list_entries()


@pytest.mark.unit
class TestClassification:
    """TEST_087."""

    def test_outbox_is_classified_local_mutable(self, tmp_path: Path) -> None:
        from hestai_context_mcp.storage.outbox import OutboxStore

        from hestai_context_mcp.storage.types import StateClassification

        store = OutboxStore(working_dir=tmp_path)
        assert store.classification is StateClassification.LOCAL_MUTABLE


@pytest.mark.unit
class TestPurityIntegration:
    """TEST_088 — get_context never touches outbox files."""

    def test_get_context_does_not_touch_outbox_mtime(self, tmp_path: Path) -> None:
        # Set up a project with a North Star and an outbox entry.
        (tmp_path / ".hestai" / "north-star").mkdir(parents=True, exist_ok=True)
        (tmp_path / ".hestai" / "north-star" / "000-PROJECT-NORTH-STAR.oct.md").write_text("ns")

        from hestai_context_mcp.storage.outbox import OutboxStore

        store = OutboxStore(working_dir=tmp_path)
        store.enqueue(ack=_failed_ack("art-py"), error_code="x", error_message="y")
        outbox_files = list(store.root.glob("*.json"))
        assert outbox_files
        before = {p: p.stat().st_mtime_ns for p in outbox_files}
        # Nudge the clock so any unintended mtime change becomes visible
        # if the call writes anything.
        time.sleep(0.005)

        from hestai_context_mcp.tools.get_context import get_context

        get_context(working_dir=str(tmp_path))

        after = {p: p.stat().st_mtime_ns for p in outbox_files}
        for p in outbox_files:
            assert before[p] == after[p], f"get_context modified outbox file {p}"
