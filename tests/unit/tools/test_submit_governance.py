"""Tests for submit_governance Gate A Rails (RFC #53).

TDD RED phase: all tests here MUST fail before implementation exists.

Coverage targets:
- lookup_token_deterministic: token found vs not found
- ValidationResult for each TYPE (DECISION_RECORD, CONCEPT_CARD, FRAME_CARD)
- Invalid TOKEN format rejected
- SUPERSEDES target checked
- Duplicate TOKEN rejected
- dry_run=True produces correct return shape without touching git
- Linker path computation for each card type
- MANIFEST generation from a fixture tree
"""

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _init_isolated_git_repo(repo: Path) -> None:
    """Initialise a temp git repo isolated from the developer's global config.

    Cross-environment robustness: a global ``init.templateDir`` /
    ``core.hooksPath`` (e.g. a ``commit-msg`` hook that blocks commits to
    ``main``) would otherwise fire inside this temp repo and break the linker
    integration tests in some sandboxes (observed in goose's sandbox; passes in
    CI and most dev envs). We pin ``core.hooksPath`` to a non-existent path on
    the repo's OWN config so EVERY subsequent git invocation against this repo
    -- including the commits run internally by ``run_linker`` -- runs with hooks
    disabled, regardless of the developer's global git configuration.
    """
    subprocess.run(["git", "init"], cwd=str(repo), check=True, capture_output=True)
    # Disable hooks for this repo specifically (persists for all later git calls,
    # including run_linker's internal checkout/add/commit).
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
        ["git", "commit", "-m", "initial"],
        cwd=str(repo),
        check=True,
        capture_output=True,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def decision_record_octave() -> str:
    """A well-formed DECISION_RECORD OCTAVE document."""
    return """\
===DECISION_RECORD===
META:
  TYPE::DECISION_RECORD
  VERSION::"1.0"
  TOKEN::"HO-CONTEXT-MCP-TEST-DECISION-20260531"
  STATUS::PROPOSED
  TIER::OPERATIONAL
  DECISION::"Test decision for Gate A coverage."
  BECAUSE::"Required for TDD."
  AUTHORED_AT::"2026-05-31T00:00:00Z"
===END===
"""


@pytest.fixture()
def concept_card_octave() -> str:
    """A well-formed CONCEPT_CARD OCTAVE document."""
    return """\
===CONCEPT_CARD===
META:
  TYPE::CONCEPT_CARD
  REPO_ID::hestai-context-mcp
  ID::"GATE_A_TEST_CONCEPT"
  STATUS::proposed
  CARD_SCHEMA_VERSION::1
  GENERATED_AT_COMMIT::"N/A"
  SOURCE_HASH::"N/A"
===END===
"""


@pytest.fixture()
def frame_card_octave() -> str:
    """A well-formed FRAME_CARD OCTAVE document."""
    return """\
===FRAME_CARD===
META:
  TYPE::FRAME_CARD
  REPO_ID::hestai-context-mcp
  ID::"GATE_A_TEST_FRAME"
  STATUS::proposed
  CARD_SCHEMA_VERSION::1
  GENERATED_AT_COMMIT::"N/A"
  SOURCE_HASH::"N/A"
===END===
"""


@pytest.fixture()
def manifest_tree(tmp_path: Path) -> Path:
    """Create a minimal .hestai decision/context tree for MANIFEST tests."""
    decisions = tmp_path / ".hestai" / "decisions"
    decisions.mkdir(parents=True)

    (decisions / "HO-CONTEXT-MCP-ALPHA-20260101.oct.md").write_text(
        '===DECISION_RECORD===\nMETA:\n  TOKEN::"HO-CONTEXT-MCP-ALPHA-20260101"\n===END===\n'
    )

    concepts = tmp_path / ".hestai" / "context" / "concepts" / "hestai-context-mcp"
    concepts.mkdir(parents=True)
    (concepts / "ALPHA_CONCEPT.oct.md").write_text(
        '===CONCEPT_CARD===\nMETA:\n  ID::"ALPHA_CONCEPT"\n===END===\n'
    )

    return tmp_path


# ---------------------------------------------------------------------------
# Lexer tests
# ---------------------------------------------------------------------------


class TestLookupTokenDeterministic:
    """Tests for lexer.lookup_token_deterministic."""

    @pytest.mark.unit
    def test_token_found_via_manifest(self, tmp_path: Path) -> None:
        """Token present in MANIFEST.md is found."""
        from hestai_context_mcp.tools.governance.lexer import lookup_token_deterministic

        manifest = tmp_path / ".hestai" / "MANIFEST.md"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(
            "| HO-CONTEXT-MCP-ALPHA-20260101 | .hestai/decisions/HO-CONTEXT-MCP-ALPHA-20260101.oct.md |\n"
        )

        assert lookup_token_deterministic(tmp_path, "HO-CONTEXT-MCP-ALPHA-20260101") is True

    @pytest.mark.unit
    def test_token_not_found_via_manifest(self, tmp_path: Path) -> None:
        """Token absent from MANIFEST.md is not found."""
        from hestai_context_mcp.tools.governance.lexer import lookup_token_deterministic

        manifest = tmp_path / ".hestai" / "MANIFEST.md"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(
            "| HO-OTHER-TOKEN-20260101 | .hestai/decisions/HO-OTHER-TOKEN-20260101.oct.md |\n"
        )

        assert lookup_token_deterministic(tmp_path, "HO-CONTEXT-MCP-ALPHA-20260101") is False

    @pytest.mark.unit
    def test_token_found_via_filesystem_fallback(self, manifest_tree: Path) -> None:
        """Token found via filesystem grep when no MANIFEST exists."""
        from hestai_context_mcp.tools.governance.lexer import lookup_token_deterministic

        assert lookup_token_deterministic(manifest_tree, "HO-CONTEXT-MCP-ALPHA-20260101") is True

    @pytest.mark.unit
    def test_id_found_via_filesystem_fallback(self, manifest_tree: Path) -> None:
        """Facet card ID found via filesystem grep."""
        from hestai_context_mcp.tools.governance.lexer import lookup_token_deterministic

        assert lookup_token_deterministic(manifest_tree, "ALPHA_CONCEPT") is True

    @pytest.mark.unit
    def test_token_not_found_empty_tree(self, tmp_path: Path) -> None:
        """Returns False when no MANIFEST and no oct.md files exist."""
        from hestai_context_mcp.tools.governance.lexer import lookup_token_deterministic

        assert lookup_token_deterministic(tmp_path, "HO-MISSING-TOKEN-20260101") is False


# ---------------------------------------------------------------------------
# Type checker tests
# ---------------------------------------------------------------------------


class TestValidationResult:
    """Tests for type_checker.validate_octave_content."""

    @pytest.mark.unit
    def test_decision_record_valid(self, decision_record_octave: str, tmp_path: Path) -> None:
        """Valid DECISION_RECORD passes validation and computes correct target path."""
        from hestai_context_mcp.tools.governance.type_checker import validate_octave_content

        result = validate_octave_content(tmp_path, decision_record_octave)

        assert result.valid is True
        assert result.errors == []
        assert result.card_type == "DECISION_RECORD"
        assert result.token == "HO-CONTEXT-MCP-TEST-DECISION-20260531"
        assert result.target_path is not None
        assert str(result.target_path).endswith(
            ".hestai/decisions/HO-CONTEXT-MCP-TEST-DECISION-20260531.oct.md"
        )

    @pytest.mark.unit
    def test_concept_card_valid(self, concept_card_octave: str, tmp_path: Path) -> None:
        """Valid CONCEPT_CARD passes validation and computes correct target path."""
        from hestai_context_mcp.tools.governance.type_checker import validate_octave_content

        result = validate_octave_content(tmp_path, concept_card_octave)

        assert result.valid is True
        assert result.errors == []
        assert result.card_type == "CONCEPT_CARD"
        assert result.token == "GATE_A_TEST_CONCEPT"
        assert result.target_path is not None
        assert "context/concepts" in str(result.target_path)
        assert "GATE_A_TEST_CONCEPT.oct.md" in str(result.target_path)

    @pytest.mark.unit
    def test_frame_card_valid(self, frame_card_octave: str, tmp_path: Path) -> None:
        """Valid FRAME_CARD passes validation and computes correct target path."""
        from hestai_context_mcp.tools.governance.type_checker import validate_octave_content

        result = validate_octave_content(tmp_path, frame_card_octave)

        assert result.valid is True
        assert result.errors == []
        assert result.card_type == "FRAME_CARD"
        assert result.token == "GATE_A_TEST_FRAME"

    @pytest.mark.unit
    def test_invalid_token_format_rejected(self, tmp_path: Path) -> None:
        """Invalid TOKEN format produces validation error."""
        from hestai_context_mcp.tools.governance.type_checker import validate_octave_content

        bad_token_content = """\
===DECISION_RECORD===
META:
  TYPE::DECISION_RECORD
  TOKEN::"bad-token-no-date"
  STATUS::PROPOSED
===END===
"""
        result = validate_octave_content(tmp_path, bad_token_content)

        assert result.valid is False
        assert any("TOKEN" in e or "format" in e.lower() for e in result.errors)

    @pytest.mark.unit
    def test_unknown_type_rejected(self, tmp_path: Path) -> None:
        """Unknown TYPE produces validation error."""
        from hestai_context_mcp.tools.governance.type_checker import validate_octave_content

        unknown_type_content = """\
===UNKNOWN_THING===
META:
  TYPE::UNKNOWN_THING
  TOKEN::"HO-SOMETHING-20260531"
===END===
"""
        result = validate_octave_content(tmp_path, unknown_type_content)

        assert result.valid is False
        assert any("TYPE" in e or "Unknown" in e or "unknown" in e for e in result.errors)

    @pytest.mark.unit
    def test_missing_octave_sentinel_rejected(self, tmp_path: Path) -> None:
        """Content missing OCTAVE sentinel is rejected."""
        from hestai_context_mcp.tools.governance.type_checker import validate_octave_content

        no_sentinel = "Just some plain text with no OCTAVE envelope."
        result = validate_octave_content(tmp_path, no_sentinel)

        assert result.valid is False
        assert result.errors

    @pytest.mark.unit
    def test_duplicate_token_rejected(self, tmp_path: Path, decision_record_octave: str) -> None:
        """TOKEN that already exists is rejected."""
        from hestai_context_mcp.tools.governance.type_checker import validate_octave_content

        # Pre-create the target file so token appears to already exist
        decisions = tmp_path / ".hestai" / "decisions"
        decisions.mkdir(parents=True)
        (decisions / "HO-CONTEXT-MCP-TEST-DECISION-20260531.oct.md").write_text(
            decision_record_octave
        )

        result = validate_octave_content(tmp_path, decision_record_octave)

        assert result.valid is False
        assert any("duplicate" in e.lower() or "already exists" in e.lower() for e in result.errors)

    @pytest.mark.unit
    def test_supersedes_target_checked_missing(self, tmp_path: Path) -> None:
        """SUPERSEDED_BY pointing at non-existent token produces error."""
        from hestai_context_mcp.tools.governance.type_checker import validate_octave_content

        content_with_supersedes = """\
===DECISION_RECORD===
META:
  TYPE::DECISION_RECORD
  TOKEN::"HO-CONTEXT-MCP-TEST-NEW-20260531"
  STATUS::PROPOSED
  SUPERSEDED_BY::"HO-NONEXISTENT-TOKEN-20260101"
===END===
"""
        result = validate_octave_content(tmp_path, content_with_supersedes)

        assert result.valid is False
        assert any("SUPERSEDED_BY" in e or "not found" in e.lower() for e in result.errors)

    @pytest.mark.unit
    def test_validate_never_raises(self, tmp_path: Path) -> None:
        """validate_octave_content never raises, always returns ValidationResult."""
        from hestai_context_mcp.tools.governance.type_checker import validate_octave_content

        # Completely garbage input
        result = validate_octave_content(tmp_path, "💥\x00\x01\x02garbage input💥")

        assert hasattr(result, "valid")
        assert hasattr(result, "errors")
        assert result.valid is False


# ---------------------------------------------------------------------------
# Linker tests (path computation, dry_run)
# ---------------------------------------------------------------------------


class TestLinker:
    """Tests for linker path computation and dry_run behavior."""

    @pytest.mark.unit
    def test_dry_run_decision_record(self, tmp_path: Path, decision_record_octave: str) -> None:
        """dry_run=True returns correct shape for DECISION_RECORD without git ops."""
        from hestai_context_mcp.tools.governance.linker import run_linker
        from hestai_context_mcp.tools.governance.type_checker import validate_octave_content

        result = validate_octave_content(tmp_path, decision_record_octave)
        assert result.valid is True

        output = run_linker(
            working_dir=tmp_path,
            validation=result,
            octave_content=decision_record_octave,
            dry_run=True,
        )

        assert output["dry_run"] is True
        assert output["branch"] is not None
        assert "governance/" in output["branch"]
        assert output["target_path"] is not None
        assert output["pr_url"] is None  # no real PR in dry_run
        assert output["token"] == "HO-CONTEXT-MCP-TEST-DECISION-20260531"

    @pytest.mark.unit
    def test_dry_run_concept_card(self, tmp_path: Path, concept_card_octave: str) -> None:
        """dry_run=True returns correct shape for CONCEPT_CARD."""
        from hestai_context_mcp.tools.governance.linker import run_linker
        from hestai_context_mcp.tools.governance.type_checker import validate_octave_content

        result = validate_octave_content(tmp_path, concept_card_octave)
        assert result.valid is True

        output = run_linker(
            working_dir=tmp_path,
            validation=result,
            octave_content=concept_card_octave,
            dry_run=True,
        )

        assert output["dry_run"] is True
        assert "context/concepts" in output["target_path"]

    @pytest.mark.unit
    def test_dry_run_does_not_write_files(
        self, tmp_path: Path, decision_record_octave: str
    ) -> None:
        """dry_run=True must not create any files on disk."""
        from hestai_context_mcp.tools.governance.linker import run_linker
        from hestai_context_mcp.tools.governance.type_checker import validate_octave_content

        result = validate_octave_content(tmp_path, decision_record_octave)

        run_linker(
            working_dir=tmp_path,
            validation=result,
            octave_content=decision_record_octave,
            dry_run=True,
        )

        # No files should have been written
        all_files = list(tmp_path.rglob("*.oct.md"))
        assert all_files == []

    @pytest.mark.unit
    def test_branch_name_slug_from_token(self, tmp_path: Path, decision_record_octave: str) -> None:
        """Branch name is derived from token with correct slugification."""
        from hestai_context_mcp.tools.governance.linker import run_linker
        from hestai_context_mcp.tools.governance.type_checker import validate_octave_content

        result = validate_octave_content(tmp_path, decision_record_octave)

        output = run_linker(
            working_dir=tmp_path,
            validation=result,
            octave_content=decision_record_octave,
            dry_run=True,
        )

        branch = output["branch"]
        assert branch.startswith("governance/")
        # Token uppercased with _ -> - conversion: HO-CONTEXT-MCP-TEST-DECISION-20260531
        # slug: ho-context-mcp-test-decision-20260531
        assert "ho-context-mcp-test-decision-20260531" in branch


# ---------------------------------------------------------------------------
# MANIFEST generator tests
# ---------------------------------------------------------------------------


class TestManifestGenerator:
    """Tests for manifest.build_manifest and write_manifest."""

    @pytest.mark.unit
    def test_build_manifest_contains_token(self, manifest_tree: Path) -> None:
        """build_manifest includes DECISION_RECORD tokens."""
        from hestai_context_mcp.tools.governance.manifest import build_manifest

        content = build_manifest(manifest_tree)

        assert "HO-CONTEXT-MCP-ALPHA-20260101" in content

    @pytest.mark.unit
    def test_build_manifest_contains_concept_id(self, manifest_tree: Path) -> None:
        """build_manifest includes CONCEPT_CARD IDs."""
        from hestai_context_mcp.tools.governance.manifest import build_manifest

        content = build_manifest(manifest_tree)

        assert "ALPHA_CONCEPT" in content

    @pytest.mark.unit
    def test_build_manifest_empty_tree(self, tmp_path: Path) -> None:
        """build_manifest returns empty/minimal string for tree with no oct.md files."""
        from hestai_context_mcp.tools.governance.manifest import build_manifest

        content = build_manifest(tmp_path)

        # Should not crash; may return empty table or header-only
        assert isinstance(content, str)

    @pytest.mark.unit
    def test_write_manifest_creates_file(self, manifest_tree: Path) -> None:
        """write_manifest writes MANIFEST.md to canonical path."""
        from hestai_context_mcp.tools.governance.manifest import (
            get_manifest_path,
            write_manifest,
        )

        write_manifest(manifest_tree)

        manifest_path = get_manifest_path(manifest_tree)
        assert manifest_path.exists()
        content = manifest_path.read_text()
        assert "HO-CONTEXT-MCP-ALPHA-20260101" in content

    @pytest.mark.unit
    def test_get_manifest_path(self, tmp_path: Path) -> None:
        """get_manifest_path returns canonical .hestai/MANIFEST.md path."""
        from hestai_context_mcp.tools.governance.manifest import get_manifest_path

        path = get_manifest_path(tmp_path)
        assert path == tmp_path / ".hestai" / "MANIFEST.md"


# ---------------------------------------------------------------------------
# submit_governance MCP tool tests
# ---------------------------------------------------------------------------


class TestSubmitGovernanceTool:
    """Tests for the submit_governance MCP tool."""

    @pytest.mark.unit
    def test_dry_run_returns_structured_dict(
        self, tmp_path: Path, decision_record_octave: str
    ) -> None:
        """submit_governance dry_run=True returns I4-conformant structured dict."""
        import asyncio

        from hestai_context_mcp.tools.submit_governance import submit_governance

        result = asyncio.run(
            submit_governance(
                working_dir=str(tmp_path),
                octave_content=decision_record_octave,
                dry_run=True,
            )
        )

        # I4: all defined fields must be present
        assert "success" in result
        assert "token" in result
        assert "card_type" in result
        assert "target_path" in result
        assert "branch" in result
        assert "pr_url" in result
        assert "validation_errors" in result
        assert "dry_run" in result
        assert result["dry_run"] is True

    @pytest.mark.unit
    def test_dry_run_decision_record_success(
        self, tmp_path: Path, decision_record_octave: str
    ) -> None:
        """submit_governance returns success for valid DECISION_RECORD in dry_run."""
        import asyncio

        from hestai_context_mcp.tools.submit_governance import submit_governance

        result = asyncio.run(
            submit_governance(
                working_dir=str(tmp_path),
                octave_content=decision_record_octave,
                dry_run=True,
            )
        )

        assert result["success"] is True
        assert result["token"] == "HO-CONTEXT-MCP-TEST-DECISION-20260531"
        assert result["card_type"] == "DECISION_RECORD"
        assert result["validation_errors"] == []

    @pytest.mark.unit
    def test_dry_run_concept_card_success(self, tmp_path: Path, concept_card_octave: str) -> None:
        """submit_governance returns success for valid CONCEPT_CARD in dry_run."""
        import asyncio

        from hestai_context_mcp.tools.submit_governance import submit_governance

        result = asyncio.run(
            submit_governance(
                working_dir=str(tmp_path),
                octave_content=concept_card_octave,
                dry_run=True,
            )
        )

        assert result["success"] is True
        assert result["card_type"] == "CONCEPT_CARD"

    @pytest.mark.unit
    def test_invalid_content_returns_failure(self, tmp_path: Path) -> None:
        """submit_governance returns failure shape for invalid content."""
        import asyncio

        from hestai_context_mcp.tools.submit_governance import submit_governance

        result = asyncio.run(
            submit_governance(
                working_dir=str(tmp_path),
                octave_content="not valid octave",
                dry_run=True,
            )
        )

        assert result["success"] is False
        assert result["validation_errors"]
        assert result["dry_run"] is True
        # I4: all fields still present even on failure
        assert "token" in result
        assert "card_type" in result
        assert "target_path" in result
        assert "branch" in result
        assert "pr_url" in result

    @pytest.mark.unit
    def test_nonexistent_working_dir_returns_failure(self, decision_record_octave: str) -> None:
        """submit_governance returns failure for nonexistent working_dir."""
        import asyncio

        from hestai_context_mcp.tools.submit_governance import submit_governance

        result = asyncio.run(
            submit_governance(
                working_dir="/nonexistent/path/that/does/not/exist",
                octave_content=decision_record_octave,
                dry_run=True,
            )
        )

        assert result["success"] is False
        assert result["validation_errors"]


# ---------------------------------------------------------------------------
# Fix 3 tests: cubic P1/P2 review findings
# ---------------------------------------------------------------------------


class TestManifestPrefixFalsePositive:
    """MANIFEST exact-match guard: shorter token must NOT match longer token row."""

    @pytest.mark.unit
    def test_prefix_token_does_not_match_longer_row(self, tmp_path: Path) -> None:
        """HO-FOO-20260101 must NOT match a MANIFEST row whose first cell is HO-FOO-BAR-20260101.

        Before the exact first-column match fix, a substring search would
        incorrectly return True because 'HO-FOO-20260101' appears inside
        'HO-FOO-BAR-20260101'.  The fix compares stripped cells exactly.
        """
        from hestai_context_mcp.tools.governance.lexer import lookup_token_deterministic

        manifest = tmp_path / ".hestai" / "MANIFEST.md"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(
            "| TOKEN/ID | path |\n"
            "| --- | --- |\n"
            "| HO-FOO-BAR-20260101 | .hestai/decisions/HO-FOO-BAR-20260101.oct.md |\n"
        )

        # The shorter token must NOT match the longer row
        assert lookup_token_deterministic(tmp_path, "HO-FOO-20260101") is False

    @pytest.mark.unit
    def test_exact_token_still_found(self, tmp_path: Path) -> None:
        """Exact token match is still found after the guard is in place."""
        from hestai_context_mcp.tools.governance.lexer import lookup_token_deterministic

        manifest = tmp_path / ".hestai" / "MANIFEST.md"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(
            "| TOKEN/ID | path |\n"
            "| --- | --- |\n"
            "| HO-FOO-BAR-20260101 | .hestai/decisions/HO-FOO-BAR-20260101.oct.md |\n"
        )

        # The exact token must still be found
        assert lookup_token_deterministic(tmp_path, "HO-FOO-BAR-20260101") is True


class TestSentinelTypeMismatch:
    """Sentinel name must equal the TYPE field value."""

    @pytest.mark.unit
    def test_sentinel_type_mismatch_produces_error(self, tmp_path: Path) -> None:
        """===DECISION_RECORD=== envelope with TYPE::CONCEPT_CARD is rejected.

        The sentinel (envelope name) and the META TYPE field must be identical.
        A mismatch indicates a copy-paste error or malformed document.
        """
        from hestai_context_mcp.tools.governance.type_checker import validate_octave_content

        content = """\
===DECISION_RECORD===
META:
  TYPE::CONCEPT_CARD
  REPO_ID::hestai-context-mcp
  ID::"SOME_CONCEPT"
===END===
"""
        result = validate_octave_content(tmp_path, content)

        assert result.valid is False
        assert any(
            "DECISION_RECORD" in e or "CONCEPT_CARD" in e or "match" in e.lower()
            for e in result.errors
        )


class TestPathTraversalGuard:
    """Path traversal attempt via crafted TOKEN must be rejected by the linker."""

    @pytest.mark.unit
    def test_path_traversal_rejected(self, tmp_path: Path) -> None:
        """A target_path that resolves outside working_dir is rejected.

        The linker must call target_path.resolve().relative_to(working_dir.resolve())
        and return an error (not raise) when the check fails.
        """
        from hestai_context_mcp.tools.governance.linker import run_linker
        from hestai_context_mcp.tools.governance.type_checker import ValidationResult

        # Minimal git repo (hooks disabled) so branch creation is possible.
        _init_isolated_git_repo(tmp_path)

        # Construct a ValidationResult whose target_path escapes working_dir
        outside_path = tmp_path.parent / "escape" / "evil.oct.md"
        fake_validation = ValidationResult(
            valid=True,
            errors=[],
            token="HO-ESCAPE-20260101",
            card_type="DECISION_RECORD",
            target_path=outside_path,
        )

        output = run_linker(
            working_dir=tmp_path,
            validation=fake_validation,
            octave_content="===DECISION_RECORD===\n===END===\n",
            dry_run=False,
        )

        assert output["error"] is not None
        assert "outside" in output["error"].lower() or "traversal" in output["error"].lower()
        # The evil file must NOT have been written
        assert not outside_path.exists()


class TestSentinelLeadingWhitespace:
    """Non-OCTAVE content with === after leading whitespace must be rejected.

    The sentinel regex is anchored to \\A (absolute document start).
    A document with whitespace before === must fail Check 1.
    """

    @pytest.mark.unit
    def test_indented_sentinel_rejected(self, tmp_path: Path) -> None:
        """Leading whitespace before === sentinel must cause rejection."""
        from hestai_context_mcp.tools.governance.type_checker import validate_octave_content

        content = "  ===DECISION_RECORD===\nMETA:\n  TYPE::DECISION_RECORD\n===END===\n"
        result = validate_octave_content(tmp_path, content)

        assert result.valid is False
        assert any("sentinel" in e.lower() or "start" in e.lower() for e in result.errors)

    @pytest.mark.unit
    def test_newline_before_sentinel_rejected(self, tmp_path: Path) -> None:
        """Newline before === sentinel must cause rejection."""
        from hestai_context_mcp.tools.governance.type_checker import validate_octave_content

        content = "\n===DECISION_RECORD===\nMETA:\n  TYPE::DECISION_RECORD\n===END===\n"
        result = validate_octave_content(tmp_path, content)

        assert result.valid is False
        assert any("sentinel" in e.lower() or "start" in e.lower() for e in result.errors)


class TestFacetCardMissingRepoId:
    """Facet card without REPO_ID field must be rejected with a clear error."""

    @pytest.mark.unit
    def test_concept_card_missing_repo_id_rejected(self, tmp_path: Path) -> None:
        """CONCEPT_CARD without REPO_ID produces a validation error.

        Before the fix, _extract_repo_id returning None would cause a silent
        coerce to 'unknown' and place the file in .hestai/context/concepts/unknown/.
        After the fix it returns a hard validation error.
        """
        from hestai_context_mcp.tools.governance.type_checker import validate_octave_content

        content = """\
===CONCEPT_CARD===
META:
  TYPE::CONCEPT_CARD
  ID::"MISSING_REPO_CONCEPT"
  STATUS::proposed
  CARD_SCHEMA_VERSION::1
  GENERATED_AT_COMMIT::"N/A"
  SOURCE_HASH::"N/A"
===END===
"""
        result = validate_octave_content(tmp_path, content)

        assert result.valid is False
        assert any("REPO_ID" in e for e in result.errors)

    @pytest.mark.unit
    def test_frame_card_missing_repo_id_rejected(self, tmp_path: Path) -> None:
        """FRAME_CARD without REPO_ID produces a validation error."""
        from hestai_context_mcp.tools.governance.type_checker import validate_octave_content

        content = """\
===FRAME_CARD===
META:
  TYPE::FRAME_CARD
  ID::"MISSING_REPO_FRAME"
  STATUS::proposed
  CARD_SCHEMA_VERSION::1
  GENERATED_AT_COMMIT::"N/A"
  SOURCE_HASH::"N/A"
===END===
"""
        result = validate_octave_content(tmp_path, content)

        assert result.valid is False
        assert any("REPO_ID" in e for e in result.errors)


class TestFacetCardUnsafeRepoIdSlug:
    """Adversarial REPO_ID slug rejection (P1 security guard, type_checker.py).

    REPO_ID feeds directly into the facet-card target path
    (.hestai/context/concepts/{repo_id}/{id}.oct.md). An attacker-controlled
    REPO_ID containing path separators or ``..`` segments could direct the
    linker to write OUTSIDE the governance tree (path traversal). The Dumb
    Type Checker MUST reject any REPO_ID that is not a safe slug
    (alphanumeric / hyphen / underscore only) BEFORE a target_path is ever
    computed -- defence in depth ahead of the linker's resolve() guard.
    """

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "unsafe_repo_id",
        [
            "../../../src/evil",  # classic relative traversal
            "a/b",  # any path separator
            "..",  # parent-dir segment
            "../sibling",  # single-level escape
            "/etc/passwd",  # absolute path
            "repo;rm",  # shell-meta noise (semicolon)
            "repo\x00null",  # NUL byte injection
        ],
    )
    def test_unsafe_repo_id_rejected_no_target_path(
        self, tmp_path: Path, unsafe_repo_id: str
    ) -> None:
        """An unsafe REPO_ID is rejected with a slug error and yields NO target_path.

        This is the security regression guard for the P1 cubic finding. The
        validator must:
          1. mark the result invalid,
          2. emit an error naming REPO_ID / slug,
          3. NOT produce a target_path (so no path-traversing path escapes to
             the linker), and
          4. NOT have created the traversal directory on disk.
        """
        from hestai_context_mcp.tools.governance.type_checker import validate_octave_content

        content = (
            "===CONCEPT_CARD===\n"
            "META:\n"
            "  TYPE::CONCEPT_CARD\n"
            f"  REPO_ID::{unsafe_repo_id}\n"
            '  ID::"EVIL_CONCEPT"\n'
            "  STATUS::proposed\n"
            "  CARD_SCHEMA_VERSION::1\n"
            "===END===\n"
        )

        result = validate_octave_content(tmp_path, content)

        assert result.valid is False
        assert any(
            "REPO_ID" in e or "slug" in e.lower() for e in result.errors
        ), f"expected a REPO_ID/slug rejection error, got: {result.errors}"
        # Critical: a rejected REPO_ID must never yield a (path-traversing) target_path.
        assert result.target_path is None
        # And the validator (read-only) must not have created the traversal dir.
        assert not (tmp_path / "src" / "evil").exists()
        assert list(tmp_path.rglob("EVIL_CONCEPT.oct.md")) == []

    @pytest.mark.unit
    def test_safe_repo_id_still_accepted(self, tmp_path: Path) -> None:
        """Control: a safe slug with hyphens/underscores still validates and stays in-tree.

        Guards against the rejection being over-broad (rejecting legitimate
        repo slugs). The computed target_path must remain inside the
        .hestai/context/concepts tree.
        """
        from hestai_context_mcp.tools.governance.type_checker import validate_octave_content

        content = (
            "===CONCEPT_CARD===\n"
            "META:\n"
            "  TYPE::CONCEPT_CARD\n"
            "  REPO_ID::hestai-context_mcp-2\n"
            '  ID::"SAFE_CONCEPT"\n'
            "  STATUS::proposed\n"
            "  CARD_SCHEMA_VERSION::1\n"
            "===END===\n"
        )

        result = validate_octave_content(tmp_path, content)

        assert result.valid is True, result.errors
        assert result.target_path is not None
        # target_path must resolve inside working_dir (no traversal).
        result.target_path.resolve().relative_to(tmp_path.resolve())
        assert "hestai-context_mcp-2" in str(result.target_path)


# ---------------------------------------------------------------------------
# Integration test: real temp git repo (linker dry_run=False mock)
# ---------------------------------------------------------------------------


class TestLinkerIntegration:
    """Integration test: real temp git repo, mocked gh CLI."""

    @pytest.mark.integration
    def test_linker_creates_branch_commits_writes_file(
        self, tmp_path: Path, decision_record_octave: str
    ) -> None:
        """Linker (dry_run=False) creates branch, writes file, commits.

        gh pr create is mocked at the linker module level to avoid real GitHub
        interaction while allowing real git operations.
        """
        # Real git repo with hooks disabled so the linker's internal
        # checkout/add/commit are not blocked by a developer's global git hooks.
        _init_isolated_git_repo(tmp_path)

        from hestai_context_mcp.tools.governance.linker import run_linker
        from hestai_context_mcp.tools.governance.type_checker import validate_octave_content

        result = validate_octave_content(tmp_path, decision_record_octave)
        assert result.valid is True

        # Mock only _open_pr in the linker module to avoid real GitHub interaction
        pr_url = "https://github.com/elevanaltd/hestai-context-mcp/pull/999"
        with patch(
            "hestai_context_mcp.tools.governance.linker._open_pr",
            return_value=(pr_url, None),
        ):
            output = run_linker(
                working_dir=tmp_path,
                validation=result,
                octave_content=decision_record_octave,
                dry_run=False,
            )

        assert output["branch"] is not None
        target = tmp_path / ".hestai" / "decisions" / "HO-CONTEXT-MCP-TEST-DECISION-20260531.oct.md"
        assert target.exists()
