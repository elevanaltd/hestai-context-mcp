"""Cubic rework cycle 2 — Finding #7 (P2, classification.py:61).

RED-first test: classifier must enforce the EXACT ADR-0013 PSS layout
``portable/pss/{ns}/{proj}/{ws}/{user}/{leaf}/{id}.json`` — 8 segments
relative to ``.hestai/state/``. The current ``len(parts) >= 4`` guard
is too permissive: a malformed 5-segment path
``portable/pss/{ns}/artifacts/x.json`` matches because parts[-2]==
"artifacts", and is incorrectly classified as PORTABLE_MEMORY.

RULE_005 of BUILD-PLAN §SCOPE_DISCIPLINE: "If a component cannot be
classified, treat it as LOCAL_MUTABLE." Per PROD::I4 STRUCTURED_RETURN_SHAPES
(no shape leaks for malformed paths) and ADR-0013 R1 (path geometry is
the basis of classification), only paths matching the canonical layout
exactly may resolve to PORTABLE_MEMORY.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.mark.unit
class TestPSSPathSegmentStrictness:
    """Cubic P2 #7: enforce canonical PSS layout segment count."""

    def _classify(self, *, working_dir: Path, relative: str) -> object:
        from hestai_context_mcp.storage.classification import classify_state_path

        return classify_state_path(working_dir / relative, working_dir=working_dir)

    def test_canonical_8_segment_artifacts_is_portable_memory(self, tmp_path: Path) -> None:
        from hestai_context_mcp.storage.types import StateClassification

        assert (
            self._classify(
                working_dir=tmp_path,
                relative=".hestai/state/portable/pss/ns/proj/wt/user/artifacts/art-1.json",
            )
            is StateClassification.PORTABLE_MEMORY
        )

    def test_canonical_8_segment_tombstones_is_portable_memory(self, tmp_path: Path) -> None:
        from hestai_context_mcp.storage.types import StateClassification

        assert (
            self._classify(
                working_dir=tmp_path,
                relative=".hestai/state/portable/pss/ns/proj/wt/user/tombstones/t-1.json",
            )
            is StateClassification.PORTABLE_MEMORY
        )

    def test_truncated_pss_path_is_local_mutable(self, tmp_path: Path) -> None:
        """``portable/pss/ns/proj`` (4 segments) is structurally too short
        and must NOT be classified as PORTABLE_MEMORY (RULE_005)."""
        from hestai_context_mcp.storage.types import StateClassification

        assert (
            self._classify(
                working_dir=tmp_path,
                relative=".hestai/state/portable/pss/ns/proj",
            )
            is StateClassification.LOCAL_MUTABLE
        )

    def test_short_pss_with_artifacts_segment_is_local_mutable(self, tmp_path: Path) -> None:
        """A 5-segment ``portable/pss/{ns}/artifacts/x.json`` matches the
        permissive ``len >= 4`` guard and parts[-2] == 'artifacts', so it
        is currently misclassified as PORTABLE_MEMORY. Strict layout
        enforcement must reject it."""
        from hestai_context_mcp.storage.types import StateClassification

        assert (
            self._classify(
                working_dir=tmp_path,
                relative=".hestai/state/portable/pss/ns/artifacts/x.json",
            )
            is StateClassification.LOCAL_MUTABLE
        )

    def test_too_many_segments_is_local_mutable(self, tmp_path: Path) -> None:
        """Excess depth beyond the canonical 8-segment layout must also be
        rejected (fail-closed) rather than classified as PORTABLE_MEMORY."""
        from hestai_context_mcp.storage.types import StateClassification

        assert (
            self._classify(
                working_dir=tmp_path,
                relative=".hestai/state/portable/pss/ns/proj/wt/user/extra/artifacts/x.json",
            )
            is StateClassification.LOCAL_MUTABLE
        )
