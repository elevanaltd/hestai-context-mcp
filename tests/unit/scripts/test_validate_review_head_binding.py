"""Head-bound, latest-verdict-per-role peer approvals (issue #201).

Contract for the peer roles TMG/CRS/CE/CIV/PE/SR (the role-checker path of
check_pr_comments, NOT the TIER_1_SELF self-review path):

1. HEAD BINDING: only a ``<!-- review: {...} -->`` footer clears a role, and only
   when its ``sha`` is a string of >=7 hex characters that the PR head SHA starts
   with. A null, missing, short or mismatched sha clears nothing.
2. LATEST VERDICT PER ROLE AT HEAD: among head-bound footers for a role, ordered
   by time across issue comments (``createdAt``) and PR Reviews
   (``submittedAt``), the last one decides. It clears the role only if it is
   APPROVED or GO; a later BLOCKED/CONDITIONAL at head revokes an earlier
   approval. On a timestamp tie a non-approval wins (fail closed).
3. FOOTERLESS PATH RETIRED: visible ``ROLE APPROVED``/``ROLE GO`` text without a
   footer clears no peer role, in comments, PR Review bodies or the PR body.
4. SYMMETRIC MISMATCH: a comment whose footer verdict is NOT an approval but
   whose visible text reads as an approval for the same role is disqualified
   (dropped and reported), mirroring the existing approval-footer check.

TIER_1_SELF behaviour is unchanged by #201 and is pinned at the bottom.
"""

from __future__ import annotations

import json
import os
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

HEAD = "0123456789abcdef0123456789abcdef01234567"
OLD_HEAD = "fedcba9876543210fedcba9876543210fedcba98"

T1 = "2026-11-16T10:00:00Z"
T2 = "2026-11-16T11:00:00Z"
T3 = "2026-11-16T12:00:00Z"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _footer(role: str, verdict: str, sha: Any, provider: str = "goose") -> str:
    """Render the metadata footer submit_review emits (review_formats.py)."""
    payload = {"role": role, "provider": provider, "verdict": verdict, "sha": sha}
    return f"<!-- review: {json.dumps(payload)} -->"


def _verdict(role: str, verdict: str, sha: Any, text: str | None = None) -> str:
    """A footer-bearing review body whose visible header agrees with its footer."""
    visible = text if text is not None else f"{role} {verdict}: assessment"
    return f"{visible}\n{_footer(role, verdict, sha)}"


def _comment(body: str, at: str = T1, login: str = "alice") -> dict[str, Any]:
    return {"author": {"login": login}, "body": body, "createdAt": at}


def _review(
    body: str, at: str = T1, state: str = "COMMENTED", login: str = "bob"
) -> dict[str, Any]:
    return {"author": {"login": login}, "body": body, "state": state, "submittedAt": at}


def _check(
    *,
    body: str = "",
    comments: list[dict[str, Any]] | None = None,
    reviews: list[dict[str, Any]] | None = None,
    required_roles: set[str] | None = None,
    tier: str = "",
    head: str = HEAD,
) -> tuple[bool, str, list[str]]:
    """Run check_pr_comments against a faked ``gh pr view`` and a fixed head SHA."""
    gh_result = MagicMock()
    gh_result.stdout = json.dumps(
        {"body": body, "comments": comments or [], "reviews": reviews or []}
    )
    with (
        patch.dict(os.environ, {"CI": "true", "PR_NUMBER": "42"}),
        patch("scripts.validate_review.subprocess.run", return_value=gh_result),
        patch("scripts.validate_review._get_head_sha", return_value=head),
    ):
        from scripts.validate_review import check_pr_comments

        return check_pr_comments(
            required_roles={"CE"} if required_roles is None else required_roles, tier=tier
        )


# ---------------------------------------------------------------------------
# The six probe cases (HO measurement at f37458e3: all returned approved=True)
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.security
class TestProbeCases:
    def test_body_only_footerless_approval_does_not_clear(self) -> None:
        approved, msg, missing = _check(body="CE APPROVED: looks good")
        assert approved is False, msg
        assert missing == ["CE"]

    def test_stale_sha_approval_footer_does_not_clear(self) -> None:
        approved, msg, missing = _check(comments=[_comment(_verdict("CE", "APPROVED", "aaaaaaa"))])
        assert approved is False, msg
        assert missing == ["CE"]

    def test_approved_then_blocked_at_head_is_revoked(self) -> None:
        approved, msg, missing = _check(
            comments=[
                _comment(_verdict("CE", "APPROVED", HEAD[:7]), at=T1),
                _comment(_verdict("CE", "BLOCKED", HEAD[:7]), at=T2),
            ]
        )
        assert approved is False, msg
        assert missing == ["CE"]

    def test_blocked_footer_with_visible_approval_is_disqualified(self) -> None:
        body = _verdict("CE", "BLOCKED", HEAD[:7], text="CE APPROVED: ok")
        approved, msg, missing = _check(comments=[_comment(body)])
        assert approved is False, msg
        assert missing == ["CE"]
        assert "spoofing" in msg.lower(), f"mismatch must be surfaced: {msg}"

    def test_null_sha_approval_footer_does_not_clear(self) -> None:
        approved, msg, missing = _check(comments=[_comment(_verdict("CE", "APPROVED", None))])
        assert approved is False, msg
        assert missing == ["CE"]

    def test_fresh_head_matching_approval_clears(self) -> None:
        """Positive control."""
        approved, msg, missing = _check(comments=[_comment(_verdict("CE", "APPROVED", HEAD[:7]))])
        assert approved is True, msg
        assert missing == []


# ---------------------------------------------------------------------------
# Head binding
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.security
class TestHeadBinding:
    def test_approval_at_old_head_without_re_review_is_missing(self) -> None:
        approved, msg, missing = _check(
            comments=[_comment(_verdict("CE", "APPROVED", OLD_HEAD[:7]))], head=HEAD
        )
        assert approved is False, msg
        assert missing == ["CE"]

    def test_re_review_at_new_head_clears(self) -> None:
        approved, msg, missing = _check(
            comments=[
                _comment(_verdict("CE", "APPROVED", OLD_HEAD[:7]), at=T1),
                _comment(_verdict("CE", "APPROVED", HEAD[:7]), at=T2),
            ],
            head=HEAD,
        )
        assert approved is True, msg
        assert missing == []

    def test_blocked_at_old_head_does_not_revoke_approval_at_head(self) -> None:
        """Verdicts at other SHAs are ignored entirely, revocations included."""
        approved, msg, _ = _check(
            comments=[
                _comment(_verdict("CE", "APPROVED", HEAD[:7]), at=T1),
                _comment(_verdict("CE", "BLOCKED", OLD_HEAD[:7]), at=T2),
            ]
        )
        assert approved is True, msg

    def test_seven_char_prefix_clears(self) -> None:
        approved, msg, _ = _check(comments=[_comment(_verdict("CE", "APPROVED", HEAD[:7]))])
        assert approved is True, msg

    def test_full_length_sha_clears(self) -> None:
        approved, msg, _ = _check(comments=[_comment(_verdict("CE", "APPROVED", HEAD))])
        assert approved is True, msg

    def test_six_char_prefix_does_not_clear(self) -> None:
        approved, msg, missing = _check(comments=[_comment(_verdict("CE", "APPROVED", HEAD[:6]))])
        assert approved is False, msg
        assert missing == ["CE"]

    def test_missing_sha_key_does_not_clear(self) -> None:
        body = 'CE APPROVED: ok\n<!-- review: {"role": "CE", "verdict": "APPROVED"} -->'
        approved, msg, missing = _check(comments=[_comment(body)])
        assert approved is False, msg
        assert missing == ["CE"]

    def test_non_hex_sha_does_not_clear(self) -> None:
        approved, msg, _ = _check(comments=[_comment(_verdict("CE", "APPROVED", "zzzzzzz"))])
        assert approved is False, msg

    def test_unknown_head_clears_nothing(self) -> None:
        """git rev-parse failure ('unknown') must fail closed, never match."""
        approved, msg, missing = _check(
            comments=[_comment(_verdict("CE", "APPROVED", HEAD[:7]))], head="unknown"
        )
        assert approved is False, msg
        assert missing == ["CE"]


# ---------------------------------------------------------------------------
# Latest verdict per role at head, ordered across comments and PR Reviews
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.security
class TestLatestVerdictAcrossSources:
    def test_comment_approved_then_later_review_blocked_is_missing(self) -> None:
        approved, msg, missing = _check(
            comments=[_comment(_verdict("CE", "APPROVED", HEAD[:7]), at=T1)],
            reviews=[_review(_verdict("CE", "BLOCKED", HEAD[:7]), at=T2)],
        )
        assert approved is False, msg
        assert missing == ["CE"]

    def test_review_blocked_then_later_comment_approved_clears(self) -> None:
        approved, msg, missing = _check(
            comments=[_comment(_verdict("CE", "APPROVED", HEAD[:7]), at=T2)],
            reviews=[_review(_verdict("CE", "BLOCKED", HEAD[:7]), at=T1)],
        )
        assert approved is True, msg
        assert missing == []

    def test_order_is_by_time_not_by_list_position(self) -> None:
        """The BLOCKED comment is listed first but posted last."""
        approved, msg, _ = _check(
            comments=[
                _comment(_verdict("CE", "BLOCKED", HEAD[:7]), at=T3),
                _comment(_verdict("CE", "APPROVED", HEAD[:7]), at=T1),
            ]
        )
        assert approved is False, msg

    def test_conditional_after_approval_revokes(self) -> None:
        approved, msg, _ = _check(
            comments=[
                _comment(_verdict("CE", "APPROVED", HEAD[:7]), at=T1),
                _comment(_verdict("CE", "CONDITIONAL", HEAD[:7]), at=T2),
            ]
        )
        assert approved is False, msg

    def test_go_verdict_clears(self) -> None:
        approved, msg, _ = _check(comments=[_comment(_verdict("CE", "GO", HEAD[:7]))])
        assert approved is True, msg

    def test_timestamp_tie_between_approval_and_block_fails_closed(self) -> None:
        approved, msg, _ = _check(
            comments=[_comment(_verdict("CE", "APPROVED", HEAD[:7]), at=T2)],
            reviews=[_review(_verdict("CE", "BLOCKED", HEAD[:7]), at=T2)],
        )
        assert approved is False, msg

    def test_timestamp_tie_with_block_listed_first_still_fails_closed(self) -> None:
        """Pins the tie-break itself: with BLOCKED listed BEFORE APPROVED at the same
        timestamp, insertion order alone would leave APPROVED last and clear."""
        approved, msg, missing = _check(
            comments=[
                _comment(_verdict("CE", "BLOCKED", HEAD[:7]), at=T2),
                _comment(_verdict("CE", "APPROVED", HEAD[:7]), at=T2),
            ]
        )
        assert approved is False, msg
        assert missing == ["CE"]

    def test_other_roles_verdict_does_not_revoke(self) -> None:
        approved, msg, _ = _check(
            comments=[
                _comment(_verdict("CE", "APPROVED", HEAD[:7]), at=T1),
                _comment(_verdict("CRS", "BLOCKED", HEAD[:7]), at=T2),
            ]
        )
        assert approved is True, msg


# ---------------------------------------------------------------------------
# Footerless path retired (comments and PR Review bodies)
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.security
class TestFooterlessRetired:
    def test_footer_bearing_review_body_clears(self) -> None:
        approved, msg, _ = _check(reviews=[_review(_verdict("CE", "APPROVED", HEAD[:7]))])
        assert approved is True, msg

    def test_footerless_review_body_does_not_clear(self) -> None:
        approved, msg, missing = _check(reviews=[_review("CE APPROVED: looks fine")])
        assert approved is False, msg
        assert missing == ["CE"]

    def test_footerless_comment_does_not_clear(self) -> None:
        approved, msg, missing = _check(comments=[_comment("CE APPROVED: looks fine")])
        assert approved is False, msg
        assert missing == ["CE"]

    def test_footerless_go_comment_does_not_clear(self) -> None:
        approved, msg, _ = _check(comments=[_comment("CE GO: ship it")])
        assert approved is False, msg

    def test_legacy_gr_text_no_longer_clears_sr(self) -> None:
        approved, msg, missing = _check(
            comments=[_comment("GR APPROVED: governance fine")], required_roles={"SR"}
        )
        assert approved is False, msg
        assert missing == ["SR"]

    def test_sr_footer_at_head_clears_sr(self) -> None:
        approved, msg, _ = _check(
            comments=[_comment(_verdict("SR", "APPROVED", HEAD[:7]))], required_roles={"SR"}
        )
        assert approved is True, msg

    @pytest.mark.parametrize("role", ["TMG", "CRS", "CE", "CIV", "PE", "SR"])
    def test_every_peer_role_rejects_footerless_text(self, role: str) -> None:
        approved, msg, missing = _check(
            comments=[_comment(f"{role} APPROVED: fine")], required_roles={role}
        )
        assert approved is False, msg
        assert missing == [role]

    @pytest.mark.parametrize("role", ["TMG", "CRS", "CE", "CIV", "PE", "SR"])
    def test_every_peer_role_clears_on_head_footer(self, role: str) -> None:
        approved, msg, _ = _check(
            comments=[_comment(_verdict(role, "APPROVED", HEAD[:7]))], required_roles={role}
        )
        assert approved is True, msg


# ---------------------------------------------------------------------------
# Symmetric mismatch (#201 item 2)
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.security
class TestSymmetricMismatch:
    def test_conditional_footer_with_visible_go_is_disqualified(self) -> None:
        body = _verdict("CE", "CONDITIONAL", HEAD[:7], text="CE GO: fine")
        approved, msg, _ = _check(comments=[_comment(body)])
        assert approved is False, msg
        assert "spoofing" in msg.lower(), msg

    def test_mismatched_comment_does_not_block_other_genuine_approvals(self) -> None:
        """#155 disqualify-don't-abort: validation continues over the rest."""
        poisoned = _verdict("CRS", "BLOCKED", HEAD[:7], text="CRS APPROVED: ok")
        approved, msg, missing = _check(
            comments=[_comment(poisoned), _comment(_verdict("CE", "APPROVED", HEAD[:7]))]
        )
        assert approved is True, msg
        assert missing == []
        assert "spoofing" in msg.lower(), msg

    def test_disqualified_block_still_revokes_earlier_approval_at_head(self) -> None:
        """Fail closed (cubic P2 on PR #295): disqualifying a non-approval must not
        resurrect the role's earlier head approval. The comment clears nothing, but
        its non-approval verdict still counts as the role's latest at head."""
        blocked = _verdict(
            "CE", "BLOCKED", HEAD[:7], text="CE BLOCKED: fix X first\nCE APPROVED once X lands"
        )
        approved, msg, missing = _check(
            comments=[
                _comment(_verdict("CE", "APPROVED", HEAD[:7]), at=T1),
                _comment(blocked, at=T2),
            ]
        )
        assert approved is False, msg
        assert missing == ["CE"]
        assert "spoofing" in msg.lower(), msg

    def test_agreeing_blocked_comment_is_not_disqualified(self) -> None:
        approved, msg, _ = _check(comments=[_comment(_verdict("CE", "BLOCKED", HEAD[:7]))])
        assert approved is False, msg
        assert "spoofing" not in msg.lower(), msg


# ---------------------------------------------------------------------------
# REGRESSION PIN: TIER_1_SELF outcomes are unchanged by #201
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTier1SelfUnchanged:
    def _self(self, *comments: dict[str, Any], body: str = "") -> tuple[bool, str, list[str]]:
        return _check(body=body, comments=list(comments), required_roles=set(), tier="TIER_1_SELF")

    def test_footerless_ho_reviewed_comment_clears(self) -> None:
        approved, msg, missing = self._self(
            _comment("HO (Claude Opus 5.5) REVIEWED: Self-review (TIER_1_SELF), 4-line change")
        )
        assert approved is True, msg
        assert missing == []

    def test_ho_reviewed_with_footer_as_posted_on_pr_291_clears(self) -> None:
        body = (
            "HO (Claude Opus 5.5) REVIEWED: Self-review (TIER_1_SELF), 4-line change\n"
            '<!-- review: {"role":"HO","provider":"claude","verdict":"REVIEWED","sha":"0101a60"} -->'
        )
        approved, msg, _ = self._self(_comment(body))
        assert approved is True, msg

    def test_footerless_il_self_reviewed_comment_clears(self) -> None:
        approved, msg, missing = self._self(_comment("IL SELF-REVIEWED: fixed a typo"))
        assert approved is True, msg
        assert missing == []

    def test_footerless_crs_approval_still_satisfies_self_review(self) -> None:
        approved, msg, _ = self._self(_comment("CRS APPROVED: looks good"))
        assert approved is True, msg

    def test_self_review_in_pr_body_still_clears(self) -> None:
        approved, msg, _ = self._self(body="IL SELF-REVIEWED: done")
        assert approved is True, msg

    def test_head_binding_does_not_apply_to_self_review(self) -> None:
        """A self-review footer at another SHA still clears TIER_1_SELF."""
        approved, msg, _ = self._self(_comment(_verdict("IL", "SELF-REVIEWED", OLD_HEAD[:7])))
        assert approved is True, msg

    def test_missing_self_review_still_fails(self) -> None:
        approved, msg, _ = self._self(_comment("just a note"))
        assert approved is False, msg


# ---------------------------------------------------------------------------
# Pre-review findings on PR #295 (/code-review high)
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.security
class TestChangesRequestedReviewRevokes:
    """A GitHub 'Request changes' review is the natural way to block. Its head-bound
    non-approval footer must count as the role's latest verdict, and it must never
    clear anything itself."""

    def test_changes_requested_block_revokes_earlier_head_approval(self) -> None:
        approved, msg, missing = _check(
            comments=[_comment(_verdict("CE", "APPROVED", HEAD[:7]), at=T1)],
            reviews=[
                _review(_verdict("CE", "BLOCKED", HEAD[:7]), at=T2, state="CHANGES_REQUESTED")
            ],
        )
        assert approved is False, msg
        assert missing == ["CE"]

    def test_changes_requested_review_never_clears(self) -> None:
        approved, msg, missing = _check(
            reviews=[
                _review(_verdict("CE", "APPROVED", HEAD[:7]), at=T1, state="CHANGES_REQUESTED")
            ]
        )
        assert approved is False, msg
        assert missing == ["CE"]

    def test_later_approval_after_changes_requested_clears(self) -> None:
        approved, msg, _ = _check(
            comments=[_comment(_verdict("CE", "APPROVED", HEAD[:7]), at=T2)],
            reviews=[
                _review(_verdict("CE", "BLOCKED", HEAD[:7]), at=T1, state="CHANGES_REQUESTED")
            ],
        )
        assert approved is True, msg

    def test_changes_requested_review_still_excluded_from_self_review(self) -> None:
        """Pin: TIER_1_SELF still ignores CHANGES_REQUESTED review bodies."""
        approved, msg, _ = _check(
            reviews=[_review("IL SELF-REVIEWED: done", state="CHANGES_REQUESTED")],
            required_roles=set(),
            tier="TIER_1_SELF",
        )
        assert approved is False, msg


@pytest.mark.unit
@pytest.mark.security
class TestMalformedFooterCannotCrashGate:
    """A footer whose role or verdict is not a string (e.g. a JSON list) is
    malformed: it clears nothing and must not crash the gate (a crash would let
    one comment block every approval, the #155 class)."""

    @pytest.mark.parametrize(
        "payload",
        [
            '{"role": "XX", "verdict": ["x"], "sha": "%s"}',
            '{"role": "CE", "verdict": ["x"], "sha": "%s"}',
            '{"role": ["CE"], "verdict": "BLOCKED", "sha": "%s"}',
        ],
    )
    def test_malformed_footer_is_ignored(self, payload: str) -> None:
        poison = f"looks fine\n<!-- review: {payload % HEAD[:7]} -->"
        approved, msg, missing = _check(
            comments=[
                _comment(_verdict("CE", "APPROVED", HEAD[:7]), at=T1),
                _comment(poison, at=T2),
            ]
        )
        assert approved is True, msg
        assert missing == []
