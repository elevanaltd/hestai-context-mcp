"""
Contract tests for the 5-tier review system in validate_review.py.

Tests verify tier determination, approval requirements, and governance compliance
for the expanded TMG/CIV/PE role structure:
- T1 threshold (<10 lines, single non-exempt file, no security paths, no new tests)
- T2 range (10-500 lines, requires TMG + CRS + CE)
- T3 triggers (>500 lines, security/architecture paths, requires TMG + CRS + CE + CIV)
- T4 strategic (manual-only, requires TMG + CRS + CE + CIV + PE)
- T0 exemptions (docs, tests, locks, generated JSON only)

Source of truth: review-requirements.oct.md v2.0 (5-tier system)
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
import validate_review


@pytest.fixture
def ci_environment(monkeypatch):
    """Set up CI environment variables."""
    monkeypatch.setenv("CI", "true")
    monkeypatch.setenv("GITHUB_BASE_REF", "origin/main")
    monkeypatch.setenv("PR_NUMBER", "999")


# ---------------------------------------------------------------------------
# 1. T1 threshold change: <10 lines (was <50)
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestTier1ThresholdChange:
    """T1 threshold must be <10 lines (was <50 in old system)."""

    def test_9_lines_single_file_is_tier_1(self) -> None:
        """9 lines changed in single non-exempt file = TIER_1_SELF."""
        files = [{"path": "src/utils.py", "added": 5, "deleted": 4, "total_changed": 9}]
        tier, _ = validate_review.determine_review_tier(files)
        assert tier == "TIER_1_SELF", f"9 lines in single file should be T1, got {tier}"

    def test_10_lines_single_file_is_not_tier_1(self) -> None:
        """10 lines changed should be TIER_2_STANDARD, not TIER_1_SELF.

        The governance rule says T1 is non_exempt_lines<10, so 10 lines
        should NOT qualify for self-review.
        """
        files = [{"path": "src/utils.py", "added": 6, "deleted": 4, "total_changed": 10}]
        tier, _ = validate_review.determine_review_tier(files)
        assert tier == "TIER_2_STANDARD", f"10 lines should be T2, got {tier}"

    def test_30_lines_single_file_is_not_tier_1(self) -> None:
        """30 lines changed must NOT be TIER_1_SELF under new <10 threshold.

        This was previously T1 under the <50 threshold. Under the new system
        it must be T2 (10-500 lines).
        """
        files = [{"path": "src/utils.py", "added": 20, "deleted": 10, "total_changed": 30}]
        tier, _ = validate_review.determine_review_tier(files)
        assert tier != "TIER_1_SELF", f"30 lines must NOT be T1 under new threshold, got {tier}"
        assert tier == "TIER_2_STANDARD", f"30 lines should be T2, got {tier}"

    def test_49_lines_single_file_is_tier_2_not_tier_1(self) -> None:
        """49 lines was T1 under old system but must be T2 under new <10 threshold."""
        files = [{"path": "src/utils.py", "added": 30, "deleted": 19, "total_changed": 49}]
        tier, _ = validate_review.determine_review_tier(files)
        assert tier == "TIER_2_STANDARD", f"49 lines must be T2 under new threshold, got {tier}"

    def test_1_line_single_file_is_tier_1(self) -> None:
        """1 line changed in single file = TIER_1_SELF."""
        files = [{"path": "src/config.py", "added": 1, "deleted": 0, "total_changed": 1}]
        tier, _ = validate_review.determine_review_tier(files)
        assert tier == "TIER_1_SELF", f"1 line should be T1, got {tier}"


# ---------------------------------------------------------------------------
# 2. T1 with security paths -- must be upgraded
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestTier1SecurityPathUpgrade:
    """T1 self-review must be denied when security-touching paths are changed."""

    def test_small_change_in_auth_path_not_tier_1(self) -> None:
        """<10 lines in auth path must NOT be TIER_1_SELF (security guard).

        The governance rule says T1 requires no_security_paths. Changes to
        auth-related files must always get a higher tier review.
        """
        files = [
            {"path": "src/hestai_mcp/auth/handler.py", "added": 3, "deleted": 2, "total_changed": 5}
        ]
        tier, _ = validate_review.determine_review_tier(files)
        assert (
            tier == "TIER_3_CRITICAL"
        ), f"Security-touching path (auth) must be TIER_3_CRITICAL, got {tier}"

    def test_small_change_in_session_management_not_tier_1(self) -> None:
        """<10 lines in session management must be TIER_3_CRITICAL (security guard)."""
        files = [
            {
                "path": "src/hestai_mcp/session/manager.py",
                "added": 2,
                "deleted": 1,
                "total_changed": 3,
            }
        ]
        tier, _ = validate_review.determine_review_tier(files)
        assert (
            tier == "TIER_3_CRITICAL"
        ), f"Security-touching path (session) must be TIER_3_CRITICAL, got {tier}"

    def test_small_change_in_env_vars_handling_not_tier_1(self) -> None:
        """<10 lines changing env var handling must be TIER_3_CRITICAL."""
        files = [
            {"path": "src/hestai_mcp/config/env.py", "added": 3, "deleted": 0, "total_changed": 3}
        ]
        tier, _ = validate_review.determine_review_tier(files)
        assert (
            tier == "TIER_3_CRITICAL"
        ), f"Security-touching path (env) must be TIER_3_CRITICAL, got {tier}"


# ---------------------------------------------------------------------------
# 3. T1 with new test files -- must be upgraded
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestTier1NewTestFileUpgrade:
    """T1 self-review must be denied when new test files are included.

    Per governance rule: T1 requires no_new_test_files. New test files
    indicate substantive changes that require TMG review at T2+.
    """

    def test_small_change_with_new_test_file_not_tier_1(self) -> None:
        """<10 lines but including a new test file must NOT be TIER_1_SELF.

        New tests indicate functional changes that need TMG review.
        """
        files = [
            {"path": "src/utils.py", "added": 3, "deleted": 0, "total_changed": 3, "status": "M"},
            {
                "path": "tests/test_utils.py",
                "added": 5,
                "deleted": 0,
                "total_changed": 5,
                "status": "A",
            },
        ]
        # Governance says no_new_test_files for T1. The "status": "A" marks the
        # test file as newly added, which should disqualify T1 self-review.
        tier, _ = validate_review.determine_review_tier(files)
        assert (
            tier == "TIER_2_STANDARD"
        ), f"PR with new test files must be TIER_2_STANDARD, got {tier}"


# ---------------------------------------------------------------------------
# 4. T2 range: 10-500 lines
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestTier2Range:
    """T2 must cover 10-500 lines (was 50-500)."""

    def test_10_lines_is_tier_2(self) -> None:
        """10 lines = lower bound of T2."""
        files = [{"path": "src/core.py", "added": 6, "deleted": 4, "total_changed": 10}]
        tier, _ = validate_review.determine_review_tier(files)
        assert tier == "TIER_2_STANDARD", f"10 lines should be T2, got {tier}"

    def test_15_lines_is_tier_2(self) -> None:
        """15 lines = within T2 range."""
        files = [{"path": "src/core.py", "added": 10, "deleted": 5, "total_changed": 15}]
        tier, _ = validate_review.determine_review_tier(files)
        assert tier == "TIER_2_STANDARD", f"15 lines should be T2, got {tier}"

    def test_500_lines_is_tier_2(self) -> None:
        """500 lines = upper bound of T2."""
        files = [{"path": "src/core.py", "added": 300, "deleted": 200, "total_changed": 500}]
        tier, _ = validate_review.determine_review_tier(files)
        assert tier == "TIER_2_STANDARD", f"500 lines should be T2, got {tier}"

    def test_multiple_files_in_range_is_tier_2(self) -> None:
        """Multiple non-exempt files with total 10-500 lines = T2."""
        files = [
            {"path": "src/a.py", "added": 5, "deleted": 0, "total_changed": 5},
            {"path": "src/b.py", "added": 10, "deleted": 0, "total_changed": 10},
        ]
        tier, _ = validate_review.determine_review_tier(files)
        assert tier == "TIER_2_STANDARD", f"Multiple files 15 lines should be T2, got {tier}"


# ---------------------------------------------------------------------------
# 5. T3 triggers
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestTier3Triggers:
    """All T3 triggers from governance rule must produce TIER_3_CRITICAL."""

    def test_over_500_lines_is_tier_3_critical(self) -> None:
        """>500 lines must trigger TIER_3_CRITICAL."""
        files = [{"path": "src/core.py", "added": 400, "deleted": 200, "total_changed": 600}]
        tier, _ = validate_review.determine_review_tier(files)
        assert tier == "TIER_3_CRITICAL", f">500 lines should be TIER_3_CRITICAL, got {tier}"

    def test_base_class_change_is_tier_3(self) -> None:
        """Changes to base class files must trigger T3.

        Per governance: touches_base_class[**/base.py,**/shared/**,abstract_classes]
        """
        files = [{"path": "src/hestai_mcp/base.py", "added": 10, "deleted": 5, "total_changed": 15}]
        tier, _ = validate_review.determine_review_tier(files)
        assert tier == "TIER_3_CRITICAL", f"Base class change should be TIER_3_CRITICAL, got {tier}"

    def test_shared_module_change_is_tier_3(self) -> None:
        """Changes to shared modules must trigger T3.

        Per governance: touches_base_class[**/shared/**]
        """
        files = [
            {
                "path": "src/hestai_mcp/modules/tools/shared/utils.py",
                "added": 10,
                "deleted": 5,
                "total_changed": 15,
            }
        ]
        tier, _ = validate_review.determine_review_tier(files)
        assert (
            tier == "TIER_3_CRITICAL"
        ), f"Shared module change should be TIER_3_CRITICAL, got {tier}"

    def test_security_touching_code_is_tier_3(self) -> None:
        """Security-touching code must trigger T3.

        Per governance: touches_security[auth,path_handling,session_management,env_vars]
        """
        files = [
            {
                "path": "src/hestai_mcp/auth/handler.py",
                "added": 50,
                "deleted": 20,
                "total_changed": 70,
            }
        ]
        tier, _ = validate_review.determine_review_tier(files)
        assert (
            tier == "TIER_3_CRITICAL"
        ), f"Security-touching code should be TIER_3_CRITICAL, got {tier}"

    def test_new_tool_addition_is_tier_3(self) -> None:
        """New tool addition must trigger T3.

        Per governance: is_new_tool[tools/**,clink/agents/**]
        """
        files = [
            {
                "path": "src/hestai_mcp/modules/tools/new_tool.py",
                "added": 50,
                "deleted": 0,
                "total_changed": 50,
            }
        ]
        tier, _ = validate_review.determine_review_tier(files)
        assert tier == "TIER_3_CRITICAL", f"New tool addition should be TIER_3_CRITICAL, got {tier}"

    def test_new_mcp_endpoint_is_tier_3(self) -> None:
        """New MCP endpoint must trigger T3.

        Per governance: is_new_mcp_endpoint[mcp/tools/**]
        """
        files = [
            {
                "path": "src/hestai_mcp/mcp/tools/new_endpoint.py",
                "added": 40,
                "deleted": 0,
                "total_changed": 40,
            }
        ]
        tier, _ = validate_review.determine_review_tier(files)
        assert tier == "TIER_3_CRITICAL", f"New MCP endpoint should be TIER_3_CRITICAL, got {tier}"

    def test_sql_change_is_tier_3(self) -> None:
        """SQL file changes must trigger T3."""
        files = [{"path": "migrations/001.sql", "added": 20, "deleted": 5, "total_changed": 25}]
        tier, _ = validate_review.determine_review_tier(files)
        assert tier == "TIER_3_CRITICAL", f"SQL change should be TIER_3_CRITICAL, got {tier}"


# ---------------------------------------------------------------------------
# 6. Tier name changes
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestTierNameChanges:
    """Tier names must match the new 5-tier system naming."""

    def test_tier_3_returns_critical_not_strict(self) -> None:
        """determine_review_tier must return TIER_3_CRITICAL, not TIER_3_STRICT.

        The old system used TIER_3_STRICT. The new 5-tier system renames
        this to TIER_3_CRITICAL per the governance rule.
        """
        files = [{"path": "src/core.py", "added": 400, "deleted": 200, "total_changed": 600}]
        tier, _ = validate_review.determine_review_tier(files)
        assert "STRICT" not in tier, f"TIER_3_STRICT is deprecated, got {tier}"
        assert tier == "TIER_3_CRITICAL", f"Must return TIER_3_CRITICAL, got {tier}"

    def test_tier_4_strategic_name(self) -> None:
        """TIER_4_STRATEGIC must be a recognized tier value.

        This tier is manual-only (triggered by /review --strategic or
        explicit tier override), so determine_review_tier won't auto-detect it.
        But the tier constant must exist and be usable.
        """
        from hestai_context_mcp.tools.shared.review_formats import TIER_4_STRATEGIC

        assert TIER_4_STRATEGIC == "TIER_4_STRATEGIC"


# ---------------------------------------------------------------------------
# 7. T2 approval checking: TMG + CRS + CE
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestTier2ApprovalRequirements:
    """TIER_2_STANDARD must require TMG + CRS + CE approval (was CRS + CE)."""

    def test_tier_2_with_tmg_crs_ce_passes(self, ci_environment, monkeypatch) -> None:
        """T2 with TMG + CRS + CE approvals must pass."""
        import subprocess

        def mock_run(cmd, *args, **kwargs):
            return MagicMock(
                stdout=json.dumps(
                    {
                        "body": "",
                        "comments": [
                            {"body": "TMG APPROVED: tests cover critical paths"},
                            {"body": "CRS APPROVED: Logic correct"},
                            {"body": "CE APPROVED: Architecture sound"},
                        ],
                    }
                ),
                returncode=0,
                check=lambda: None,
            )

        monkeypatch.setattr(subprocess, "run", mock_run)

        approved, message, _ = validate_review.check_pr_comments("TIER_2_STANDARD")
        assert approved is True, f"T2 with TMG+CRS+CE should pass, got: {message}"
        assert "No review required" not in message, "Must actively validate, not fall through"

    def test_tier_2_without_tmg_fails(self, ci_environment, monkeypatch) -> None:
        """T2 with only CRS + CE (no TMG) must FAIL.

        Under the old system, CRS+CE was sufficient for T2.
        Under the new 5-tier system, TMG is also required.
        """
        import subprocess

        def mock_run(cmd, *args, **kwargs):
            return MagicMock(
                stdout=json.dumps(
                    {
                        "body": "",
                        "comments": [
                            {"body": "CRS APPROVED: Logic correct"},
                            {"body": "CE APPROVED: Architecture sound"},
                        ],
                    }
                ),
                returncode=0,
                check=lambda: None,
            )

        monkeypatch.setattr(subprocess, "run", mock_run)

        approved, message, _ = validate_review.check_pr_comments("TIER_2_STANDARD")
        assert approved is False, f"T2 without TMG should fail under 5-tier system, got: {message}"
        assert "TMG" in message, f"Error message should mention missing TMG, got: {message}"


# ---------------------------------------------------------------------------
# 8. T3 approval checking: TMG + CRS + CE + CIV
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestTier3ApprovalRequirements:
    """TIER_3_CRITICAL must require TMG + CRS + CE + CIV approval."""

    def test_tier_3_with_tmg_crs_ce_civ_passes(self, ci_environment, monkeypatch) -> None:
        """T3 with TMG + CRS + CE + CIV approvals must pass."""
        import subprocess

        def mock_run(cmd, *args, **kwargs):
            return MagicMock(
                stdout=json.dumps(
                    {
                        "body": "",
                        "comments": [
                            {"body": "TMG APPROVED: tests cover critical paths"},
                            {"body": "CRS APPROVED: Logic correct"},
                            {"body": "CE APPROVED: Architecture sound"},
                            {"body": "CIV APPROVED: Implementation matches spec"},
                        ],
                    }
                ),
                returncode=0,
                check=lambda: None,
            )

        monkeypatch.setattr(subprocess, "run", mock_run)

        approved, message, _ = validate_review.check_pr_comments("TIER_3_CRITICAL")
        assert approved is True, f"T3 with TMG+CRS+CE+CIV should pass, got: {message}"
        assert "No review required" not in message, "Must actively validate, not fall through"

    def test_tier_3_without_civ_fails(self, ci_environment, monkeypatch) -> None:
        """T3 with TMG + CRS + CE but no CIV must FAIL."""
        import subprocess

        def mock_run(cmd, *args, **kwargs):
            return MagicMock(
                stdout=json.dumps(
                    {
                        "body": "",
                        "comments": [
                            {"body": "TMG APPROVED: tests cover critical paths"},
                            {"body": "CRS APPROVED: Logic correct"},
                            {"body": "CE APPROVED: Architecture sound"},
                        ],
                    }
                ),
                returncode=0,
                check=lambda: None,
            )

        monkeypatch.setattr(subprocess, "run", mock_run)

        approved, message, _ = validate_review.check_pr_comments("TIER_3_CRITICAL")
        assert approved is False, f"T3 without CIV should fail, got: {message}"
        assert "CIV" in message, f"Error message should mention missing CIV, got: {message}"

    def test_tier_3_without_tmg_fails(self, ci_environment, monkeypatch) -> None:
        """T3 with CRS + CE + CIV but no TMG must FAIL."""
        import subprocess

        def mock_run(cmd, *args, **kwargs):
            return MagicMock(
                stdout=json.dumps(
                    {
                        "body": "",
                        "comments": [
                            {"body": "CRS APPROVED: Logic correct"},
                            {"body": "CE APPROVED: Architecture sound"},
                            {"body": "CIV APPROVED: Implementation valid"},
                        ],
                    }
                ),
                returncode=0,
                check=lambda: None,
            )

        monkeypatch.setattr(subprocess, "run", mock_run)

        approved, message, _ = validate_review.check_pr_comments("TIER_3_CRITICAL")
        assert approved is False, f"T3 without TMG should fail, got: {message}"
        assert "TMG" in message, f"Error message should mention missing TMG, got: {message}"


# ---------------------------------------------------------------------------
# 9. T4 approval checking: TMG + CRS + CE + CIV + PE
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestTier4ApprovalRequirements:
    """TIER_4_STRATEGIC must require TMG + CRS + CE + CIV + PE approval."""

    def test_tier_4_with_all_five_passes(self, ci_environment, monkeypatch) -> None:
        """T4 with TMG + CRS + CE + CIV + PE approvals must pass."""
        import subprocess

        def mock_run(cmd, *args, **kwargs):
            return MagicMock(
                stdout=json.dumps(
                    {
                        "body": "",
                        "comments": [
                            {"body": "TMG APPROVED: tests comprehensive"},
                            {"body": "CRS APPROVED: Logic correct"},
                            {"body": "CE APPROVED: Architecture sound"},
                            {"body": "CIV APPROVED: Implementation matches spec"},
                            {"body": "PE APPROVED: Architecture sound for 6 months"},
                        ],
                    }
                ),
                returncode=0,
                check=lambda: None,
            )

        monkeypatch.setattr(subprocess, "run", mock_run)

        approved, message, _ = validate_review.check_pr_comments("TIER_4_STRATEGIC")
        assert approved is True, f"T4 with TMG+CRS+CE+CIV+PE should pass, got: {message}"
        assert "No review required" not in message, "Must actively validate, not fall through"

    def test_tier_4_without_pe_fails(self, ci_environment, monkeypatch) -> None:
        """T4 with TMG + CRS + CE + CIV but no PE must FAIL."""
        import subprocess

        def mock_run(cmd, *args, **kwargs):
            return MagicMock(
                stdout=json.dumps(
                    {
                        "body": "",
                        "comments": [
                            {"body": "TMG APPROVED: tests comprehensive"},
                            {"body": "CRS APPROVED: Logic correct"},
                            {"body": "CE APPROVED: Architecture sound"},
                            {"body": "CIV APPROVED: Implementation matches spec"},
                        ],
                    }
                ),
                returncode=0,
                check=lambda: None,
            )

        monkeypatch.setattr(subprocess, "run", mock_run)

        approved, message, _ = validate_review.check_pr_comments("TIER_4_STRATEGIC")
        assert approved is False, f"T4 without PE should fail, got: {message}"
        assert "PE" in message, f"Error message should mention missing PE, got: {message}"

    def test_tier_4_without_civ_fails(self, ci_environment, monkeypatch) -> None:
        """T4 with TMG + CRS + CE + PE but no CIV must FAIL."""
        import subprocess

        def mock_run(cmd, *args, **kwargs):
            return MagicMock(
                stdout=json.dumps(
                    {
                        "body": "",
                        "comments": [
                            {"body": "TMG APPROVED: tests comprehensive"},
                            {"body": "CRS APPROVED: Logic correct"},
                            {"body": "CE APPROVED: Architecture sound"},
                            {"body": "PE APPROVED: Sustainable"},
                        ],
                    }
                ),
                returncode=0,
                check=lambda: None,
            )

        monkeypatch.setattr(subprocess, "run", mock_run)

        approved, message, _ = validate_review.check_pr_comments("TIER_4_STRATEGIC")
        assert approved is False, f"T4 without CIV should fail, got: {message}"
        assert "CIV" in message, f"Error message should mention missing CIV, got: {message}"

    def test_tier_4_with_only_crs_ce_fails(self, ci_environment, monkeypatch) -> None:
        """T4 with only CRS + CE (no TMG, CIV, PE) must FAIL."""
        import subprocess

        def mock_run(cmd, *args, **kwargs):
            return MagicMock(
                stdout=json.dumps(
                    {
                        "body": "",
                        "comments": [
                            {"body": "CRS APPROVED: Logic correct"},
                            {"body": "CE APPROVED: Architecture sound"},
                        ],
                    }
                ),
                returncode=0,
                check=lambda: None,
            )

        monkeypatch.setattr(subprocess, "run", mock_run)

        approved, message, _ = validate_review.check_pr_comments("TIER_4_STRATEGIC")
        assert approved is False, f"T4 with only CRS+CE should fail, got: {message}"


# ---------------------------------------------------------------------------
# C3: T0 exemption tests
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestTier0Exemption:
    """TIER_0_EXEMPT must cover docs-only, tests-only, lock-only PRs.

    Governance defines conditional exemptions for changes that only touch
    exempt file types. Mixed exempt + non-exempt must NOT be exempt.
    """

    def test_docs_only_pr_is_exempt(self) -> None:
        """PR with only .md files -> TIER_0_EXEMPT."""
        files = [
            {"path": "docs/README.md", "added": 10, "deleted": 5, "total_changed": 15},
            {"path": "CHANGELOG.md", "added": 3, "deleted": 0, "total_changed": 3},
        ]
        tier, _ = validate_review.determine_review_tier(files)
        assert tier == "TIER_0_EXEMPT", f"Docs-only PR should be exempt, got {tier}"

    def test_tests_only_pr_no_src_is_exempt(self) -> None:
        """PR with only test files and no src changes -> TIER_0_EXEMPT."""
        files = [
            {"path": "tests/unit/test_foo.py", "added": 20, "deleted": 5, "total_changed": 25},
            {"path": "tests/conftest.py", "added": 5, "deleted": 0, "total_changed": 5},
        ]
        tier, _ = validate_review.determine_review_tier(files)
        assert tier == "TIER_0_EXEMPT", f"Tests-only PR should be exempt, got {tier}"

    def test_lock_only_pr_is_exempt(self) -> None:
        """PR with only lock files -> TIER_0_EXEMPT."""
        files = [
            {"path": "uv.lock", "added": 100, "deleted": 50, "total_changed": 150},
        ]
        tier, _ = validate_review.determine_review_tier(files)
        assert tier == "TIER_0_EXEMPT", f"Lock-only PR should be exempt, got {tier}"

    def test_mixed_exempt_and_non_exempt_is_not_exempt(self) -> None:
        """PR with exempt + non-exempt files must NOT be exempt."""
        files = [
            {"path": "docs/README.md", "added": 10, "deleted": 0, "total_changed": 10},
            {"path": "src/utils.py", "added": 5, "deleted": 0, "total_changed": 5},
        ]
        tier, _ = validate_review.determine_review_tier(files)
        assert tier != "TIER_0_EXEMPT", f"Mixed PR must NOT be exempt, got {tier}"

    def test_non_generated_json_not_exempt(self) -> None:
        """Hand-edited .json config files must NOT be TIER_0_EXEMPT.

        Governance says **/*.json[when:generated_file] -- JSON is exempt ONLY
        when it is a generated file (package-lock.json, coverage reports).
        Hand-edited config files like src/config/settings.json are NOT exempt.
        """
        files = [
            {
                "path": "src/config/settings.json",
                "added": 5,
                "deleted": 2,
                "total_changed": 7,
            },
        ]
        tier, _ = validate_review.determine_review_tier(files)
        assert tier != "TIER_0_EXEMPT", (
            f"Hand-edited JSON (src/config/settings.json) must NOT be exempt, got {tier}. "
            "Governance says **/*.json[when:generated_file] — only generated JSON is exempt."
        )

    def test_oct_md_files_are_not_exempt(self) -> None:
        """.oct.md files are governance code and must NOT be exempt.

        The exempt pattern uses a negative lookbehind: .*(?<!\\.oct)\\.md$
        so regular .md files are exempt but .oct.md files are not.
        """
        files = [
            {
                "path": "src/hestai_mcp/_bundled_hub/library/skills/foo/SKILL.oct.md",
                "added": 10,
                "deleted": 5,
                "total_changed": 15,
            },
        ]
        tier, _ = validate_review.determine_review_tier(files)
        assert tier != "TIER_0_EXEMPT", f".oct.md files must NOT be exempt, got {tier}"


# ---------------------------------------------------------------------------
# C4: GO alias tests in validator
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestGOAliasApprovalInValidator:
    """Governance defines TMG GO, CIV GO, PE GO as valid approval forms.

    check_pr_comments() must accept GO as well as APPROVED for new roles.
    """

    def test_tier_2_passes_with_tmg_go(self, ci_environment, monkeypatch) -> None:
        """T2 passes with TMG GO + CRS APPROVED + CE APPROVED."""
        import subprocess

        def mock_run(cmd, *args, **kwargs):
            return MagicMock(
                stdout=json.dumps(
                    {
                        "body": "",
                        "comments": [
                            {"body": "TMG GO: sufficient test coverage"},
                            {"body": "CRS APPROVED: Logic correct"},
                            {"body": "CE APPROVED: Architecture sound"},
                        ],
                    }
                ),
                returncode=0,
                check=lambda: None,
            )

        monkeypatch.setattr(subprocess, "run", mock_run)

        approved, message, _ = validate_review.check_pr_comments("TIER_2_STANDARD")
        assert approved is True, f"T2 with TMG GO should pass, got: {message}"
        assert "No review required" not in message, "Must actively validate, not fall through"

    def test_tier_3_passes_with_civ_go(self, ci_environment, monkeypatch) -> None:
        """T3 passes with TMG APPROVED + CRS APPROVED + CE APPROVED + CIV GO."""
        import subprocess

        def mock_run(cmd, *args, **kwargs):
            return MagicMock(
                stdout=json.dumps(
                    {
                        "body": "",
                        "comments": [
                            {"body": "TMG APPROVED: tests cover critical paths"},
                            {"body": "CRS APPROVED: Logic correct"},
                            {"body": "CE APPROVED: Architecture sound"},
                            {"body": "CIV GO: implementation clean"},
                        ],
                    }
                ),
                returncode=0,
                check=lambda: None,
            )

        monkeypatch.setattr(subprocess, "run", mock_run)

        approved, message, _ = validate_review.check_pr_comments("TIER_3_CRITICAL")
        assert approved is True, f"T3 with CIV GO should pass, got: {message}"
        assert "No review required" not in message, "Must actively validate, not fall through"

    def test_tier_4_passes_with_pe_go(self, ci_environment, monkeypatch) -> None:
        """T4 passes with all required including PE GO."""
        import subprocess

        def mock_run(cmd, *args, **kwargs):
            return MagicMock(
                stdout=json.dumps(
                    {
                        "body": "",
                        "comments": [
                            {"body": "TMG APPROVED: tests comprehensive"},
                            {"body": "CRS APPROVED: Logic correct"},
                            {"body": "CE APPROVED: Architecture sound"},
                            {"body": "CIV APPROVED: Implementation matches spec"},
                            {"body": "PE GO: long-term sustainable"},
                        ],
                    }
                ),
                returncode=0,
                check=lambda: None,
            )

        monkeypatch.setattr(subprocess, "run", mock_run)

        approved, message, _ = validate_review.check_pr_comments("TIER_4_STRATEGIC")
        assert approved is True, f"T4 with PE GO should pass, got: {message}"
        assert "No review required" not in message, "Must actively validate, not fall through"


# ---------------------------------------------------------------------------
# H1: Missing T3 trigger paths
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestTier3TriggersMissing:
    """Additional T3 triggers from governance not covered by original tests."""

    def test_path_handling_security_path_is_tier_3(self) -> None:
        """path_handling security path (e.g., src/core/path_utils.py) -> T3."""
        files = [
            {
                "path": "src/core/path_utils.py",
                "added": 10,
                "deleted": 5,
                "total_changed": 15,
            }
        ]
        tier, _ = validate_review.determine_review_tier(files)
        assert tier == "TIER_3_CRITICAL", f"Path handling code should be T3, got {tier}"

    def test_abstract_class_change_is_tier_3(self) -> None:
        """Abstract class file -> T3 per governance: abstract_classes."""
        files = [
            {
                "path": "src/hestai_mcp/abstract/base_handler.py",
                "added": 10,
                "deleted": 5,
                "total_changed": 15,
            }
        ]
        tier, _ = validate_review.determine_review_tier(files)
        assert (
            tier == "TIER_3_CRITICAL"
        ), f"Abstract class change should be TIER_3_CRITICAL, got {tier}"

    def test_clink_agents_path_is_tier_3(self) -> None:
        """clink/agents/** path -> T3 per governance: is_new_tool."""
        files = [
            {
                "path": "clink/agents/new_agent.py",
                "added": 30,
                "deleted": 0,
                "total_changed": 30,
            }
        ]
        tier, _ = validate_review.determine_review_tier(files)
        assert tier == "TIER_3_CRITICAL", f"clink/agents path should be TIER_3_CRITICAL, got {tier}"

    def test_new_hooks_change_triggers_tier_3(self) -> None:
        """Hooks directory files must trigger TIER_3_CRITICAL.

        Per governance: architecture_changes[base_class_mods,new_hooks] is a T3
        trigger. Files in a hooks directory (e.g., src/hestai_mcp/hooks/pre_commit.py)
        are classified as TIER_3_CRITICAL.
        """
        files = [
            {
                "path": "src/hestai_mcp/hooks/pre_commit.py",
                "added": 20,
                "deleted": 5,
                "total_changed": 25,
            }
        ]
        tier, _ = validate_review.determine_review_tier(files)
        assert tier == "TIER_3_CRITICAL", (
            f"New hooks file should be TIER_3_CRITICAL, got {tier}. "
            "Governance says architecture_changes[base_class_mods,new_hooks] triggers T3."
        )

    def test_501_lines_boundary_is_tier_3(self) -> None:
        """501 lines (just over the 500 boundary) -> TIER_3_CRITICAL."""
        files = [{"path": "src/big_module.py", "added": 300, "deleted": 201, "total_changed": 501}]
        tier, _ = validate_review.determine_review_tier(files)
        assert tier == "TIER_3_CRITICAL", f"501 lines should be TIER_3_CRITICAL, got {tier}"


# ---------------------------------------------------------------------------
# H2: Multi-file <10 lines -> T2 (not T1)
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestMultiFileLowLinesIsT2:
    """Multiple non-exempt files with <10 total lines must be T2 (not T1).

    Governance requires single_non_exempt_file for T1. Two files with 5 total
    lines should be T2 because the file count guard disqualifies T1.
    """

    def test_two_files_under_10_lines_is_tier_2(self) -> None:
        """2 non-exempt files, 3+2=5 total lines -> T2, not T1."""
        files = [
            {"path": "src/a.py", "added": 2, "deleted": 1, "total_changed": 3},
            {"path": "src/b.py", "added": 1, "deleted": 1, "total_changed": 2},
        ]
        tier, _ = validate_review.determine_review_tier(files)
        assert (
            tier == "TIER_2_STANDARD"
        ), f"Multiple non-exempt files even with <10 lines should be T2, got {tier}"


# ---------------------------------------------------------------------------
# H3: T4 auto-detection guard
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestTier4NeverAutoDetected:
    """determine_review_tier() must NEVER return TIER_4_STRATEGIC.

    T4 is manual-only, triggered by /review --strategic or explicit override.
    Even extreme inputs (1000 lines, SQL, security paths) should cap at T3.
    """

    def test_extreme_inputs_never_return_tier_4(self) -> None:
        """1000 lines + SQL + security path should still be T3 at most."""
        files = [
            {
                "path": "src/hestai_mcp/auth/critical.py",
                "added": 500,
                "deleted": 200,
                "total_changed": 700,
            },
            {
                "path": "migrations/dangerous.sql",
                "added": 200,
                "deleted": 100,
                "total_changed": 300,
            },
        ]
        tier, _ = validate_review.determine_review_tier(files)
        assert (
            tier != "TIER_4_STRATEGIC"
        ), f"determine_review_tier must never auto-detect T4, got {tier}"
        # It should be T3 (TIER_3_CRITICAL under the 5-tier system)
        assert tier == "TIER_3_CRITICAL", f"Extreme inputs should be TIER_3_CRITICAL, got {tier}"


# ---------------------------------------------------------------------------
# H4: Metadata/cross-validation tests for new roles
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestMetadataCrossValidationNewRoles:
    """Validator anti-spoof logic must work with TMG/CIV/PE.

    Once TMG/CIV/PE are in VALID_ROLES, the cross-validation at
    validate_review.py:206-264 must reject spoofed approvals.
    """

    def test_metadata_backed_tmg_crs_ce_satisfies_tier_2(self, ci_environment, monkeypatch) -> None:
        """Metadata-backed TMG/CRS/CE approvals satisfy T2 gate."""
        import subprocess

        tmg_comment = (
            "TMG APPROVED: tests cover critical paths\n"
            '<!-- review: {"role":"TMG","provider":"goose","verdict":"APPROVED","sha":"abc1234"} -->'
        )
        crs_comment = (
            "CRS APPROVED: Logic correct\n"
            '<!-- review: {"role":"CRS","provider":"gemini","verdict":"APPROVED","sha":"abc1234"} -->'
        )
        ce_comment = (
            "CE APPROVED: Architecture sound\n"
            '<!-- review: {"role":"CE","provider":"codex","verdict":"APPROVED","sha":"abc1234"} -->'
        )

        def mock_run(cmd, *args, **kwargs):
            return MagicMock(
                stdout=json.dumps(
                    {
                        "body": "",
                        "comments": [
                            {"body": tmg_comment},
                            {"body": crs_comment},
                            {"body": ce_comment},
                        ],
                    }
                ),
                returncode=0,
                check=lambda: None,
            )

        monkeypatch.setattr(subprocess, "run", mock_run)

        approved, message, _ = validate_review.check_pr_comments("TIER_2_STANDARD")
        assert approved is True, f"Metadata-backed T2 should pass, got: {message}"
        assert "No review required" not in message, "Must actively validate, not fall through"

    def test_spoofed_tmg_approval_fails_cross_validation(self, ci_environment, monkeypatch) -> None:
        """Spoofed TMG: metadata says APPROVED but visible text says BLOCKED -> fails.

        The cross-validation logic strips metadata HTML comments and checks
        that visible text also matches the approval pattern.
        """
        import subprocess

        # Visible text says BLOCKED but metadata claims APPROVED
        spoofed_comment = (
            "TMG BLOCKED: tests insufficient\n"
            '<!-- review: {"role":"TMG","provider":"goose","verdict":"APPROVED","sha":"abc1234"} -->'
        )

        def mock_run(cmd, *args, **kwargs):
            return MagicMock(
                stdout=json.dumps(
                    {
                        "body": "",
                        "comments": [
                            {"body": spoofed_comment},
                            {"body": "CRS APPROVED: Logic correct"},
                            {"body": "CE APPROVED: Architecture sound"},
                        ],
                    }
                ),
                returncode=0,
                check=lambda: None,
            )

        monkeypatch.setattr(subprocess, "run", mock_run)

        approved, message, _ = validate_review.check_pr_comments("TIER_2_STANDARD")
        assert approved is False, f"Spoofed TMG should fail cross-validation, got: {message}"
        assert (
            "Cross-validation" in message or "spoofing" in message.lower()
        ), f"Error should mention cross-validation or spoofing, got: {message}"


# ---------------------------------------------------------------------------
# H5: T1 approval tests in validator
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestTier1ApprovalInValidator:
    """check_pr_comments('TIER_1_SELF') must validate self-review patterns."""

    def test_tier_1_passes_with_il_self_reviewed(self, ci_environment, monkeypatch) -> None:
        """T1 passes with IL SELF-REVIEWED: rationale."""
        import subprocess

        def mock_run(cmd, *args, **kwargs):
            return MagicMock(
                stdout=json.dumps(
                    {
                        "body": "",
                        "comments": [
                            {"body": "IL SELF-REVIEWED: Fixed typo in error message"},
                        ],
                    }
                ),
                returncode=0,
                check=lambda: None,
            )

        monkeypatch.setattr(subprocess, "run", mock_run)

        approved, message, _ = validate_review.check_pr_comments("TIER_1_SELF")
        assert approved is True, f"T1 with IL SELF-REVIEWED should pass, got: {message}"

    def test_tier_1_passes_with_ho_reviewed(self, ci_environment, monkeypatch) -> None:
        """T1 passes with HO REVIEWED: rationale."""
        import subprocess

        def mock_run(cmd, *args, **kwargs):
            return MagicMock(
                stdout=json.dumps(
                    {
                        "body": "",
                        "comments": [
                            {"body": "HO REVIEWED: delegated to IL, verified output"},
                        ],
                    }
                ),
                returncode=0,
                check=lambda: None,
            )

        monkeypatch.setattr(subprocess, "run", mock_run)

        approved, message, _ = validate_review.check_pr_comments("TIER_1_SELF")
        assert approved is True, f"T1 with HO REVIEWED should pass, got: {message}"

    def test_tier_1_fails_without_any_review(self, ci_environment, monkeypatch) -> None:
        """T1 fails without IL SELF-REVIEWED or HO REVIEWED."""
        import subprocess

        def mock_run(cmd, *args, **kwargs):
            return MagicMock(
                stdout=json.dumps(
                    {
                        "body": "",
                        "comments": [
                            {"body": "Just a random comment"},
                        ],
                    }
                ),
                returncode=0,
                check=lambda: None,
            )

        monkeypatch.setattr(subprocess, "run", mock_run)

        approved, message, _ = validate_review.check_pr_comments("TIER_1_SELF")
        assert approved is False, f"T1 without self-review should fail, got: {message}"

    def test_tier_1_with_generic_role_self_reviewed(self, ci_environment, monkeypatch) -> None:
        """T1 passes with any role name followed by SELF-REVIEWED.

        The self-review pattern should be role-agnostic: 'skills-expert SELF-REVIEWED'
        or 'Shaun SELF-REVIEWED' should satisfy T1, not just 'IL SELF-REVIEWED'.
        """
        import subprocess

        def mock_run(cmd, *args, **kwargs):
            return MagicMock(
                stdout=json.dumps(
                    {
                        "body": "",
                        "comments": [
                            {"body": "skills-expert SELF-REVIEWED: updated GATES section"},
                        ],
                    }
                ),
                returncode=0,
                check=lambda: None,
            )

        monkeypatch.setattr(subprocess, "run", mock_run)

        approved, message, _ = validate_review.check_pr_comments("TIER_1_SELF")
        assert approved is True, f"T1 with generic role SELF-REVIEWED should pass, got: {message}"


# ---------------------------------------------------------------------------
# M2: Missing negative approval tests for new roles in validator
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestNegativeApprovalNewRoles:
    """BLOCKED comments and wrong-role duplicates must NOT satisfy gates."""

    def test_tmg_blocked_does_not_satisfy_tier_2(self, ci_environment, monkeypatch) -> None:
        """TMG BLOCKED must NOT satisfy the T2 TMG requirement."""
        import subprocess

        def mock_run(cmd, *args, **kwargs):
            return MagicMock(
                stdout=json.dumps(
                    {
                        "body": "",
                        "comments": [
                            {"body": "TMG BLOCKED: tests insufficient"},
                            {"body": "CRS APPROVED: Logic correct"},
                            {"body": "CE APPROVED: Architecture sound"},
                        ],
                    }
                ),
                returncode=0,
                check=lambda: None,
            )

        monkeypatch.setattr(subprocess, "run", mock_run)

        approved, message, _ = validate_review.check_pr_comments("TIER_2_STANDARD")
        assert approved is False, f"TMG BLOCKED should not satisfy T2, got: {message}"

    def test_duplicate_crs_does_not_substitute_for_tmg(self, ci_environment, monkeypatch) -> None:
        """Duplicate CRS APPROVED should not substitute for missing TMG approval."""
        import subprocess

        def mock_run(cmd, *args, **kwargs):
            return MagicMock(
                stdout=json.dumps(
                    {
                        "body": "",
                        "comments": [
                            {"body": "CRS APPROVED: first review"},
                            {"body": "CRS APPROVED: second review"},
                            {"body": "CE APPROVED: Architecture sound"},
                        ],
                    }
                ),
                returncode=0,
                check=lambda: None,
            )

        monkeypatch.setattr(subprocess, "run", mock_run)

        approved, message, _ = validate_review.check_pr_comments("TIER_2_STANDARD")
        assert approved is False, f"Duplicate CRS should not substitute for TMG, got: {message}"


# ---------------------------------------------------------------------------
# M3: Old T3 dual-CRS rule regression
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestOldTier3DualCRSRegression:
    """Old TIER_3_STRICT dual-CRS(Gemini)+CRS(Codex)+CE model is replaced.

    Under the new 5-tier system, T3 (now TIER_3_CRITICAL) requires
    TMG + CRS + CE + CIV. The old dual-CRS model must no longer pass.
    """

    def test_old_dual_crs_plus_ce_fails_for_tier_3(self, ci_environment, monkeypatch) -> None:
        """T3 with old-style dual CRS + CE (no TMG, no CIV) -> FAILS."""
        import subprocess

        def mock_run(cmd, *args, **kwargs):
            return MagicMock(
                stdout=json.dumps(
                    {
                        "body": "",
                        "comments": [
                            {"body": "CRS (Gemini) APPROVED: Logic verified"},
                            {"body": "CRS (Codex) APPROVED: Patterns sound"},
                            {"body": "CE APPROVED: Architecture sound"},
                        ],
                    }
                ),
                returncode=0,
                check=lambda: None,
            )

        monkeypatch.setattr(subprocess, "run", mock_run)

        approved, message, _ = validate_review.check_pr_comments("TIER_3_CRITICAL")
        assert approved is False, f"Old dual-CRS+CE model should NOT satisfy new T3, got: {message}"


# ---------------------------------------------------------------------------
# Bot comment filtering
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestBotCommentFiltering:
    """Bot comments must NOT be included in approval pattern matching.

    Copilot, Cubic, and github-actions bot comments often contain
    approval-like text ('APPROVED', 'GO', etc.) in their review prose. These
    must be excluded so only human/agent review comments count.
    """

    def test_copilot_approval_text_not_counted(self, ci_environment, monkeypatch) -> None:
        """Copilot bot comment with approval text must NOT satisfy gate."""
        import subprocess

        def mock_run(cmd, *args, **kwargs):
            return MagicMock(
                stdout=json.dumps(
                    {
                        "body": "",
                        "comments": [
                            {
                                "author": {"login": "copilot"},
                                "body": "CRS APPROVED: All checks pass\nCE APPROVED: Sound",
                            },
                        ],
                    }
                ),
                returncode=0,
                check=lambda: None,
            )

        monkeypatch.setattr(subprocess, "run", mock_run)

        approved, message, _ = validate_review.check_pr_comments("TIER_2_STANDARD")
        assert (
            approved is False
        ), f"Copilot bot comment must NOT satisfy approval gate, got: {message}"

    def test_human_approval_still_counted(self, ci_environment, monkeypatch) -> None:
        """Human comments alongside bot comments must still be counted."""
        import subprocess

        def mock_run(cmd, *args, **kwargs):
            return MagicMock(
                stdout=json.dumps(
                    {
                        "body": "",
                        "comments": [
                            {
                                "author": {"login": "cubic-dev-ai"},
                                "body": "TMG APPROVED: bot text (should be ignored)",
                            },
                            {
                                "author": {"login": "real-user"},
                                "body": "TMG APPROVED: tests verified",
                            },
                            {
                                "author": {"login": "another-user"},
                                "body": "CRS APPROVED: Logic correct",
                            },
                            {
                                "author": {"login": "ce-user"},
                                "body": "CE APPROVED: Architecture sound",
                            },
                        ],
                    }
                ),
                returncode=0,
                check=lambda: None,
            )

        monkeypatch.setattr(subprocess, "run", mock_run)

        approved, message, _ = validate_review.check_pr_comments("TIER_2_STANDARD")
        assert approved is True, (
            f"Human comments should still satisfy gate even with bot comments present, "
            f"got: {message}"
        )


# ---------------------------------------------------------------------------
# Advisory bot constants and normalization
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestAdvisoryBotsConstant:
    """Pin test for the ADVISORY_BOTS constant.

    ADVISORY_BOTS is the canonical list of bot accounts whose comments are
    treated as advisory context (never blocking/satisfying review gates).
    This test prevents silent drift.
    """

    def test_advisory_bots_contains_expected_entries(self) -> None:
        """ADVISORY_BOTS must contain all canonical bot accounts."""
        assert "cubic-dev-ai[bot]" in validate_review.ADVISORY_BOTS
        assert "github-copilot[bot]" in validate_review.ADVISORY_BOTS

    def test_advisory_bots_does_not_contain_removed_bots(self) -> None:
        """ADVISORY_BOTS must NOT contain removed bot accounts (CodeRabbit, Qodo)."""
        assert "coderabbitai[bot]" not in validate_review.ADVISORY_BOTS
        assert "qodo-code-review[bot]" not in validate_review.ADVISORY_BOTS

    def test_advisory_bots_length(self) -> None:
        """ADVISORY_BOTS should have exactly 2 entries (detect unintended additions)."""
        assert len(validate_review.ADVISORY_BOTS) == 2, (
            f"Expected 2 advisory bots, got {len(validate_review.ADVISORY_BOTS)}: "
            f"{validate_review.ADVISORY_BOTS}"
        )


@pytest.mark.unit
class TestBotLoginSetNormalization:
    """_BOT_LOGIN_SET must correctly strip [bot] suffix and include legacy logins.

    GitHub APIs return different login formats for the same bot accounts:
    - ``gh pr view --json comments`` strips the [bot] suffix
    - ``gh api repos/.../pulls/.../comments`` preserves it
    _BOT_LOGIN_SET normalizes by stripping [bot] and adding known variants.
    """

    def test_stripped_bot_suffix_logins_present(self) -> None:
        """Stripped versions of ADVISORY_BOTS must be in _BOT_LOGIN_SET."""
        assert "cubic-dev-ai" in validate_review._BOT_LOGIN_SET
        assert "github-copilot" in validate_review._BOT_LOGIN_SET

    def test_removed_bot_logins_absent(self) -> None:
        """Fully removed bots (CodeRabbit) must NOT be in _BOT_LOGIN_SET."""
        assert "coderabbitai" not in validate_review._BOT_LOGIN_SET

    def test_decommissioned_bot_logins_still_excluded(self) -> None:
        """Bots removed from ADVISORY_BOTS must STAY in _BOT_LOGIN_SET for gate exclusion.

        _BOT_LOGIN_SET is a security filter: it prevents bot comments from
        satisfying approval gates.  Even after a bot is removed from
        ADVISORY_BOTS (no longer surfaced in advisory output), its logins must
        remain excluded to prevent false-approval paths.
        """
        assert "qodo-code-review" in validate_review._BOT_LOGIN_SET
        assert "qodo-merge-pro" in validate_review._BOT_LOGIN_SET
        assert "qodo-merge-pro-for-open-source" in validate_review._BOT_LOGIN_SET

    def test_legacy_login_variants_present(self) -> None:
        """Legacy login variants must be in _BOT_LOGIN_SET."""
        assert "github-actions" in validate_review._BOT_LOGIN_SET
        assert "copilot" in validate_review._BOT_LOGIN_SET  # Copilot legacy login
        assert "cubic-bot" in validate_review._BOT_LOGIN_SET

    def test_bot_login_set_is_frozenset(self) -> None:
        """_BOT_LOGIN_SET must be immutable (frozenset)."""
        assert isinstance(validate_review._BOT_LOGIN_SET, frozenset)


# ---------------------------------------------------------------------------
# Per-variant bot comment exclusion
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestPerVariantBotExclusion:
    """Each advisory bot variant must be excluded from gate validation.

    Tests cover all known login variants that GitHub APIs may return for
    each advisory bot account.
    """

    @pytest.mark.parametrize(
        "login",
        [
            "cubic-dev-ai",  # gh pr view format (no [bot])
            "cubic-bot",  # Legacy login variant
        ],
    )
    def test_cubic_variants_excluded(self, login, ci_environment, monkeypatch) -> None:
        """Cubic bot comment variants must NOT satisfy approval gate."""
        import subprocess

        def mock_run(cmd, *args, **kwargs):
            return MagicMock(
                stdout=json.dumps(
                    {
                        "body": "",
                        "comments": [
                            {
                                "author": {"login": login},
                                "body": "TMG APPROVED: all tests pass\nCRS APPROVED: ok\nCE APPROVED: ok",
                            },
                        ],
                    }
                ),
                returncode=0,
                check=lambda: None,
            )

        monkeypatch.setattr(subprocess, "run", mock_run)
        approved, message, _ = validate_review.check_pr_comments("TIER_2_STANDARD")
        assert approved is False, f"Cubic bot login '{login}' must NOT satisfy gate, got: {message}"

    @pytest.mark.parametrize(
        "login",
        [
            "qodo-code-review",  # gh pr view format (no [bot])
            "qodo-merge-pro",  # Legacy login variant
            "qodo-merge-pro-for-open-source",  # Another legacy variant
        ],
    )
    def test_qodo_variants_excluded(self, login, ci_environment, monkeypatch) -> None:
        """Qodo bot comment variants must NOT satisfy approval gate.

        Qodo was removed from ADVISORY_BOTS but its logins remain in
        _BOT_LOGIN_SET as a security filter.  This test verifies that a
        Qodo comment containing approval text is correctly rejected.
        """
        import subprocess

        def mock_run(cmd, *args, **kwargs):
            return MagicMock(
                stdout=json.dumps(
                    {
                        "body": "",
                        "comments": [
                            {
                                "author": {"login": login},
                                "body": "TMG APPROVED: tests ok\nCRS APPROVED: ok\nCE APPROVED: ok",
                            },
                        ],
                    }
                ),
                returncode=0,
                check=lambda: None,
            )

        monkeypatch.setattr(subprocess, "run", mock_run)
        approved, message, _ = validate_review.check_pr_comments("TIER_2_STANDARD")
        assert approved is False, f"Qodo bot login '{login}' must NOT satisfy gate, got: {message}"

    @pytest.mark.parametrize(
        "login",
        [
            "github-copilot",  # Stripped [bot] format
            "copilot",  # Legacy login variant (no [bot], no github- prefix)
            "Copilot",  # GitHub API returns capital-C variant
        ],
    )
    def test_copilot_variants_excluded(self, login, ci_environment, monkeypatch) -> None:
        """Copilot bot comment variants must NOT satisfy approval gate."""
        import subprocess

        def mock_run(cmd, *args, **kwargs):
            return MagicMock(
                stdout=json.dumps(
                    {
                        "body": "",
                        "comments": [
                            {
                                "author": {"login": login},
                                "body": "CRS APPROVED: All checks pass\nCE APPROVED: Sound",
                            },
                        ],
                    }
                ),
                returncode=0,
                check=lambda: None,
            )

        monkeypatch.setattr(subprocess, "run", mock_run)
        approved, message, _ = validate_review.check_pr_comments("TIER_2_STANDARD")
        assert (
            approved is False
        ), f"Copilot bot login '{login}' must NOT satisfy gate, got: {message}"


# ---------------------------------------------------------------------------
# Skipped-bot logging output
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestSkippedBotLogging:
    """The validator must log which bot comments were skipped and how many."""

    def test_skipped_bot_logging_output(self, ci_environment, monkeypatch, capsys) -> None:
        """Skipped bot log message must include count and bot names."""
        import subprocess

        def mock_run(cmd, *args, **kwargs):
            return MagicMock(
                stdout=json.dumps(
                    {
                        "body": "",
                        "comments": [
                            {
                                "author": {"login": "github-copilot"},
                                "body": "Some copilot review text",
                            },
                            {
                                "author": {"login": "cubic-dev-ai"},
                                "body": "Some cubic review",
                            },
                            {
                                "author": {"login": "real-user"},
                                "body": "TMG APPROVED: tests ok",
                            },
                        ],
                    }
                ),
                returncode=0,
                check=lambda: None,
            )

        monkeypatch.setattr(subprocess, "run", mock_run)
        validate_review.check_pr_comments("TIER_2_STANDARD")

        captured = capsys.readouterr()
        assert (
            "Skipped 2 bot comment(s)" in captured.out
        ), f"Expected 'Skipped 2 bot comment(s)' in output, got: {captured.out}"
        assert (
            "github-copilot" in captured.out
        ), f"Expected 'github-copilot' in skipped bot names, got: {captured.out}"
        assert (
            "cubic-dev-ai" in captured.out
        ), f"Expected 'cubic-dev-ai' in skipped bot names, got: {captured.out}"

    def test_no_skipped_bot_log_when_no_bots(self, ci_environment, monkeypatch, capsys) -> None:
        """No skipped-bot log line when there are no bot comments."""
        import subprocess

        def mock_run(cmd, *args, **kwargs):
            return MagicMock(
                stdout=json.dumps(
                    {
                        "body": "",
                        "comments": [
                            {
                                "author": {"login": "real-user"},
                                "body": "TMG APPROVED: tests ok",
                            },
                        ],
                    }
                ),
                returncode=0,
                check=lambda: None,
            )

        monkeypatch.setattr(subprocess, "run", mock_run)
        validate_review.check_pr_comments("TIER_2_STANDARD")

        captured = capsys.readouterr()
        assert (
            "Skipped" not in captured.out or "0 bot" not in captured.out
        ), f"Should not log skipped bots when there are none, got: {captured.out}"
