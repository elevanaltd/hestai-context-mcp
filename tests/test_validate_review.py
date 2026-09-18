#!/usr/bin/env python3
"""
Test suite for scripts/validate_review.py

Validates fail-closed behavior in CI, local mode permissiveness,
fork PR support, and emergency bypass audit trail.

SECURITY: Tests marked with @pytest.mark.security validate critical
fail-closed behavior - failures indicate security vulnerabilities.
"""

import json
import os
import re
import subprocess

# Import the module under test
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import validate_review


@pytest.fixture
def ci_environment(monkeypatch):
    """Set up CI environment variables."""
    monkeypatch.setenv("CI", "true")
    monkeypatch.setenv("GITHUB_BASE_REF", "origin/main")
    monkeypatch.setenv("PR_NUMBER", "123")


@pytest.fixture
def local_environment(monkeypatch):
    """Set up local development environment."""
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("GITHUB_BASE_REF", raising=False)
    monkeypatch.delenv("PR_NUMBER", raising=False)


@pytest.mark.security
class TestFailClosedBehavior:
    """Critical security tests - validate fail-closed behavior in CI."""

    def test_get_changed_files_git_failure_in_ci_exits_nonzero(self, ci_environment, monkeypatch):
        """SECURITY: Git failures in CI must exit non-zero, not return empty list."""

        # Mock subprocess.run to raise CalledProcessError
        def mock_run(*args, **kwargs):
            raise subprocess.CalledProcessError(1, "git diff")

        monkeypatch.setattr(subprocess, "run", mock_run)

        # In CI context, git failures should raise, not return []
        with pytest.raises(SystemExit) as exc_info:
            validate_review.get_changed_files()
        assert exc_info.value.code == 1, "Git failure in CI must exit code 1"

    def test_check_pr_comments_failure_in_ci_blocks(self, ci_environment, monkeypatch):
        """SECURITY: PR comment check failures in CI must return False, not True."""

        # Mock gh CLI to raise CalledProcessError
        def mock_run(*args, **kwargs):
            if "gh" in args[0]:
                raise subprocess.CalledProcessError(1, "gh pr view")
            # Allow other git commands to succeed
            return MagicMock(stdout="", returncode=0)

        monkeypatch.setattr(subprocess, "run", mock_run)

        # In CI context, comment check failures should return False
        approved, message, _ = validate_review.check_pr_comments("TIER_2_STANDARD")
        assert approved is False, "Comment check failure in CI must return False"
        assert "error" in message.lower() or "failed" in message.lower()

    def test_main_blocks_on_missing_review_in_ci(self, ci_environment, monkeypatch):
        """SECURITY: main() must exit 1 when reviews missing in CI."""
        # Mock get_changed_files to return non-exempt files
        monkeypatch.setattr(
            validate_review,
            "get_changed_files",
            lambda: [{"path": "src/core.py", "added": 10, "deleted": 5, "total_changed": 15}],
        )

        # Mock check_pr_comments to return False (missing review)
        monkeypatch.setattr(
            validate_review,
            "check_pr_comments",
            lambda *args, **kwargs: (False, "Missing review", []),
        )

        # Mock check_emergency_bypass to return False
        monkeypatch.setattr(validate_review, "check_emergency_bypass", lambda: False)

        # main() should exit 1 in CI when reviews missing
        exit_code = validate_review.main()
        assert exit_code == 1, "main() must exit 1 when reviews missing in CI"


@pytest.mark.behavior
class TestLocalModePermissiveness:
    """Validate that local mode remains permissive for developer UX."""

    def test_get_changed_files_git_failure_local_returns_empty(
        self, local_environment, monkeypatch
    ):
        """Local mode: Git failures return empty list (permissive)."""

        # Mock subprocess.run to raise CalledProcessError
        def mock_run(*args, **kwargs):
            raise subprocess.CalledProcessError(1, "git diff")

        monkeypatch.setattr(subprocess, "run", mock_run)

        # In local context, git failures should return empty list
        files = validate_review.get_changed_files()
        assert files == [], "Git failure in local mode should return empty list"

    def test_check_pr_comments_skips_in_local_mode(self, local_environment):
        """Local mode: PR comment checks are skipped."""
        approved, message, _ = validate_review.check_pr_comments("TIER_2_STANDARD")
        assert approved is True, "Local mode should skip PR comment checks"
        assert "local" in message.lower() or "skip" in message.lower()

    def test_main_permits_without_review_locally(self, local_environment, monkeypatch):
        """Local mode: main() exits 0 even without reviews (permissive)."""
        # Mock get_changed_files to return non-exempt files
        monkeypatch.setattr(
            validate_review,
            "get_changed_files",
            lambda: [{"path": "src/core.py", "added": 10, "deleted": 5, "total_changed": 15}],
        )

        # Mock check_emergency_bypass to return False
        monkeypatch.setattr(validate_review, "check_emergency_bypass", lambda: False)

        # main() should exit 0 in local mode even without reviews
        exit_code = validate_review.main()
        assert exit_code == 0, "main() should exit 0 in local mode (permissive)"


@pytest.mark.behavior
class TestForkPRSupport:
    """Validate fork PR support (already fixed in PR #193)."""

    def test_get_changed_files_uses_base_ref_in_ci(self, ci_environment, monkeypatch):
        """CI mode: Uses GITHUB_BASE_REF for fork PRs.

        The base ref is now consumed via `git merge-base <base_ref> HEAD`, and
        the diff runs against that resolved tree. `git diff A...HEAD` is exactly
        `git diff $(git merge-base A HEAD) HEAD`, so this is equivalent for the
        diff -- but it names the tree explicitly, so old-side rename
        classification can read the SAME tree instead of guessing (issue #161
        round 3). This test previously pinned the literal "origin/main...HEAD";
        that spelling encoded the defect, the fork-PR intent it guarded does not.
        """
        calls = []

        def mock_run(cmd, *args, **kwargs):
            calls.append(cmd)
            if cmd[:2] == ["git", "merge-base"]:
                return MagicMock(stdout="deadbeef\n", stderr="", returncode=0)
            return MagicMock(
                stdout="10\t5\tsrc/core.py\n", stderr="", returncode=0, check=lambda: None
            )

        monkeypatch.setattr(subprocess, "run", mock_run)

        validate_review.get_changed_files()

        # The base ref is still what drives CI mode (fork PR support) ...
        assert ["git", "merge-base", "origin/main", "HEAD"] in calls
        # ... and the diff runs against the tree that resolved from it.
        assert any("deadbeef..HEAD" in " ".join(cmd) for cmd in calls)
        # Never the local staged path.
        assert not any("--cached" in cmd for cmd in calls)

    def test_get_changed_files_uses_cached_locally(self, local_environment, monkeypatch):
        """Local mode: Uses --cached for staged files."""
        calls = []

        def mock_run(cmd, *args, **kwargs):
            calls.append(cmd)
            return MagicMock(
                stdout="10\t5\tsrc/core.py\n", stderr="", returncode=0, check=lambda: None
            )

        monkeypatch.setattr(subprocess, "run", mock_run)

        validate_review.get_changed_files()

        # Verify git diff command uses --cached
        assert len(calls) > 0
        assert any("--cached" in cmd for cmd in calls)


@pytest.mark.security
class TestEmergencyBypassAudit:
    """Validate emergency bypass creates audit trail."""

    def test_emergency_bypass_creates_audit_log(self, ci_environment, monkeypatch, tmp_path):
        """SECURITY: Emergency bypass must create audit log entry."""
        # Set up temporary audit directory
        audit_dir = tmp_path / ".hestai" / "audit"
        audit_log = audit_dir / "bypass-log.jsonl"

        # Mock get_changed_files
        monkeypatch.setattr(
            validate_review,
            "get_changed_files",
            lambda: [{"path": "src/core.py", "added": 10, "deleted": 5, "total_changed": 15}],
        )

        # Mock check_emergency_bypass to return True
        monkeypatch.setattr(validate_review, "check_emergency_bypass", lambda: True)

        # Mock Path.cwd() to return tmp_path
        monkeypatch.setattr(Path, "cwd", lambda: tmp_path)

        # Run main() - should create audit log
        exit_code = validate_review.main()
        assert exit_code == 0, "Emergency bypass should exit 0"

        # Verify audit log was created
        assert audit_log.exists(), "Audit log must be created for emergency bypass"

        # Verify audit log content
        with open(audit_log) as f:
            entries = [json.loads(line) for line in f]
            assert len(entries) > 0, "Audit log must contain at least one entry"
            entry = entries[-1]
            assert "timestamp" in entry
            assert "pr_number" in entry or "commit" in entry
            assert "reason" in entry
            assert entry["reason"] == "EMERGENCY_BYPASS"

    def test_emergency_bypass_audit_includes_metadata(self, ci_environment, monkeypatch, tmp_path):
        """Emergency bypass audit log includes PR number and user metadata."""
        audit_dir = tmp_path / ".hestai" / "audit"
        audit_log = audit_dir / "bypass-log.jsonl"

        # Mock functions
        monkeypatch.setattr(
            validate_review,
            "get_changed_files",
            lambda: [{"path": "src/core.py", "added": 10, "deleted": 5, "total_changed": 15}],
        )
        monkeypatch.setattr(validate_review, "check_emergency_bypass", lambda: True)
        monkeypatch.setattr(Path, "cwd", lambda: tmp_path)

        # Mock git user info
        def mock_run(cmd, *args, **kwargs):
            if "config" in cmd and "user.name" in cmd:
                return MagicMock(stdout="Test User\n")
            if "config" in cmd and "user.email" in cmd:
                return MagicMock(stdout="test@example.com\n")
            return MagicMock(stdout="", returncode=0)

        monkeypatch.setattr(subprocess, "run", mock_run)

        validate_review.main()

        # Verify audit log includes metadata
        with open(audit_log) as f:
            entry = json.loads(f.read())
            assert "pr_number" in entry or "commit" in entry
            assert entry.get("pr_number") == "123" or "commit" in entry


@pytest.mark.behavior
class TestReviewTierLogic:
    """Validate review tier determination logic."""

    def test_tier_0_exempt_for_markdown_only(self):
        """TIER_0_EXEMPT for markdown-only changes."""
        files = [
            {"path": "README.md", "added": 10, "deleted": 5, "total_changed": 15},
            {"path": "docs/guide.md", "added": 20, "deleted": 10, "total_changed": 30},
        ]
        tier, reason = validate_review.determine_review_tier(files)
        assert tier == "TIER_0_EXEMPT"
        assert "exempt" in reason.lower()

    def test_tier_1_self_for_small_single_file(self):
        """TIER_1_SELF for <10 lines in single file (5-tier system threshold)."""
        files = [{"path": "src/utils.py", "added": 5, "deleted": 3, "total_changed": 8}]
        tier, reason = validate_review.determine_review_tier(files)
        assert tier == "TIER_1_SELF"

    def test_tier_2_crs_for_medium_changes(self):
        """TIER_2_STANDARD for 50-500 lines."""
        files = [{"path": "src/core.py", "added": 100, "deleted": 50, "total_changed": 150}]
        tier, reason = validate_review.determine_review_tier(files)
        assert tier == "TIER_2_STANDARD"

    def test_tier_3_full_for_large_changes(self):
        """TIER_3_CRITICAL for >500 lines (5-tier system)."""
        files = [{"path": "src/core.py", "added": 400, "deleted": 200, "total_changed": 600}]
        tier, reason = validate_review.determine_review_tier(files)
        assert tier == "TIER_3_CRITICAL"

    def test_tier_0_exempt_for_architecture_markdown(self):
        """TIER_0_EXEMPT for architecture markdown (all .md exempt)."""
        files = [
            {"path": "docs/architecture/system.md", "added": 10, "deleted": 5, "total_changed": 15}
        ]
        tier, reason = validate_review.determine_review_tier(files)
        assert tier == "TIER_0_EXEMPT"
        assert "exempt" in reason.lower()

    def test_oct_md_files_are_not_exempt(self):
        """GOVERNANCE: .oct.md files must NOT be exempt from review tier calculation.

        .oct.md files are governance code (cognition definitions, agent definitions,
        skills, patterns) and must be subject to review requirements per I3
        (Dual-Layer Authority). The markdown exemption must not apply to them.
        Under the 5-tier system, 15 lines falls into T2 (10-500 range).
        """
        files = [
            {
                "path": ".hestai-sys/library/cognitions/logos.oct.md",
                "added": 10,
                "deleted": 5,
                "total_changed": 15,
            }
        ]
        tier, reason = validate_review.determine_review_tier(files)
        assert tier != "TIER_0_EXEMPT", f".oct.md files must NOT be exempt, got {tier}"

    def test_oct_md_agent_files_are_not_exempt(self):
        """GOVERNANCE: Agent definition .oct.md files must NOT be exempt."""
        files = [
            {
                "path": "src/hestai_mcp/_bundled_hub/library/agents/implementation-lead.oct.md",
                "added": 30,
                "deleted": 10,
                "total_changed": 40,
            }
        ]
        tier, reason = validate_review.determine_review_tier(files)
        assert tier != "TIER_0_EXEMPT", f"Agent .oct.md files must NOT be exempt, got {tier}"

    def test_regular_md_files_remain_exempt(self):
        """Regular .md files (README, CLAUDE, docs) must still be exempt."""
        files = [
            {"path": "README.md", "added": 5, "deleted": 2, "total_changed": 7},
            {"path": "CLAUDE.md", "added": 3, "deleted": 1, "total_changed": 4},
            {"path": "docs/ARCHITECTURE.md", "added": 10, "deleted": 5, "total_changed": 15},
        ]
        tier, reason = validate_review.determine_review_tier(files)
        assert (
            tier == "TIER_0_EXEMPT"
        ), "Regular .md files must remain exempt from review tier calculation"

    def test_mixed_oct_md_and_regular_md_only_oct_md_counts(self):
        """When .oct.md and regular .md are mixed, only .oct.md should count."""
        files = [
            {"path": "README.md", "added": 50, "deleted": 20, "total_changed": 70},
            {
                "path": ".hestai-sys/library/cognitions/logos.oct.md",
                "added": 10,
                "deleted": 5,
                "total_changed": 15,
            },
        ]
        tier, reason = validate_review.determine_review_tier(files)
        assert (
            tier != "TIER_0_EXEMPT"
        ), ".oct.md changes must prevent TIER_0_EXEMPT even when mixed with regular .md"


@pytest.mark.behavior
class TestPRCommentValidation:
    """Validate PR comment checking logic."""

    def test_tier_1_requires_self_review_comment(self, ci_environment, monkeypatch):
        """TIER_1_SELF requires 'IL SELF-REVIEWED:' or 'HO REVIEWED:' comment."""

        # Mock gh CLI to return comments without self-review
        def mock_run(cmd, *args, **kwargs):
            return MagicMock(
                stdout=json.dumps({"body": "", "comments": [{"body": "Some other comment"}]}),
                returncode=0,
                check=lambda: None,
            )

        monkeypatch.setattr(subprocess, "run", mock_run)

        approved, message, _ = validate_review.check_pr_comments("TIER_1_SELF")
        assert approved is False
        assert "SELF-REVIEWED" in message or "HO REVIEWED" in message

    def test_tier_2_requires_tmg_crs_and_ce_approval(self, ci_environment, monkeypatch):
        """TIER_2_STANDARD requires TMG + CRS + CE approval (5-tier system)."""

        # Mock gh CLI to return comments with TMG, CRS and CE approval
        def mock_run(cmd, *args, **kwargs):
            return MagicMock(
                stdout=json.dumps(
                    {
                        "body": "",
                        "comments": [
                            {"body": "TMG APPROVED: tests cover critical paths"},
                            {"body": "CRS APPROVED: Logic correct, tests pass"},
                            {"body": "CE APPROVED: Architecture sound"},
                        ],
                    }
                ),
                returncode=0,
                check=lambda: None,
            )

        monkeypatch.setattr(subprocess, "run", mock_run)

        approved, message, _ = validate_review.check_pr_comments("TIER_2_STANDARD")
        assert approved is True
        assert "TMG" in message and "CRS" in message and "CE" in message

    def test_tier_2_missing_ce_fails(self, ci_environment, monkeypatch):
        """TIER_2_STANDARD with only CRS approval (no CE) should fail."""

        def mock_run(cmd, *args, **kwargs):
            return MagicMock(
                stdout=json.dumps(
                    {"body": "", "comments": [{"body": "CRS APPROVED: Logic correct, tests pass"}]}
                ),
                returncode=0,
                check=lambda: None,
            )

        monkeypatch.setattr(subprocess, "run", mock_run)

        approved, message, _ = validate_review.check_pr_comments("TIER_2_STANDARD")
        assert approved is False
        assert "CE APPROVED" in message or "CE GO" in message

    def test_tier_3_requires_tmg_crs_ce_civ(self, ci_environment, monkeypatch):
        """TIER_3_CRITICAL requires TMG + CRS + CE + CIV (5-tier system)."""

        # Mock gh CLI to return comments with only CRS approval (missing TMG, CE, CIV)
        def mock_run(cmd, *args, **kwargs):
            return MagicMock(
                stdout=json.dumps(
                    {
                        "body": "",
                        "comments": [
                            {"body": "CRS APPROVED: Logic correct"},
                        ],
                    }
                ),
                returncode=0,
                check=lambda: None,
            )

        monkeypatch.setattr(subprocess, "run", mock_run)

        approved, message, _ = validate_review.check_pr_comments("TIER_3_CRITICAL")
        assert approved is False
        assert "TMG" in message or "CE" in message or "CIV" in message


# ---------------------------------------------------------------------------
# Requirement 7: template self-match guard.
# ---------------------------------------------------------------------------
# The gate's OWN "Review requirements not met" status comment embeds the
# literal guidance template "CE APPROVED: [assessment] (or CE GO:)" (and the
# TMG/CRS/CIV equivalents) inside a fenced code block -- see
# review-gate.yml around the `${role} APPROVED: [assessment] (or ${role} GO:)`
# line, mirroring the text validate_review.py itself prints at
# "   - '{role} APPROVED: [assessment]' (or {role} GO:)" (~line 1370).
#
# matches_approval_pattern() matches per-LINE (review_formats.py, `for line in
# cleaned.splitlines()`), so line-anchoring alone does NOT protect this
# template text from re-triggering four phantom approvals: the template line
# "CE APPROVED: [assessment] (or CE GO:)" starts with a valid role prefix at
# line-start, followed by the APPROVED keyword with no negation/hedge token in
# the gap -- pattern-wise it WOULD match, proven below.
#
# The real protection is TWO independent lines of defense in
# check_pr_comments()'s _is_bot_comment() filter (validate_review.py
# ~lines 840-900):
#   1. bot-author exclusion: the status comment is always posted by a
#      [bot]-suffixed account (github-actions[bot] via GITHUB_TOKEN), and
#      _is_bot_comment() excludes any `login.endswith("[bot]")`.
#   2. a LEGACY MARKER check, independent of author: any comment body
#      containing the literal string "<!-- review-gate-status -->" is also
#      excluded, regardless of who posted it.
# Both are proven independently below so a single point of failure (e.g. the
# bot-author check alone) is not silently assumed to be the whole story.
@pytest.mark.security
class TestTemplateSelfMatchGuard:
    """The gate's own status-comment template must never self-clear the gate."""

    # Reconstructed from review-gate.yml's guidance block: one line per
    # required role, exactly the shape validate_review.py prints and the
    # workflow embeds in its "Required" fenced code block.
    _TEMPLATE_BODY = (
        "## Review Gate Status: ❌\n\n"
        "**Review requirements not met**\n\n"
        "**Required**: CE + CIV + CRS + TMG approval:\n"
        "```\n"
        "CE APPROVED: [assessment] (or CE GO:)\n"
        "CIV APPROVED: [assessment] (or CIV GO:)\n"
        "CRS APPROVED: [assessment] (or CRS GO:)\n"
        "TMG APPROVED: [assessment] (or TMG GO:)\n"
        "```\n"
    )

    def test_template_text_matches_pattern_in_isolation(self):
        """Format-wise, the template lines DO satisfy the approval regex.

        Proves line-anchoring alone is NOT the protection: matches_approval_
        pattern() matches per-line, and the template's own guidance lines are
        indistinguishable, pattern-wise, from a real approval.
        """
        from hestai_context_mcp.tools.shared.review_formats import matches_approval_pattern

        for role in ("CE", "CIV", "CRS", "TMG"):
            assert matches_approval_pattern(self._TEMPLATE_BODY, role, "APPROVED") is True

    def test_bot_authored_template_comment_does_not_clear_gate(self, ci_environment, monkeypatch):
        """Defense 1: a [bot]-suffixed author's template comment is excluded."""

        def mock_run(cmd, *args, **kwargs):
            return MagicMock(
                stdout=json.dumps(
                    {
                        "body": "",
                        "comments": [
                            {
                                "body": self._TEMPLATE_BODY,
                                "author": {"login": "github-actions[bot]"},
                            }
                        ],
                    }
                ),
                returncode=0,
                check=lambda: None,
            )

        monkeypatch.setattr(subprocess, "run", mock_run)

        approved, _message, missing = validate_review.check_pr_comments(
            required_roles={"CE", "CIV", "CRS", "TMG"}, tier="TIER_3_CRITICAL"
        )
        assert approved is False
        assert set(missing) == {"CE", "CIV", "CRS", "TMG"}

    def test_marker_tagged_template_comment_does_not_clear_gate_even_from_non_bot_author(
        self, ci_environment, monkeypatch
    ):
        """Defense 2 (independent of author): the legacy marker string alone
        is sufficient to exclude a comment, even if the author is NOT flagged
        as a bot (e.g. a spoofed/renamed account, or an author whose login
        doesn't match the `[bot]` convention).
        """

        def mock_run(cmd, *args, **kwargs):
            return MagicMock(
                stdout=json.dumps(
                    {
                        "body": "",
                        "comments": [
                            {
                                "body": "<!-- review-gate-status -->\n" + self._TEMPLATE_BODY,
                                "author": {"login": "definitely-not-a-bot-account"},
                            }
                        ],
                    }
                ),
                returncode=0,
                check=lambda: None,
            )

        monkeypatch.setattr(subprocess, "run", mock_run)

        approved, _message, missing = validate_review.check_pr_comments(
            required_roles={"CE", "CIV", "CRS", "TMG"}, tier="TIER_3_CRITICAL"
        )
        assert approved is False
        assert set(missing) == {"CE", "CIV", "CRS", "TMG"}

    def test_removing_both_defenses_would_self_clear(self, ci_environment, monkeypatch):
        """Control case: WITHOUT bot-author or marker exclusion, the same
        template text posted by a non-bot author with no marker DOES clear
        the gate -- demonstrating these two checks are load-bearing, not
        incidental. If this test ever fails, _is_bot_comment() has grown a
        third, different exclusion path and this pin needs updating.
        """

        def mock_run(cmd, *args, **kwargs):
            return MagicMock(
                stdout=json.dumps(
                    {
                        "body": "",
                        "comments": [
                            {
                                "body": self._TEMPLATE_BODY,
                                "author": {"login": "a-regular-human-reviewer"},
                            }
                        ],
                    }
                ),
                returncode=0,
                check=lambda: None,
            )

        monkeypatch.setattr(subprocess, "run", mock_run)

        approved, _message, _missing = validate_review.check_pr_comments(
            required_roles={"CE", "CIV", "CRS", "TMG"}, tier="TIER_3_CRITICAL"
        )
        # Not gated by bot-exclusion or marker -- the template text alone
        # satisfies the regex for all four roles.
        assert approved is True


@pytest.mark.behavior
class TestPRBodyScanning:
    """Validate that PR body is scanned for approval patterns in addition to comments."""

    def test_tmg_crs_and_ce_approval_in_pr_body_is_accepted(self, ci_environment, monkeypatch):
        """Approval patterns in PR body should satisfy the review gate (5-tier)."""

        def mock_run(cmd, *args, **kwargs):
            return MagicMock(
                stdout=json.dumps(
                    {
                        "body": "## Review Summary\nTMG APPROVED: tests verified\nCRS APPROVED: Logic correct, tests pass\nCE APPROVED: Architecture sound",
                        "comments": [],
                    }
                ),
                returncode=0,
                check=lambda: None,
            )

        monkeypatch.setattr(subprocess, "run", mock_run)

        approved, message, _ = validate_review.check_pr_comments("TIER_2_STANDARD")
        assert approved is True, "TMG, CRS and CE approval in PR body should be accepted"

    def test_self_review_in_pr_body_is_accepted(self, ci_environment, monkeypatch):
        """Self-review pattern in PR body should satisfy TIER_1_SELF."""

        def mock_run(cmd, *args, **kwargs):
            return MagicMock(
                stdout=json.dumps(
                    {
                        "body": "IL SELF-REVIEWED: Small config change",
                        "comments": [],
                    }
                ),
                returncode=0,
                check=lambda: None,
            )

        monkeypatch.setattr(subprocess, "run", mock_run)

        approved, message, _ = validate_review.check_pr_comments("TIER_1_SELF")
        assert approved is True, "Self-review in PR body should be accepted"
        assert "Self-review found" in message

    def test_tier_3_approvals_split_between_body_and_comments(self, ci_environment, monkeypatch):
        """TIER_3_CRITICAL: TMG+CRS+CE+CIV split between body and comments should pass."""

        def mock_run(cmd, *args, **kwargs):
            return MagicMock(
                stdout=json.dumps(
                    {
                        "body": "TMG APPROVED: tests verified\nCRS APPROVED: Logic verified",
                        "comments": [
                            {"body": "CE APPROVED: Performance acceptable"},
                            {"body": "CIV APPROVED: Implementation matches spec"},
                        ],
                    }
                ),
                returncode=0,
                check=lambda: None,
            )

        monkeypatch.setattr(subprocess, "run", mock_run)

        approved, message, _ = validate_review.check_pr_comments("TIER_3_CRITICAL")
        assert approved is True, "Approvals split between body and comments should pass"

    def test_gh_cli_fetches_body_and_comments(self, ci_environment, monkeypatch):
        """The gh CLI call should request 'body', 'comments', and 'reviews' fields."""
        captured_cmds = []

        def mock_run(cmd, *args, **kwargs):
            captured_cmds.append(cmd)
            return MagicMock(
                stdout=json.dumps(
                    {
                        "body": "",
                        "comments": [
                            {"body": "CRS APPROVED: ok"},
                            {"body": "CE APPROVED: ok"},
                        ],
                        "reviews": [],
                    }
                ),
                returncode=0,
                check=lambda: None,
            )

        monkeypatch.setattr(subprocess, "run", mock_run)

        validate_review.check_pr_comments("TIER_2_STANDARD")

        # Verify gh pr view fetches body, comments, and reviews
        assert len(captured_cmds) > 0
        gh_cmd = captured_cmds[0]
        json_arg = next((a for a in gh_cmd if "comments" in a and "body" in a), None)
        assert json_arg is not None, f"gh CLI should fetch comments and body, got: {gh_cmd}"
        assert "reviews" in json_arg, f"gh CLI should also fetch reviews, got: {gh_cmd}"

    def test_empty_pr_body_still_checks_comments(self, ci_environment, monkeypatch):
        """Empty or null PR body should not break comment checking."""

        def mock_run(cmd, *args, **kwargs):
            return MagicMock(
                stdout=json.dumps(
                    {
                        "body": None,
                        "comments": [
                            {"body": "TMG APPROVED: tests verified"},
                            {"body": "CRS APPROVED: Looks good"},
                            {"body": "CE APPROVED: Architecture sound"},
                        ],
                    }
                ),
                returncode=0,
                check=lambda: None,
            )

        monkeypatch.setattr(subprocess, "run", mock_run)

        approved, message, _ = validate_review.check_pr_comments("TIER_2_STANDARD")
        assert approved is True, "Null PR body should not block comment-based approval"


@pytest.mark.behavior
class TestHOSupervisoryReview:
    """Validate that HO REVIEWED is accepted as an alternative T1 approval.

    When HO delegates to IL and then reviews the work, it's a supervisory
    review (higher authority than self-review) and should satisfy T1.
    """

    def test_tier_1_ho_reviewed_passes(self, ci_environment, monkeypatch):
        """'HO REVIEWED: delegated to IL, verified output' should pass T1."""

        def mock_run(cmd, *args, **kwargs):
            return MagicMock(
                stdout=json.dumps(
                    {
                        "body": "",
                        "comments": [{"body": "HO REVIEWED: delegated to IL, verified output"}],
                    }
                ),
                returncode=0,
                check=lambda: None,
            )

        monkeypatch.setattr(subprocess, "run", mock_run)

        approved, message, _ = validate_review.check_pr_comments("TIER_1_SELF")
        assert approved is True, "'HO REVIEWED' should satisfy T1"
        assert "HO supervisory review found" in message

    def test_tier_1_ho_reviewed_with_model_format(self, ci_environment, monkeypatch):
        """'HO (Claude): REVIEWED: verified' should also pass T1."""

        def mock_run(cmd, *args, **kwargs):
            return MagicMock(
                stdout=json.dumps(
                    {
                        "body": "",
                        "comments": [{"body": "HO (Claude): REVIEWED: verified"}],
                    }
                ),
                returncode=0,
                check=lambda: None,
            )

        monkeypatch.setattr(subprocess, "run", mock_run)

        approved, message, _ = validate_review.check_pr_comments("TIER_1_SELF")
        assert approved is True, "'HO (Claude): REVIEWED' should satisfy T1"
        assert "HO supervisory review found" in message

    def test_tier_1_il_self_reviewed_still_passes(self, ci_environment, monkeypatch):
        """Existing IL SELF-REVIEWED must still pass T1 after HO REVIEWED addition."""

        def mock_run(cmd, *args, **kwargs):
            return MagicMock(
                stdout=json.dumps(
                    {
                        "body": "",
                        "comments": [{"body": "IL SELF-REVIEWED: Fixed typo in error message"}],
                    }
                ),
                returncode=0,
                check=lambda: None,
            )

        monkeypatch.setattr(subprocess, "run", mock_run)

        approved, message, _ = validate_review.check_pr_comments("TIER_1_SELF")
        assert approved is True, "IL SELF-REVIEWED must still pass T1"
        assert "Self-review found" in message

    def test_tier_1_ho_reviewed_in_pr_body(self, ci_environment, monkeypatch):
        """HO REVIEWED in PR body should also satisfy T1."""

        def mock_run(cmd, *args, **kwargs):
            return MagicMock(
                stdout=json.dumps(
                    {
                        "body": "HO REVIEWED: delegated implementation verified",
                        "comments": [],
                    }
                ),
                returncode=0,
                check=lambda: None,
            )

        monkeypatch.setattr(subprocess, "run", mock_run)

        approved, message, _ = validate_review.check_pr_comments("TIER_1_SELF")
        assert approved is True, "HO REVIEWED in PR body should satisfy T1"

    def test_tier_1_crs_still_satisfies_after_ho_addition(self, ci_environment, monkeypatch):
        """CRS approval should still satisfy T1 (hierarchy rule preserved)."""

        def mock_run(cmd, *args, **kwargs):
            return MagicMock(
                stdout=json.dumps(
                    {
                        "body": "",
                        "comments": [{"body": "CRS APPROVED: Logic correct, tests pass"}],
                    }
                ),
                returncode=0,
                check=lambda: None,
            )

        monkeypatch.setattr(subprocess, "run", mock_run)

        approved, message, _ = validate_review.check_pr_comments("TIER_1_SELF")
        assert approved is True, "CRS approval should still satisfy T1"
        assert "CRS approval satisfies" in message


@pytest.mark.behavior
class TestFlexiblePatternMatching:
    """Validate flexible approval pattern matching beyond exact string match."""

    def test_crs_parenthetical_model_format(self, ci_environment, monkeypatch):
        """'CRS (Gemini): APPROVED' format should be recognized at TIER_2."""

        def mock_run(cmd, *args, **kwargs):
            return MagicMock(
                stdout=json.dumps(
                    {
                        "body": "TMG APPROVED: tests verified\nCRS (Gemini): APPROVED - Logic correct, tests pass",
                        "comments": [{"body": "CE APPROVED: Architecture sound"}],
                    }
                ),
                returncode=0,
                check=lambda: None,
            )

        monkeypatch.setattr(subprocess, "run", mock_run)

        approved, message, _ = validate_review.check_pr_comments("TIER_2_STANDARD")
        assert approved is True, "'CRS (Gemini): APPROVED' + TMG + CE should be recognized"

    def test_ce_parenthetical_model_format(self, ci_environment, monkeypatch):
        """'CE (Claude): APPROVED' format should be recognized at TIER_3_CRITICAL."""

        def mock_run(cmd, *args, **kwargs):
            return MagicMock(
                stdout=json.dumps(
                    {
                        "body": "",
                        "comments": [
                            {"body": "TMG APPROVED: tests verified"},
                            {"body": "CRS APPROVED: Logic ok"},
                            {"body": "CE (Claude): APPROVED - Architecture sound"},
                            {"body": "CIV APPROVED: Implementation matches spec"},
                        ],
                    }
                ),
                returncode=0,
                check=lambda: None,
            )

        monkeypatch.setattr(subprocess, "run", mock_run)

        approved, message, _ = validate_review.check_pr_comments("TIER_3_CRITICAL")
        assert approved is True, "'CE (Claude): APPROVED' with TMG+CRS+CIV should be recognized"

    def test_crs_with_extra_whitespace(self, ci_environment, monkeypatch):
        """Patterns with varied whitespace should still match."""

        def mock_run(cmd, *args, **kwargs):
            return MagicMock(
                stdout=json.dumps(
                    {
                        "body": "TMG APPROVED: ok\nCRS  APPROVED: Logic correct",
                        "comments": [{"body": "CE APPROVED: Sound"}],
                    }
                ),
                returncode=0,
                check=lambda: None,
            )

        monkeypatch.setattr(subprocess, "run", mock_run)

        approved, message, _ = validate_review.check_pr_comments("TIER_2_STANDARD")
        assert approved is True, "CRS APPROVED with extra whitespace should match"

    def test_il_parenthetical_model_format(self, ci_environment, monkeypatch):
        """'IL (Claude): SELF-REVIEWED' format should be recognized."""

        def mock_run(cmd, *args, **kwargs):
            return MagicMock(
                stdout=json.dumps(
                    {
                        "body": "IL (Claude): SELF-REVIEWED: Quick fix",
                        "comments": [],
                    }
                ),
                returncode=0,
                check=lambda: None,
            )

        monkeypatch.setattr(subprocess, "run", mock_run)

        approved, message, _ = validate_review.check_pr_comments("TIER_1_SELF")
        assert approved is True, "'IL (Claude): SELF-REVIEWED' should be recognized"

    def test_original_exact_format_still_works(self, ci_environment, monkeypatch):
        """Original exact format 'CRS APPROVED:' must continue to work at TIER_2."""

        def mock_run(cmd, *args, **kwargs):
            return MagicMock(
                stdout=json.dumps(
                    {
                        "body": "",
                        "comments": [
                            {"body": "TMG APPROVED: tests verified"},
                            {"body": "CRS APPROVED: Logic correct, tests pass"},
                            {"body": "CE APPROVED: Architecture sound"},
                        ],
                    }
                ),
                returncode=0,
                check=lambda: None,
            )

        monkeypatch.setattr(subprocess, "run", mock_run)

        approved, message, _ = validate_review.check_pr_comments("TIER_2_STANDARD")
        assert approved is True, "Original exact format must continue to work"


@pytest.mark.behavior
class TestSubstringFalsePositivePrevention:
    """Regression tests for CRS MEDIUM finding: keyword substring false positive.

    The keyword 'APPROVED' could match as a substring of longer words like
    'APPROVEDLY' or 'APPROVEDISH'. The approval regex must use word boundaries
    after the keyword to prevent such false positives. Note: prefix substrings
    like 'DISAPPROVED' are already prevented by the regex structure (the prefix
    must be followed by whitespace then the keyword), but suffix substrings
    require an explicit word boundary.
    """

    def test_approved_suffix_word_does_not_match(self):
        """REGRESSION: 'CRS APPROVEDLY' must NOT match as 'CRS APPROVED'."""
        result = validate_review._matches_approval_pattern(
            "CRS APPROVEDLY noted", "CRS", "APPROVED"
        )
        assert (
            result is False
        ), "APPROVEDLY must not match as APPROVED - suffix substring false positive"

    def test_approved_suffix_compound_does_not_match(self):
        """REGRESSION: 'CRS APPROVEDISH' must NOT match as approval."""
        result = validate_review._matches_approval_pattern(
            "CRS APPROVEDISH maybe", "CRS", "APPROVED"
        )
        assert (
            result is False
        ), "APPROVEDISH must not match as APPROVED - suffix substring false positive"

    def test_disapproved_does_not_match_as_approval(self):
        """REGRESSION: 'CRS DISAPPROVED' must NOT match as 'CRS APPROVED'."""
        result = validate_review._matches_approval_pattern(
            "CRS DISAPPROVED: This change has issues", "CRS", "APPROVED"
        )
        assert result is False, "DISAPPROVED must not match as APPROVED"

    def test_disapproved_with_parenthetical_does_not_match(self):
        """REGRESSION: 'CRS (Gemini): DISAPPROVED' must NOT match as approval."""
        result = validate_review._matches_approval_pattern(
            "CRS (Gemini): DISAPPROVED - Rejected", "CRS", "APPROVED"
        )
        assert result is False, "Parenthetical DISAPPROVED must not match as APPROVED"

    def test_approved_still_matches_after_fix(self):
        """Sanity check: 'CRS APPROVED' must still match after word boundary fix."""
        result = validate_review._matches_approval_pattern(
            "CRS APPROVED: Logic correct", "CRS", "APPROVED"
        )
        assert result is True, "APPROVED must still match after word boundary fix"

    def test_approved_with_colon_suffix_still_matches(self):
        """Sanity check: 'APPROVED:' (with colon) must still match with word boundary."""
        result = validate_review._matches_approval_pattern(
            "CRS APPROVED: tests pass", "CRS", "APPROVED"
        )
        assert result is True, "APPROVED followed by colon must still match"

    def test_approved_at_end_of_line_still_matches(self):
        """Sanity check: 'CRS APPROVED' at end of string must still match."""
        result = validate_review._matches_approval_pattern("CRS APPROVED", "CRS", "APPROVED")
        assert result is True, "APPROVED at end of string must still match"

    def test_ce_disapproved_does_not_match(self):
        """REGRESSION: 'CE DISAPPROVED' must NOT match as 'CE APPROVED'."""
        result = validate_review._matches_approval_pattern(
            "CE DISAPPROVED: Architecture concerns", "CE", "APPROVED"
        )
        assert result is False, "CE DISAPPROVED must not match as CE APPROVED"


@pytest.mark.behavior
class TestGoKeywordApproval:
    """Validate that 'GO' is accepted as an approval synonym alongside 'APPROVED'.

    Agents sometimes write 'CRS (Gemini): GO (9/10)' or 'CE (Codex): GO after fix'
    instead of the standard 'APPROVED' keyword. Both must be accepted for CRS and CE
    tiers. TIER_1_SELF (IL SELF-REVIEWED) is NOT affected.
    """

    def test_crs_go_matches_as_crs_approval(self, ci_environment, monkeypatch):
        """'CRS (Gemini): GO' should match as CRS approval at TIER_2."""

        def mock_run(cmd, *args, **kwargs):
            return MagicMock(
                stdout=json.dumps(
                    {
                        "body": "TMG APPROVED: ok\nCRS (Gemini): GO",
                        "comments": [{"body": "CE APPROVED: Sound"}],
                    }
                ),
                returncode=0,
                check=lambda: None,
            )

        monkeypatch.setattr(subprocess, "run", mock_run)

        approved, message, _ = validate_review.check_pr_comments("TIER_2_STANDARD")
        assert approved is True, "'CRS (Gemini): GO' + TMG + CE should be recognized"

    def test_ce_go_after_fix_matches_as_ce_approval(self, ci_environment, monkeypatch):
        """'CE (Codex): GO after fix' should match as CE approval at TIER_3_CRITICAL."""

        def mock_run(cmd, *args, **kwargs):
            return MagicMock(
                stdout=json.dumps(
                    {
                        "body": "",
                        "comments": [
                            {"body": "TMG APPROVED: tests verified"},
                            {"body": "CRS APPROVED: ok"},
                            {"body": "CE (Codex): GO after fix"},
                            {"body": "CIV APPROVED: Implementation matches spec"},
                        ],
                    }
                ),
                returncode=0,
                check=lambda: None,
            )

        monkeypatch.setattr(subprocess, "run", mock_run)

        approved, message, _ = validate_review.check_pr_comments("TIER_3_CRITICAL")
        assert approved is True, "'CE (Codex): GO after fix' with TMG+CRS+CIV should pass"

    def test_crs_go_with_score_matches(self, ci_environment, monkeypatch):
        """'CRS (Gemini): GO (9/10)' should match -- the real-world failing case."""

        def mock_run(cmd, *args, **kwargs):
            return MagicMock(
                stdout=json.dumps(
                    {
                        "body": "TMG APPROVED: ok\nCRS (Gemini): GO (9/10)",
                        "comments": [{"body": "CE APPROVED: Sound"}],
                    }
                ),
                returncode=0,
                check=lambda: None,
            )

        monkeypatch.setattr(subprocess, "run", mock_run)

        approved, message, _ = validate_review.check_pr_comments("TIER_2_STANDARD")
        assert approved is True, "'CRS (Gemini): GO (9/10)' + TMG + CE should pass"

    def test_tier_3_go_plus_ce_approved_passes(self, ci_environment, monkeypatch):
        """TIER_3_CRITICAL with TMG+CRS GO+CE+CIV should pass."""

        def mock_run(cmd, *args, **kwargs):
            return MagicMock(
                stdout=json.dumps(
                    {
                        "body": "",
                        "comments": [
                            {"body": "TMG APPROVED: tests verified"},
                            {"body": "CRS GO: Logic sound"},
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
        assert approved is True, "TMG+CRS GO+CE+CIV should satisfy TIER_3_CRITICAL"

    def test_tier_3_approved_plus_ce_go_passes(self, ci_environment, monkeypatch):
        """TIER_3_CRITICAL with TMG+CRS+CE GO+CIV should pass."""

        def mock_run(cmd, *args, **kwargs):
            return MagicMock(
                stdout=json.dumps(
                    {
                        "body": "",
                        "comments": [
                            {"body": "TMG APPROVED: tests verified"},
                            {"body": "CRS APPROVED: Logic correct"},
                            {"body": "CE (Codex): GO - looks good"},
                            {"body": "CIV APPROVED: Implementation matches spec"},
                        ],
                    }
                ),
                returncode=0,
                check=lambda: None,
            )

        monkeypatch.setattr(subprocess, "run", mock_run)

        approved, message, _ = validate_review.check_pr_comments("TIER_3_CRITICAL")
        assert approved is True, "TMG+CRS+CE GO+CIV should satisfy TIER_3_CRITICAL"

    def test_go_substring_does_not_false_positive(self):
        """'CRS GOING' must NOT match as 'CRS GO' -- word boundary enforcement."""
        result = validate_review._matches_approval_pattern("CRS GOING ahead", "CRS", "GO")
        assert result is False, "GOING must not match as GO - suffix substring false positive"

    def test_tier_3_missing_all_mentions_roles_in_error(self, ci_environment, monkeypatch):
        """Error message for TIER_3_CRITICAL missing approvals should mention required roles."""

        def mock_run(cmd, *args, **kwargs):
            return MagicMock(
                stdout=json.dumps(
                    {
                        "body": "",
                        "comments": [{"body": "Some other comment"}],
                    }
                ),
                returncode=0,
                check=lambda: None,
            )

        monkeypatch.setattr(subprocess, "run", mock_run)

        approved, message, _ = validate_review.check_pr_comments("TIER_3_CRITICAL")
        assert approved is False
        assert "TMG" in message, "Error message should mention TMG"
        assert "CRS" in message, "Error message should mention CRS"
        assert "CE" in message, "Error message should mention CE"
        assert "CIV" in message, "Error message should mention CIV"

    def test_tier_2_missing_mentions_go_in_error(self, ci_environment, monkeypatch):
        """Error message for TIER_2_STANDARD missing approval should mention GO as alternative."""

        def mock_run(cmd, *args, **kwargs):
            return MagicMock(
                stdout=json.dumps(
                    {
                        "body": "",
                        "comments": [{"body": "Some other comment"}],
                    }
                ),
                returncode=0,
                check=lambda: None,
            )

        monkeypatch.setattr(subprocess, "run", mock_run)

        approved, message, _ = validate_review.check_pr_comments("TIER_2_STANDARD")
        assert approved is False
        assert "GO" in message, "Error message should mention GO as an accepted format"


@pytest.mark.behavior
class TestFlexibleSeparatorMatching:
    """Validate that em dash, en dash, hyphen, and colon separators are accepted.

    Real-world approval text uses varied separators between the prefix/parenthetical
    and the keyword. For example:
      - 'CRS (Gemini) \u2014 APPROVED (98/100)' (em dash U+2014)
      - 'CE (Codex) \u2014 APPROVED (GO)' (em dash)
      - 'CRS (Gemini) \u2013 APPROVED' (en dash U+2013)
      - 'CRS (Gemini) - APPROVED' (hyphen)
      - 'CRS \u2014 APPROVED' (em dash, no parenthetical)
      - 'CRS: APPROVED' (colon, no parenthetical)

    The regex must handle any mix of whitespace, colons, and dashes as separators.
    """

    # --- Em dash separator (the actual failing case from issue #213) ---

    def test_crs_em_dash_with_parenthetical_approved(self):
        """'CRS (Gemini) \u2014 APPROVED (98/100)' must match -- the real-world failing case."""
        result = validate_review._matches_approval_pattern(
            "CRS (Gemini) \u2014 APPROVED (98/100)", "CRS", "APPROVED"
        )
        assert result is True, "Em dash separator with parenthetical must match"

    def test_ce_em_dash_with_parenthetical_approved_go(self):
        """'CE (Codex) \u2014 APPROVED (GO)' must match for APPROVED keyword."""
        result = validate_review._matches_approval_pattern(
            "CE (Codex) \u2014 APPROVED (GO)", "CE", "APPROVED"
        )
        assert result is True, "Em dash separator CE with parenthetical must match"

    def test_crs_em_dash_no_parenthetical(self):
        """'CRS \u2014 APPROVED' must match (no model annotation, em dash separator)."""
        result = validate_review._matches_approval_pattern("CRS \u2014 APPROVED", "CRS", "APPROVED")
        assert result is True, "Em dash separator without parenthetical must match"

    def test_crs_em_dash_go_keyword(self):
        """'CRS (Gemini) \u2014 GO (9/10)' must match for GO keyword."""
        result = validate_review._matches_approval_pattern(
            "CRS (Gemini) \u2014 GO (9/10)", "CRS", "GO"
        )
        assert result is True, "Em dash separator with GO keyword must match"

    # --- En dash separator (defensive) ---

    def test_crs_en_dash_with_parenthetical(self):
        """'CRS (Gemini) \u2013 APPROVED' must match (en dash separator)."""
        result = validate_review._matches_approval_pattern(
            "CRS (Gemini) \u2013 APPROVED", "CRS", "APPROVED"
        )
        assert result is True, "En dash separator with parenthetical must match"

    def test_crs_en_dash_no_parenthetical(self):
        """'CRS \u2013 APPROVED' must match (en dash, no parenthetical)."""
        result = validate_review._matches_approval_pattern("CRS \u2013 APPROVED", "CRS", "APPROVED")
        assert result is True, "En dash separator without parenthetical must match"

    # --- Hyphen separator (defensive) ---

    def test_crs_hyphen_with_parenthetical(self):
        """'CRS (Gemini) - APPROVED' must match (hyphen separator)."""
        result = validate_review._matches_approval_pattern(
            "CRS (Gemini) - APPROVED", "CRS", "APPROVED"
        )
        assert result is True, "Hyphen separator with parenthetical must match"

    def test_crs_hyphen_no_parenthetical(self):
        """'CRS - APPROVED' must match (hyphen, no parenthetical)."""
        result = validate_review._matches_approval_pattern("CRS - APPROVED", "CRS", "APPROVED")
        assert result is True, "Hyphen separator without parenthetical must match"

    # --- Colon separator without parenthetical ---

    def test_crs_colon_no_parenthetical(self):
        """'CRS: APPROVED' must match (colon separator, no parenthetical)."""
        result = validate_review._matches_approval_pattern("CRS: APPROVED", "CRS", "APPROVED")
        assert result is True, "Colon separator without parenthetical must match"

    # --- IL / SELF-REVIEWED with dash separators ---

    def test_il_em_dash_self_reviewed(self):
        """'IL (Claude) \u2014 SELF-REVIEWED' must match."""
        result = validate_review._matches_approval_pattern(
            "IL (Claude) \u2014 SELF-REVIEWED: quick fix", "IL", "SELF-REVIEWED"
        )
        assert result is True, "IL with em dash separator must match SELF-REVIEWED"

    # --- Negative cases: separators must not cause false positives ---

    def test_approved_suffix_with_em_dash_does_not_false_positive(self):
        """'CRS (Gemini) \u2014 APPROVEDLY' must NOT match (word boundary still enforced)."""
        result = validate_review._matches_approval_pattern(
            "CRS (Gemini) \u2014 APPROVEDLY noted", "CRS", "APPROVED"
        )
        assert result is False, "Word boundary must still prevent suffix false positives"

    def test_going_with_em_dash_does_not_false_positive(self):
        """'CRS \u2014 GOING' must NOT match as GO."""
        result = validate_review._matches_approval_pattern("CRS \u2014 GOING ahead", "CRS", "GO")
        assert result is False, "Word boundary must still prevent GOING matching as GO"


@pytest.mark.security
class TestCRSModelApprovalSpoofing:
    """Regression tests for CE review finding: approval-spoofing bypass.

    has_crs_model_approval() must not allow:
    1. Single-line dual-model spoof: one APPROVED keyword satisfying two model checks
    2. BLOCKED-then-APPROVED on same line: intervening BLOCKED before APPROVED
    """

    def test_single_line_dual_model_spoof_does_not_satisfy_both(self):
        """SECURITY: 'CRS (Gemini) and CRS (Codex) APPROVED' must NOT satisfy both models.

        A single APPROVED keyword at the end of a line must not count as approval
        for both CRS (Gemini) and CRS (Codex) when both appear earlier on that line.
        """
        texts = ["CRS (Gemini) and CRS (Codex) APPROVED"]
        gemini_approved = validate_review._has_crs_model_approval(texts, "Gemini")
        codex_approved = validate_review._has_crs_model_approval(texts, "Codex")
        assert not (
            gemini_approved and codex_approved
        ), "Single APPROVED must not satisfy both CRS (Gemini) and CRS (Codex)"

    def test_blocked_then_approved_on_same_line_does_not_pass(self):
        """SECURITY: 'CRS (Gemini) BLOCKED but later APPROVED' must NOT pass.

        If BLOCKED appears between the model tag and APPROVED, the function must
        not treat this as an approval. Only direct CRS(model) -> APPROVED with
        separator-only tokens in between should count.
        """
        texts = ["CRS (Gemini) BLOCKED but later APPROVED"]
        result = validate_review._has_crs_model_approval(texts, "Gemini")
        assert result is False, "BLOCKED-then-APPROVED must not count as model approval"

    def test_legitimate_separate_line_approvals_still_work(self):
        """Sanity: Separate per-model approval lines must still pass."""
        texts = [
            "CRS (Gemini) APPROVED: Logic correct",
            "CRS (Codex) APPROVED: Verified",
        ]
        assert validate_review._has_crs_model_approval(
            texts, "Gemini"
        ), "Separate Gemini approval line must pass"
        assert validate_review._has_crs_model_approval(
            texts, "Codex"
        ), "Separate Codex approval line must pass"

    def test_model_approval_with_separator_still_works(self):
        """Sanity: 'CRS (Gemini): APPROVED' with colon separator must still pass."""
        texts = ["CRS (Gemini): APPROVED - Logic verified"]
        assert validate_review._has_crs_model_approval(
            texts, "Gemini"
        ), "Colon-separated model approval must pass"

    def test_model_approval_with_go_keyword_still_works(self):
        """Sanity: 'CRS (Gemini) GO' must still pass."""
        texts = ["CRS (Gemini) GO (9/10)"]
        assert validate_review._has_crs_model_approval(
            texts, "Gemini"
        ), "GO keyword model approval must pass"

    def test_model_approval_with_dash_separator_still_works(self):
        """Sanity: 'CRS (Gemini) - APPROVED' with dash separator must still pass."""
        texts = ["CRS (Gemini) - APPROVED: Architecture sound"]
        assert validate_review._has_crs_model_approval(
            texts, "Gemini"
        ), "Dash-separated model approval must pass"

    def test_model_approval_with_em_dash_still_works(self):
        """Sanity: 'CRS (Gemini) \u2014 APPROVED' with em dash must still pass."""
        texts = ["CRS (Gemini) \u2014 APPROVED (98/100)"]
        assert validate_review._has_crs_model_approval(
            texts, "Gemini"
        ), "Em dash-separated model approval must pass"

    def test_model_approval_with_double_dash_still_works(self):
        """Sanity: 'CRS (Gemini) -- APPROVED' with double dash must still pass."""
        texts = ["CRS (Gemini) -- APPROVED: Logic verified"]
        assert validate_review._has_crs_model_approval(
            texts, "Gemini"
        ), "Double-dash-separated model approval must pass"


@pytest.mark.security
class TestCrossValidationUnrecognizedRoles:
    """Regression tests for cross-validation false positive on unrecognized roles.

    When a comment contains review metadata with a role not in VALID_ROLES
    (e.g., "code-review-specialist"), cross-validation should skip it because
    unrecognized roles cannot satisfy any gate check. Cross-validating them
    causes a false positive "spoofing detected" failure that blocks the PR.

    Security invariant: recognized roles (CRS, CE, IL, HO) with mismatched
    metadata MUST still fail cross-validation (spoofing detection preserved).
    """

    def test_unrecognized_role_in_metadata_does_not_trigger_cross_validation(
        self, ci_environment, monkeypatch
    ):
        """Unrecognized role (e.g., code-review-specialist) must NOT cause false positive.

        When metadata has role='code-review-specialist' and verdict='APPROVED',
        the cross-validation should skip it because 'code-review-specialist' is
        not in VALID_ROLES. Previously this caused a hard fail: "possible spoofing detected."
        """

        def mock_run(cmd, *args, **kwargs):
            return MagicMock(
                stdout=json.dumps(
                    {
                        "body": "",
                        "comments": [
                            {
                                "body": (
                                    "code-review-specialist APPROVED: looks good\n"
                                    '<!-- review: {"role": "code-review-specialist", '
                                    '"verdict": "APPROVED", "provider": "gemini"} -->'
                                )
                            },
                            {"body": "TMG APPROVED: tests verified"},
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
        assert approved is True, (
            "Unrecognized role in metadata must not cause cross-validation failure. "
            f"Got: {message}"
        )

    def test_unrecognized_role_without_visible_match_does_not_fail(
        self, ci_environment, monkeypatch
    ):
        """Unrecognized role with no visible text match must NOT fail.

        This is the exact failure scenario: metadata says role='code-review-specialist'
        verdict='APPROVED', but visible text does NOT contain
        'code-review-specialist APPROVED:' pattern. Previously this caused the
        cross-validation to fail with "possible spoofing detected."
        """

        def mock_run(cmd, *args, **kwargs):
            return MagicMock(
                stdout=json.dumps(
                    {
                        "body": "",
                        "comments": [
                            {
                                "body": (
                                    "## Review Assessment\n\nAll checks pass.\n"
                                    '<!-- review: {"role": "code-review-specialist", '
                                    '"verdict": "APPROVED", "provider": "gemini"} -->'
                                )
                            },
                            {"body": "TMG APPROVED: tests verified"},
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
        assert approved is True, (
            "Unrecognized role without visible text match must not trigger spoofing detection. "
            f"Got: {message}"
        )

    def test_recognized_role_with_mismatched_metadata_still_fails(
        self, ci_environment, monkeypatch
    ):
        """SECURITY: Recognized role (CRS) with mismatched visible text MUST still fail.

        If metadata says role='CRS' verdict='APPROVED' but visible text shows
        'CRS BLOCKED:', this mismatch must be detected as potential spoofing.
        This test ensures the security behavior is preserved for recognized roles.
        """

        def mock_run(cmd, *args, **kwargs):
            return MagicMock(
                stdout=json.dumps(
                    {
                        "body": "",
                        "comments": [
                            {
                                "body": (
                                    "CRS BLOCKED: Major issues found\n"
                                    '<!-- review: {"role": "CRS", '
                                    '"verdict": "APPROVED", "provider": "gemini"} -->'
                                )
                            },
                        ],
                    }
                ),
                returncode=0,
                check=lambda: None,
            )

        monkeypatch.setattr(subprocess, "run", mock_run)

        approved, message, _ = validate_review.check_pr_comments("TIER_2_STANDARD")
        assert approved is False, (
            "Recognized role with mismatched metadata must fail cross-validation "
            "(spoofing detection). "
            f"Got: {message}"
        )
        assert (
            "spoofing" in message.lower() or "cross-validation" in message.lower()
        ), f"Error message should mention spoofing or cross-validation. Got: {message}"


@pytest.mark.behavior
class TestImportlibFallbackDiagnostic:
    """Validate that the importlib fallback produces clear diagnostics on failure.

    These tests exercise the ACTUAL production code in validate_review.py by
    running it as a subprocess with manipulated paths, ensuring that if the
    FileNotFoundError handling is removed from production code, these tests fail.
    """

    def test_missing_review_formats_raises_file_not_found_error(self, tmp_path):
        """importlib fallback must raise FileNotFoundError with path info when file missing.

        The fallback path uses importlib.util.spec_from_file_location to load
        review_formats.py. When the file doesn't exist, the error message must
        include the expected file path for diagnostic clarity.

        This test exercises the ACTUAL production code by running validate_review.py
        in a subprocess where the normal import fails (via -S to skip site-packages)
        and the fallback path computes a _module_path that doesn't exist.
        """
        # Create a fake scripts/ directory with a copy of validate_review.py
        # but NO src/hestai_mcp/modules/tools/shared/review_formats.py
        fake_scripts = tmp_path / "scripts"
        fake_scripts.mkdir()

        # Copy the real validate_review.py
        real_script = Path(__file__).parent.parent / "scripts" / "validate_review.py"
        (fake_scripts / "validate_review.py").write_text(real_script.read_text())

        # Run with -S (no site-packages) so hestai_mcp is NOT importable,
        # forcing the except ImportError fallback path in validate_review.py.
        # The fallback will compute _module_path relative to the script location,
        # but since there's no src/ tree in tmp_path, the path won't exist.
        result = subprocess.run(
            [
                sys.executable,
                "-S",
                "-c",
                "import sys; " f"sys.path.insert(0, '{fake_scripts}'); " "import validate_review",
            ],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
        )

        # The import should fail with FileNotFoundError since
        # review_formats.py doesn't exist at the computed fallback path
        assert result.returncode != 0, (
            f"Expected non-zero exit (FileNotFoundError), got 0.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert (
            "FileNotFoundError" in result.stderr
        ), f"Expected FileNotFoundError in stderr.\nstderr: {result.stderr}"
        assert "review_formats.py not found" in result.stderr, (
            f"Error message must include 'review_formats.py not found'.\n"
            f"stderr: {result.stderr}"
        )

    def test_missing_review_formats_error_includes_path(self, tmp_path):
        """FileNotFoundError message must include the expected file path.

        Exercises the production code's importlib fallback to verify the
        diagnostic message contains the computed path for troubleshooting.
        """
        fake_scripts = tmp_path / "scripts"
        fake_scripts.mkdir()

        real_script = Path(__file__).parent.parent / "scripts" / "validate_review.py"
        (fake_scripts / "validate_review.py").write_text(real_script.read_text())

        result = subprocess.run(
            [
                sys.executable,
                "-S",
                "-c",
                "import sys; " f"sys.path.insert(0, '{fake_scripts}'); " "import validate_review",
            ],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
        )

        # Verify the error message includes path information for diagnostics
        assert (
            "Expected relative to scripts/ directory" in result.stderr
        ), f"Error must include diagnostic path hint.\nstderr: {result.stderr}"


@pytest.mark.behavior
class TestCallerTemplateAlignment:
    """Validate that the caller template YAML has aligned bot-exclusion filters.

    The caller template (.github/workflows/review-gate-caller.yml.template) must
    include the same bot-exclusion and keyword filters as the main workflow
    (review-gate.yml) to prevent bot noise from triggering unnecessary workflow_call
    invocations in consuming repos.
    """

    @pytest.fixture
    def template_content(self):
        """Load the caller template YAML content."""
        template_path = (
            Path(__file__).parent.parent
            / ".github"
            / "workflows"
            / "review-gate-caller.yml.template"
        )
        assert template_path.exists(), f"Caller template not found at {template_path}"
        return template_path.read_text()

    def test_template_is_valid_yaml(self, template_content):
        """Caller template must be valid YAML."""
        import yaml

        # Should not raise an exception
        parsed = yaml.safe_load(template_content)
        assert parsed is not None
        assert "jobs" in parsed

    def test_template_has_bot_exclusion_filter(self, template_content):
        """Caller template must exclude bot comments (user.type != 'Bot')."""
        assert "github.event.comment.user.type != 'Bot'" in template_content, (
            "Caller template must include bot-exclusion filter "
            "(github.event.comment.user.type != 'Bot') to prevent bot noise "
            "from triggering workflow_call invocations"
        )

    def test_template_has_keyword_filters(self, template_content):
        """Caller template must filter issue_comment events by review keywords."""
        # These keywords match what review-gate.yml uses
        assert (
            "APPROVED" in template_content
        ), "Caller template must filter comments containing 'APPROVED'"
        assert (
            "REVIEWED" in template_content
        ), "Caller template must filter comments containing 'REVIEWED'"
        assert "GO" in template_content, "Caller template must filter comments containing 'GO'"

    def test_template_preserves_pr_event_pass_through(self, template_content):
        """Caller template must still pass through pull_request events unconditionally."""
        assert (
            "github.event_name == 'pull_request'" in template_content
        ), "Caller template must pass through pull_request events"


@pytest.mark.behavior
class TestStructuredJsonOutput:
    """Validate that main() emits a structured JSON summary as an HTML comment.

    The JSON line is formatted as:
      <!-- REVIEW_GATE_JSON:{"tier":"T2","reason":"...","reviewers":["TMG"],...} -->

    This enables the JS parser in review-gate.yml to consume structured data
    instead of relying solely on fragile regex patterns against human-readable output.
    """

    def test_main_emits_json_comment_for_tier_2(self, ci_environment, monkeypatch, capsys):
        """main() must emit a REVIEW_GATE_JSON HTML comment for TIER_2_STANDARD."""
        monkeypatch.setattr(validate_review, "check_emergency_bypass", lambda: False)
        monkeypatch.setattr(
            validate_review,
            "get_changed_files",
            lambda: [{"path": "src/core.py", "added": 50, "deleted": 20, "total_changed": 70}],
        )
        monkeypatch.setattr(
            validate_review,
            "check_pr_comments",
            lambda *args, **kwargs: (True, "All approvals found (CE, CRS, TMG)", []),
        )

        validate_review.main()
        output = capsys.readouterr().out

        # Must contain the JSON comment marker
        assert (
            "<!-- REVIEW_GATE_JSON:" in output
        ), "main() must emit structured JSON as HTML comment"

        # Extract and parse the JSON
        import re

        json_match = re.search(r"<!-- REVIEW_GATE_JSON:(.*?) -->", output)
        assert json_match is not None, "JSON comment must be parseable"

        data = json.loads(json_match.group(1))
        assert "tier" in data
        assert "status" in data
        assert data["status"] == "pass"
        assert data["tier"] == "TIER_2_STANDARD"

    def test_main_emits_json_comment_for_failed_review(self, ci_environment, monkeypatch, capsys):
        """main() must emit JSON comment with status=fail when reviews missing."""
        monkeypatch.setattr(validate_review, "check_emergency_bypass", lambda: False)
        monkeypatch.setattr(
            validate_review,
            "get_changed_files",
            lambda: [{"path": "src/core.py", "added": 50, "deleted": 20, "total_changed": 70}],
        )
        monkeypatch.setattr(
            validate_review,
            "check_pr_comments",
            lambda *args, **kwargs: (False, "Missing CE APPROVED", ["CE"]),
        )

        validate_review.main()
        output = capsys.readouterr().out

        import re

        json_match = re.search(r"<!-- REVIEW_GATE_JSON:(.*?) -->", output)
        assert json_match is not None, "JSON comment must be emitted even on failure"

        data = json.loads(json_match.group(1))
        assert data["status"] == "fail"

    def test_json_comment_includes_reviewers_list(self, ci_environment, monkeypatch, capsys):
        """JSON output must include the reviewers list from classify_pr_facets."""
        monkeypatch.setattr(validate_review, "check_emergency_bypass", lambda: False)
        monkeypatch.setattr(
            validate_review,
            "get_changed_files",
            lambda: [
                {
                    "path": "scripts/validate_review.py",
                    "added": 10,
                    "deleted": 5,
                    "total_changed": 15,
                    "status": "M",
                }
            ],
        )
        monkeypatch.setattr(
            validate_review,
            "check_pr_comments",
            lambda *args, **kwargs: (True, "All approvals found", []),
        )

        validate_review.main()
        output = capsys.readouterr().out

        import re

        json_match = re.search(r"<!-- REVIEW_GATE_JSON:(.*?) -->", output)
        assert json_match is not None

        data = json.loads(json_match.group(1))
        assert "reviewers" in data
        assert isinstance(data["reviewers"], list)
        # validate_review.py is META_CONTROL_PLANE, which requires CIV, CE, CRS, SR, TMG
        assert len(data["reviewers"]) > 0

    def test_json_comment_includes_required_count(self, ci_environment, monkeypatch, capsys):
        """JSON output must include required_count and found_count."""
        monkeypatch.setattr(validate_review, "check_emergency_bypass", lambda: False)
        monkeypatch.setattr(
            validate_review,
            "get_changed_files",
            lambda: [{"path": "src/core.py", "added": 50, "deleted": 20, "total_changed": 70}],
        )
        monkeypatch.setattr(
            validate_review,
            "check_pr_comments",
            lambda *args, **kwargs: (True, "All approvals found (CE, CRS, TMG)", []),
        )

        validate_review.main()
        output = capsys.readouterr().out

        import re

        json_match = re.search(r"<!-- REVIEW_GATE_JSON:(.*?) -->", output)
        assert json_match is not None

        data = json.loads(json_match.group(1))
        assert "required_count" in data
        assert "found_count" in data
        assert isinstance(data["required_count"], int)
        assert isinstance(data["found_count"], int)

    def test_json_comment_not_emitted_for_exempt_tier(self, monkeypatch, capsys):
        """TIER_0_EXEMPT should still emit JSON with tier and status info."""
        monkeypatch.delenv("CI", raising=False)
        monkeypatch.setattr(validate_review, "check_emergency_bypass", lambda: False)
        monkeypatch.setattr(
            validate_review,
            "get_changed_files",
            lambda: [{"path": "README.md", "added": 5, "deleted": 2, "total_changed": 7}],
        )

        validate_review.main()
        output = capsys.readouterr().out

        import re

        json_match = re.search(r"<!-- REVIEW_GATE_JSON:(.*?) -->", output)
        assert json_match is not None, "JSON comment must be emitted even for exempt tier"

        data = json.loads(json_match.group(1))
        assert data["tier"] == "TIER_0_EXEMPT"
        assert data["status"] == "pass"

    def test_found_count_reflects_partial_approvals_on_failure(
        self, ci_environment, monkeypatch, capsys
    ):
        """found_count must reflect actual approvals found, not hardcoded 0 on failure.

        When 2 of 3 required roles have approved but one is missing, the JSON
        output should report found_count=2, not found_count=0. This is critical
        for downstream consumers that need accurate progress information.
        """
        monkeypatch.setattr(validate_review, "check_emergency_bypass", lambda: False)
        # ROUTINE_CODE file -> requires CE, CRS, TMG (3 roles)
        monkeypatch.setattr(
            validate_review,
            "get_changed_files",
            lambda: [{"path": "src/core.py", "added": 50, "deleted": 20, "total_changed": 70}],
        )
        # Simulate 2 of 3 approvals present: TMG approved, CRS approved, CE missing
        monkeypatch.setattr(
            validate_review,
            "check_pr_comments",
            lambda *args, **kwargs: (
                False,
                "\u274c Missing: CE APPROVED or CE GO",
                ["CE"],
            ),
        )

        validate_review.main()
        output = capsys.readouterr().out

        import re

        json_match = re.search(r"<!-- REVIEW_GATE_JSON:(.*?) -->", output)
        assert json_match is not None, "JSON comment must be emitted on failure path"

        data = json.loads(json_match.group(1))
        assert data["status"] == "fail"
        assert (
            data["required_count"] == 3
        ), f"Expected 3 required roles, got {data['required_count']}"
        # The key assertion: found_count must NOT be hardcoded 0
        assert data["found_count"] == 2, (
            f"Expected found_count=2 (2 of 3 roles approved), got {data['found_count']}. "
            "found_count must reflect actual approvals found, not hardcoded 0."
        )

    def test_found_count_is_zero_when_no_approvals_found(self, ci_environment, monkeypatch, capsys):
        """found_count=0 is correct when genuinely no approvals are found."""
        monkeypatch.setattr(validate_review, "check_emergency_bypass", lambda: False)
        monkeypatch.setattr(
            validate_review,
            "get_changed_files",
            lambda: [{"path": "src/core.py", "added": 50, "deleted": 20, "total_changed": 70}],
        )
        # All 3 roles missing
        monkeypatch.setattr(
            validate_review,
            "check_pr_comments",
            lambda *args, **kwargs: (
                False,
                "\u274c Missing: CE APPROVED or CE GO, CRS APPROVED or CRS GO, TMG APPROVED or TMG GO",
                ["CE", "CRS", "TMG"],
            ),
        )

        validate_review.main()
        output = capsys.readouterr().out

        import re

        json_match = re.search(r"<!-- REVIEW_GATE_JSON:(.*?) -->", output)
        assert json_match is not None

        data = json.loads(json_match.group(1))
        assert (
            data["found_count"] == 0
        ), f"Expected found_count=0 (no approvals found), got {data['found_count']}"

    def test_found_count_equals_required_count_on_pass(self, ci_environment, monkeypatch, capsys):
        """found_count must equal required_count on the pass path."""
        monkeypatch.setattr(validate_review, "check_emergency_bypass", lambda: False)
        monkeypatch.setattr(
            validate_review,
            "get_changed_files",
            lambda: [{"path": "src/core.py", "added": 50, "deleted": 20, "total_changed": 70}],
        )
        monkeypatch.setattr(
            validate_review,
            "check_pr_comments",
            lambda *args, **kwargs: (True, "All approvals found (CE, CRS, TMG)", []),
        )

        validate_review.main()
        output = capsys.readouterr().out

        import re

        json_match = re.search(r"<!-- REVIEW_GATE_JSON:(.*?) -->", output)
        assert json_match is not None

        data = json.loads(json_match.group(1))
        assert data["status"] == "pass"
        assert data["found_count"] == data["required_count"], (
            f"On pass path, found_count ({data['found_count']}) must equal "
            f"required_count ({data['required_count']})"
        )

    def test_json_comment_reason_field_matches_output(self, ci_environment, monkeypatch, capsys):
        """JSON reason field must match the human-readable reason string."""
        monkeypatch.setattr(validate_review, "check_emergency_bypass", lambda: False)
        monkeypatch.setattr(
            validate_review,
            "get_changed_files",
            lambda: [{"path": "src/core.py", "added": 50, "deleted": 20, "total_changed": 70}],
        )
        monkeypatch.setattr(
            validate_review,
            "check_pr_comments",
            lambda *args, **kwargs: (True, "All approvals found", []),
        )

        validate_review.main()
        output = capsys.readouterr().out

        import re

        json_match = re.search(r"<!-- REVIEW_GATE_JSON:(.*?) -->", output)
        assert json_match is not None

        data = json.loads(json_match.group(1))
        assert "reason" in data
        assert isinstance(data["reason"], str)
        assert len(data["reason"]) > 0


@pytest.mark.behavior
class TestStructuredMissingRoles:
    """check_pr_comments must return structured missing roles, not just a message string.

    CE BLOCKED finding: found_count was computed by string-scraping the human-readable
    error message from check_pr_comments(). This is brittle because if the message format
    changes, found_count silently breaks. The fix: check_pr_comments returns a third
    element — the list of missing role names — so callers use structured data.
    """

    def test_check_pr_comments_returns_missing_roles_list(self, ci_environment, monkeypatch):
        """check_pr_comments must return (bool, str, list[str]) with missing roles."""
        monkeypatch.setenv("PR_NUMBER", "999")

        def mock_run(*args, **kwargs):
            mock = MagicMock()
            mock.stdout = json.dumps(
                {
                    "body": "",
                    "comments": [],
                }
            )
            return mock

        monkeypatch.setattr(subprocess, "run", mock_run)

        result = validate_review.check_pr_comments(
            required_roles={"CE", "CRS", "TMG"}, tier="TIER_2_STANDARD"
        )

        # Must return a 3-tuple
        assert (
            len(result) == 3
        ), f"check_pr_comments must return (bool, str, list[str]), got {len(result)}-tuple"
        approved, message, missing_roles = result
        assert approved is False
        assert isinstance(missing_roles, list)
        # All 3 roles should be missing (no approvals in comments)
        assert set(missing_roles) == {
            "CE",
            "CRS",
            "TMG",
        }, f"Expected missing_roles={{'CE', 'CRS', 'TMG'}}, got {set(missing_roles)}"

    def test_check_pr_comments_handles_null_author(self, ci_environment, monkeypatch):
        """A comment/review with author=null (ghost/deleted user) must not crash the gate.

        Regression: ``comment.get("author", {})`` returns None when the key exists
        with a null value, so ``.get("login")`` raised AttributeError and failed the
        gate on otherwise-valid PR data.
        """
        monkeypatch.setenv("PR_NUMBER", "999")

        def mock_run(*args, **kwargs):
            mock = MagicMock()
            mock.stdout = json.dumps(
                {
                    "body": "",
                    "comments": [
                        {"author": None, "body": "just some prose from a ghost user"},
                        {"author": {"login": "reviewer1"}, "body": "CE APPROVED: real"},
                    ],
                    "reviews": [
                        {"author": None, "state": "COMMENTED", "body": "ghost review"},
                    ],
                }
            )
            return mock

        monkeypatch.setattr(subprocess, "run", mock_run)

        # Must not raise AttributeError on null author; real reviewer satisfies CE.
        approved, _message, missing_roles = validate_review.check_pr_comments(
            required_roles={"CE"}, tier="TIER_2_STANDARD"
        )
        assert approved is True
        assert missing_roles == []

    def test_check_pr_comments_returns_empty_missing_on_success(self, ci_environment, monkeypatch):
        """When all approvals found, missing_roles must be an empty list."""
        monkeypatch.setenv("PR_NUMBER", "999")

        def mock_run(*args, **kwargs):
            mock = MagicMock()
            mock.stdout = json.dumps(
                {
                    "body": "",
                    "comments": [
                        {
                            "author": {"login": "reviewer1"},
                            "body": "CE APPROVED: looks good",
                        },
                        {
                            "author": {"login": "reviewer2"},
                            "body": "CRS APPROVED: standards met",
                        },
                        {
                            "author": {"login": "reviewer3"},
                            "body": "TMG APPROVED: tests verified",
                        },
                    ],
                }
            )
            return mock

        monkeypatch.setattr(subprocess, "run", mock_run)

        result = validate_review.check_pr_comments(
            required_roles={"CE", "CRS", "TMG"}, tier="TIER_2_STANDARD"
        )

        assert (
            len(result) == 3
        ), f"check_pr_comments must return (bool, str, list[str]), got {len(result)}-tuple"
        approved, message, missing_roles = result
        assert approved is True
        assert missing_roles == [], f"Expected empty missing_roles on success, got {missing_roles}"

    def test_check_pr_comments_partial_approvals_structured(self, ci_environment, monkeypatch):
        """With partial approvals, missing_roles lists only the actually missing ones."""
        monkeypatch.setenv("PR_NUMBER", "999")

        def mock_run(*args, **kwargs):
            mock = MagicMock()
            mock.stdout = json.dumps(
                {
                    "body": "",
                    "comments": [
                        {
                            "author": {"login": "reviewer1"},
                            "body": "CRS APPROVED: standards met",
                        },
                        {
                            "author": {"login": "reviewer2"},
                            "body": "TMG APPROVED: tests verified",
                        },
                    ],
                }
            )
            return mock

        monkeypatch.setattr(subprocess, "run", mock_run)

        result = validate_review.check_pr_comments(
            required_roles={"CE", "CRS", "TMG"}, tier="TIER_2_STANDARD"
        )

        assert len(result) == 3
        approved, message, missing_roles = result
        assert approved is False
        assert missing_roles == ["CE"], f"Expected only CE missing, got {missing_roles}"

    def test_found_count_uses_structured_data_not_string_scraping(
        self, ci_environment, monkeypatch, capsys
    ):
        """main() must compute found_count from structured missing_roles, not string scraping.

        This is the core CE BLOCKED finding: the old code scraped the human-readable
        error message to count missing roles. The new code must use the structured
        missing_roles list returned by check_pr_comments.
        """
        monkeypatch.setattr(validate_review, "check_emergency_bypass", lambda: False)
        monkeypatch.setattr(
            validate_review,
            "get_changed_files",
            lambda: [{"path": "src/core.py", "added": 50, "deleted": 20, "total_changed": 70}],
        )
        # Mock returns structured data: CE is missing, CRS and TMG approved
        monkeypatch.setattr(
            validate_review,
            "check_pr_comments",
            lambda *args, **kwargs: (
                False,
                "\u274c Missing: CE APPROVED or CE GO",
                ["CE"],
            ),
        )

        validate_review.main()
        output = capsys.readouterr().out

        import re

        json_match = re.search(r"<!-- REVIEW_GATE_JSON:(.*?) -->", output)
        assert json_match is not None

        data = json.loads(json_match.group(1))
        assert data["required_count"] == 3
        assert data["found_count"] == 2, (
            f"found_count must be computed from structured missing_roles (3 required - 1 missing = 2), "
            f"got {data['found_count']}"
        )


@pytest.mark.behavior
class TestShaTrackingInJsonSummary:
    """Validate that JSON summary includes SHA for approval-commit validation.

    The SHA field enables downstream consumers (review-gate.yml JS parser) to:
    1. Track which commit the review gate evaluated
    2. Validate that approvals were made against the correct commit
    3. Detect stale approvals when new commits are pushed after approval
    """

    def test_json_summary_includes_sha_field(self, ci_environment, monkeypatch, capsys):
        """JSON output must include a 'sha' field with the current HEAD commit SHA."""
        monkeypatch.setattr(validate_review, "check_emergency_bypass", lambda: False)
        monkeypatch.setattr(
            validate_review,
            "get_changed_files",
            lambda: [{"path": "src/core.py", "added": 50, "deleted": 20, "total_changed": 70}],
        )
        monkeypatch.setattr(
            validate_review,
            "check_pr_comments",
            lambda *args, **kwargs: (True, "All approvals found (CE, CRS, TMG)", []),
        )
        original_run = subprocess.run

        def mock_run(cmd, *args, **kwargs):
            if isinstance(cmd, list) and "rev-parse" in cmd and "HEAD" in cmd:
                return MagicMock(stdout="abc123def456\n", returncode=0)
            return original_run(cmd, *args, **kwargs)

        monkeypatch.setattr(subprocess, "run", mock_run)

        validate_review.main()
        output = capsys.readouterr().out

        json_match = re.search(r"<!-- REVIEW_GATE_JSON:(.*?) -->", output)
        assert json_match is not None, "JSON comment must be emitted"

        data = json.loads(json_match.group(1))
        assert "sha" in data, "JSON output must include 'sha' field for commit tracking"
        assert (
            data["sha"] == "abc123def456"
        ), f"SHA must match HEAD commit, expected 'abc123def456', got '{data['sha']}'"

    def test_json_summary_sha_is_string(self, ci_environment, monkeypatch, capsys):
        """SHA field must be a non-empty string."""
        monkeypatch.setattr(validate_review, "check_emergency_bypass", lambda: False)
        monkeypatch.setattr(
            validate_review,
            "get_changed_files",
            lambda: [{"path": "src/core.py", "added": 50, "deleted": 20, "total_changed": 70}],
        )
        monkeypatch.setattr(
            validate_review,
            "check_pr_comments",
            lambda *args, **kwargs: (True, "All approvals found (CE, CRS, TMG)", []),
        )
        original_run = subprocess.run

        def mock_run(cmd, *args, **kwargs):
            if isinstance(cmd, list) and "rev-parse" in cmd and "HEAD" in cmd:
                return MagicMock(stdout="deadbeef1234\n", returncode=0)
            return original_run(cmd, *args, **kwargs)

        monkeypatch.setattr(subprocess, "run", mock_run)

        validate_review.main()
        output = capsys.readouterr().out

        json_match = re.search(r"<!-- REVIEW_GATE_JSON:(.*?) -->", output)
        assert json_match is not None

        data = json.loads(json_match.group(1))
        assert isinstance(data["sha"], str), "SHA must be a string"
        assert len(data["sha"]) > 0, "SHA must not be empty"

    def test_json_summary_sha_on_failure_path(self, ci_environment, monkeypatch, capsys):
        """SHA must be included in JSON output even when review fails."""
        monkeypatch.setattr(validate_review, "check_emergency_bypass", lambda: False)
        monkeypatch.setattr(
            validate_review,
            "get_changed_files",
            lambda: [{"path": "src/core.py", "added": 50, "deleted": 20, "total_changed": 70}],
        )
        monkeypatch.setattr(
            validate_review,
            "check_pr_comments",
            lambda *args, **kwargs: (False, "Missing CE APPROVED", ["CE"]),
        )
        original_run = subprocess.run

        def mock_run(cmd, *args, **kwargs):
            if isinstance(cmd, list) and "rev-parse" in cmd and "HEAD" in cmd:
                return MagicMock(stdout="sha_on_fail_path\n", returncode=0)
            return original_run(cmd, *args, **kwargs)

        monkeypatch.setattr(subprocess, "run", mock_run)

        validate_review.main()
        output = capsys.readouterr().out

        json_match = re.search(r"<!-- REVIEW_GATE_JSON:(.*?) -->", output)
        assert json_match is not None, "JSON comment must be emitted even on failure"

        data = json.loads(json_match.group(1))
        assert "sha" in data, "SHA must be present even when review fails"
        assert data["sha"] == "sha_on_fail_path"

    def test_json_summary_sha_on_exempt_path(self, monkeypatch, capsys):
        """SHA must be included in JSON output even for TIER_0_EXEMPT."""
        monkeypatch.delenv("CI", raising=False)
        monkeypatch.setattr(validate_review, "check_emergency_bypass", lambda: False)
        monkeypatch.setattr(
            validate_review,
            "get_changed_files",
            lambda: [{"path": "README.md", "added": 5, "deleted": 2, "total_changed": 7}],
        )
        original_run = subprocess.run

        def mock_run(cmd, *args, **kwargs):
            if isinstance(cmd, list) and "rev-parse" in cmd and "HEAD" in cmd:
                return MagicMock(stdout="sha_exempt_path\n", returncode=0)
            return original_run(cmd, *args, **kwargs)

        monkeypatch.setattr(subprocess, "run", mock_run)

        validate_review.main()
        output = capsys.readouterr().out

        json_match = re.search(r"<!-- REVIEW_GATE_JSON:(.*?) -->", output)
        assert json_match is not None

        data = json.loads(json_match.group(1))
        assert "sha" in data, "SHA must be present even for TIER_0_EXEMPT"

    def test_json_summary_sha_fallback_on_git_failure(self, ci_environment, monkeypatch, capsys):
        """If git rev-parse fails, SHA should be 'unknown' rather than crashing."""
        monkeypatch.setattr(validate_review, "check_emergency_bypass", lambda: False)
        monkeypatch.setattr(
            validate_review,
            "get_changed_files",
            lambda: [{"path": "src/core.py", "added": 50, "deleted": 20, "total_changed": 70}],
        )
        monkeypatch.setattr(
            validate_review,
            "check_pr_comments",
            lambda *args, **kwargs: (True, "All approvals found (CE, CRS, TMG)", []),
        )
        original_run = subprocess.run

        def mock_run(cmd, *args, **kwargs):
            if isinstance(cmd, list) and "rev-parse" in cmd and "HEAD" in cmd:
                raise subprocess.CalledProcessError(1, "git rev-parse HEAD")
            return original_run(cmd, *args, **kwargs)

        monkeypatch.setattr(subprocess, "run", mock_run)

        validate_review.main()
        output = capsys.readouterr().out

        json_match = re.search(r"<!-- REVIEW_GATE_JSON:(.*?) -->", output)
        assert json_match is not None

        data = json.loads(json_match.group(1))
        assert (
            data["sha"] == "unknown"
        ), f"SHA must fall back to 'unknown' on git failure, got '{data['sha']}'"


@pytest.mark.behavior
class TestCommentEventFastPath:
    """Validate that CACHED_GATE_DATA enables comment-event fast path.

    On issue_comment events, the diff hasn't changed — only approvals may have.
    When CACHED_GATE_DATA is set with matching SHA, validate_review.py should
    skip file classification and use cached tier/reviewers, then only re-check
    comment approvals.
    """

    def test_cached_gate_data_skips_file_classification(self, ci_environment, monkeypatch, capsys):
        """When CACHED_GATE_DATA is set, get_changed_files must NOT be called."""
        monkeypatch.setattr(validate_review, "check_emergency_bypass", lambda: False)
        cached = json.dumps(
            {
                "tier": "TIER_2_STANDARD",
                "reason": "Cached reason",
                "roles": ["CE", "CRS", "TMG"],
                "sha": "abc123",
                "base_sha": "base_abc",
            }
        )
        monkeypatch.setenv("CACHED_GATE_DATA", cached)
        monkeypatch.setenv("PR_BASE_REF", "main")

        def explode():
            raise AssertionError("get_changed_files must not be called with cached gate data")

        monkeypatch.setattr(validate_review, "get_changed_files", explode)
        monkeypatch.setattr(
            validate_review,
            "check_pr_comments",
            lambda *args, **kwargs: (True, "All approvals found (CE, CRS, TMG)", []),
        )
        original_run = subprocess.run

        def mock_run(cmd, *args, **kwargs):
            if isinstance(cmd, list) and "rev-parse" in cmd and "HEAD" in cmd:
                return MagicMock(stdout="abc123\n", returncode=0)
            if isinstance(cmd, list) and "rev-parse" in cmd and "HEAD" not in cmd:
                return MagicMock(stdout="base_abc\n", returncode=0)
            return original_run(cmd, *args, **kwargs)

        monkeypatch.setattr(subprocess, "run", mock_run)

        exit_code = validate_review.main()
        assert exit_code == 0

        output = capsys.readouterr().out
        assert "fast path" in output.lower(), "Output must indicate fast path was used"

    def test_cached_gate_data_uses_cached_tier(self, ci_environment, monkeypatch, capsys):
        """When cached, tier from CACHED_GATE_DATA must be used in JSON output."""
        monkeypatch.setattr(validate_review, "check_emergency_bypass", lambda: False)
        cached = json.dumps(
            {
                "tier": "TIER_3_CRITICAL",
                "reason": "Cached: META_CONTROL_PLANE",
                "roles": ["CE", "CRS", "CIV", "SR", "TMG"],
                "sha": "def456",
                "base_sha": "base_def",
            }
        )
        monkeypatch.setenv("CACHED_GATE_DATA", cached)
        monkeypatch.setenv("PR_BASE_REF", "main")

        monkeypatch.setattr(
            validate_review,
            "check_pr_comments",
            lambda *args, **kwargs: (True, "All approvals found", []),
        )
        original_run = subprocess.run

        def mock_run(cmd, *args, **kwargs):
            if isinstance(cmd, list) and "rev-parse" in cmd and "HEAD" in cmd:
                return MagicMock(stdout="def456\n", returncode=0)
            if isinstance(cmd, list) and "rev-parse" in cmd and "HEAD" not in cmd:
                return MagicMock(stdout="base_def\n", returncode=0)
            return original_run(cmd, *args, **kwargs)

        monkeypatch.setattr(subprocess, "run", mock_run)

        validate_review.main()
        output = capsys.readouterr().out

        json_match = re.search(r"<!-- REVIEW_GATE_JSON:(.*?) -->", output)
        assert json_match is not None
        data = json.loads(json_match.group(1))
        assert (
            data["tier"] == "TIER_3_CRITICAL"
        ), f"Tier must come from cached data, got {data['tier']}"

    def test_cached_gate_data_passes_roles_to_comment_check(
        self, ci_environment, monkeypatch, capsys
    ):
        """Cached roles must be passed to check_pr_comments as required_roles."""
        monkeypatch.setattr(validate_review, "check_emergency_bypass", lambda: False)
        cached = json.dumps(
            {
                "tier": "TIER_2_STANDARD",
                "reason": "Cached",
                "roles": ["CE", "CRS", "TMG"],
                "sha": "abc",
                "base_sha": "base_abc",
            }
        )
        monkeypatch.setenv("CACHED_GATE_DATA", cached)
        monkeypatch.setenv("PR_BASE_REF", "main")

        captured_kwargs: dict = {}

        def mock_check(*args, **kwargs):
            captured_kwargs.update(kwargs)
            return (True, "All approvals found", [])

        monkeypatch.setattr(validate_review, "check_pr_comments", mock_check)
        original_run = subprocess.run

        def mock_run(cmd, *args, **kwargs):
            if isinstance(cmd, list) and "rev-parse" in cmd and "HEAD" in cmd:
                return MagicMock(stdout="abc\n", returncode=0)
            if isinstance(cmd, list) and "rev-parse" in cmd and "HEAD" not in cmd:
                return MagicMock(stdout="base_abc\n", returncode=0)
            return original_run(cmd, *args, **kwargs)

        monkeypatch.setattr(subprocess, "run", mock_run)

        validate_review.main()

        assert "required_roles" in captured_kwargs, "check_pr_comments must receive required_roles"
        assert captured_kwargs["required_roles"] == {"CE", "CRS", "TMG"}, (
            f"required_roles must match cached roles, " f"got {captured_kwargs['required_roles']}"
        )

    def test_invalid_cached_gate_data_falls_back_to_normal(
        self, ci_environment, monkeypatch, capsys
    ):
        """Invalid CACHED_GATE_DATA JSON must fall back to normal file classification."""
        monkeypatch.setattr(validate_review, "check_emergency_bypass", lambda: False)
        monkeypatch.setenv("CACHED_GATE_DATA", "not-valid-json{{{")

        monkeypatch.setattr(
            validate_review,
            "get_changed_files",
            lambda: [{"path": "src/core.py", "added": 50, "deleted": 20, "total_changed": 70}],
        )
        monkeypatch.setattr(
            validate_review,
            "check_pr_comments",
            lambda *args, **kwargs: (True, "All approvals found (CE, CRS, TMG)", []),
        )
        original_run = subprocess.run

        def mock_run(cmd, *args, **kwargs):
            if isinstance(cmd, list) and "rev-parse" in cmd and "HEAD" in cmd:
                return MagicMock(stdout="sha123\n", returncode=0)
            return original_run(cmd, *args, **kwargs)

        monkeypatch.setattr(subprocess, "run", mock_run)

        exit_code = validate_review.main()
        assert exit_code == 0

        output = capsys.readouterr().out
        assert "fast path" not in output.lower(), "Invalid cached data must not trigger fast path"

    def test_empty_cached_gate_data_uses_normal_path(self, ci_environment, monkeypatch, capsys):
        """Empty CACHED_GATE_DATA string must use normal file classification."""
        monkeypatch.setattr(validate_review, "check_emergency_bypass", lambda: False)
        monkeypatch.setenv("CACHED_GATE_DATA", "")

        monkeypatch.setattr(
            validate_review,
            "get_changed_files",
            lambda: [{"path": "src/core.py", "added": 50, "deleted": 20, "total_changed": 70}],
        )
        monkeypatch.setattr(
            validate_review,
            "check_pr_comments",
            lambda *args, **kwargs: (True, "All approvals found (CE, CRS, TMG)", []),
        )
        original_run = subprocess.run

        def mock_run(cmd, *args, **kwargs):
            if isinstance(cmd, list) and "rev-parse" in cmd and "HEAD" in cmd:
                return MagicMock(stdout="sha456\n", returncode=0)
            return original_run(cmd, *args, **kwargs)

        monkeypatch.setattr(subprocess, "run", mock_run)

        exit_code = validate_review.main()
        assert exit_code == 0

        output = capsys.readouterr().out
        assert "fast path" not in output.lower(), "Empty cached data must not trigger fast path"

    def test_stale_cached_sha_falls_back_to_normal_classification(
        self, ci_environment, monkeypatch, capsys
    ):
        """Stale cached SHA (different from HEAD) must fall back to normal classification.

        Bug fix: The original code unconditionally trusts CACHED_GATE_DATA without
        comparing cached_gate['sha'] against the locally computed head_sha. If the
        env var contains stale data (workflow bug, manual run), incorrect tier/roles
        would be silently applied.
        """
        monkeypatch.setattr(validate_review, "check_emergency_bypass", lambda: False)

        # Cached data has SHA "stale_sha_abc" but HEAD will be "current_sha_xyz"
        cached = json.dumps(
            {
                "tier": "TIER_3_CRITICAL",
                "reason": "Stale cached reason",
                "roles": ["CE", "CRS", "CIV", "SR", "TMG"],
                "sha": "stale_sha_abc",
            }
        )
        monkeypatch.setenv("CACHED_GATE_DATA", cached)

        # get_changed_files MUST be called when SHA mismatches (fallback path)
        get_changed_files_called = False

        def mock_get_changed_files():
            nonlocal get_changed_files_called
            get_changed_files_called = True
            return [{"path": "src/core.py", "added": 10, "deleted": 5, "total_changed": 15}]

        monkeypatch.setattr(validate_review, "get_changed_files", mock_get_changed_files)
        monkeypatch.setattr(
            validate_review,
            "check_pr_comments",
            lambda *args, **kwargs: (True, "All approvals found (CE, CRS, TMG)", []),
        )

        original_run = subprocess.run

        def mock_run(cmd, *args, **kwargs):
            if isinstance(cmd, list) and "rev-parse" in cmd and "HEAD" in cmd:
                return MagicMock(stdout="current_sha_xyz\n", returncode=0)
            return original_run(cmd, *args, **kwargs)

        monkeypatch.setattr(subprocess, "run", mock_run)

        exit_code = validate_review.main()
        assert exit_code == 0

        output = capsys.readouterr().out
        # Must NOT use the fast path when SHA mismatches
        assert (
            "fast path" not in output.lower() or "falling back" in output.lower()
        ), "Stale SHA must not use fast path without fallback indication"
        # Must call get_changed_files for normal classification
        assert (
            get_changed_files_called
        ), "get_changed_files must be called when cached SHA differs from HEAD"

    def test_stale_cached_sha_logs_warning(self, ci_environment, monkeypatch, capsys):
        """Stale cached SHA must produce a visible warning in output."""
        monkeypatch.setattr(validate_review, "check_emergency_bypass", lambda: False)

        cached = json.dumps(
            {
                "tier": "TIER_2_STANDARD",
                "reason": "Stale",
                "roles": ["CE", "CRS", "TMG"],
                "sha": "old_sha_111",
            }
        )
        monkeypatch.setenv("CACHED_GATE_DATA", cached)

        monkeypatch.setattr(
            validate_review,
            "get_changed_files",
            lambda: [{"path": "src/core.py", "added": 10, "deleted": 5, "total_changed": 15}],
        )
        monkeypatch.setattr(
            validate_review,
            "check_pr_comments",
            lambda *args, **kwargs: (True, "All approvals found", []),
        )

        original_run = subprocess.run

        def mock_run(cmd, *args, **kwargs):
            if isinstance(cmd, list) and "rev-parse" in cmd and "HEAD" in cmd:
                return MagicMock(stdout="new_sha_222\n", returncode=0)
            return original_run(cmd, *args, **kwargs)

        monkeypatch.setattr(subprocess, "run", mock_run)

        validate_review.main()
        output = capsys.readouterr().out

        # Must contain a warning about SHA mismatch
        assert (
            "falling back" in output.lower() or "!=" in output
        ), "Output must warn about SHA mismatch and indicate fallback to normal classification"

    def test_stale_base_ref_sha_falls_back_to_normal_classification(
        self, ci_environment, monkeypatch, capsys
    ):
        """Stale base ref SHA must fall back to normal classification.

        When the base branch moves while PR head stays the same, the cached
        tier/roles could be stale because the diff changes with the base.
        The fast path must validate both head SHA AND base branch tip SHA.
        """
        monkeypatch.setattr(validate_review, "check_emergency_bypass", lambda: False)

        # Cached data has matching head SHA but STALE base ref SHA
        cached = json.dumps(
            {
                "tier": "TIER_2_STANDARD",
                "reason": "Cached reason",
                "roles": ["CE", "CRS", "TMG"],
                "sha": "head_sha_match",
                "base_sha": "old_base_ref_aaa",
            }
        )
        monkeypatch.setenv("CACHED_GATE_DATA", cached)
        monkeypatch.setenv("PR_BASE_REF", "main")

        # get_changed_files MUST be called when base ref mismatches
        get_changed_files_called = False

        def mock_get_changed_files():
            nonlocal get_changed_files_called
            get_changed_files_called = True
            return [{"path": "src/core.py", "added": 10, "deleted": 5, "total_changed": 15}]

        monkeypatch.setattr(validate_review, "get_changed_files", mock_get_changed_files)
        monkeypatch.setattr(
            validate_review,
            "check_pr_comments",
            lambda *args, **kwargs: (True, "All approvals found (CE, CRS, TMG)", []),
        )

        original_run = subprocess.run

        def mock_run(cmd, *args, **kwargs):
            if isinstance(cmd, list) and "rev-parse" in cmd and "HEAD" in cmd:
                return MagicMock(stdout="head_sha_match\n", returncode=0)
            if isinstance(cmd, list) and "rev-parse" in cmd and "HEAD" not in cmd:
                return MagicMock(stdout="new_base_ref_bbb\n", returncode=0)
            return original_run(cmd, *args, **kwargs)

        monkeypatch.setattr(subprocess, "run", mock_run)

        exit_code = validate_review.main()
        assert exit_code == 0

        output = capsys.readouterr().out
        # Must NOT use the fast path when base ref mismatches
        assert (
            "fast path" not in output.lower() or "falling back" in output.lower()
        ), "Stale base ref SHA must not use fast path without fallback indication"
        # Must call get_changed_files for normal classification
        assert (
            get_changed_files_called
        ), "get_changed_files must be called when cached base ref SHA differs from current"

    def test_both_sha_and_base_sha_match_uses_fast_path(self, ci_environment, monkeypatch, capsys):
        """When both head SHA and base ref SHA match, fast path must be used."""
        monkeypatch.setattr(validate_review, "check_emergency_bypass", lambda: False)

        cached = json.dumps(
            {
                "tier": "TIER_2_STANDARD",
                "reason": "Cached reason",
                "roles": ["CE", "CRS", "TMG"],
                "sha": "head_sha_match",
                "base_sha": "base_ref_match",
            }
        )
        monkeypatch.setenv("CACHED_GATE_DATA", cached)
        monkeypatch.setenv("PR_BASE_REF", "main")

        def explode():
            raise AssertionError("get_changed_files must not be called with valid cached data")

        monkeypatch.setattr(validate_review, "get_changed_files", explode)
        monkeypatch.setattr(
            validate_review,
            "check_pr_comments",
            lambda *args, **kwargs: (True, "All approvals found (CE, CRS, TMG)", []),
        )

        original_run = subprocess.run

        def mock_run(cmd, *args, **kwargs):
            if isinstance(cmd, list) and "rev-parse" in cmd and "HEAD" in cmd:
                return MagicMock(stdout="head_sha_match\n", returncode=0)
            if isinstance(cmd, list) and "rev-parse" in cmd and "HEAD" not in cmd:
                return MagicMock(stdout="base_ref_match\n", returncode=0)
            return original_run(cmd, *args, **kwargs)

        monkeypatch.setattr(subprocess, "run", mock_run)

        exit_code = validate_review.main()
        assert exit_code == 0

        output = capsys.readouterr().out
        assert "fast path" in output.lower(), "Output must indicate fast path was used"

    def test_missing_base_sha_in_cached_data_falls_back(self, ci_environment, monkeypatch, capsys):
        """Cached data without base_sha (old format) must fall back to normal classification.

        Backward compatibility: old status comments that don't include base_sha
        should be treated as a cache miss to ensure correctness.
        """
        monkeypatch.setattr(validate_review, "check_emergency_bypass", lambda: False)

        # Old format: no base_sha field
        cached = json.dumps(
            {
                "tier": "TIER_2_STANDARD",
                "reason": "Cached reason",
                "roles": ["CE", "CRS", "TMG"],
                "sha": "head_sha_match",
            }
        )
        monkeypatch.setenv("CACHED_GATE_DATA", cached)
        monkeypatch.setenv("PR_BASE_REF", "main")

        get_changed_files_called = False

        def mock_get_changed_files():
            nonlocal get_changed_files_called
            get_changed_files_called = True
            return [{"path": "src/core.py", "added": 10, "deleted": 5, "total_changed": 15}]

        monkeypatch.setattr(validate_review, "get_changed_files", mock_get_changed_files)
        monkeypatch.setattr(
            validate_review,
            "check_pr_comments",
            lambda *args, **kwargs: (True, "All approvals found (CE, CRS, TMG)", []),
        )

        original_run = subprocess.run

        def mock_run(cmd, *args, **kwargs):
            if isinstance(cmd, list) and "rev-parse" in cmd and "HEAD" in cmd:
                return MagicMock(stdout="head_sha_match\n", returncode=0)
            if isinstance(cmd, list) and "rev-parse" in cmd and "HEAD" not in cmd:
                return MagicMock(stdout="some_base_ref\n", returncode=0)
            return original_run(cmd, *args, **kwargs)

        monkeypatch.setattr(subprocess, "run", mock_run)

        exit_code = validate_review.main()
        assert exit_code == 0

        # Must fall back to normal classification when base_sha is missing
        assert (
            get_changed_files_called
        ), "get_changed_files must be called when base_sha is missing from cached data"

    def test_base_ref_git_failure_falls_back_gracefully(self, ci_environment, monkeypatch, capsys):
        """If git rev-parse for base ref fails, must fall back to normal classification."""
        monkeypatch.setattr(validate_review, "check_emergency_bypass", lambda: False)

        cached = json.dumps(
            {
                "tier": "TIER_2_STANDARD",
                "reason": "Cached reason",
                "roles": ["CE", "CRS", "TMG"],
                "sha": "head_sha_match",
                "base_sha": "some_base_ref",
            }
        )
        monkeypatch.setenv("CACHED_GATE_DATA", cached)
        monkeypatch.setenv("PR_BASE_REF", "main")

        get_changed_files_called = False

        def mock_get_changed_files():
            nonlocal get_changed_files_called
            get_changed_files_called = True
            return [{"path": "src/core.py", "added": 10, "deleted": 5, "total_changed": 15}]

        monkeypatch.setattr(validate_review, "get_changed_files", mock_get_changed_files)
        monkeypatch.setattr(
            validate_review,
            "check_pr_comments",
            lambda *args, **kwargs: (True, "All approvals found (CE, CRS, TMG)", []),
        )

        original_run = subprocess.run

        def mock_run(cmd, *args, **kwargs):
            if isinstance(cmd, list) and "rev-parse" in cmd and "HEAD" in cmd:
                return MagicMock(stdout="head_sha_match\n", returncode=0)
            if isinstance(cmd, list) and "rev-parse" in cmd and "HEAD" not in cmd:
                raise subprocess.CalledProcessError(1, cmd)
            return original_run(cmd, *args, **kwargs)

        monkeypatch.setattr(subprocess, "run", mock_run)

        exit_code = validate_review.main()
        assert exit_code == 0

        # Must fall back when git rev-parse for base ref fails
        assert (
            get_changed_files_called
        ), "get_changed_files must be called when git rev-parse for base ref fails"


@pytest.mark.security
class TestSecurityLoadBearingExtensionlessDotfiles:
    """SECURITY: extensionless leading-dot files that gate consumer-repo security
    invariants must classify as SECURITY, not fall through to ROUTINE_CODE.

    elevana-studio#1833: supabase/tests/.pgtap-quarantine and
    supabase/migrations/.drift-exceptions are both leading-dot AND extensionless,
    so no extension-based rule in _classify_file_facet matches them, and the
    ``^tests/.*$`` exempt pattern does not match either (both paths start with
    ``supabase/``, not ``tests/``). Both reach the default fall-through
    (ROUTINE_CODE), so a small quarantine-only PR rewriting quarantine-gate
    enforcement logic was classified TIER_1_SELF with zero required
    reviewers -- verified against main's copy of classify_pr_facets() for
    this exact single-file, 3-line-changed shape -- rather than what the
    SECURITY facet guarantees: CIV present in required_roles and a tier
    floor of TIER_3_CRITICAL. A declared escalation role such as PE can lift
    the tier further, to TIER_4_STRATEGIC, but does not remove CIV or lower
    the floor.
    """

    def test_pgtap_quarantine_classifies_security(self):
        """supabase/tests/.pgtap-quarantine must classify as SECURITY."""
        assert (
            validate_review._classify_file_facet("supabase/tests/.pgtap-quarantine") == "SECURITY"
        )

    def test_drift_exceptions_classifies_security(self):
        """supabase/migrations/.drift-exceptions must classify as SECURITY."""
        assert (
            validate_review._classify_file_facet("supabase/migrations/.drift-exceptions")
            == "SECURITY"
        )

    def test_quarantine_only_pr_yields_civ_and_tier_3_critical(self):
        """A quarantine-only changed-file list must yield SECURITY in facets,
        CIV in required_roles, and tier_label TIER_3_CRITICAL — not the
        ROUTINE_CODE -> TIER_1_SELF misclassification (zero required
        reviewers) that let CIV go absent."""
        files = [
            {
                "path": "supabase/tests/.pgtap-quarantine",
                "added": 3,
                "deleted": 0,
                "total_changed": 3,
                "status": "M",
            }
        ]
        facets, required_roles, tier_label, _reason = validate_review.classify_pr_facets(files)
        assert "SECURITY" in facets
        assert "CIV" in required_roles
        assert tier_label == "TIER_3_CRITICAL"


@pytest.mark.security
class TestSecurityBasenameNotShadowedByExemptPatterns:
    """REWORK (coordinator repro, blocking): the original placement of the
    _SECURITY_BASENAMES check sat AFTER the exempt_patterns block, so the
    pre-existing ``^tests/.*$`` exempt branch returned None for
    ``tests/.pgtap-quarantine`` before the security check ever ran -- a
    hole worse than the bug (full exemption instead of merely wrong tier).
    This is also the non-shadowability regression: what is actually
    guaranteed is that the basename check must precede ``exempt_patterns``,
    and specifically the ``^tests/.*$`` pattern within it -- moving the
    check to AFTER that block reintroduces this exact failure. Intermediate
    positions (e.g. after the bundled-hub ``/library/skills/`` and
    ``/library/patterns/`` branches, still before ``exempt_patterns``) are
    behaviourally equivalent today but are untested here and therefore
    unsupported by this test -- this path (top-level ``tests/``, not
    ``supabase/tests/``) is asserted here explicitly and was NOT covered by
    the original three #1833 tests (none of which used a path matching an
    earlier exempt pattern).
    """

    def test_top_level_tests_prefixed_quarantine_is_not_exempt(self):
        """tests/.pgtap-quarantine must classify SECURITY, not be exempted
        by the earlier ``^tests/.*$`` branch."""
        assert validate_review._classify_file_facet("tests/.pgtap-quarantine") == "SECURITY"

    def test_top_level_tests_prefixed_drift_exceptions_is_not_exempt(self):
        """tests/.drift-exceptions must classify SECURITY, not be exempted
        by the earlier ``^tests/.*$`` branch."""
        assert validate_review._classify_file_facet("tests/.drift-exceptions") == "SECURITY"


@pytest.mark.security
class TestSecurityBasenamesIsFrozen:
    """BLOCKING (small), cubic P2 flagged on the very first review
    (f989e6f) and unaddressed for four rework rounds: _SECURITY_BASENAMES
    was declared as a plain mutable ``set`` literal, while both the PR
    body and prior commit messages in this repo's history called it
    "frozen". This test pins the actual immutability the name/prose
    claims.

    Round 8 (CRS, MODERATE): _classify_file_facet() never reads
    _SECURITY_BASENAMES directly -- it consults
    _SECURITY_BASENAMES_CASEFOLDED (see the ``.casefold()`` membership
    check in _classify_file_facet). Pinning immutability on only the
    decorative constant left the load-bearing one unpinned, so this class
    now covers both."""

    def test_security_basenames_is_a_frozenset(self):
        """_SECURITY_BASENAMES must be an actual frozenset, not a mutable
        set that merely happens not to be mutated at runtime."""
        assert isinstance(validate_review._SECURITY_BASENAMES, frozenset), (
            "_SECURITY_BASENAMES must be a frozenset -- it is currently a "
            f"mutable {type(validate_review._SECURITY_BASENAMES).__name__}, "
            "contradicting the 'frozen' claim made about it in the PR body "
            "and prior commit messages."
        )

    def test_security_basenames_rejects_mutation(self):
        """A frozenset has no .add() -- attempting to mutate it must raise
        AttributeError, proving immutability is structural, not just
        conventional."""
        with pytest.raises(AttributeError):
            validate_review._SECURITY_BASENAMES.add(".new-basename")  # type: ignore[attr-defined]

    def test_security_basenames_casefolded_is_a_frozenset(self):
        """_SECURITY_BASENAMES_CASEFOLDED -- the constant _classify_file_facet()
        actually consults -- must be an actual frozenset, not a mutable set
        that merely happens not to be mutated at runtime."""
        assert isinstance(validate_review._SECURITY_BASENAMES_CASEFOLDED, frozenset), (
            "_SECURITY_BASENAMES_CASEFOLDED must be a frozenset -- it is "
            f"currently a mutable "
            f"{type(validate_review._SECURITY_BASENAMES_CASEFOLDED).__name__}, "
            "and this is the constant the classifier's membership check "
            "actually reads."
        )

    def test_security_basenames_casefolded_rejects_mutation(self):
        """A frozenset has no .add() -- attempting to mutate
        _SECURITY_BASENAMES_CASEFOLDED must raise AttributeError, proving
        immutability is structural for the load-bearing constant, not just
        the decorative one."""
        with pytest.raises(AttributeError):
            validate_review._SECURITY_BASENAMES_CASEFOLDED.add(  # type: ignore[attr-defined]
                ".new-basename"
            )


@pytest.mark.security
class TestSecurityBasenameCaseInsensitive:
    """BLOCKING (round 5, cold non-Claude reviewer catch -- CIV via codex).
    The basename check used an exact-case membership test, so a
    differently-cased copy of a security-load-bearing basename bypassed
    classification entirely. This matters more on macOS, where the
    filesystem is case-insensitive: the SAME on-disk file can reach the
    classifier under a different casing than the set literally contains
    (e.g. a case-preserving-but-insensitive checkout, or an editor/tool
    that normalises casing on write). Both sides of the comparison must be
    casefolded."""

    @pytest.mark.parametrize(
        "path",
        [
            "supabase/tests/.pgTap-quarantine",
            "supabase/tests/.PGTAP-QUARANTINE",
            "supabase/tests/.PgTap-Quarantine",
        ],
    )
    def test_pgtap_quarantine_case_variants_still_classify_security(self, path: str):
        assert validate_review._classify_file_facet(path) == "SECURITY"

    @pytest.mark.parametrize(
        "path",
        [
            "supabase/migrations/.Drift-Exceptions",
            "supabase/migrations/.DRIFT-EXCEPTIONS",
        ],
    )
    def test_drift_exceptions_case_variants_still_classify_security(self, path: str):
        assert validate_review._classify_file_facet(path) == "SECURITY"


@pytest.mark.security
class TestSecurityBasenameSkipsVendoredPaths:
    """BLOCKING (round 5, cold non-Claude reviewer catch -- CRS via
    gemini). Moving the basename check to the FIRST position (correct, and
    required to close the tests/-prefix shadowing hole from round 3) made
    it fire on VENDORED copies of these basenames too -- a third-party
    dependency tree checked into node_modules/ or vendor/ can legitimately
    contain a file with one of these exact names with zero bearing on THIS
    repo's security posture. A spurious TIER_3_CRITICAL/four-role demand
    on every such vendored path in every consumer repo is exactly the kind
    of gate noise that pushes operators toward bypassing the gate
    altogether -- the failure mode this whole thread exists to prevent.

    Fix, minimally, MIP-consistent with the basenames themselves: skip the
    basename check when `vendor` or `node_modules` appears as an exact,
    casefolded path segment anywhere in the path (see `_is_vendored_path`,
    segment-anchored per the round-6 fix) -- two entries, no configurable
    list. The check's FIRST position ahead of the ^tests/ exemption is
    unchanged and remains load-bearing (round 3 mutation-tested); this
    only narrows WHEN the first-position check fires, not WHERE it sits."""

    def test_node_modules_anywhere_in_path_is_not_forced_security(self):
        assert (
            validate_review._classify_file_facet("node_modules/x/.pgtap-quarantine")
            == "ROUTINE_CODE"
        )

    def test_nested_vendor_node_modules_is_not_forced_security(self):
        assert (
            validate_review._classify_file_facet("vendor/node_modules/example/.drift-exceptions")
            == "ROUTINE_CODE"
        )

    def test_leading_vendor_prefix_is_not_forced_security(self):
        assert (
            validate_review._classify_file_facet("vendor/some-dep/.pgtap-quarantine")
            == "ROUTINE_CODE"
        )

    def test_non_vendored_quarantine_still_classifies_security_regression(self):
        """Regression control: the vendor guard must not swallow the
        legitimate, non-vendored case this whole fix exists for."""
        assert (
            validate_review._classify_file_facet("supabase/tests/.pgtap-quarantine") == "SECURITY"
        )


@pytest.mark.security
class TestVendorGuardSegmentAnchoringAndCasefold:
    """BLOCKING 2 (round 6, found independently by gemini and codex).

    The vendor guard added in round 5 tested membership with a bare
    ``_VENDOR_PATH_MARKER in path`` substring check for
    ``node_modules/`` -- unanchored to path segments. A directory that
    merely CONTAINS "node_modules" as a substring of its own name (e.g.
    "my_node_modules", a real, non-vendored directory with zero relation
    to an actual node_modules/ dependency tree) silently matched too,
    exempting a genuinely security-relevant path from classification --
    a real security-classification bypass in the guard, not merely an
    over-broad exemption. Separately, the ``vendor/`` marker used
    ``path.startswith(_VENDOR_LEADING_PREFIX)`` -- root-anchored ONLY --
    so a nested ``app/vendor/...`` path was NOT treated as vendored even
    though a nested ``vendor/node_modules/...`` path already was (via the
    substring marker), an inconsistent semantics between the two markers.
    Neither marker was casefolded, so ``Vendor/`` and ``Node_Modules/``
    (case variants a case-insensitive filesystem, e.g. macOS, can produce
    for the same on-disk directory) evaded the guard entirely.

    Fix: match both markers by PATH SEGMENT (an exact, casefolded segment
    equal to "vendor" or "node_modules" anywhere in the path), not by
    substring or by root-only prefix. One semantics for both markers.
    """

    def test_directory_name_merely_containing_node_modules_substring_is_not_vendored(
        self,
    ):
        """BYPASS: 'src/my_node_modules/.pgtap-quarantine' must classify
        SECURITY -- 'my_node_modules' is a real, non-vendored directory
        name that happens to contain 'node_modules' as a substring; it is
        not an actual vendored dependency tree and must not be exempted."""
        assert (
            validate_review._classify_file_facet("src/my_node_modules/.pgtap-quarantine")
            == "SECURITY"
        )

    def test_nested_vendor_directory_is_treated_as_vendored_consistently(self):
        """Consistency: 'app/vendor/.pgtap-quarantine' must be treated as
        vendored the same way a nested node_modules/ path already is --
        one segment-anywhere semantics for both markers, not root-only
        for 'vendor/' and anywhere for 'node_modules/'."""
        assert (
            validate_review._classify_file_facet("app/vendor/.pgtap-quarantine") == "ROUTINE_CODE"
        )

    def test_capitalized_vendor_segment_is_casefolded(self):
        """'Vendor/.pgtap-quarantine' must be treated as vendored --
        case-insensitive filesystems (macOS) can present the same
        on-disk vendor/ directory under different casing."""
        assert validate_review._classify_file_facet("Vendor/.pgtap-quarantine") == "ROUTINE_CODE"

    def test_capitalized_node_modules_segment_is_casefolded(self):
        """'Node_Modules/x/.drift-exceptions' must be treated as
        vendored, consistent with the casefolded basename set."""
        assert (
            validate_review._classify_file_facet("Node_Modules/x/.drift-exceptions")
            == "ROUTINE_CODE"
        )

    def test_exact_segment_match_required_not_substring(self):
        """Round 8 (CRS, CERTAIN): the discriminating case for
        segment-vs-substring matching is a path whose SUBSTRING contains a
        vendor marker but whose SEGMENTS do not. Round-5 whole-path
        substring/prefix logic (``"node_modules/" in path or
        path.startswith("vendor/")``) treats 'src/my_node_modules/...' as
        vendored, because 'node_modules/' is a literal substring of
        'my_node_modules/' -- a real security-classification bypass.
        Segment logic (splitting on '/' and requiring an exact, casefolded
        segment equal to 'vendor' or 'node_modules') correctly rejects it,
        since the segment 'my_node_modules' is not exactly 'node_modules'.
        Mutation-verified: reintroducing the round-5 whole-path
        substring/prefix check locally turns this assertion red (it would
        classify ROUTINE_CODE instead of SECURITY); the segment-anchored
        fix turns it back green. The plural-directory case ('vendors/',
        a different real directory name) is retained below as companion
        coverage but does not by itself discriminate the two
        implementations -- neither the round-5 substring/prefix check nor
        the current segment check treats 'vendors/' as vendored, so both
        agree on SECURITY for that path."""
        assert (
            validate_review._classify_file_facet("src/my_node_modules/.pgtap-quarantine")
            == "SECURITY"
        )
        assert validate_review._classify_file_facet("vendors/.pgtap-quarantine") == "SECURITY"


# ---------------------------------------------------------------------------
# Matcher provenance (issue #116 P0-1)
# ---------------------------------------------------------------------------
# The review gate checks out the PR's tree and then runs the validator.  For
# the gate to be trustworthy, BOTH the validator script and the review_formats
# matcher module it uses must come from the same trusted checkout.  Before this
# fix, validate_review.py preferred the *installed* hestai_context_mcp package
# and only fell back to the file co-located with the script on ImportError.
# That happened to be correct in CI only because the package is never installed
# there -- an accident of environment, not a guarantee.  These tests pin the
# guarantee: the matcher is always loaded from the tree the script itself lives
# in, whether or not hestai_context_mcp is importable.

_SENTINEL_ROLE = "TRUSTED-CHECKOUT-SENTINEL"

_STUB_REVIEW_FORMATS = f'''"""Stub matcher standing in for a trusted checkout's review_formats."""

VALID_ROLES = frozenset({{"{_SENTINEL_ROLE}"}})


def _stub(*args, **kwargs):
    return None


matches_approval_pattern = _stub
has_crs_approval = _stub
has_crs_model_approval = _stub
has_ce_approval = _stub
has_ho_review = _stub
has_tmg_approval = _stub
has_civ_approval = _stub
has_pe_approval = _stub
has_self_review = _stub
has_sr_approval = _stub
has_gr_approval = _stub
parse_review_metadata = _stub
'''

_PROBE = """
import importlib.util
import json
import sys

spec = importlib.util.spec_from_file_location("validate_review_probe", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
print(json.dumps(sorted(module._VALID_ROLES)))
"""


def _build_fake_checkout(tmp_path, *, with_matcher=True):
    """Lay out a checkout containing validate_review.py and (optionally) its matcher."""
    repo_root = Path(__file__).resolve().parent.parent
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "validate_review.py").write_text(
        (repo_root / "scripts" / "validate_review.py").read_text()
    )
    if with_matcher:
        shared_dir = tmp_path / "src" / "hestai_context_mcp" / "tools" / "shared"
        shared_dir.mkdir(parents=True)
        (shared_dir / "review_formats.py").write_text(_STUB_REVIEW_FORMATS)
    return scripts_dir / "validate_review.py"


def _run_probe(script_path, tmp_path):
    """Execute the probe with hestai_context_mcp IMPORTABLE (simulating an install)."""
    repo_root = Path(__file__).resolve().parent.parent
    env = dict(os.environ)
    env["PYTHONPATH"] = str(repo_root / "src")
    return subprocess.run(
        [sys.executable, "-c", _PROBE, str(script_path)],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        env=env,
    )


@pytest.mark.security
class TestMatcherProvenance:
    """The matcher must come from the script's own checkout, not from an install."""

    def test_matcher_loads_from_script_checkout_even_when_package_importable(self, tmp_path):
        """RED before fix: the installed package wins the import and the
        sentinel from the co-located matcher never appears.

        This is the exact failure mode of issue #116 P0-1: once the validator
        is sourced from a trusted checkout, an importable hestai_context_mcp
        would silently re-substitute the PR's own matchers.
        """
        script_path = _build_fake_checkout(tmp_path)
        result = _run_probe(script_path, tmp_path)
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout) == [_SENTINEL_ROLE], (
            "validate_review.py loaded review_formats from somewhere other than "
            "its own checkout; matcher provenance is not guaranteed"
        )

    def test_missing_co_located_matcher_fails_closed(self, tmp_path):
        """A checkout without its matcher must abort, never silently fall back
        to an installed package that the gate does not control."""
        script_path = _build_fake_checkout(tmp_path, with_matcher=False)
        result = _run_probe(script_path, tmp_path)
        assert result.returncode != 0
        assert "review_formats.py not found" in result.stderr


_POISONED_CRS_COMMENT = {
    "body": (
        "CRS BLOCKED: this PR must not land\n"
        '<!-- review: {"role": "CRS", "verdict": "APPROVED", "provider": "gemini"} -->'
    )
}


def _mock_gh_pr_view(comments, body=""):
    """Build a subprocess.run replacement returning a `gh pr view --json` payload."""

    def mock_run(cmd, *args, **kwargs):
        return MagicMock(
            stdout=json.dumps({"body": body, "comments": comments}),
            returncode=0,
            check=lambda: None,
        )

    return mock_run


@pytest.mark.security
class TestCrossValidationDisqualifiesInsteadOfWedging:
    """Issue #155 (fail-CLOSED half): one poisoned comment must not wedge the PR.

    A comment whose ``<!-- review: ... -->`` metadata claims an approval verdict
    that the visible text contradicts used to abort the ENTIRE validation run
    before any role checker ran. Anyone able to comment on a PR could therefore
    block every approval on it -- including a revert of a bad ``main``.

    The comment must be DISQUALIFIED (cleared of both regex-matchable text and
    metadata) while validation continues over the remaining comments. The
    security property is unchanged: a spoofed comment still clears nothing.
    """

    def test_poisoned_comment_does_not_block_genuine_approvals(self, ci_environment, monkeypatch):
        """BLAST RADIUS: genuine approvals for every required role must still satisfy
        the gate when an unrelated poisoned comment is present on the same PR."""
        monkeypatch.setattr(
            subprocess,
            "run",
            _mock_gh_pr_view(
                [
                    _POISONED_CRS_COMMENT,
                    {"body": "TMG APPROVED: tests verified"},
                    {"body": "CRS APPROVED: Logic correct"},
                    {"body": "CE APPROVED: Architecture sound"},
                ]
            ),
        )

        approved, message, missing = validate_review.check_pr_comments("TIER_2_STANDARD")

        assert approved is True, (
            "A single poisoned metadata comment wedged the whole PR shut; genuine "
            f"TMG/CRS/CE approvals must still satisfy the gate. Got: {message}"
        )
        assert missing == []

    def test_disqualification_is_surfaced_not_silent(self, ci_environment, monkeypatch):
        """A wedge attempt must remain visible in the gate's human-readable reason."""
        monkeypatch.setattr(
            subprocess,
            "run",
            _mock_gh_pr_view(
                [
                    _POISONED_CRS_COMMENT,
                    {"body": "TMG APPROVED: tests verified"},
                    {"body": "CRS APPROVED: Logic correct"},
                    {"body": "CE APPROVED: Architecture sound"},
                ]
            ),
        )

        approved, message, _ = validate_review.check_pr_comments("TIER_2_STANDARD")

        # Both halves matter: the gate PASSES (no wedge) and the wedge attempt is
        # still reported. Asserting only the message would also pass against the
        # old aborting code, whose failure message likewise mentions spoofing.
        assert approved is True, f"Gate must not be wedged. Got: {message}"
        assert (
            "spoofing" in message.lower()
        ), f"Disqualifying a comment must not be silent. Got: {message}"

    def test_poisoned_comment_clears_nothing(self, ci_environment, monkeypatch):
        """SECURITY: the disqualified comment must satisfy neither the regex
        matchers nor the metadata check -- CRS stays missing."""
        monkeypatch.setattr(
            subprocess,
            "run",
            _mock_gh_pr_view(
                [
                    _POISONED_CRS_COMMENT,
                    {"body": "TMG APPROVED: tests verified"},
                    {"body": "CE APPROVED: Architecture sound"},
                ]
            ),
        )

        approved, message, missing = validate_review.check_pr_comments("TIER_2_STANDARD")

        assert approved is False, f"Spoofed CRS metadata must not clear CRS. Got: {message}"
        assert missing == ["CRS"], (
            "Validation must run to completion and report exactly the role the "
            f"poisoned comment failed to satisfy. Got missing={missing}, message={message}"
        )


def _git_fixture_env():
    """Hermetic git environment for fixture repos.

    Identity via env vars: works where CI has no git identity (exit 128) and
    where user.useConfigOnly is set.

    GIT_CONFIG_GLOBAL/SYSTEM are neutralised because a developer's global
    core.hooksPath can refuse `git switch` in a scratch repo ("Cannot switch
    branches in main repo"), which would break the advancing-base fixtures
    non-deterministically depending on whose machine runs them.
    """
    return {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t.t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t.t",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
    }


def _git_rename_repro(tmp_path, old_path: str, new_path: str, old_content: str | None = None):
    """Create a repo whose STAGED diff is a real git rename plus a content edit.

    Returns the repo path. Identity is supplied BOTH by GIT_AUTHOR_*/GIT_COMMITTER_*
    env vars and by repo-local user.name/user.email, so the fixture works where CI
    has no git identity (exit 128) and where user.useConfigOnly is set on macOS.
    ``git init -b testwork`` pins the symbolic ref to a non-main branch, keeping
    the commit clear of any global main-branch protection hook.

    Args:
        old_content: Contents of the pre-rename file. Defaults to filler lines.
            Pass real OCTAVE to exercise content-sensitive classification.
    """
    import subprocess as sp

    repo = tmp_path / "repo"
    repo.mkdir()
    env = _git_fixture_env()
    sp.run(["git", "init", "-q", "-b", "testwork"], cwd=repo, check=True, env=env)
    sp.run(["git", "config", "user.name", "t"], cwd=repo, check=True, env=env)
    sp.run(["git", "config", "user.email", "t@t.t"], cwd=repo, check=True, env=env)

    src = repo / old_path
    src.parent.mkdir(parents=True, exist_ok=True)
    # Enough content that git still scores the pair as a rename after the edit.
    if old_content is None:
        old_content = "\n".join(f"line {i}" for i in range(40)) + "\n"
    src.write_text(old_content)
    sp.run(["git", "add", "-A"], cwd=repo, check=True, env=env)
    sp.run(["git", "commit", "-qm", "seed"], cwd=repo, check=True, env=env)

    dst = repo / new_path
    dst.parent.mkdir(parents=True, exist_ok=True)
    sp.run(["git", "mv", old_path, new_path], cwd=repo, check=True, env=env)
    # Content edit in the SAME commit -> git emits R0xx, not R100.
    with dst.open("a") as fh:
        fh.write("appended by the same commit\n")
    sp.run(["git", "add", "-A"], cwd=repo, check=True, env=env)
    return repo


def _changed_files_in(repo):
    """Run get_changed_files with the repo as cwd.

    Honours whichever branch the ambient env selects: the local ``--cached``
    branch, or the ``CI`` + ``GITHUB_BASE_REF`` branch.
    """
    cwd0 = os.getcwd()
    try:
        os.chdir(repo)
        return validate_review.get_changed_files()
    finally:
        os.chdir(cwd0)


@pytest.mark.security
class TestRenameFacetClassification:
    """Issue #161: a rename must not launder a file out of its facet.

    ``git mv auth/login.py notes.md`` plus a content edit in the same commit
    still emits an ``R0xx`` rename status, and ``get_changed_files`` populates
    ``previous_path``. ``classify_pr_facets`` classified the NEW path only, so
    the PR landed as ``TIER_0_EXEMPT`` with ZERO required reviewers.
    """

    def test_rename_out_of_security_path_still_requires_reviewers(self, tmp_path, monkeypatch):
        monkeypatch.delenv("CI", raising=False)
        repo = _git_rename_repro(tmp_path, "auth/login.py", "notes.md")

        files = _changed_files_in(repo)

        # Guard against fixture theatre: assert git really produced a rename.
        assert len(files) == 1, files
        assert files[0]["path"] == "notes.md"
        assert files[0]["status"] == "R", f"fixture did not produce a rename: {files}"
        assert files[0]["previous_path"] == "auth/login.py"

        facets, required_roles, tier_label, reason = validate_review.classify_pr_facets(files)

        assert (
            "SECURITY" in facets
        ), f"renaming a security-path file to an exempt name laundered its facet: {reason}"
        assert required_roles, f"rename produced ZERO required reviewers: {tier_label} / {reason}"
        assert tier_label != "TIER_0_EXEMPT"

    def test_validator_renamed_out_of_its_own_rule_still_requires_reviewers(
        self, tmp_path, monkeypatch
    ):
        """The gate must not be renamable out from under META_CONTROL_PLANE."""
        monkeypatch.delenv("CI", raising=False)
        repo = _git_rename_repro(tmp_path, "scripts/validate_review.py", "notes.md")

        files = _changed_files_in(repo)
        assert files[0]["status"] == "R", f"fixture did not produce a rename: {files}"

        facets, required_roles, tier_label, reason = validate_review.classify_pr_facets(files)

        assert "META_CONTROL_PLANE" in facets, reason
        assert {
            "CIV",
            "CE",
            "CRS",
            "SR",
            "TMG",
        } <= required_roles, (
            f"validate_review.py renamed out of its own rule: {required_roles} / {reason}"
        )

    def test_non_rename_modification_is_unchanged(self, tmp_path, monkeypatch):
        """REGRESSION: a plain edit (no rename) classifies exactly as before."""
        import subprocess as sp

        monkeypatch.delenv("CI", raising=False)
        repo = tmp_path / "repo"
        repo.mkdir()
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t.t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t.t",
        }
        sp.run(["git", "init", "-q", "-b", "testwork"], cwd=repo, check=True, env=env)
        target = repo / "src" / "thing.py"
        target.parent.mkdir(parents=True)
        target.write_text("\n".join(f"line {i}" for i in range(40)) + "\n")
        sp.run(["git", "add", "-A"], cwd=repo, check=True, env=env)
        sp.run(["git", "commit", "-qm", "seed"], cwd=repo, check=True, env=env)
        with target.open("a") as fh:
            fh.write("".join(f"edited {i}\n" for i in range(12)))
        sp.run(["git", "add", "-A"], cwd=repo, check=True, env=env)

        files = _changed_files_in(repo)

        assert files[0]["status"] == "M"
        assert "previous_path" not in files[0]

        facets, required_roles, _, reason = validate_review.classify_pr_facets(files)

        assert facets == {"ROUTINE_CODE"}, reason
        assert required_roles == {"CE", "CRS", "TMG"}, reason


_OCT_AGENT_DEFINITION = (
    "===DYNAMIC_AGENT===\n"
    "META:\n"
    "  TYPE::AGENT_DEFINITION\n"
    '  VERSION::"1.0"\n'
    "\n"  # blank line: sniffing must not stop here
    "§1::IDENTITY\n"
    "  ROLE::DYNAMIC\n"
    "===END===\n"
)

_OCT_SKILL = (
    "===DYNAMIC_SKILL===\n"
    "META:\n"
    "  TYPE::SKILL\n"
    '  VERSION::"1.0"\n'
    "\n"
    "§1::PURPOSE\n"
    "  DO::things\n"
    "===END===\n"
)


def _commit_staged_rename(repo) -> str:
    """Commit the staged rename. Returns the BASE sha (the pre-rename commit)."""
    import subprocess as sp

    env = _git_fixture_env()
    base_sha = sp.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
        env=env,
    ).stdout.strip()
    sp.run(["git", "commit", "-qm", "rename"], cwd=repo, check=True, env=env)
    return base_sha


def _classify_in(repo, files):
    """Run classify_pr_facets with the repo as cwd.

    Required for renames: the old side is read from a git blob, and in
    production the validator runs inside the repository being validated.
    """
    cwd0 = os.getcwd()
    try:
        os.chdir(repo)
        return validate_review.classify_pr_facets(files)
    finally:
        os.chdir(cwd0)


@pytest.mark.security
class TestRenameOldSideContentSensitiveClassification:
    """Issue #161 (rework): the OLD side of a rename cannot be sniffed from HEAD.

    ``_classify_file_facet`` resolves a non-library ``.oct.md`` by calling
    ``_sniff_octave_type``, which ``open()``s the path on the working
    filesystem. A renamed-away ``previous_path`` does not exist there, so the
    sniff returns "" and the file is downgraded from EXECUTABLE_SPEC to
    GOVERNANCE. The ``TIER_1_SELF`` short-circuit excludes SECURITY,
    META_CONTROL_PLANE and EXECUTABLE_SPEC -- but NOT GOVERNANCE -- so the
    zero-external-reviewer outcome #161 exists to close is still reachable.

    The old side must therefore be classified from its BASE BLOB:
    ``HEAD:<previous_path>`` locally, ``<base-ref>:<previous_path>`` under CI.

    Both branches of ``get_changed_files`` are covered here. Only the local
    ``--cached`` branch was previously exercised, and the CI branch is where
    this defect lived.
    """

    def test_out_of_library_agent_definition_rename_local_cached_branch(
        self, tmp_path, monkeypatch
    ):
        """LOCAL (--cached) branch: old side read from HEAD:<previous_path>."""
        monkeypatch.delenv("CI", raising=False)
        repo = _git_rename_repro(
            tmp_path,
            "governance/dynamic.oct.md",
            "notes.md",
            old_content=_OCT_AGENT_DEFINITION,
        )

        files = _changed_files_in(repo)

        assert files[0]["status"] == "R", f"fixture did not produce a rename: {files}"
        assert files[0]["previous_path"] == "governance/dynamic.oct.md"

        facets, required_roles, tier_label, reason = _classify_in(repo, files)

        assert "EXECUTABLE_SPEC" in facets, (
            "an out-of-library AGENT_DEFINITION renamed to an exempt path was "
            f"downgraded instead of classified from its BASE blob: {reason}"
        )
        assert required_roles, f"ZERO required reviewers: {tier_label} / {reason}"
        assert tier_label not in ("TIER_0_EXEMPT", "TIER_1_SELF"), reason

    def test_out_of_library_agent_definition_rename_ci_base_ref_branch(self, tmp_path, monkeypatch):
        """CI branch: old side read from <base-ref>:<previous_path>.

        This is the branch of get_changed_files that no test previously
        executed, and the one the review gate actually runs.
        """
        repo = _git_rename_repro(
            tmp_path,
            "governance/dynamic.oct.md",
            "notes.md",
            old_content=_OCT_AGENT_DEFINITION,
        )
        base_sha = _commit_staged_rename(repo)

        monkeypatch.setenv("CI", "true")
        monkeypatch.setenv("GITHUB_BASE_REF", base_sha)

        files = _changed_files_in(repo)

        assert files[0]["status"] == "R", f"fixture did not produce a rename: {files}"
        assert files[0]["previous_path"] == "governance/dynamic.oct.md"

        facets, required_roles, tier_label, reason = _classify_in(repo, files)

        assert "EXECUTABLE_SPEC" in facets, reason
        assert required_roles, f"ZERO required reviewers: {tier_label} / {reason}"
        assert tier_label not in ("TIER_0_EXEMPT", "TIER_1_SELF"), reason

    def test_out_of_library_skill_rename_ci_base_ref_branch(self, tmp_path, monkeypatch):
        """TYPE::SKILL is the other executable-spec type and must behave identically."""
        repo = _git_rename_repro(
            tmp_path,
            "governance/dynamic.oct.md",
            "notes.md",
            old_content=_OCT_SKILL,
        )
        base_sha = _commit_staged_rename(repo)

        monkeypatch.setenv("CI", "true")
        monkeypatch.setenv("GITHUB_BASE_REF", base_sha)

        files = _changed_files_in(repo)
        assert files[0]["status"] == "R", f"fixture did not produce a rename: {files}"

        facets, required_roles, tier_label, reason = _classify_in(repo, files)

        assert "EXECUTABLE_SPEC" in facets, reason
        assert required_roles, f"ZERO required reviewers: {tier_label} / {reason}"
        assert tier_label not in ("TIER_0_EXEMPT", "TIER_1_SELF"), reason

    def test_ordinary_governance_rename_is_not_over_escalated(self, tmp_path, monkeypatch):
        """REGRESSION: the rejected blanket fix (treat every missing old .oct.md as
        EXECUTABLE_SPEC) would add reviewers to ordinary governance renames.

        A TYPE::RULE document must still classify as GOVERNANCE, not EXECUTABLE_SPEC.

        This guard is not RED before the fix: today's failed sniff also yields
        GOVERNANCE. It exists to fail if the fix over-reaches.
        """
        repo = _git_rename_repro(
            tmp_path,
            "governance/rule.oct.md",
            "notes.md",
            old_content=("===RULE===\nMETA:\n  TYPE::RULE\n\n§1::BODY\n  X::Y\n===END===\n"),
        )
        base_sha = _commit_staged_rename(repo)

        monkeypatch.setenv("CI", "true")
        monkeypatch.setenv("GITHUB_BASE_REF", base_sha)

        files = _changed_files_in(repo)
        facets, required_roles, _, reason = _classify_in(repo, files)

        assert facets == {"GOVERNANCE"}, f"over-escalated an ordinary rule rename: {reason}"
        assert "EXECUTABLE_SPEC" not in facets, reason
        # No reviewer assertion here: a 1-line single-file governance rename
        # legitimately takes the TIER_1_SELF short-circuit, which returns an
        # empty role set. The facet is the claim under test.
        assert required_roles == set(), reason


@pytest.mark.security
class TestDisqualificationSurfacedOnSelfReviewPath:
    """cubic P2: the disqualification notice must reach the TIER_1_SELF SUCCESS exits.

    The notice reached the role-check returns and the TIER_1_SELF FAILURE return,
    but every successful self-review return exited before it was appended. The
    security property held -- the poisoned comment was still disqualified and
    cleared nothing -- but the wedge attempt became invisible in exactly the tier
    where a single reviewer is least likely to notice it.
    """

    def test_self_review_success_still_reports_the_disqualification(
        self, ci_environment, monkeypatch
    ):
        monkeypatch.setattr(
            subprocess,
            "run",
            _mock_gh_pr_view(
                [
                    _POISONED_CRS_COMMENT,
                    {"body": "IL SELF-REVIEWED: fixed a typo"},
                ]
            ),
        )

        approved, message, missing = validate_review.check_pr_comments(
            required_roles=set(), tier="TIER_1_SELF"
        )

        assert approved is True, f"genuine self-review must still clear T1. Got: {message}"
        assert missing == []
        assert "spoofing" in message.lower(), (
            "a wedge attempt on a self-review PR must not be silent. " f"Got: {message}"
        )

    def test_self_review_via_crs_metadata_success_reports_the_disqualification(
        self, ci_environment, monkeypatch
    ):
        """The metadata-satisfied self-review exits are separate returns and
        regressed identically."""
        monkeypatch.setattr(
            subprocess,
            "run",
            _mock_gh_pr_view(
                [
                    _POISONED_CRS_COMMENT,
                    {
                        "body": (
                            "CRS APPROVED: looks good\n"
                            '<!-- review: {"role": "CRS", "verdict": "APPROVED", '
                            '"provider": "gemini"} -->'
                        )
                    },
                ]
            ),
        )

        approved, message, _ = validate_review.check_pr_comments(
            required_roles=set(), tier="TIER_1_SELF"
        )

        assert approved is True, message
        assert (
            "spoofing" in message.lower()
        ), f"metadata self-review exit lost the disqualification notice. Got: {message}"


def _git_advancing_base_repro(
    tmp_path,
    old_path: str,
    new_path: str,
    old_content: str,
    base_action: str = "modify",
    advanced_content: str = "===RULE===\nMETA:\n  TYPE::RULE\n===END===\n",
):
    """Repo with a REAL NAMED base branch that ADVANCES after divergence.

    A SHA-pinned fixture cannot express this defect: pinning GITHUB_BASE_REF to
    the pre-rename commit makes the base tip equal the merge base by
    construction. Only a named branch that has moved on since divergence
    distinguishes `base_tip:<old_path>` from `merge_base:<old_path>`.

    Layout::

        M (basebranch, old_path = old_content)   <- merge base
        |\\
        | R (testwork, HEAD: old_path renamed to new_path + edited)
        A (basebranch tip: old_path modified or deleted)

    Returns (repo, base_branch_name).
    """
    import subprocess as sp

    repo = tmp_path / "repo"
    repo.mkdir()
    env = _git_fixture_env()

    def git(*args):
        sp.run(["git", *args], cwd=repo, check=True, env=env)

    git("init", "-q", "-b", "basebranch")
    git("config", "user.name", "t")
    git("config", "user.email", "t@t.t")

    src = repo / old_path
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text(old_content)
    git("add", "-A")
    git("commit", "-qm", "merge base")

    # Feature branch: the rename plus a content edit in the same commit.
    git("switch", "-qc", "testwork")
    (repo / new_path).parent.mkdir(parents=True, exist_ok=True)
    git("mv", old_path, new_path)
    with (repo / new_path).open("a") as fh:
        fh.write("appended by the same commit\n")
    git("add", "-A")
    git("commit", "-qm", "rename")

    # Base branch advances AFTER divergence, touching the very path the
    # feature branch renamed away.
    git("switch", "-q", "basebranch")
    if base_action == "delete":
        git("rm", "-q", old_path)
    else:
        src.write_text(advanced_content)
        git("add", "-A")
    git("commit", "-qm", "base advances")

    git("switch", "-q", "testwork")
    return repo, "basebranch"


@pytest.mark.security
class TestRenameClassifiedFromMergeBaseNotBaseTip:
    """Issue #161 (round 3): three-dot diff semantics.

    get_changed_files diffs ``{base_ref}...HEAD``. Three dots means the
    left-hand tree is ``merge-base(base_ref, HEAD)`` -- NOT the base_ref tip.
    Classifying the old side against the base TIP reads the wrong tree on any
    PR whose base has advanced since divergence, which is the normal case, and
    the zero-external-reviewer outcome becomes reachable again.
    """

    def test_advanced_base_still_classifies_old_side_from_merge_base(self, tmp_path, monkeypatch):
        """Base branch changed the old path to TYPE::RULE after divergence.

        Merge base still holds TYPE::AGENT_DEFINITION, so the rename must
        classify EXECUTABLE_SPEC. Reading the base tip yields GOVERNANCE and
        drops to zero external reviewers.
        """
        repo, base_branch = _git_advancing_base_repro(
            tmp_path,
            "governance/dynamic.oct.md",
            "notes.md",
            _OCT_AGENT_DEFINITION,
            base_action="modify",
        )
        monkeypatch.setenv("CI", "true")
        monkeypatch.setenv("GITHUB_BASE_REF", base_branch)

        files = _changed_files_in(repo)

        assert files[0]["status"] == "R", f"fixture did not produce a rename: {files}"
        assert files[0]["previous_path"] == "governance/dynamic.oct.md"

        facets, required_roles, tier_label, reason = _classify_in(repo, files)

        assert "EXECUTABLE_SPEC" in facets, (
            "old side was classified against the base TIP, not the merge base "
            f"the diff actually used: {reason}"
        )
        assert required_roles, f"ZERO required reviewers: {tier_label} / {reason}"
        assert tier_label not in ("TIER_0_EXEMPT", "TIER_1_SELF"), reason

    def test_base_deleted_old_path_still_classifies_from_merge_base(self, tmp_path, monkeypatch):
        """Base branch DELETED the old path after divergence.

        The merge base still holds the blob, so this must classify precisely
        (not via the conservative error path).
        """
        repo, base_branch = _git_advancing_base_repro(
            tmp_path,
            "governance/dynamic.oct.md",
            "notes.md",
            _OCT_AGENT_DEFINITION,
            base_action="delete",
        )
        monkeypatch.setenv("CI", "true")
        monkeypatch.setenv("GITHUB_BASE_REF", base_branch)

        files = _changed_files_in(repo)
        assert files[0]["status"] == "R", f"fixture did not produce a rename: {files}"

        facets, required_roles, tier_label, reason = _classify_in(repo, files)

        assert "EXECUTABLE_SPEC" in facets, reason
        assert required_roles, f"ZERO required reviewers: {tier_label} / {reason}"
        assert tier_label not in ("TIER_0_EXEMPT", "TIER_1_SELF"), reason

    def test_advanced_base_does_not_over_escalate_an_ordinary_rule(self, tmp_path, monkeypatch):
        """REGRESSION: reading the merge base must stay PRECISE for a genuine
        TYPE::RULE, even when the base tip has since made it an AGENT_DEFINITION.

        Guards the inverse error: escalating everything unreadable-or-changed.
        """
        repo, base_branch = _git_advancing_base_repro(
            tmp_path,
            "governance/rule.oct.md",
            "notes.md",
            "===RULE===\nMETA:\n  TYPE::RULE\n===END===\n",
            base_action="modify",
            advanced_content=_OCT_AGENT_DEFINITION,
        )
        monkeypatch.setenv("CI", "true")
        monkeypatch.setenv("GITHUB_BASE_REF", base_branch)

        files = _changed_files_in(repo)
        facets, _, _, reason = _classify_in(repo, files)

        assert facets == {"GOVERNANCE"}, f"over-escalated an ordinary rule rename: {reason}"


@pytest.mark.security
class TestRenameOldSideFailsClosedWhenUnreadable:
    """Once rename metadata has identified an old path, an inability to resolve
    the base tree or read the blob must NOT silently downgrade an executable
    specification to governance/self-review.

    Precise when resolvable; conservative only on the ERROR path. This does not
    contradict the rejected blanket fix, which concerned the resolvable case.
    """

    def test_unresolvable_base_ref_does_not_downgrade(self, tmp_path, monkeypatch):
        """An unresolvable base ref must fail CLOSED, not fall back to GOVERNANCE.

        NOTE: the file dict here is constructed rather than produced by
        get_changed_files, because an unresolvable base ref makes collection
        itself fail closed and return nothing to classify. The rename SHAPE is
        proven against real git elsewhere in this file; what is under test here
        is the classifier's behaviour when the blob cannot be read.
        """
        repo, _ = _git_advancing_base_repro(
            tmp_path,
            "governance/dynamic.oct.md",
            "notes.md",
            _OCT_AGENT_DEFINITION,
        )
        monkeypatch.setenv("CI", "true")
        monkeypatch.setenv("GITHUB_BASE_REF", "no-such-branch-exists")

        files = [
            {
                "path": "notes.md",
                "added": 1,
                "deleted": 0,
                "total_changed": 1,
                "status": "R",
                "previous_path": "governance/dynamic.oct.md",
            }
        ]

        facets, required_roles, tier_label, reason = _classify_in(repo, files)

        assert (
            "GOVERNANCE" not in facets
        ), f"silently downgraded an unreadable old side to GOVERNANCE: {reason}"
        assert required_roles, f"ZERO required reviewers on the error path: {reason}"
        assert tier_label not in ("TIER_0_EXEMPT", "TIER_1_SELF"), reason


# Characters str.splitlines() treats as line boundaries but readline() does not.
# The next one someone thinks of should already be covered by this list.
_SPLITLINES_ONLY_SEPARATORS = [
    "\x0b",  # line tabulation
    "\x0c",  # form feed
    "\x1c",  # file separator
    "\x1d",  # group separator
    "\x1e",  # record separator
    "\x85",  # next line (NEL)
    " ",  # line separator
    " ",  # paragraph separator
]


@pytest.mark.security
class TestSniffSemanticsAgreeAcrossInputs:
    """cubic P2: one rule, two implementations, drifting.

    _sniff_octave_type read a file with readline() (splits on \\n) but a blob
    with str.splitlines() (ALSO splits on \\x0b \\x0c \\x1c \\x1d \\x1e \\x85
    \\u2028 \\u2029). More than 50 such separators before TYPE:: truncated the
    blob path while the file path still found it.

    Since the OLD side of a rename is now ALWAYS read as a blob, an
    out-of-library AGENT_DEFINITION or SKILL shaped this way classified
    GOVERNANCE, fell into TIER_1_SELF and reached zero external reviewers --
    the #161 outcome, reachable through the #161 fix. The old blob is
    attacker-authorable: whoever wrote the file chooses its bytes.

    This is the same shape as the merge-base defect: two code paths
    independently deciding what should be a single rule.
    """

    @staticmethod
    def _write(tmp_path, content: str) -> str:
        rel = "governance/dynamic.oct.md"
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
        return rel

    @pytest.mark.parametrize("sep", _SPLITLINES_ONLY_SEPARATORS)
    def test_sniff_agrees_between_file_and_blob(self, tmp_path, sep, monkeypatch):
        """PROPERTY: identical bytes must sniff identically from either input."""
        content = ("A" + sep) * 60 + "TYPE::AGENT_DEFINITION\n"
        rel = self._write(tmp_path, content)
        monkeypatch.chdir(tmp_path)

        from_file = validate_review._sniff_octave_type(rel)
        from_blob = validate_review._sniff_octave_type(rel, content=content)

        assert from_blob == from_file, (
            f"separator {sep!r}: file sniff gave {from_file!r} but blob sniff "
            f"gave {from_blob!r} for identical content"
        )
        assert from_file == "AGENT_DEFINITION"

    @pytest.mark.parametrize("sep", _SPLITLINES_ONLY_SEPARATORS)
    def test_facet_agrees_between_file_and_blob(self, tmp_path, sep, monkeypatch):
        """END TO END: the facet is where the harm lands, so assert the facet."""
        content = ("A" + sep) * 60 + "TYPE::AGENT_DEFINITION\n"
        rel = self._write(tmp_path, content)
        monkeypatch.chdir(tmp_path)

        from_file = validate_review._classify_file_facet(rel)
        from_blob = validate_review._classify_file_facet(rel, content=content)

        assert from_blob == from_file, (
            f"separator {sep!r}: same bytes classified {from_file} from the file "
            f"but {from_blob} from the blob"
        )
        assert from_file == "EXECUTABLE_SPEC", (
            "an out-of-library AGENT_DEFINITION must not be downgraded; "
            "GOVERNANCE falls into TIER_1_SELF and reaches zero external reviewers"
        )

    def test_skill_type_agrees_too(self, tmp_path, monkeypatch):
        """TYPE::SKILL is the other executable-spec type."""
        content = ("A\x0c") * 60 + "TYPE::SKILL\n"
        rel = self._write(tmp_path, content)
        monkeypatch.chdir(tmp_path)

        assert (
            validate_review._classify_file_facet(rel, content=content)
            == validate_review._classify_file_facet(rel)
            == "EXECUTABLE_SPEC"
        )

    def test_blank_line_before_type_does_not_truncate_either_input(self, tmp_path, monkeypatch):
        """REGRESSION: a blank line is '\\n' (truthy) to readline and must not be
        read as end-of-input by either path."""
        content = "===DOC===\nMETA:\n\n\n  TYPE::AGENT_DEFINITION\n===END===\n"
        rel = self._write(tmp_path, content)
        monkeypatch.chdir(tmp_path)

        assert validate_review._sniff_octave_type(rel) == "AGENT_DEFINITION"
        assert validate_review._sniff_octave_type(rel, content=content) == "AGENT_DEFINITION"

    def test_fifty_line_scan_limit_is_the_same_for_both_inputs(self, tmp_path, monkeypatch):
        """The cap must be counted in the same units on both paths: TYPE:: beyond
        the 50th real line is found by neither."""
        content = "filler\n" * 60 + "  TYPE::AGENT_DEFINITION\n"
        rel = self._write(tmp_path, content)
        monkeypatch.chdir(tmp_path)

        assert validate_review._sniff_octave_type(rel) == ""
        assert validate_review._sniff_octave_type(rel, content=content) == ""


@pytest.mark.security
class TestBaseTreeResolvedOnceAndThreaded:
    """Issue #161 (cycle 3): a shared FUNCTION is not a shared VALUE.

    get_changed_files resolved the base tree, _classify_renamed_old_side
    resolved it AGAIN per renamed file, and classify_pr_facets is called twice
    in the production path -- so resolution repeated. A ref movement, a
    concurrent fetch, or a transient inconsistent result between those calls
    lets collection diff tree A while classification reads a blob from tree B.
    With executable content at A and TYPE::RULE at B the result is
    facets={GOVERNANCE}, roles={}, tier=TIER_1_SELF: zero external reviewers.

    The resolver below deliberately returns a DIFFERENT sha on every call, so
    any second resolution is observable. That is what makes the
    resolve-once-and-thread invariant real rather than asserted in a comment.
    """

    @staticmethod
    def _install(monkeypatch, tmp_path):
        """Wire a drifting resolver + a git/gh mock. Returns (resolutions, calls)."""
        resolutions: list[str] = []
        calls: list[list[str]] = []

        def drifting_resolver():
            sha = f"sha{len(resolutions)}"
            resolutions.append(sha)
            return sha

        monkeypatch.setattr(validate_review, "_resolve_base_tree_rev", drifting_resolver)

        executable = _OCT_AGENT_DEFINITION
        rule = "===RULE===\nMETA:\n  TYPE::RULE\n===END===\n"

        def mock_run(cmd, *args, **kwargs):
            calls.append(list(cmd))
            joined = " ".join(cmd)
            if cmd[:2] == ["git", "diff"] and "--name-status" in cmd:
                return MagicMock(
                    stdout="R094\tgovernance/dynamic.oct.md\tnotes.md\n",
                    stderr="",
                    returncode=0,
                    check=lambda: None,
                )
            if cmd[:2] == ["git", "diff"] and "--numstat" in cmd:
                return MagicMock(
                    stdout="1\t0\tgovernance/dynamic.oct.md\tnotes.md\n",
                    stderr="",
                    returncode=0,
                    check=lambda: None,
                )
            if cmd[:2] == ["git", "show"]:
                # The FIRST resolved tree holds the executable spec; any later
                # tree holds a plain rule. Reading the wrong one downgrades.
                body = executable if joined.startswith("git show sha0:") else rule
                return MagicMock(stdout=body, stderr="", returncode=0, check=lambda: None)
            if cmd[0] == "gh":
                return MagicMock(
                    stdout=json.dumps({"body": "", "comments": []}),
                    stderr="",
                    returncode=0,
                    check=lambda: None,
                )
            return MagicMock(stdout="", stderr="", returncode=0, check=lambda: None)

        monkeypatch.setattr(subprocess, "run", mock_run)
        monkeypatch.setattr(validate_review, "check_emergency_bypass", lambda: False)
        monkeypatch.setattr(validate_review, "check_pr_comments", lambda *a, **k: (True, "ok", []))
        monkeypatch.setattr(validate_review, "_get_pr_body", lambda: "")
        monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
        return resolutions, calls

    def test_base_tree_is_resolved_exactly_once_per_run(
        self, ci_environment, monkeypatch, tmp_path
    ):
        resolutions, _ = self._install(monkeypatch, tmp_path)

        validate_review.main()

        assert len(resolutions) == 1, (
            "the base tree was resolved more than once in a single validation run; "
            f"resolutions={resolutions}. Collection and classification can therefore "
            "disagree about which tree the diff was taken against."
        )

    def test_diff_and_blob_read_use_the_same_sha(self, ci_environment, monkeypatch, tmp_path):
        resolutions, calls = self._install(monkeypatch, tmp_path)

        validate_review.main()

        diff_shas = {
            arg.split("..")[0]
            for cmd in calls
            if cmd[:2] == ["git", "diff"]
            for arg in cmd
            if ".." in arg and arg.endswith("HEAD")
        }
        show_shas = {
            cmd[2].split(":", 1)[0] for cmd in calls if cmd[:2] == ["git", "show"] and len(cmd) > 2
        }

        assert diff_shas, f"no git diff against a resolved tree was issued: {calls}"
        assert show_shas, f"no git show blob read was issued: {calls}"
        assert diff_shas == show_shas, (
            f"collection diffed {diff_shas} but classification read blobs from "
            f"{show_shas} - the diff tree and the blob tree must be the same value"
        )
        assert diff_shas == {resolutions[0]}
