"""GROUP_013: GET_CONTEXT_PURITY — RED-first tests.

Asserts that ``get_context`` remains a pure read per BUILD-PLAN
§INTEGRATION_PLAN GET_CONTEXT_EDIT_PLAN and §TDD_TEST_LIST GROUP_013
(TEST_139..TEST_148).

Binding rulings exercised here:

- OPTION_C: ``get_context(working_dir: str)`` signature is unchanged.
- G3: source-level guard — no ``StorageAdapter`` or
  ``LocalFilesystemAdapter`` symbols appear inside ``get_context.py``.
- INVARIANT_001 (R10): filesystem snapshot diff is empty before and
  after ``get_context``.
- R5 + R10: snapshot mtime is unchanged across calls; outbox files
  are not drained / created.
- R7: ``get_context`` never publishes or restores; that boundary is
  owned by clock_in / clock_out exclusively.
"""

from __future__ import annotations

import inspect
import json
import os
import re
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_GET_CONTEXT_PATH = _REPO_ROOT / "src" / "hestai_context_mcp" / "tools" / "get_context.py"


def _snapshot_fs(root: Path) -> dict[str, tuple[float, int]]:
    """Take a (mtime_ns, size) snapshot of every regular file under ``root``."""
    out: dict[str, tuple[float, int]] = {}
    if not root.exists():
        return out
    for path in root.rglob("*"):
        if path.is_file():
            stat = path.stat()
            out[str(path.relative_to(root))] = (stat.st_mtime_ns, stat.st_size)
    return out


@pytest.mark.integration
class TestGetContextSignatureContract:
    """TEST_140 + TEST_141 + TEST_145 — OPTION_C guard."""

    def test_get_context_signature_is_option_c(self) -> None:
        """OPTION_C: signature is exactly ``get_context(working_dir: str)``."""
        from hestai_context_mcp.tools.get_context import get_context

        sig = inspect.signature(get_context)
        params = list(sig.parameters)
        assert params == [
            "working_dir"
        ], f"OPTION_C requires get_context(working_dir: str); got {params}"
        wd_param = sig.parameters["working_dir"]
        assert (
            wd_param.annotation is str
        ), f"working_dir must be annotated str; got {wd_param.annotation}"

    def test_get_context_does_not_import_storage_adapter_protocol(self) -> None:
        """G3: ``StorageAdapter`` symbol is absent from get_context.py source."""
        source = _GET_CONTEXT_PATH.read_text(encoding="utf-8")
        assert (
            "StorageAdapter" not in source
        ), "G3 violation: 'StorageAdapter' must not appear in get_context.py"

    def test_get_context_does_not_import_local_filesystem_adapter(self) -> None:
        """G3: ``LocalFilesystemAdapter`` symbol is absent from get_context.py."""
        source = _GET_CONTEXT_PATH.read_text(encoding="utf-8")
        assert (
            "LocalFilesystemAdapter" not in source
        ), "G3 violation: 'LocalFilesystemAdapter' must not appear in get_context.py"

    def test_get_context_visible_return_shape_remains_backward_compatible(
        self, tmp_path: Path
    ) -> None:
        """The response top-level keys remain {working_dir, context}."""
        from hestai_context_mcp.tools.get_context import get_context

        result = get_context(working_dir=str(tmp_path))
        assert set(result.keys()) >= {"working_dir", "context"}
        ctx = result["context"]
        assert {
            "product_north_star",
            "project_context",
            "phase_constraints",
            "git_state",
            "active_sessions",
        } <= set(ctx.keys())


@pytest.mark.integration
class TestGetContextFilesystemPurity:
    """TEST_139 + TEST_142 — INVARIANT_001."""

    def test_get_context_filesystem_snapshot_diff_empty_before_after(self, tmp_path: Path) -> None:
        """R10 INVARIANT_001: fs snapshot diff is empty across get_context."""
        from hestai_context_mcp.tools.get_context import get_context

        # Pre-seed an existing state directory so we have files to diff
        # against; get_context must touch nothing.
        state_dir = tmp_path / ".hestai" / "state" / "context"
        state_dir.mkdir(parents=True)
        (state_dir / "PROJECT-CONTEXT.oct.md").write_text("seed\n")

        before = _snapshot_fs(tmp_path)
        get_context(working_dir=str(tmp_path))
        after = _snapshot_fs(tmp_path)

        # Diff: any added, removed, or mtime-changed entry is a violation.
        added = set(after) - set(before)
        removed = set(before) - set(after)
        assert not added, f"get_context created files: {sorted(added)}"
        assert not removed, f"get_context removed files: {sorted(removed)}"
        for k in before:
            assert before[k] == after[k], f"get_context mutated {k}: {before[k]} -> {after[k]}"

    def test_get_context_does_not_create_portable_directories(self, tmp_path: Path) -> None:
        """R10: get_context never creates portable/{outbox,snapshots,pss}."""
        from hestai_context_mcp.tools.get_context import get_context

        get_context(working_dir=str(tmp_path))

        portable = tmp_path / ".hestai" / "state" / "portable"
        # The portable subtree must not be created by get_context.
        # CE rework RISK_006: artifacts now live under portable/pss/.
        assert not (portable / "outbox").exists()
        assert not (portable / "snapshots").exists()
        assert not (portable / "pss").exists()


@pytest.mark.integration
class TestGetContextSnapshotStability:
    """TEST_143 + TEST_144 — R5 + R7 + INVARIANT_001."""

    def test_get_context_does_not_modify_snapshot_mtime(self, tmp_path: Path) -> None:
        """G3 + R5: a pre-existing snapshot's mtime is not changed by get_context."""
        from hestai_context_mcp.tools.get_context import get_context

        snap_dir = tmp_path / ".hestai" / "state" / "portable" / "snapshots" / "sess-1"
        snap_dir.mkdir(parents=True)
        proj = snap_dir / "context-projection.json"
        meta = snap_dir / "metadata.json"
        proj.write_text("{}")
        meta.write_text("{}")

        # Set a known mtime in the past so any touch is detectable.
        past = 1_700_000_000
        os.utime(proj, (past, past))
        os.utime(meta, (past, past))

        before_proj = proj.stat().st_mtime
        before_meta = meta.stat().st_mtime

        get_context(working_dir=str(tmp_path))

        assert (
            proj.stat().st_mtime == before_proj
        ), "get_context modified context-projection.json mtime"
        assert meta.stat().st_mtime == before_meta, "get_context modified metadata.json mtime"

    def test_get_context_does_not_drain_outbox(self, tmp_path: Path) -> None:
        """R7 + G3: outbox entries are not consumed/created by get_context."""
        from hestai_context_mcp.tools.get_context import get_context

        outbox_dir = tmp_path / ".hestai" / "state" / "portable" / "outbox"
        outbox_dir.mkdir(parents=True)
        entry = outbox_dir / "art-1.json"
        entry.write_text(json.dumps({"artifact_id": "art-1", "status": "failed"}))
        before = list(outbox_dir.iterdir())

        get_context(working_dir=str(tmp_path))

        after = list(outbox_dir.iterdir())
        # No file added, none removed.
        assert {p.name for p in before} == {p.name for p in after}
        # Content unchanged.
        assert entry.read_text() == json.dumps({"artifact_id": "art-1", "status": "failed"})


@pytest.mark.integration
class TestGetContextSnapshotRead:
    """TEST_146 + TEST_147 + TEST_148 — local-only behavior."""

    def test_get_context_reads_local_snapshot_when_available(self, tmp_path: Path) -> None:
        """When a snapshot exists, get_context reads only the local projection.

        OPTION_C: signature unchanged. The 'reads local snapshot' contract
        is delegate-friendly: get_context's response remains the same
        shape; this test only verifies that the call does not raise when
        a snapshot is present and that the response shape stays intact.
        """
        from hestai_context_mcp.tools.get_context import get_context

        snap_dir = tmp_path / ".hestai" / "state" / "portable" / "snapshots" / "sess-x"
        snap_dir.mkdir(parents=True)
        (snap_dir / "context-projection.json").write_text(
            json.dumps({"identity": {}, "tombstoned_artifact_ids": [], "artifact_refs": []})
        )
        (snap_dir / "metadata.json").write_text(json.dumps({"session_id": "sess-x"}))

        result = get_context(working_dir=str(tmp_path))
        assert "context" in result
        # The response must not surface restoration as having happened
        # (TEST_148): no "restore_status" / "portable_state" keys leak in.
        assert "portable_state" not in result
        assert "restore_status" not in result

    def test_get_context_without_snapshot_falls_back_to_existing_local_projection(
        self, tmp_path: Path
    ) -> None:
        """Behavior when no snapshot is present: existing PROJECT-CONTEXT path."""
        from hestai_context_mcp.tools.get_context import get_context

        ctx_dir = tmp_path / ".hestai" / "state" / "context"
        ctx_dir.mkdir(parents=True)
        (ctx_dir / "PROJECT-CONTEXT.oct.md").write_text("local-projection-only\n")

        result = get_context(working_dir=str(tmp_path))
        assert "context" in result
        # project_context surfaced; no portable_state in response.
        assert "portable_state" not in result

    def test_get_context_never_reports_hydration_as_successful(self, tmp_path: Path) -> None:
        """TEST_148: get_context never surfaces hydration as happening from itself."""
        from hestai_context_mcp.tools.get_context import get_context

        snap_dir = tmp_path / ".hestai" / "state" / "portable" / "snapshots" / "sess-y"
        snap_dir.mkdir(parents=True)
        (snap_dir / "context-projection.json").write_text(
            json.dumps({"identity": {}, "tombstoned_artifact_ids": [], "artifact_refs": []})
        )
        (snap_dir / "metadata.json").write_text(json.dumps({"session_id": "sess-y"}))

        result = get_context(working_dir=str(tmp_path))
        # Forbidden keys: anything that suggests hydration semantics.
        forbidden = {"portable_state", "restore_status", "hydrated", "restored_artifacts"}
        assert not (forbidden & set(result.keys()))
        # And no restore_status key buried under context either.
        assert "restore_status" not in result.get("context", {})


@pytest.mark.integration
class TestGetContextSourceLevelGuard:
    """G3 source guard — independent of behavior."""

    def test_get_context_module_has_no_storage_adapter_imports(self) -> None:
        """Source AST: no ``from hestai_context_mcp.storage.local_filesystem`` etc."""
        source = _GET_CONTEXT_PATH.read_text(encoding="utf-8")
        forbidden_imports = (
            r"from\s+hestai_context_mcp\.storage\.local_filesystem",
            r"from\s+hestai_context_mcp\.storage\.outbox",
            r"from\s+hestai_context_mcp\.storage\.protocol",
            r"import\s+hestai_context_mcp\.storage\.local_filesystem",
        )
        for pattern in forbidden_imports:
            assert not re.search(
                pattern, source
            ), f"G3 violation: get_context.py must not match /{pattern}/"

    def test_get_context_module_does_not_reference_adapter_symbols(self) -> None:
        """Belt-and-braces: forbidden symbol names are absent."""
        source = _GET_CONTEXT_PATH.read_text(encoding="utf-8")
        for symbol in ("StorageAdapter", "LocalFilesystemAdapter", "OutboxStore"):
            assert (
                symbol not in source
            ), f"G3 violation: '{symbol}' must not appear in get_context.py"

    def test_get_context_module_carries_explicit_purity_marker(self) -> None:
        """G3: get_context.py must carry an explicit PURITY_GUARD marker.

        The marker is a load-bearing comment + docstring contract. Future
        modifications can grep for it before adding any storage import.
        Per CE RISK_003 OPTION_C: get_context has zero side effects and
        its session-bound snapshot is exposed only via
        ``clock_in.portable_state.snapshot``. The marker MUST cite both
        rulings so any reader of the file knows why imports are forbidden.
        """
        source = _GET_CONTEXT_PATH.read_text(encoding="utf-8")
        # Single explicit marker comment that cites the binding rulings.
        assert "PURITY_GUARD::G3" in source, (
            "G3 violation: get_context.py must carry an explicit "
            "'PURITY_GUARD::G3' marker citing CE RISK_003 OPTION_C."
        )
        # The marker must also reference OPTION_C so the tie-back to the
        # arbitration record is unambiguous.
        assert "OPTION_C" in source, (
            "G3 violation: get_context.py must reference 'OPTION_C' so the "
            "binding ruling that forbids signature/behavior change is "
            "discoverable in-source."
        )


# Sanity helper kept inline so the file is self-contained.
def _ensure_no_response_key(result: dict[str, Any], key: str) -> None:
    assert key not in result, f"response must not contain key {key!r}"
