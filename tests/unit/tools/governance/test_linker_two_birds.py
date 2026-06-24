"""Linker-level tests for the two-birds ADR write surface (#112).

When ``adr_prose`` is supplied, ``run_linker`` must:
  * dumb-write the VERBATIM prose to ``docs/adr/<TOKEN>.md`` (no AI, no OCTAVE,
    no provenance marker -- pure verbatim),
  * write the AGR to ``.hestai/decisions/<TOKEN>.oct.md`` as before,
  * stage BOTH in ONE branch/commit/PR,
  * apply the SAME path-traversal guard to the ADR path as the AGR path,
  * on dry_run, report the WOULD-write ADR path and write nothing.

These are deterministic, no AI call. A real (hooks-disabled) git repo is used so
the live commit path is exercised end-to-end.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from hestai_context_mcp.tools.governance.linker import _stamp_human_adr_ref, run_linker
from hestai_context_mcp.tools.governance.type_checker import (
    ValidationResult,
    validate_octave_content,
)

_TOKEN = "HO-CONTEXT-MCP-TWOBIRDS-20260601"
_ADR_PROSE = (
    "# Decision: adopt fail-closed redaction\n\n"
    "We considered three options ... and chose fail-closed because a single "
    "leaked credential is a security incident. This is the full ADR narrative, "
    "verbatim, with multiple sentences and newlines that an AGR would compress.\n"
)

_AGR_OCTAVE = (
    "===DECISION_RECORD===\n"
    "META:\n"
    "  TYPE::DECISION_RECORD\n"
    '  VERSION::"1.0"\n'
    f'  TOKEN::"{_TOKEN}"\n'
    "  STATUS::PROPOSED\n"
    "  TIER::OPERATIONAL\n"
    '  DECISION::"Adopt fail-closed redaction on archive write."\n'
    '  BECAUSE::"Single leaked credential ⇌ security incident → fail closed."\n'
    '  AUTHORED_AT::"2026-06-01T00:00:00Z"\n'
    "===END===\n"
)


def _init_isolated_git_repo(repo: Path) -> None:
    """Initialise a temp git repo isolated from the developer's global config."""
    subprocess.run(["git", "init"], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "core.hooksPath", str(repo / ".git" / "no-hooks")],
        cwd=str(repo),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=str(repo),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=str(repo),
        check=True,
        capture_output=True,
    )
    (repo / "README.md").write_text("test")
    subprocess.run(["git", "add", "."], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"], cwd=str(repo), check=True, capture_output=True
    )


def _validation(target: Path) -> ValidationResult:
    return ValidationResult(
        valid=True,
        errors=[],
        token=_TOKEN,
        card_type="DECISION_RECORD",
        target_path=target,
    )


class TestStampHumanAdrRef:
    def test_stamp_inserts_single_meta_line(self) -> None:
        # RED #8: the stamp is a single META line; it must not touch DECISION/
        # BECAUSE or otherwise break the bytecode form.
        stamped = _stamp_human_adr_ref(_AGR_OCTAVE, _TOKEN)
        assert f'HUMAN_ADR_REF::"{_TOKEN}"' in stamped
        # Exactly one HUMAN_ADR_REF line.
        assert stamped.count("HUMAN_ADR_REF::") == 1
        # The reasoning fields are untouched.
        assert '  DECISION::"Adopt fail-closed redaction on archive write."' in stamped
        assert "  BECAUSE::" in stamped

    def test_stamp_is_idempotent(self) -> None:
        once = _stamp_human_adr_ref(_AGR_OCTAVE, _TOKEN)
        twice = _stamp_human_adr_ref(once, _TOKEN)
        assert once == twice
        assert twice.count("HUMAN_ADR_REF::") == 1

    def test_stamp_replaces_stale_human_adr_ref(self) -> None:
        stale_octave = (
            "===DECISION_RECORD===\n"
            "META:\n"
            "  TYPE::DECISION_RECORD\n"
            '  VERSION::"1.0"\n'
            f'  TOKEN::"{_TOKEN}"\n'
            '  HUMAN_ADR_REF::"HO-WRONG-STALE-VALUE-20200101"\n'
            "  STATUS::PROPOSED\n"
            "  TIER::OPERATIONAL\n"
            '  DECISION::"Adopt fail-closed redaction on archive write."\n'
            '  BECAUSE::"Single leaked credential ⇌ security incident → fail closed."\n'
            '  AUTHORED_AT::"2026-06-01T00:00:00Z"\n'
            "===END===\n"
        )
        stamped = _stamp_human_adr_ref(stale_octave, _TOKEN)
        assert f'HUMAN_ADR_REF::"{_TOKEN}"' in stamped
        assert "HO-WRONG-STALE-VALUE-20200101" not in stamped
        assert stamped.count("HUMAN_ADR_REF::") == 1
        assert '  DECISION::"Adopt fail-closed redaction on archive write."' in stamped

    def test_stamp_correct_present_is_unchanged(self) -> None:
        correct_octave = (
            "===DECISION_RECORD===\n"
            "META:\n"
            "  TYPE::DECISION_RECORD\n"
            '  VERSION::"1.0"\n'
            f'  TOKEN::"{_TOKEN}"\n'
            f'  HUMAN_ADR_REF::"{_TOKEN}"\n'
            "  STATUS::PROPOSED\n"
            "  TIER::OPERATIONAL\n"
            '  DECISION::"Adopt fail-closed redaction on archive write."\n'
            '  BECAUSE::"Single leaked credential ⇌ security incident → fail closed."\n'
            '  AUTHORED_AT::"2026-06-01T00:00:00Z"\n'
            "===END===\n"
        )
        stamped = _stamp_human_adr_ref(correct_octave, _TOKEN)
        assert stamped == correct_octave

    def test_stamp_none_present_inserted_after_meta(self) -> None:
        stamped = _stamp_human_adr_ref(_AGR_OCTAVE, _TOKEN)
        lines = stamped.splitlines()
        meta_idx = -1
        ref_idx = -1
        for idx, line in enumerate(lines):
            if "META:" in line:
                meta_idx = idx
            if "HUMAN_ADR_REF::" in line:
                ref_idx = idx
        assert meta_idx != -1
        assert ref_idx != -1
        assert ref_idx == meta_idx + 1

    def test_stamped_agr_still_passes_gate_a(self, tmp_path: Path) -> None:
        # RED #4: the stamped AGR (token-form HUMAN_ADR_REF) still passes Gate A.
        stamped = _stamp_human_adr_ref(_AGR_OCTAVE, _TOKEN)
        result = validate_octave_content(tmp_path, stamped)
        assert result.valid, result.errors
        # And the reasoning-density guard is unaffected (bytecode intact).
        assert not any("words (max" in e for e in result.errors)

    def test_stamp_preserves_decision_containing_substring(self) -> None:
        # (a) BYTECODE-PRESERVE (the bug): an AGR whose DECISION value contains the literal HUMAN_ADR_REF::
        octave_with_substring = (
            "===DECISION_RECORD===\n"
            "META:\n"
            "  TYPE::DECISION_RECORD\n"
            '  VERSION::"1.0"\n'
            f'  TOKEN::"{_TOKEN}"\n'
            "  STATUS::PROPOSED\n"
            "  TIER::OPERATIONAL\n"
            '  DECISION::"adopt the engine-side HUMAN_ADR_REF:: stamp ∴ deterministic link"\n'
            '  BECAUSE::"Single leaked credential ⇌ security incident → fail closed."\n'
            '  AUTHORED_AT::"2026-06-01T00:00:00Z"\n'
            "===END===\n"
        )
        stamped = _stamp_human_adr_ref(octave_with_substring, _TOKEN)
        # Verify the DECISION line is completely unchanged
        assert (
            '  DECISION::"adopt the engine-side HUMAN_ADR_REF:: stamp ∴ deterministic link"\n'
            in stamped
        )
        # Verify a separate correct HUMAN_ADR_REF META line is present (after META:)
        assert f'  HUMAN_ADR_REF::"{_TOKEN}"\n' in stamped
        assert stamped.count("HUMAN_ADR_REF::") == 2

    def test_stamp_collapses_multiple_pre_existing_refs(self) -> None:
        # (b) MULTI-LINE: an AGR with TWO pre-existing HUMAN_ADR_REF lines
        octave_with_multi = (
            "===DECISION_RECORD===\n"
            "META:\n"
            "  TYPE::DECISION_RECORD\n"
            '  VERSION::"1.0"\n'
            f'  TOKEN::"{_TOKEN}"\n'
            '  HUMAN_ADR_REF::"HO-WRONG-STALE-ONE-20260601"\n'
            "  STATUS::PROPOSED\n"
            '  HUMAN_ADR_REF::"HO-WRONG-STALE-TWO-20260601"\n'
            "  TIER::OPERATIONAL\n"
            '  DECISION::"Adopt fail-closed redaction on archive write."\n'
            '  BECAUSE::"Single leaked credential ⇌ security incident → fail closed."\n'
            '  AUTHORED_AT::"2026-06-01T00:00:00Z"\n'
            "===END===\n"
        )
        stamped = _stamp_human_adr_ref(octave_with_multi, _TOKEN)
        # Verify exactly one HUMAN_ADR_REF line remains and has the correct token
        assert f'  HUMAN_ADR_REF::"{_TOKEN}"\n' in stamped
        assert "HO-WRONG-STALE-ONE-20260601" not in stamped
        assert "HO-WRONG-STALE-TWO-20260601" not in stamped
        assert stamped.count("HUMAN_ADR_REF::") == 1


class TestLinkerDualWrite:
    def test_adr_prose_writes_verbatim_doc(self, tmp_path: Path) -> None:
        # RED #2: docs/adr/<TOKEN>.md written byte-exact to the prose.
        _init_isolated_git_repo(tmp_path)
        target = tmp_path / ".hestai" / "decisions" / f"{_TOKEN}.oct.md"
        run_linker(
            working_dir=tmp_path,
            validation=_validation(target),
            octave_content=_stamp_human_adr_ref(_AGR_OCTAVE, _TOKEN),
            dry_run=False,
            adr_prose=_ADR_PROSE,
        )
        adr_path = tmp_path / "docs" / "adr" / f"{_TOKEN}.md"
        assert adr_path.is_file()
        # VERBATIM: byte-exact, no AI/OCTAVE/marker mutation.
        assert adr_path.read_text(encoding="utf-8") == _ADR_PROSE

    def test_both_files_staged_in_one_commit(self, tmp_path: Path) -> None:
        # RED #3: AGR + ADR land in the SAME commit on one branch.
        _init_isolated_git_repo(tmp_path)
        target = tmp_path / ".hestai" / "decisions" / f"{_TOKEN}.oct.md"
        output = run_linker(
            working_dir=tmp_path,
            validation=_validation(target),
            octave_content=_stamp_human_adr_ref(_AGR_OCTAVE, _TOKEN),
            dry_run=False,
            adr_prose=_ADR_PROSE,
        )
        # Branch created; no orphan-state error from the write/commit steps.
        assert output["branch"]
        # HEAD commit contains BOTH files.
        files = subprocess.run(
            ["git", "show", "--name-only", "--pretty=format:", "HEAD"],
            cwd=str(tmp_path),
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        assert f".hestai/decisions/{_TOKEN}.oct.md" in files
        assert f"docs/adr/{_TOKEN}.md" in files

    def test_no_adr_prose_writes_no_doc(self, tmp_path: Path) -> None:
        # RED #1: absent adr_prose -> no docs/adr write (back-compat).
        _init_isolated_git_repo(tmp_path)
        target = tmp_path / ".hestai" / "decisions" / f"{_TOKEN}.oct.md"
        run_linker(
            working_dir=tmp_path,
            validation=_validation(target),
            octave_content=_AGR_OCTAVE,
            dry_run=False,
        )
        assert not (tmp_path / "docs" / "adr").exists()


class TestLinkerAdrTraversalGuard:
    def test_adr_path_traversal_rejected(self, tmp_path: Path) -> None:
        # RED #5: an ADR path escaping working_dir is rejected; nothing written.
        # We force the escape by making working_dir a SUBDIR while the AGR target
        # and the computed docs/adr path are derived from it; the guard must use
        # resolve().relative_to(working_dir.resolve()). Here we assert the guard
        # exists by pointing the AGR target inside but tampering the token cannot
        # (token is format-validated), so we exercise the guard via a working_dir
        # that does not contain the resolved docs/adr path.
        _init_isolated_git_repo(tmp_path)
        inner = tmp_path / "inner"
        inner.mkdir()
        _init_isolated_git_repo(inner)
        # AGR target is inside `inner`; but we pass a docs root that resolves
        # outside by symlinking docs to the parent (path-escape simulation).
        evil_docs = tmp_path / "evil"
        evil_docs.mkdir()
        (inner / "docs").symlink_to(evil_docs)
        target = inner / ".hestai" / "decisions" / f"{_TOKEN}.oct.md"
        output = run_linker(
            working_dir=inner,
            validation=_validation(target),
            octave_content=_stamp_human_adr_ref(_AGR_OCTAVE, _TOKEN),
            dry_run=False,
            adr_prose=_ADR_PROSE,
        )
        assert output["error"] is not None
        assert "outside" in output["error"].lower() or "traversal" in output["error"].lower()
        # The evil ADR file must NOT have been written.
        assert not (evil_docs / "adr" / f"{_TOKEN}.md").exists()


class TestLinkerDryRunReportsAdr:
    def test_dry_run_reports_would_write_adr_and_writes_nothing(self, tmp_path: Path) -> None:
        # RED #6: dry_run + adr_prose -> report the WOULD-write ADR path, no write.
        target = tmp_path / ".hestai" / "decisions" / f"{_TOKEN}.oct.md"
        output = run_linker(
            working_dir=tmp_path,
            validation=_validation(target),
            octave_content=_stamp_human_adr_ref(_AGR_OCTAVE, _TOKEN),
            dry_run=True,
            adr_prose=_ADR_PROSE,
        )
        assert output["dry_run"] is True
        assert output.get("adr_target_path") == f"docs/adr/{_TOKEN}.md"
        assert not (tmp_path / "docs" / "adr" / f"{_TOKEN}.md").exists()
