"""Corpus guard — every committed AGR passes Gate A (incl. the v1.1 density guard).

This is the forcing function for the Wave A landing (issues #113 + #114): the
moment the §4.1 #13 reasoning-density guard lands, the legacy verbose records
(HO-INTAKE-MODEL-RESOLUTION-PER-REPO, HO-AGR-DETERMINISTIC-REVIEW-CONVENTION,
HO-AGR-SEMANTIC-REVIEWER-ANALYSIS-TIER) turn this test RED. It only returns
GREEN once those records are migrated to compliant bytecode, so the guard and
the migration are bound to land together — the merge boundary is never red
(ADR-RFC-ARCH-004 §1.6 "no grandfather clause").

Read-only: validates the real ``.hestai/decisions/`` corpus against the
write-side Gate A validator. DECISION_RECORD-typed files only — co-located
non-AGR governance artefacts are out of scope (ADR-RFC-ARCH-001 / agr_read F1).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hestai_context_mcp.tools.governance.agr_read import is_decision_record
from hestai_context_mcp.tools.governance.type_checker import validate_octave_content

# Repo root = three parents up from this file
# (tests/integration/<file> -> tests -> <repo root>).
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DECISIONS_DIR = _REPO_ROOT / ".hestai" / "decisions"


def _agr_paths() -> list[Path]:
    if not _DECISIONS_DIR.exists():
        return []
    paths: list[Path] = []
    for path in sorted(_DECISIONS_DIR.rglob("*.oct.md")):
        if is_decision_record(path.read_text(encoding="utf-8", errors="replace")):
            paths.append(path)
    return paths


@pytest.mark.integration
def test_decisions_corpus_is_non_empty() -> None:
    """Sanity: the guard test is meaningful only if AGRs actually exist."""
    assert _agr_paths(), f"no DECISION_RECORD AGRs found under {_DECISIONS_DIR}"


def _seed_human_adr_refs(working_dir: Path, content: str) -> None:
    """Materialise any HUMAN_ADR_REF target the record cites under ``working_dir``.

    The §4.1 #11 check resolves HUMAN_ADR_REF as a repo-relative path; in an
    isolated temp store the cited file would be absent and #11 would fail for a
    reason unrelated to the density guard under test. Create an empty placeholder
    at the cited path so #11 passes structurally — keeping this test focused on
    the v1.1 density/format invariants (uniqueness/path-presence are unit-tested
    elsewhere).
    """
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("HUMAN_ADR_REF::"):
            raw = stripped[len("HUMAN_ADR_REF::") :].strip().strip('"')
            if raw:
                target = working_dir / raw
                target.parent.mkdir(parents=True, exist_ok=True)
                target.touch()


@pytest.mark.integration
@pytest.mark.parametrize("agr_path", _agr_paths(), ids=lambda p: p.name)
def test_committed_agr_passes_gate_a(agr_path: Path, tmp_path: Path) -> None:
    """Every committed DECISION_RECORD validates against Gate A (v1.1 guard incl.).

    Validated against an ISOLATED temp working dir (not the live repo) so the
    record's own on-disk copy does not trip the token-uniqueness check (Check 6),
    while any HUMAN_ADR_REF target it cites is materialised so the §4.1 #11
    path-resolution check passes structurally. This isolates the §4.1
    structural/value invariants — the v1.1 reasoning-density guard among them —
    which are exactly what the migration must satisfy.
    """
    content = agr_path.read_text(encoding="utf-8")
    (tmp_path / ".hestai" / "decisions").mkdir(parents=True, exist_ok=True)
    _seed_human_adr_refs(tmp_path, content)
    result = validate_octave_content(tmp_path, content)
    assert result.valid, f"{agr_path.name} failed Gate A: {result.errors}"
