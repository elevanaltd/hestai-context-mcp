"""Tests for focus resolution logic.

Tests the priority chain: explicit > github_issue > branch > default.
"""

from hestai_context_mcp.core.focus import resolve_focus, resolve_focus_from_branch


class TestResolveFocusFromBranch:
    """Test branch pattern matching for focus resolution."""

    def test_issue_branch_hash_pattern(self):
        """Branch with #XX pattern resolves to github_issue."""
        result = resolve_focus_from_branch("fix-#42-login-bug")
        assert result is not None
        assert result["value"] == "issue-42"
        assert result["source"] == "github_issue"

    def test_issue_branch_issue_prefix(self):
        """Branch with issue-XX pattern resolves to github_issue."""
        result = resolve_focus_from_branch("issue-123")
        assert result is not None
        assert result["value"] == "issue-123"
        assert result["source"] == "github_issue"

    def test_issue_branch_issues_prefix(self):
        """Branch with issues-XX pattern resolves to github_issue."""
        result = resolve_focus_from_branch("issues-456")
        assert result is not None
        assert result["value"] == "issue-456"
        assert result["source"] == "github_issue"

    def test_feat_branch(self):
        """Branch with feat/ prefix resolves to branch source."""
        result = resolve_focus_from_branch("feat/add-login")
        assert result is not None
        assert result["value"] == "feat: add-login"
        assert result["source"] == "branch"

    def test_fix_branch(self):
        """Branch with fix/ prefix resolves to branch source."""
        result = resolve_focus_from_branch("fix/broken-auth")
        assert result is not None
        assert result["value"] == "fix: broken-auth"
        assert result["source"] == "branch"

    def test_chore_branch(self):
        """Branch with chore/ prefix resolves to branch source."""
        result = resolve_focus_from_branch("chore/update-deps")
        assert result is not None
        assert result["value"] == "chore: update-deps"
        assert result["source"] == "branch"

    def test_refactor_branch(self):
        """Branch with refactor/ prefix resolves to branch source."""
        result = resolve_focus_from_branch("refactor/simplify-api")
        assert result is not None
        assert result["value"] == "refactor: simplify-api"
        assert result["source"] == "branch"

    def test_docs_branch(self):
        """Branch with docs/ prefix resolves to branch source."""
        result = resolve_focus_from_branch("docs/update-readme")
        assert result is not None
        assert result["value"] == "docs: update-readme"
        assert result["source"] == "branch"

    def test_unrecognized_branch_returns_none(self):
        """Unrecognized branch pattern returns None."""
        result = resolve_focus_from_branch("main")
        assert result is None

    def test_empty_branch_returns_none(self):
        """Empty branch string returns None."""
        result = resolve_focus_from_branch("")
        assert result is None

    def test_issue_takes_priority_over_feature_prefix(self):
        """Issue pattern takes priority when branch has both patterns."""
        result = resolve_focus_from_branch("feat/issue-99-something")
        assert result is not None
        assert result["value"] == "issue-99"
        assert result["source"] == "github_issue"


class TestResolveFocus:
    """Test the full focus resolution priority chain."""

    def test_explicit_focus_highest_priority(self):
        """Explicit focus always wins."""
        result = resolve_focus(explicit_focus="my-task", branch="feat/something")
        assert result["value"] == "my-task"
        assert result["source"] == "explicit"

    def test_explicit_focus_strips_whitespace(self):
        """Explicit focus is stripped of whitespace."""
        result = resolve_focus(explicit_focus="  my-task  ")
        assert result["value"] == "my-task"
        assert result["source"] == "explicit"

    def test_empty_explicit_falls_through(self):
        """Empty/whitespace explicit focus falls through to branch."""
        result = resolve_focus(explicit_focus="   ", branch="feat/something")
        assert result["value"] == "feat: something"
        assert result["source"] == "branch"

    def test_none_explicit_falls_through(self):
        """None explicit focus falls through to branch."""
        result = resolve_focus(explicit_focus=None, branch="issue-42")
        assert result["value"] == "issue-42"
        assert result["source"] == "github_issue"

    def test_no_explicit_no_branch_returns_default(self):
        """No explicit and no branch returns general default."""
        result = resolve_focus()
        assert result["value"] == "general"
        assert result["source"] == "default"

    def test_unrecognized_branch_returns_default(self):
        """Unrecognized branch falls through to default."""
        result = resolve_focus(branch="main")
        assert result["value"] == "general"
        assert result["source"] == "default"

    def test_none_branch_returns_default(self):
        """None branch falls through to default."""
        result = resolve_focus(explicit_focus=None, branch=None)
        assert result["value"] == "general"
        assert result["source"] == "default"
