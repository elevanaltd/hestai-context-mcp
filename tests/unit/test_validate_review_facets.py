"""
Contract tests for facet-based content-aware review routing in validate_review.py.

Tests verify that classify_pr_facets() assigns correct facets and required
reviewer roles based on file content types, and that check_pr_comments()
validates role-based (not tier-based) approvals.

Source of truth: review-requirements.oct.md v2.0 (5-tier system with facets)
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
import validate_review


# ---------------------------------------------------------------------------
# 1. Facet classification tests
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestFacetClassification:
    """classify_pr_facets() must assign correct facets based on file paths."""

    def test_pure_markdown_is_exempt(self) -> None:
        """Pure .md files -> no facets, no roles, TIER_0_EXEMPT."""
        files = [
            {"path": "docs/README.md", "added": 10, "deleted": 5, "total_changed": 15},
        ]
        facets, roles, tier, _ = validate_review.classify_pr_facets(files)
        assert len(facets) == 0, f"Pure .md should have no facets, got {facets}"
        assert len(roles) == 0, f"Pure .md should need no roles, got {roles}"
        assert tier == "TIER_0_EXEMPT"

    def test_pure_python_code_is_routine(self) -> None:
        """Normal .py file -> ROUTINE_CODE facet -> {CE, CRS, TMG}."""
        files = [
            {"path": "src/utils.py", "added": 50, "deleted": 20, "total_changed": 70},
        ]
        facets, roles, tier, _ = validate_review.classify_pr_facets(files)
        assert "ROUTINE_CODE" in facets, f"Python file should be ROUTINE_CODE, got {facets}"
        assert roles == {"CE", "CRS", "TMG"}, f"Expected CE+CRS+TMG, got {roles}"

    def test_octave_rule_is_governance(self) -> None:
        """.oct.md TYPE::RULE file -> GOVERNANCE facet -> {SR}."""
        files = [
            {
                "path": "src/hestai_mcp/_bundled_hub/standards/rules/review-requirements.oct.md",
                "added": 10,
                "deleted": 5,
                "total_changed": 15,
            },
        ]
        facets, roles, tier, _ = validate_review.classify_pr_facets(files)
        assert "GOVERNANCE" in facets or "META_CONTROL_PLANE" in facets
        assert "SR" in roles, f"Governance file should require SR, got {roles}"

    def test_octave_agent_is_executable_spec(self) -> None:
        """.oct.md TYPE::AGENT_DEFINITION -> EXECUTABLE_SPEC facet -> {CE, CRS, SR}."""
        files = [
            {
                "path": "src/hestai_mcp/_bundled_hub/library/agents/implementation-lead.oct.md",
                "added": 20,
                "deleted": 10,
                "total_changed": 30,
            },
        ]
        facets, roles, tier, _ = validate_review.classify_pr_facets(files)
        assert "EXECUTABLE_SPEC" in facets, f"Agent .oct.md should be EXECUTABLE_SPEC, got {facets}"
        assert "CE" in roles, f"Agent def should require CE, got {roles}"
        assert "CRS" in roles, f"Agent def should require CRS, got {roles}"
        assert "SR" in roles, f"Agent def should require SR, got {roles}"

    def test_security_path_includes_civ(self) -> None:
        """Auth path code -> SECURITY facet -> includes CIV."""
        files = [
            {
                "path": "src/hestai_mcp/auth/handler.py",
                "added": 50,
                "deleted": 20,
                "total_changed": 70,
            },
        ]
        facets, roles, tier, _ = validate_review.classify_pr_facets(files)
        assert "SECURITY" in facets, f"Auth path should be SECURITY, got {facets}"
        assert "CIV" in roles, f"Security should require CIV, got {roles}"

    def test_validate_review_is_meta_control_plane(self) -> None:
        """validate_review.py itself -> META_CONTROL_PLANE -> includes PE."""
        files = [
            {
                "path": "scripts/validate_review.py",
                "added": 50,
                "deleted": 20,
                "total_changed": 70,
            },
        ]
        facets, roles, tier, _ = validate_review.classify_pr_facets(files)
        assert "META_CONTROL_PLANE" in facets, f"validate_review.py should be META, got {facets}"
        assert "CRS" in roles, f"Meta control plane should require CRS, got {roles}"
        assert "CIV" in roles, f"Meta control plane should require CIV, got {roles}"
        assert (
            "PE" not in roles
        ), f"Meta control plane should NOT require PE (T4 manual), got {roles}"

    def test_skill_md_is_executable_spec(self) -> None:
        """Bundled hub SKILL.md files must be EXECUTABLE_SPEC, not exempt."""
        files = [
            {
                "path": "src/hestai_mcp/_bundled_hub/library/skills/standards-review/SKILL.md",
                "added": 20,
                "deleted": 10,
                "total_changed": 30,
            },
        ]
        facets, roles, tier, _ = validate_review.classify_pr_facets(files)
        assert "EXECUTABLE_SPEC" in facets, f"SKILL.md should be EXECUTABLE_SPEC, got {facets}"
        assert (
            "CE" in roles and "CRS" in roles and "SR" in roles
        ), f"SKILL.md needs CE+CRS+SR, got {roles}"
        assert tier != "TIER_0_EXEMPT", f"SKILL.md must NOT be exempt, got {tier}"

    def test_pattern_md_is_executable_spec(self) -> None:
        """Bundled hub pattern .oct.md files must be EXECUTABLE_SPEC, not exempt."""
        files = [
            {
                "path": "src/hestai_mcp/_bundled_hub/library/patterns/tdd-discipline.oct.md",
                "added": 10,
                "deleted": 5,
                "total_changed": 15,
            },
        ]
        facets, roles, tier, _ = validate_review.classify_pr_facets(files)
        assert tier != "TIER_0_EXEMPT", f"Pattern file must NOT be exempt, got {tier}"
        assert (
            "EXECUTABLE_SPEC" in facets or "GOVERNANCE" in facets
        ), f"Pattern file should be EXECUTABLE_SPEC or GOVERNANCE, got {facets}"
        assert "SR" in roles, f"Pattern file should require SR, got {roles}"

    def test_regular_md_still_exempt(self) -> None:
        """Regular docs .md files must still be exempt."""
        files = [
            {"path": "docs/README.md", "added": 10, "deleted": 5, "total_changed": 15},
        ]
        facets, roles, tier, _ = validate_review.classify_pr_facets(files)
        assert tier == "TIER_0_EXEMPT", f"Regular .md should be exempt, got {tier}"

    def test_skill_pr_requires_ce_crs_sr_review(self) -> None:
        """A PR with only SKILL.md files must require CE+CRS+SR (EXECUTABLE_SPEC)."""
        files = [
            {
                "path": "src/hestai_mcp/_bundled_hub/library/skills/build-execution/SKILL.md",
                "added": 30,
                "deleted": 10,
                "total_changed": 40,
            },
        ]
        facets, roles, tier, _ = validate_review.classify_pr_facets(files)
        assert roles == {"CE", "CRS", "SR"}, f"Skill PR should need CE+CRS+SR, got {roles}"

    def test_mixed_code_and_governance(self) -> None:
        """Mixed .py + .oct.md -> union of ROUTINE_CODE + GOVERNANCE roles."""
        files = [
            {"path": "src/utils.py", "added": 20, "deleted": 10, "total_changed": 30},
            {
                "path": ".hestai/state/context/PROJECT-CONTEXT.oct.md",
                "added": 5,
                "deleted": 2,
                "total_changed": 7,
            },
        ]
        facets, roles, tier, _ = validate_review.classify_pr_facets(files)
        assert "SR" in roles, f"Mixed PR should require SR for .oct.md, got {roles}"
        assert "CRS" in roles, f"Mixed PR should require CRS for .py, got {roles}"


# ---------------------------------------------------------------------------
# 1b. Functional EXECUTABLE_SPEC gate tests
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestExecutableSpecGateRequiresCRS:
    """EXECUTABLE_SPEC PRs must fail the gate without CRS approval.

    Since CRS was added to the EXECUTABLE_SPEC facet reviewer set, a PR
    touching only agent/skill files must require CRS APPROVED alongside
    CE and SR.  This functional test calls check_pr_comments() to verify
    the gate rejects when CRS is missing.
    """

    @pytest.fixture(autouse=True)
    def ci_environment(self, monkeypatch):
        """Set CI + PR_NUMBER so check_pr_comments runs its full logic."""
        monkeypatch.setenv("CI", "true")
        monkeypatch.setenv("PR_NUMBER", "999")

    def test_executable_spec_fails_without_crs(self, monkeypatch) -> None:
        """EXECUTABLE_SPEC gate must reject when CRS approval is missing."""
        import subprocess

        def mock_run(cmd, *args, **kwargs):
            return MagicMock(
                stdout=json.dumps(
                    {
                        "body": "",
                        "comments": [
                            {
                                "author": {"login": "human-ce"},
                                "body": "CE APPROVED: code looks good",
                            },
                            {
                                "author": {"login": "human-sr"},
                                "body": "SR APPROVED: standards met",
                            },
                        ],
                    }
                ),
                returncode=0,
                check=lambda: None,
            )

        monkeypatch.setattr(subprocess, "run", mock_run)
        # EXECUTABLE_SPEC requires {CE, CRS, SR} — CE and SR present, CRS missing
        approved, message, missing = validate_review.check_pr_comments(
            required_roles={"CE", "CRS", "SR"}, tier="TIER_2_STANDARD"
        )
        assert approved is False, f"Should fail without CRS, got: {message}"
        assert "CRS" in missing, f"CRS should be in missing roles, got: {missing}"

    def test_executable_spec_passes_with_all_roles(self, monkeypatch) -> None:
        """EXECUTABLE_SPEC gate must pass when CE, CRS, and SR all approve."""
        import subprocess

        def mock_run(cmd, *args, **kwargs):
            return MagicMock(
                stdout=json.dumps(
                    {
                        "body": "",
                        "comments": [
                            {
                                "author": {"login": "human-ce"},
                                "body": "CE APPROVED: code looks good",
                            },
                            {
                                "author": {"login": "human-crs"},
                                "body": "CRS APPROVED: review complete",
                            },
                            {
                                "author": {"login": "human-sr"},
                                "body": "SR APPROVED: standards met",
                            },
                        ],
                    }
                ),
                returncode=0,
                check=lambda: None,
            )

        monkeypatch.setattr(subprocess, "run", mock_run)
        approved, message, missing = validate_review.check_pr_comments(
            required_roles={"CE", "CRS", "SR"}, tier="TIER_2_STANDARD"
        )
        assert approved is True, f"Should pass with all roles, got: {message}"
        assert missing == [], f"No roles should be missing, got: {missing}"


# ---------------------------------------------------------------------------
# 2. Tier label computation tests
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestTierLabelComputation:
    """Tier labels must be backward-computed from the required role set."""

    def test_exempt_only_is_tier_0(self) -> None:
        """All exempt files -> TIER_0_EXEMPT."""
        files = [
            {"path": "README.md", "added": 5, "deleted": 2, "total_changed": 7},
        ]
        _, _, tier, _ = validate_review.classify_pr_facets(files)
        assert tier == "TIER_0_EXEMPT"

    def test_small_single_file_no_facets_is_tier_1(self) -> None:
        """<10 lines, single non-exempt file, no special facets -> TIER_1_SELF."""
        files = [
            {"path": "src/config.py", "added": 3, "deleted": 1, "total_changed": 4},
        ]
        _, _, tier, _ = validate_review.classify_pr_facets(files)
        assert tier == "TIER_1_SELF"

    def test_routine_code_is_tier_2(self) -> None:
        """ROUTINE_CODE roles (CE+CRS+TMG, no CIV/PE) -> TIER_2_STANDARD."""
        files = [
            {"path": "src/core.py", "added": 50, "deleted": 20, "total_changed": 70},
        ]
        _, roles, tier, _ = validate_review.classify_pr_facets(files)
        assert tier == "TIER_2_STANDARD", f"Routine code should be T2, got {tier}"

    def test_security_path_is_tier_3(self) -> None:
        """SECURITY facet (has CIV) -> TIER_3_CRITICAL."""
        files = [
            {
                "path": "src/hestai_mcp/auth/handler.py",
                "added": 20,
                "deleted": 5,
                "total_changed": 25,
            },
        ]
        _, roles, tier, _ = validate_review.classify_pr_facets(files)
        assert tier == "TIER_3_CRITICAL", f"Security path should be T3, got {tier}"

    def test_meta_control_plane_is_tier_3(self) -> None:
        """META_CONTROL_PLANE (has CIV, no PE) -> TIER_3_CRITICAL."""
        files = [
            {
                "path": "scripts/validate_review.py",
                "added": 50,
                "deleted": 20,
                "total_changed": 70,
            },
        ]
        _, roles, tier, _ = validate_review.classify_pr_facets(files)
        assert (
            tier == "TIER_3_CRITICAL"
        ), f"Meta control plane should be T3 (PE excluded), got {tier}"

    def test_governance_only_is_tier_2(self) -> None:
        """Pure governance .oct.md (SR only, no CIV/PE) -> TIER_2_STANDARD."""
        files = [
            {
                "path": ".hestai/state/context/PROJECT-CONTEXT.oct.md",
                "added": 10,
                "deleted": 5,
                "total_changed": 15,
            },
        ]
        _, roles, tier, _ = validate_review.classify_pr_facets(files)
        assert tier == "TIER_2_STANDARD", f"Governance-only should be T2, got {tier}"


# ---------------------------------------------------------------------------
# 3. Role-based approval tests
# ---------------------------------------------------------------------------
@pytest.fixture
def ci_environment(monkeypatch):
    """Set up CI environment variables."""
    monkeypatch.setenv("CI", "true")
    monkeypatch.setenv("GITHUB_BASE_REF", "origin/main")
    monkeypatch.setenv("PR_NUMBER", "999")


@pytest.mark.unit
class TestRoleBasedApproval:
    """check_pr_comments() must validate per-role approvals from required_roles set."""

    def test_sr_only_passes_with_sr_approved(self, ci_environment, monkeypatch) -> None:
        """required_roles={SR} passes with SR APPROVED only."""
        import subprocess

        def mock_run(cmd, *args, **kwargs):
            return MagicMock(
                stdout=json.dumps(
                    {
                        "body": "",
                        "comments": [
                            {"body": "SR APPROVED: standards aligned with North Star"},
                        ],
                    }
                ),
                returncode=0,
                check=lambda: None,
            )

        monkeypatch.setattr(subprocess, "run", mock_run)

        approved, message, _ = validate_review.check_pr_comments(
            required_roles={"SR"}, tier="TIER_2_STANDARD"
        )
        assert approved is True, f"SR-only should pass with SR APPROVED, got: {message}"

    def test_routine_code_needs_all_three(self, ci_environment, monkeypatch) -> None:
        """required_roles={CE, CRS, TMG} needs all three approvals."""
        import subprocess

        def mock_run(cmd, *args, **kwargs):
            return MagicMock(
                stdout=json.dumps(
                    {
                        "body": "",
                        "comments": [
                            {"body": "TMG APPROVED: tests verified"},
                            {"body": "CRS APPROVED: logic correct"},
                            {"body": "CE APPROVED: architecture sound"},
                        ],
                    }
                ),
                returncode=0,
                check=lambda: None,
            )

        monkeypatch.setattr(subprocess, "run", mock_run)

        approved, message, _ = validate_review.check_pr_comments(
            required_roles={"CE", "CRS", "TMG"}, tier="TIER_2_STANDARD"
        )
        assert approved is True, f"CE+CRS+TMG should pass, got: {message}"

    def test_missing_role_fails(self, ci_environment, monkeypatch) -> None:
        """required_roles={CE, CRS, TMG} fails when TMG is missing."""
        import subprocess

        def mock_run(cmd, *args, **kwargs):
            return MagicMock(
                stdout=json.dumps(
                    {
                        "body": "",
                        "comments": [
                            {"body": "CRS APPROVED: logic correct"},
                            {"body": "CE APPROVED: architecture sound"},
                        ],
                    }
                ),
                returncode=0,
                check=lambda: None,
            )

        monkeypatch.setattr(subprocess, "run", mock_run)

        approved, message, _ = validate_review.check_pr_comments(
            required_roles={"CE", "CRS", "TMG"}, tier="TIER_2_STANDARD"
        )
        assert approved is False, f"Missing TMG should fail, got: {message}"
        assert "TMG" in message

    def test_mixed_code_and_standards_needs_all(self, ci_environment, monkeypatch) -> None:
        """required_roles={CE, CRS, TMG, SR} needs all four."""
        import subprocess

        def mock_run(cmd, *args, **kwargs):
            return MagicMock(
                stdout=json.dumps(
                    {
                        "body": "",
                        "comments": [
                            {"body": "TMG APPROVED: tests verified"},
                            {"body": "CRS APPROVED: logic correct"},
                            {"body": "CE APPROVED: architecture sound"},
                            {"body": "SR APPROVED: standards aligned"},
                        ],
                    }
                ),
                returncode=0,
                check=lambda: None,
            )

        monkeypatch.setattr(subprocess, "run", mock_run)

        approved, message, _ = validate_review.check_pr_comments(
            required_roles={"CE", "CRS", "TMG", "SR"}, tier="TIER_2_STANDARD"
        )
        assert approved is True, f"CE+CRS+TMG+SR should pass, got: {message}"

    def test_self_review_still_works_for_tier_1(self, ci_environment, monkeypatch) -> None:
        """T1 with empty required_roles still accepts SELF-REVIEWED."""
        import subprocess

        def mock_run(cmd, *args, **kwargs):
            return MagicMock(
                stdout=json.dumps(
                    {
                        "body": "",
                        "comments": [
                            {"body": "IL SELF-REVIEWED: Fixed typo"},
                        ],
                    }
                ),
                returncode=0,
                check=lambda: None,
            )

        monkeypatch.setattr(subprocess, "run", mock_run)

        approved, message, _ = validate_review.check_pr_comments(
            required_roles=set(), tier="TIER_1_SELF"
        )
        assert approved is True, f"T1 self-review should still work, got: {message}"


# ---------------------------------------------------------------------------
# 4. Semantic sniffing tests
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestSniffOctaveType:
    """_sniff_octave_type() must read META.TYPE from .oct.md files."""

    def test_agent_definition_detected(self, tmp_path) -> None:
        """File with TYPE::AGENT_DEFINITION returns 'AGENT_DEFINITION'."""
        f = tmp_path / "test.oct.md"
        f.write_text('===TEST===\nMETA:\n  TYPE::AGENT_DEFINITION\n  VERSION::"1.0"\n')
        result = validate_review._sniff_octave_type(str(f))
        assert result == "AGENT_DEFINITION"

    def test_rule_detected(self, tmp_path) -> None:
        """File with TYPE::RULE returns 'RULE'."""
        f = tmp_path / "test.oct.md"
        f.write_text('===TEST===\nMETA:\n  TYPE::RULE\n  VERSION::"1.0"\n')
        result = validate_review._sniff_octave_type(str(f))
        assert result == "RULE"

    def test_skill_detected(self, tmp_path) -> None:
        """File with TYPE::SKILL returns 'SKILL'."""
        f = tmp_path / "test.oct.md"
        f.write_text('===TEST===\nMETA:\n  TYPE::SKILL\n  VERSION::"1.0"\n')
        result = validate_review._sniff_octave_type(str(f))
        assert result == "SKILL"

    def test_empty_file_returns_empty(self, tmp_path) -> None:
        """Empty file returns empty string."""
        f = tmp_path / "test.oct.md"
        f.write_text("")
        result = validate_review._sniff_octave_type(str(f))
        assert result == ""

    def test_no_type_field_returns_empty(self, tmp_path) -> None:
        """File without TYPE:: returns empty string."""
        f = tmp_path / "test.oct.md"
        f.write_text("===TEST===\nMETA:\n  VERSION::1.0\n")
        result = validate_review._sniff_octave_type(str(f))
        assert result == ""

    def test_nonexistent_file_returns_empty(self) -> None:
        """Nonexistent file returns empty string (fail-safe)."""
        result = validate_review._sniff_octave_type("/nonexistent/path.oct.md")
        assert result == ""


# ---------------------------------------------------------------------------
# 5. Backward compat: determine_review_tier still works
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestDetermineReviewTierBackwardCompat:
    """determine_review_tier() must still return (tier, reason) tuples."""

    def test_returns_tuple(self) -> None:
        """determine_review_tier() returns a (str, str) tuple."""
        files = [{"path": "src/utils.py", "added": 50, "deleted": 20, "total_changed": 70}]
        result = validate_review.determine_review_tier(files)
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], str)
        assert isinstance(result[1], str)

    def test_exempt_files_return_tier_0(self) -> None:
        """Exempt-only files still return TIER_0_EXEMPT."""
        files = [{"path": "README.md", "added": 5, "deleted": 2, "total_changed": 7}]
        tier, _ = validate_review.determine_review_tier(files)
        assert tier == "TIER_0_EXEMPT"


# ---------------------------------------------------------------------------
# 6. Security: fail-closed for unknown roles
# ---------------------------------------------------------------------------
@pytest.mark.unit
@pytest.mark.security
class TestFailClosedUnknownRoles:
    """Unknown roles in required_roles must cause the gate to FAIL, not silently pass."""

    def test_unknown_role_causes_failure(self, ci_environment, monkeypatch) -> None:
        """A required role not in _role_checkers must fail the gate."""
        import subprocess

        def mock_run(cmd, *args, **kwargs):
            return MagicMock(
                stdout=json.dumps(
                    {
                        "body": "",
                        "comments": [
                            {"body": "CE APPROVED: architecture sound"},
                        ],
                    }
                ),
                returncode=0,
                check=lambda: None,
            )

        monkeypatch.setattr(subprocess, "run", mock_run)

        approved, message, _ = validate_review.check_pr_comments(
            required_roles={"CE", "UNKNOWN_ROLE"}, tier="TIER_2_STANDARD"
        )
        assert (
            approved is False
        ), f"Unknown role should cause gate to FAIL (fail-closed), got: {message}"
        assert "UNKNOWN_ROLE" in message


# ---------------------------------------------------------------------------
# 7. SR checker backward compat with GR
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestSRCheckerGRBackwardCompat:
    """SR checker in check_pr_comments must accept legacy GR APPROVED comments."""

    def test_sr_satisfied_by_legacy_gr_comment(self, ci_environment, monkeypatch) -> None:
        """required_roles={SR} passes with legacy 'GR APPROVED' comment."""
        import subprocess

        def mock_run(cmd, *args, **kwargs):
            return MagicMock(
                stdout=json.dumps(
                    {
                        "body": "",
                        "comments": [
                            {"body": "GR APPROVED: legacy governance review"},
                        ],
                    }
                ),
                returncode=0,
                check=lambda: None,
            )

        monkeypatch.setattr(subprocess, "run", mock_run)

        approved, message, _ = validate_review.check_pr_comments(
            required_roles={"SR"}, tier="TIER_2_STANDARD"
        )
        assert approved is True, f"SR should accept legacy GR APPROVED comments, got: {message}"
