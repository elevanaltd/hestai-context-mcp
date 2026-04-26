"""GROUP_009: CLASSIFICATION — RED-first tests for storage/classification.py.

Asserts the state-classification helper contract per BUILD-PLAN
§TDD_TEST_LIST GROUP_009 (TEST_099..TEST_108) and ADR-0013 R1.

Binding rulings exercised here:
- R1: classification is mandatory; unknown state → LOCAL_MUTABLE.
- §MIGRATION_PLAN EXISTING_STATE_CLASSIFICATION_MAP fixes the
  authoritative mapping for known paths.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hestai_context_mcp.storage.types import StateClassification


@pytest.mark.unit
class TestKnownLocalMutablePaths:
    """TEST_099..TEST_103."""

    def _classify(self, *, working_dir: Path, relative: str) -> StateClassification:
        from hestai_context_mcp.storage.classification import classify_state_path

        return classify_state_path(working_dir / relative, working_dir=working_dir)

    def test_sessions_active_session_json_is_local_mutable(self, tmp_path: Path) -> None:
        assert (
            self._classify(
                working_dir=tmp_path,
                relative=".hestai/state/sessions/active/abc/session.json",
            )
            is StateClassification.LOCAL_MUTABLE
        )

    def test_sessions_archive_redacted_jsonl_is_local_mutable(self, tmp_path: Path) -> None:
        assert (
            self._classify(
                working_dir=tmp_path,
                relative=".hestai/state/sessions/archive/2026-04-26-foo-redacted.jsonl",
            )
            is StateClassification.LOCAL_MUTABLE
        )

    def test_learnings_index_is_local_mutable(self, tmp_path: Path) -> None:
        assert (
            self._classify(
                working_dir=tmp_path,
                relative=".hestai/state/learnings-index.jsonl",
            )
            is StateClassification.LOCAL_MUTABLE
        )

    def test_context_state_fast_layer_is_local_mutable(self, tmp_path: Path) -> None:
        for f in ("current-focus.oct.md", "checklist.oct.md", "blockers.oct.md"):
            assert (
                self._classify(
                    working_dir=tmp_path,
                    relative=f".hestai/state/context/state/{f}",
                )
                is StateClassification.LOCAL_MUTABLE
            )

    def test_portable_outbox_is_local_mutable(self, tmp_path: Path) -> None:
        assert (
            self._classify(
                working_dir=tmp_path,
                relative=".hestai/state/portable/outbox/art-1.json",
            )
            is StateClassification.LOCAL_MUTABLE
        )


@pytest.mark.unit
class TestPortableMemoryPaths:
    """TEST_104..TEST_105."""

    def _classify(self, *, working_dir: Path, relative: str) -> StateClassification:
        from hestai_context_mcp.storage.classification import classify_state_path

        return classify_state_path(working_dir / relative, working_dir=working_dir)

    def test_portable_artifacts_are_portable_memory(self, tmp_path: Path) -> None:
        assert (
            self._classify(
                working_dir=tmp_path,
                relative=".hestai/state/portable/artifacts/personal/proj/wt/u/v1/art-1.json",
            )
            is StateClassification.PORTABLE_MEMORY
        )

    def test_portable_tombstones_are_portable_memory(self, tmp_path: Path) -> None:
        assert (
            self._classify(
                working_dir=tmp_path,
                relative=".hestai/state/portable/tombstones/personal/proj/wt/u/v1/tomb-1.json",
            )
            is StateClassification.PORTABLE_MEMORY
        )


@pytest.mark.unit
class TestDerivedProjectionPaths:
    """TEST_106..TEST_107."""

    def _classify(self, *, working_dir: Path, relative: str) -> StateClassification:
        from hestai_context_mcp.storage.classification import classify_state_path

        return classify_state_path(working_dir / relative, working_dir=working_dir)

    def test_portable_snapshots_are_derived_projection(self, tmp_path: Path) -> None:
        for f in ("context-projection.json", "metadata.json"):
            assert (
                self._classify(
                    working_dir=tmp_path,
                    relative=f".hestai/state/portable/snapshots/sess-1/{f}",
                )
                is StateClassification.DERIVED_PROJECTION
            )

    def test_materialized_project_context_from_portable_memory_is_derived_projection(
        self, tmp_path: Path
    ) -> None:
        from hestai_context_mcp.storage.classification import (
            classify_materialized_context,
        )

        # Default-classification of the bare PROJECT-CONTEXT path is fail-closed
        # to LOCAL_MUTABLE per MAP_008. The explicit "from portable memory"
        # helper lifts that to DERIVED_PROJECTION.
        target = tmp_path / ".hestai" / "state" / "context" / "PROJECT-CONTEXT.oct.md"
        assert (
            classify_materialized_context(target, derived_from_portable_memory=True)
            is StateClassification.DERIVED_PROJECTION
        )
        assert (
            classify_materialized_context(target, derived_from_portable_memory=False)
            is StateClassification.LOCAL_MUTABLE
        )


@pytest.mark.unit
class TestUnknownPath:
    """TEST_108 — fail-closed default (R1)."""

    def test_unknown_state_path_defaults_to_local_mutable(self, tmp_path: Path) -> None:
        from hestai_context_mcp.storage.classification import classify_state_path

        unknown = tmp_path / ".hestai" / "state" / "something-new" / "x.bin"
        assert (
            classify_state_path(unknown, working_dir=tmp_path) is StateClassification.LOCAL_MUTABLE
        )
