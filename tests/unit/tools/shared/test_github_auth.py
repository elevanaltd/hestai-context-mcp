"""Direct unit tests for the shared GitHub token resolution helper.

This module is the single source of truth test for
``hestai_context_mcp.tools.shared.github_auth.resolve_github_token``. The
former duplicated copies in ``governance.linker`` and ``submit_review`` were
extracted into this shared module; these tests exercise the implementation
body directly (patching ``subprocess.run`` on the shared module).

Behavioral contract (preserved from the pre-extraction copies):
  Three-tier lookup, first hit wins:
    1. ``GITHUB_TOKEN`` environment variable.
    2. ``GH_TOKEN`` environment variable.
    3. ``gh auth token`` subprocess (5 s timeout), with a shape sanity guard.

  Any failure in tier 3 (gh missing, non-zero exit, empty/whitespace output,
  malformed shape, timeout, or unexpected exception) collapses to ``None``
  rather than raising -- the stdio MCP server must never crash on auth.

  Security: the resolved value is opaque; it is never logged or surfaced.
"""

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from hestai_context_mcp.tools.shared.github_auth import (
    AUTH_ERROR_MESSAGE,
    resolve_github_token,
)

_MOD = "hestai_context_mcp.tools.shared.github_auth"


def _fake_completed(returncode: int, stdout: str = "", stderr: str = "") -> MagicMock:
    """Build a stand-in for subprocess.CompletedProcess."""
    result = MagicMock()
    result.returncode = returncode
    result.stdout = stdout
    result.stderr = stderr
    return result


class TestResolveGithubToken:
    @pytest.mark.unit
    def test_github_token_env_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """GITHUB_TOKEN is returned without invoking gh (tier 1)."""
        monkeypatch.setenv("GITHUB_TOKEN", "env-token-value")
        monkeypatch.delenv("GH_TOKEN", raising=False)
        with patch(f"{_MOD}.subprocess.run") as run:
            assert resolve_github_token() == "env-token-value"
            run.assert_not_called()

    @pytest.mark.unit
    def test_gh_token_env_used_when_github_token_absent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """GH_TOKEN is the second-tier source."""
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.setenv("GH_TOKEN", "gh-env-token")
        with patch(f"{_MOD}.subprocess.run") as run:
            assert resolve_github_token() == "gh-env-token"
            run.assert_not_called()

    @pytest.mark.unit
    def test_gh_subprocess_success_with_valid_shape(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A well-shaped token from ``gh auth token`` is accepted (tier 3)."""
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.delenv("GH_TOKEN", raising=False)
        valid = "ghp_" + "A" * 36
        with patch(f"{_MOD}.subprocess.run", return_value=_fake_completed(0, stdout=valid)):
            assert resolve_github_token() == valid

    @pytest.mark.unit
    def test_gh_subprocess_accepts_fine_grained_pat(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Fine-grained ``github_pat_`` tokens are accepted (cubic P1, PR #35)."""
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.delenv("GH_TOKEN", raising=False)
        valid = "github_pat_" + "B" * 30
        with patch(f"{_MOD}.subprocess.run", return_value=_fake_completed(0, stdout=valid)):
            assert resolve_github_token() == valid

    @pytest.mark.unit
    def test_gh_subprocess_accepts_classic_hex_pat(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Classic 40-char lowercase hex PATs are accepted."""
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.delenv("GH_TOKEN", raising=False)
        valid = "a" * 40
        with patch(f"{_MOD}.subprocess.run", return_value=_fake_completed(0, stdout=valid)):
            assert resolve_github_token() == valid

    @pytest.mark.unit
    def test_gh_subprocess_strips_trailing_whitespace(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A trailing newline from ``gh auth token`` stdout is stripped."""
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.delenv("GH_TOKEN", raising=False)
        valid = "ghp_" + "C" * 36
        with patch(f"{_MOD}.subprocess.run", return_value=_fake_completed(0, stdout=f"{valid}\n")):
            assert resolve_github_token() == valid

    @pytest.mark.unit
    def test_gh_subprocess_nonzero_returncode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Non-zero exit from gh -> None."""
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.delenv("GH_TOKEN", raising=False)
        with patch(
            f"{_MOD}.subprocess.run", return_value=_fake_completed(1, stderr="not logged in")
        ):
            assert resolve_github_token() is None

    @pytest.mark.unit
    def test_gh_subprocess_empty_output(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Whitespace-only stdout from gh -> None."""
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.delenv("GH_TOKEN", raising=False)
        with patch(f"{_MOD}.subprocess.run", return_value=_fake_completed(0, stdout="   ")):
            assert resolve_github_token() is None

    @pytest.mark.unit
    def test_gh_subprocess_malformed_shape_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A token that does not match the shape regex -> None (defensive)."""
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.delenv("GH_TOKEN", raising=False)
        with patch(
            f"{_MOD}.subprocess.run",
            return_value=_fake_completed(0, stdout="not-a-real-token-shape"),
        ):
            assert resolve_github_token() is None

    @pytest.mark.unit
    def test_gh_subprocess_timeout_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A TimeoutExpired from the gh subprocess is swallowed -> None."""
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.delenv("GH_TOKEN", raising=False)
        with patch(
            f"{_MOD}.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="gh", timeout=5),
        ):
            assert resolve_github_token() is None

    @pytest.mark.unit
    def test_gh_subprocess_filenotfound_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """gh binary missing (FileNotFoundError) is swallowed -> None."""
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.delenv("GH_TOKEN", raising=False)
        with patch(f"{_MOD}.subprocess.run", side_effect=FileNotFoundError("gh")):
            assert resolve_github_token() is None

    @pytest.mark.unit
    def test_resolved_token_never_in_error_message(self) -> None:
        """The shared auth error message lists the tiers but no token value."""
        assert "GITHUB_TOKEN" in AUTH_ERROR_MESSAGE
        assert "GH_TOKEN" in AUTH_ERROR_MESSAGE
        assert "gh auth token" in AUTH_ERROR_MESSAGE
