"""Tests for check_pr_comments() including PR review bodies.

Contract:
- check_pr_comments() fetches `reviews` alongside `comments,body`
- Each review's .body is included in searchable_texts for APPROVED and COMMENTED states
- DISMISSED and PENDING reviews are excluded regardless of body content
- Bot reviews are excluded using the same _BOT_LOGIN_SET logic
- A review body containing a valid approval satisfies the relevant role checker
- Existing comment-path behaviour is unaffected (no regression)
"""

from __future__ import annotations

import json
import os
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_pr_data(
    *,
    body: str = "",
    comments: list[dict[str, Any]] | None = None,
    reviews: list[dict[str, Any]] | None = None,
) -> str:
    """Build the JSON string that `gh pr view` would emit."""
    return json.dumps(
        {
            "body": body,
            "comments": comments or [],
            "reviews": reviews or [],
        }
    )


def _run_check(
    pr_data_json: str,
    required_roles: set[str] | None = None,
    tier: str = "",
) -> tuple[bool, str, list[str]]:
    """Invoke check_pr_comments with a mocked subprocess and CI env."""
    mock_result = MagicMock()
    mock_result.stdout = pr_data_json

    env_patch = {"CI": "true", "PR_NUMBER": "42"}

    with (
        patch.dict(os.environ, env_patch),
        patch("scripts.validate_review.subprocess.run", return_value=mock_result),
    ):
        from scripts.validate_review import check_pr_comments

        return check_pr_comments(required_roles=required_roles, tier=tier)


# ---------------------------------------------------------------------------
# Tests: review bodies ARE included in searchable_texts
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCheckPrCommentsIncludesReviews:
    """check_pr_comments() must include PR review bodies in approval search."""

    def test_crs_approval_in_review_body_satisfies_gate(self) -> None:
        """A CRS APPROVED verdict posted as a PR review body must pass the gate."""
        pr_data = _make_pr_data(
            reviews=[
                {
                    "author": {"login": "crs-agent"},
                    "state": "COMMENTED",
                    "body": "CRS APPROVED: looks good",
                }
            ]
        )
        approved, _msg, missing = _run_check(pr_data, required_roles={"CRS"})
        assert approved is True, f"Expected approval from review body; missing={missing}"
        assert missing == []

    def test_ce_approval_in_review_body_satisfies_gate(self) -> None:
        """A CE APPROVED verdict in a PR review body must pass the CE check."""
        pr_data = _make_pr_data(
            reviews=[
                {
                    "author": {"login": "ce-agent"},
                    "state": "COMMENTED",
                    "body": "CE APPROVED: implementation is clean",
                }
            ]
        )
        approved, _msg, missing = _run_check(pr_data, required_roles={"CE"})
        assert approved is True, f"Expected approval from review body; missing={missing}"
        assert missing == []

    def test_tmg_approval_in_review_body_satisfies_gate(self) -> None:
        """A TMG APPROVED verdict in a PR review body must pass the TMG check."""
        pr_data = _make_pr_data(
            reviews=[
                {
                    "author": {"login": "tmg-agent"},
                    "state": "COMMENTED",
                    "body": "## TMG APPROVED ✅\nAll checks pass.",
                }
            ]
        )
        approved, _msg, missing = _run_check(pr_data, required_roles={"TMG"})
        assert approved is True, f"Expected approval from review body; missing={missing}"
        assert missing == []

    def test_multiple_roles_all_in_review_bodies(self) -> None:
        """Multiple roles approved via PR review bodies all satisfy the gate."""
        pr_data = _make_pr_data(
            reviews=[
                {
                    "author": {"login": "tmg-agent"},
                    "state": "COMMENTED",
                    "body": "TMG APPROVED: structural review complete",
                },
                {
                    "author": {"login": "crs-agent"},
                    "state": "COMMENTED",
                    "body": "CRS APPROVED: code quality confirmed",
                },
                {
                    "author": {"login": "ce-agent"},
                    "state": "COMMENTED",
                    "body": "CE APPROVED: engineering standards met",
                },
            ]
        )
        approved, _msg, missing = _run_check(pr_data, required_roles={"TMG", "CRS", "CE"})
        assert approved is True, f"Expected all roles approved; missing={missing}"
        assert missing == []

    def test_approvals_split_across_comments_and_reviews(self) -> None:
        """One role approved via issue comment, another via PR review body."""
        pr_data = _make_pr_data(
            comments=[
                {
                    "author": {"login": "ce-user"},
                    "body": "CE APPROVED: implementation looks correct",
                }
            ],
            reviews=[
                {
                    "author": {"login": "crs-agent"},
                    "state": "COMMENTED",
                    "body": "CRS APPROVED: passes review",
                }
            ],
        )
        approved, _msg, missing = _run_check(pr_data, required_roles={"CE", "CRS"})
        assert approved is True, f"Expected both roles satisfied; missing={missing}"
        assert missing == []

    def test_review_body_without_approval_does_not_satisfy(self) -> None:
        """A review body without an approval pattern must not satisfy the gate."""
        pr_data = _make_pr_data(
            reviews=[
                {
                    "author": {"login": "reviewer"},
                    "state": "COMMENTED",
                    "body": "Looking at this PR now, will review shortly.",
                }
            ]
        )
        approved, _msg, missing = _run_check(pr_data, required_roles={"CRS"})
        assert approved is False
        assert "CRS" in missing

    def test_missing_role_still_reported_when_review_has_different_role(self) -> None:
        """A review body satisfying CRS must not satisfy CE."""
        pr_data = _make_pr_data(
            reviews=[
                {
                    "author": {"login": "crs-agent"},
                    "state": "COMMENTED",
                    "body": "CRS APPROVED: code quality confirmed",
                }
            ]
        )
        approved, _msg, missing = _run_check(pr_data, required_roles={"CE"})
        assert approved is False
        assert "CE" in missing


# ---------------------------------------------------------------------------
# Tests: dismissed and pending reviews are excluded
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCheckPrCommentsReviewStateFiltering:
    """Only APPROVED and COMMENTED reviews must contribute to approval matching."""

    def test_dismissed_review_approval_is_ignored(self) -> None:
        """A DISMISSED review containing an approval keyword must not satisfy the gate."""
        pr_data = _make_pr_data(
            reviews=[
                {
                    "author": {"login": "crs-agent"},
                    "state": "DISMISSED",
                    "body": "CRS APPROVED: looked good at the time",
                }
            ]
        )
        approved, _msg, missing = _run_check(pr_data, required_roles={"CRS"})
        assert approved is False, "DISMISSED review must not satisfy the gate"
        assert "CRS" in missing

    def test_pending_review_approval_is_ignored(self) -> None:
        """A PENDING review (not yet submitted) must not satisfy the gate."""
        pr_data = _make_pr_data(
            reviews=[
                {
                    "author": {"login": "ce-agent"},
                    "state": "PENDING",
                    "body": "CE APPROVED: draft review",
                }
            ]
        )
        approved, _msg, missing = _run_check(pr_data, required_roles={"CE"})
        assert approved is False, "PENDING review must not satisfy the gate"
        assert "CE" in missing

    def test_commented_review_approval_is_included(self) -> None:
        """A COMMENTED review (self-review state) must satisfy the gate."""
        pr_data = _make_pr_data(
            reviews=[
                {
                    "author": {"login": "crs-agent"},
                    "state": "COMMENTED",
                    "body": "CRS APPROVED: review complete",
                }
            ]
        )
        approved, _msg, missing = _run_check(pr_data, required_roles={"CRS"})
        assert approved is True, "COMMENTED review must satisfy the gate"
        assert missing == []

    def test_approved_state_review_is_included(self) -> None:
        """A review with state=APPROVED must also satisfy the gate."""
        pr_data = _make_pr_data(
            reviews=[
                {
                    "author": {"login": "crs-agent"},
                    "state": "APPROVED",
                    "body": "CRS APPROVED: full approval",
                }
            ]
        )
        approved, _msg, missing = _run_check(pr_data, required_roles={"CRS"})
        assert approved is True, "APPROVED-state review must satisfy the gate"
        assert missing == []

    def test_dismissed_review_does_not_block_valid_comment_approval(self) -> None:
        """A dismissed review for a role must not prevent a valid comment from satisfying it."""
        pr_data = _make_pr_data(
            comments=[
                {
                    "author": {"login": "crs-user"},
                    "body": "CRS APPROVED: approved via comment",
                }
            ],
            reviews=[
                {
                    "author": {"login": "crs-agent"},
                    "state": "DISMISSED",
                    "body": "CRS APPROVED: earlier dismissed review",
                }
            ],
        )
        approved, _msg, missing = _run_check(pr_data, required_roles={"CRS"})
        assert approved is True, "Valid comment approval must satisfy gate despite dismissed review"
        assert missing == []


# ---------------------------------------------------------------------------
# Tests: bot reviews are excluded
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCheckPrCommentsBotReviewExclusion:
    """Bot-authored PR review bodies must be excluded from approval matching."""

    def test_bot_review_approval_is_ignored(self) -> None:
        """A CRS APPROVED in a review from a known bot must not satisfy the gate."""
        pr_data = _make_pr_data(
            reviews=[
                {
                    "author": {"login": "github-actions"},
                    "state": "COMMENTED",
                    "body": "CRS APPROVED: auto-generated review",
                }
            ]
        )
        approved, _msg, missing = _run_check(pr_data, required_roles={"CRS"})
        assert approved is False, "Bot review approval must not satisfy the gate"
        assert "CRS" in missing

    def test_copilot_review_approval_is_ignored(self) -> None:
        """A CE APPROVED in a review from github-copilot bot must be excluded."""
        pr_data = _make_pr_data(
            reviews=[
                {
                    "author": {"login": "Copilot"},
                    "state": "COMMENTED",
                    "body": "CE APPROVED: copilot auto-review",
                }
            ]
        )
        approved, _msg, missing = _run_check(pr_data, required_roles={"CE"})
        assert approved is False, "Copilot bot review must not satisfy the gate"
        assert "CE" in missing

    def test_bot_suffix_review_approval_is_ignored(self) -> None:
        """A review from any [bot]-suffixed account must be excluded."""
        pr_data = _make_pr_data(
            reviews=[
                {
                    "author": {"login": "some-new-bot[bot]"},
                    "state": "COMMENTED",
                    "body": "CRS APPROVED: auto-review",
                }
            ]
        )
        approved, _msg, missing = _run_check(pr_data, required_roles={"CRS"})
        assert approved is False, "[bot]-suffixed review must not satisfy the gate"
        assert "CRS" in missing

    def test_human_review_with_bot_marker_is_excluded(self) -> None:
        """A review body containing the review-gate-status marker must be excluded."""
        pr_data = _make_pr_data(
            reviews=[
                {
                    "author": {"login": "some-human"},
                    "state": "COMMENTED",
                    "body": "<!-- review-gate-status -->\nCRS APPROVED: injected",
                }
            ]
        )
        approved, _msg, missing = _run_check(pr_data, required_roles={"CRS"})
        assert approved is False, "Status-marker review must not satisfy the gate"
        assert "CRS" in missing

    def test_human_non_bot_review_is_included(self) -> None:
        """A review from a non-bot human account must be included."""
        pr_data = _make_pr_data(
            reviews=[
                {
                    "author": {"login": "shaun"},
                    "state": "COMMENTED",
                    "body": "CRS APPROVED: reviewed by human",
                }
            ]
        )
        approved, _msg, missing = _run_check(pr_data, required_roles={"CRS"})
        assert approved is True, "Human review must satisfy the gate"
        assert missing == []


# ---------------------------------------------------------------------------
# Tests: no regression on existing comment path
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCheckPrCommentsNoRegression:
    """Existing comment-based approval path must still work after the fix."""

    def test_comment_approval_still_works(self) -> None:
        """CRS approval in an issue comment still satisfies the gate (no regression)."""
        pr_data = _make_pr_data(
            comments=[
                {
                    "author": {"login": "crs-user"},
                    "body": "CRS APPROVED: all good",
                }
            ]
        )
        approved, _msg, missing = _run_check(pr_data, required_roles={"CRS"})
        assert approved is True
        assert missing == []

    def test_pr_body_approval_still_works(self) -> None:
        """CRS approval in the PR body itself still satisfies the gate."""
        pr_data = _make_pr_data(body="CRS APPROVED: in the PR description")
        approved, _msg, missing = _run_check(pr_data, required_roles={"CRS"})
        assert approved is True
        assert missing == []

    def test_empty_reviews_field_does_not_crash(self) -> None:
        """When reviews key is absent from API response, the gate must not crash."""
        # Simulate old response format without reviews key
        pr_data_dict = {"body": "", "comments": []}
        pr_data = json.dumps(pr_data_dict)
        approved, _msg, missing = _run_check(pr_data, required_roles={"CRS"})
        assert approved is False  # No approval present
        assert "CRS" in missing
