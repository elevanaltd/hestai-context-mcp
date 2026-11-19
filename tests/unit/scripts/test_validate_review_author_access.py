"""Review verdicts count only from accounts with write access to the repository.

check_pr_comments collects the sources for peer-role verdicts and for the
TIER_1_SELF / HO REVIEWED self-review lines. A comment or PR Review is a source
only when its author has write access (write, maintain or admin) to the
repository being gated. Bot accounts never count.

The mechanism is the collaborator permission endpoint, called through
``gh api repos/{owner}/{repo}/collaborators/<login>/permission``. gh resolves
``{owner}/{repo}`` the same way it resolves the repository for
``gh pr view``, so the lookup targets the gated repository in local mode and in
remote mode alike. The response shapes below are the ones the default
GITHUB_TOKEN returned in Actions run 44496751555 (both permission blocks):

    shaunbuswell       -> {"permission": "admin", "user": {"type": "User"}}
    cubic-dev-ai       -> {"permission": "read",  "user": {"type": "User"}}
    cubic-dev-ai[bot]  -> {"permission": "none",  "user": {"type": "Bot"}}
    octocat            -> {"permission": "read",  "user": {"type": "User"}}

A lookup that errors fails closed (the author does not count) and loudly (the
validator output names the failed lookup).

These tests fake only the gh boundary (subprocess.run), so they exercise the
real eligibility logic end to end.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

HEAD = "0123456789abcdef0123456789abcdef01234567"
T1 = "2026-11-19T10:00:00Z"
T2 = "2026-11-19T11:00:00Z"

_PERMISSION_PATH = re.compile(
    r"^repos/\{owner\}/\{repo\}/collaborators/(?P<login>[^/]+)/permission$"
)


def _footer(role: str, verdict: str, sha: str = HEAD[:7]) -> str:
    payload = {"role": role, "provider": "goose", "verdict": verdict, "sha": sha}
    return f"<!-- review: {json.dumps(payload)} -->"


def _verdict(role: str, verdict: str = "APPROVED") -> str:
    """A head-bound review body whose visible header agrees with its footer."""
    return f"{role} {verdict}: assessment\n{_footer(role, verdict)}"


def _comment(body: str, login: str, at: str = T1) -> dict[str, Any]:
    return {"author": {"login": login}, "body": body, "createdAt": at}


def _review(body: str, login: str, at: str = T1, state: str = "COMMENTED") -> dict[str, Any]:
    return {"author": {"login": login}, "body": body, "state": state, "submittedAt": at}


def _perm(permission: Any, login: str = "", user_type: Any = "User") -> dict[str, Any]:
    """A collaborator-permission response body, as the REST API returns it."""
    return {
        "permission": permission,
        "role_name": permission if permission != "none" else "",
        "user": {"login": login, "type": user_type},
    }


class _FakeGh:
    """Fake ``subprocess.run`` for the two gh calls check_pr_comments makes.

    ``permissions`` maps a login to either a response dict (returned as JSON on
    stdout) or an exception instance (raised, as subprocess.run with check=True
    would). A login absent from the map is a lookup the test did not expect.
    """

    def __init__(
        self,
        *,
        comments: list[dict[str, Any]] | None = None,
        reviews: list[dict[str, Any]] | None = None,
        permissions: dict[str, Any] | None = None,
    ) -> None:
        self.pr_payload = json.dumps({"comments": comments or [], "reviews": reviews or []})
        self.permissions = permissions or {}
        self.permission_lookups: list[str] = []
        self.api_paths: list[str] = []

    def __call__(self, cmd: list[str], *args: Any, **kwargs: Any) -> MagicMock:
        if cmd[:3] == ["gh", "pr", "view"]:
            return MagicMock(stdout=self.pr_payload, returncode=0)
        if cmd[:2] == ["gh", "api"]:
            path = cmd[2]
            self.api_paths.append(path)
            match = _PERMISSION_PATH.match(path)
            assert match is not None, f"unexpected gh api path: {path}"
            login = match.group("login")
            self.permission_lookups.append(login)
            assert login in self.permissions, f"unexpected permission lookup for {login!r}"
            answer = self.permissions[login]
            if isinstance(answer, BaseException):
                raise answer
            return MagicMock(stdout=answer if isinstance(answer, str) else json.dumps(answer))
        raise AssertionError(f"unexpected command: {cmd}")


def _check(
    fake: _FakeGh,
    *,
    required_roles: set[str] | None = None,
    tier: str = "",
) -> tuple[bool, str, list[str]]:
    with (
        patch.dict(os.environ, {"CI": "true", "PR_NUMBER": "42"}),
        patch("scripts.validate_review.subprocess.run", side_effect=fake),
        patch("scripts.validate_review._get_head_sha", return_value=HEAD),
    ):
        from scripts.validate_review import check_pr_comments

        return check_pr_comments(required_roles=required_roles, tier=tier)


def _lookup_error(login: str) -> subprocess.CalledProcessError:
    return subprocess.CalledProcessError(
        1,
        ["gh", "api", f"repos/{{owner}}/{{repo}}/collaborators/{login}/permission"],
        output="",
        stderr="gh: Resource not accessible by integration (HTTP 403)\n",
    )


# ---------------------------------------------------------------------------
# Accounts without write access clear nothing
# ---------------------------------------------------------------------------


@pytest.mark.security
class TestAccountWithoutWriteAccessClearsNothing:
    @pytest.mark.parametrize("permission", ["read", "none"])
    def test_head_bound_peer_verdict_in_comment_clears_nothing(self, permission: str) -> None:
        fake = _FakeGh(
            comments=[_comment(_verdict("CE"), "outside-reader")],
            permissions={"outside-reader": _perm(permission, "outside-reader")},
        )
        approved, _msg, missing = _check(fake, required_roles={"CE"})
        assert approved is False
        assert missing == ["CE"]

    def test_head_bound_peer_verdict_in_pr_review_clears_nothing(self) -> None:
        fake = _FakeGh(
            reviews=[_review(_verdict("CRS"), "outside-reader")],
            permissions={"outside-reader": _perm("read", "outside-reader")},
        )
        approved, _msg, missing = _check(fake, required_roles={"CRS"})
        assert approved is False
        assert missing == ["CRS"]

    @pytest.mark.parametrize(
        "body",
        [
            "IL SELF-REVIEWED: looked at it\n" + _footer("IL", "SELF-REVIEWED"),
            "IL SELF-REVIEWED: looked at it",
            "HO REVIEWED: supervised\n" + _footer("HO", "REVIEWED"),
            "HO REVIEWED: supervised",
            _verdict("CRS"),
        ],
        ids=["self-footer", "self-text", "ho-footer", "ho-text", "crs-footer"],
    )
    def test_self_review_line_clears_nothing_on_tier_1_self(self, body: str) -> None:
        fake = _FakeGh(
            comments=[_comment(body, "outside-reader")],
            permissions={"outside-reader": _perm("read", "outside-reader")},
        )
        approved, _msg, _missing = _check(fake, required_roles=set(), tier="TIER_1_SELF")
        assert approved is False

    def test_self_review_in_pr_review_clears_nothing_on_tier_1_self(self) -> None:
        fake = _FakeGh(
            reviews=[_review("IL SELF-REVIEWED: looked at it", "outside-reader")],
            permissions={"outside-reader": _perm("read", "outside-reader")},
        )
        approved, _msg, _missing = _check(fake, required_roles=set(), tier="TIER_1_SELF")
        assert approved is False

    def test_non_approval_cannot_revoke_a_write_account_approval(self) -> None:
        """Latest-verdict-per-role ranges over counted sources only."""
        fake = _FakeGh(
            comments=[
                _comment(_verdict("CE"), "maintainer", at=T1),
                _comment(_verdict("CE", "BLOCKED"), "outside-reader", at=T2),
            ],
            permissions={
                "maintainer": _perm("admin", "maintainer"),
                "outside-reader": _perm("read", "outside-reader"),
            },
        )
        approved, _msg, missing = _check(fake, required_roles={"CE"})
        assert approved is True
        assert missing == []

    def test_changes_requested_review_cannot_revoke_a_write_account_approval(self) -> None:
        fake = _FakeGh(
            comments=[_comment(_verdict("CE"), "maintainer", at=T1)],
            reviews=[
                _review(
                    _verdict("CE", "BLOCKED"), "outside-reader", at=T2, state="CHANGES_REQUESTED"
                )
            ],
            permissions={
                "maintainer": _perm("admin", "maintainer"),
                "outside-reader": _perm("read", "outside-reader"),
            },
        )
        approved, _msg, missing = _check(fake, required_roles={"CE"})
        assert approved is True
        assert missing == []

    def test_skipped_accounts_are_named_in_output(self, capsys: pytest.CaptureFixture[str]) -> None:
        fake = _FakeGh(
            comments=[_comment(_verdict("CE"), "outside-reader")],
            permissions={"outside-reader": _perm("read", "outside-reader")},
        )
        _check(fake, required_roles={"CE"})
        out = capsys.readouterr().out
        assert "without write access" in out
        assert "outside-reader" in out


# ---------------------------------------------------------------------------
# Accounts with write access clear as before
# ---------------------------------------------------------------------------


@pytest.mark.behavior
class TestWriteAccessAccountClears:
    @pytest.mark.parametrize("permission", ["write", "maintain", "admin"])
    def test_head_bound_peer_verdict_clears(self, permission: str) -> None:
        fake = _FakeGh(
            comments=[_comment(_verdict("CE"), "maintainer")],
            permissions={"maintainer": _perm(permission, "maintainer")},
        )
        approved, _msg, missing = _check(fake, required_roles={"CE"})
        assert approved is True
        assert missing == []

    def test_head_bound_peer_verdict_in_pr_review_clears(self) -> None:
        fake = _FakeGh(
            reviews=[_review(_verdict("CRS"), "maintainer")],
            permissions={"maintainer": _perm("write", "maintainer")},
        )
        approved, _msg, _missing = _check(fake, required_roles={"CRS"})
        assert approved is True

    @pytest.mark.parametrize(
        "body",
        [
            "IL SELF-REVIEWED: looked at it\n" + _footer("IL", "SELF-REVIEWED"),
            "IL SELF-REVIEWED: looked at it",
            "HO REVIEWED: supervised",
        ],
        ids=["self-footer", "self-text", "ho-text"],
    )
    def test_self_review_clears_tier_1_self(self, body: str) -> None:
        fake = _FakeGh(
            comments=[_comment(body, "maintainer")],
            permissions={"maintainer": _perm("admin", "maintainer")},
        )
        approved, _msg, _missing = _check(fake, required_roles=set(), tier="TIER_1_SELF")
        assert approved is True

    def test_lookup_targets_the_gated_repository_via_gh_placeholders(self) -> None:
        """gh resolves {owner}/{repo} exactly as it does for `gh pr view`."""
        fake = _FakeGh(
            comments=[_comment(_verdict("CE"), "maintainer")],
            permissions={"maintainer": _perm("admin", "maintainer")},
        )
        _check(fake, required_roles={"CE"})
        assert fake.api_paths == ["repos/{owner}/{repo}/collaborators/maintainer/permission"]

    def test_each_login_is_looked_up_once_per_run(self) -> None:
        fake = _FakeGh(
            comments=[
                _comment(_verdict("CE"), "maintainer", at=T1),
                _comment("discussion", "maintainer", at=T2),
            ],
            reviews=[_review(_verdict("CRS"), "maintainer", at=T2)],
            permissions={"maintainer": _perm("admin", "maintainer")},
        )
        approved, _msg, _missing = _check(fake, required_roles={"CE", "CRS"})
        assert approved is True
        assert fake.permission_lookups == ["maintainer"]


# ---------------------------------------------------------------------------
# Bots never clear
# ---------------------------------------------------------------------------


@pytest.mark.security
class TestBotsNeverClear:
    @pytest.mark.parametrize("login", ["cubic-dev-ai", "github-actions", "copilot", "Copilot"])
    def test_known_bot_login_clears_nothing_and_is_not_looked_up(self, login: str) -> None:
        fake = _FakeGh(comments=[_comment(_verdict("CE"), login)])
        approved, _msg, missing = _check(fake, required_roles={"CE"})
        assert approved is False
        assert missing == ["CE"]
        assert fake.permission_lookups == []

    def test_bot_type_account_clears_nothing_even_with_write_permission(self) -> None:
        fake = _FakeGh(
            comments=[_comment(_verdict("CE"), "some-app")],
            permissions={"some-app": _perm("write", "some-app", user_type="Bot")},
        )
        approved, _msg, missing = _check(fake, required_roles={"CE"})
        assert approved is False
        assert missing == ["CE"]

    def test_bot_type_account_clears_nothing_on_tier_1_self(self) -> None:
        fake = _FakeGh(
            comments=[_comment("IL SELF-REVIEWED: auto", "some-app")],
            permissions={"some-app": _perm("admin", "some-app", user_type="Bot")},
        )
        approved, _msg, _missing = _check(fake, required_roles=set(), tier="TIER_1_SELF")
        assert approved is False


# ---------------------------------------------------------------------------
# App and organization accounts never count
# ---------------------------------------------------------------------------
# gh returns app accounts without their [bot] suffix, so the permission lookup
# for an app comment (e.g. "vercel", "supabase") answers for the same-named
# organization: type Organization, permission none. Such an account never
# counts and is listed quietly -- it is an expected response, not a failed
# lookup.


@pytest.mark.security
class TestAppAndOrganizationAccountsNeverCount:
    @pytest.mark.parametrize("permission", ["none", "read", "admin", "write"])
    def test_organization_account_never_counts_and_is_not_a_failed_lookup(
        self, permission: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        fake = _FakeGh(
            comments=[_comment(_verdict("CE"), "some-org")],
            permissions={"some-org": _perm(permission, "some-org", user_type="Organization")},
        )
        approved, msg, missing = _check(fake, required_roles={"CE"})
        out = capsys.readouterr().out
        assert approved is False
        assert missing == ["CE"]
        assert "write-access lookup failed" not in msg
        assert "write-access lookup failed" not in out
        assert "app and organization accounts" in out
        assert "some-org" in out

    def test_organization_account_never_counts_on_tier_1_self(self) -> None:
        fake = _FakeGh(
            comments=[_comment("IL SELF-REVIEWED: looked at it", "some-org")],
            permissions={"some-org": _perm("admin", "some-org", user_type="Organization")},
        )
        approved, msg, _missing = _check(fake, required_roles=set(), tier="TIER_1_SELF")
        assert approved is False
        assert "write-access lookup failed" not in msg

    def test_app_comment_beside_write_access_approval(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A deployment-bot comment does not disturb a real approval or warn."""
        fake = _FakeGh(
            comments=[
                _comment(
                    "Deployment preview ready. Status: APPROVED for preview.", "vercel", at=T1
                ),
                _comment(_verdict("CE"), "maintainer", at=T2),
            ],
            permissions={
                "vercel": _perm("none", "vercel", user_type="Organization"),
                "maintainer": _perm("admin", "maintainer"),
            },
        )
        approved, msg, missing = _check(fake, required_roles={"CE"})
        out = capsys.readouterr().out
        assert approved is True
        assert missing == []
        assert "write-access lookup failed" not in msg
        assert "write-access lookup failed" not in out
        assert "vercel" in out


# ---------------------------------------------------------------------------
# A failed lookup clears nothing, and says so
# ---------------------------------------------------------------------------


@pytest.mark.security
class TestLookupFailureFailsClosedAndLoud:
    @pytest.mark.parametrize(
        "answer",
        [
            _lookup_error("maintainer"),
            OSError("gh not found"),
            "not json",
            '["a", "list"]',
            {"user": {"type": "User"}},
            {"permission": 7, "user": {"type": "User"}},
        ],
        ids=["gh-error", "os-error", "not-json", "not-object", "no-permission", "bad-permission"],
    )
    def test_failed_lookup_clears_nothing_and_is_named(self, answer: Any) -> None:
        fake = _FakeGh(
            comments=[_comment(_verdict("CE"), "maintainer")],
            permissions={"maintainer": answer},
        )
        approved, msg, missing = _check(fake, required_roles={"CE"})
        assert approved is False
        assert missing == ["CE"]
        assert "write-access lookup failed" in msg
        assert "maintainer" in msg

    def test_failed_lookup_reports_the_gh_error(self) -> None:
        fake = _FakeGh(
            comments=[_comment(_verdict("CE"), "maintainer")],
            permissions={"maintainer": _lookup_error("maintainer")},
        )
        _approved, msg, _missing = _check(fake, required_roles={"CE"})
        assert "HTTP 403" in msg

    def test_failed_lookup_clears_nothing_on_tier_1_self_and_is_named(self) -> None:
        fake = _FakeGh(
            comments=[_comment("IL SELF-REVIEWED: looked at it", "maintainer")],
            permissions={"maintainer": _lookup_error("maintainer")},
        )
        approved, msg, _missing = _check(fake, required_roles=set(), tier="TIER_1_SELF")
        assert approved is False
        assert "write-access lookup failed" in msg
        assert "maintainer" in msg

    def test_failed_lookup_is_named_even_when_the_gate_passes(self) -> None:
        """A failure never reads as a pass, and never disappears from a pass."""
        fake = _FakeGh(
            comments=[
                _comment(_verdict("CE"), "maintainer"),
                _comment(_verdict("CRS"), "second-maintainer"),
            ],
            permissions={
                "maintainer": _perm("admin", "maintainer"),
                "second-maintainer": _lookup_error("second-maintainer"),
            },
        )
        approved, msg, _missing = _check(fake, required_roles={"CE"})
        assert approved is True
        assert "write-access lookup failed" in msg
        assert "second-maintainer" in msg

    def test_failed_lookup_is_printed(self, capsys: pytest.CaptureFixture[str]) -> None:
        fake = _FakeGh(
            comments=[_comment(_verdict("CE"), "maintainer")],
            permissions={"maintainer": _lookup_error("maintainer")},
        )
        _check(fake, required_roles={"CE"})
        out = capsys.readouterr().out
        assert "write-access lookup failed" in out
        assert "maintainer" in out

    @pytest.mark.parametrize(
        "answer",
        [
            _perm("admin", "maintainer", user_type="Mannequin"),
            _perm("admin", "maintainer", user_type=""),
            _perm("admin", "maintainer", user_type=None),
            _perm("admin", "maintainer", user_type="user"),
            _perm("ADMIN", "maintainer"),
            _perm("triage", "maintainer"),
            _perm(["admin"], "maintainer"),
            {"permission": "admin", "user": "maintainer"},
            '"admin"',
        ],
        ids=[
            "type-mannequin",
            "type-empty",
            "type-null",
            "type-lowercase-user",
            "permission-uppercase",
            "permission-triage",
            "permission-list",
            "user-not-object",
            "response-not-object",
        ],
    )
    def test_unexpected_type_or_permission_clears_nothing_and_is_named(self, answer: Any) -> None:
        """Only type "User" with admin/maintain/write counts; anything outside
        the expected values (User/Bot/Organization; admin/maintain/write/read/
        none) is a failed lookup, never a pass."""
        fake = _FakeGh(
            comments=[_comment(_verdict("CE"), "maintainer")],
            permissions={"maintainer": answer},
        )
        approved, msg, missing = _check(fake, required_roles={"CE"})
        assert approved is False
        assert missing == ["CE"]
        assert "write-access lookup failed" in msg
        assert "maintainer" in msg

    def test_unexpected_type_clears_nothing_on_tier_1_self_and_is_named(self) -> None:
        fake = _FakeGh(
            comments=[_comment("IL SELF-REVIEWED: looked at it", "maintainer")],
            permissions={"maintainer": _perm("admin", "maintainer", user_type="Mannequin")},
        )
        approved, msg, _missing = _check(fake, required_roles=set(), tier="TIER_1_SELF")
        assert approved is False
        assert "write-access lookup failed" in msg

    @pytest.mark.parametrize("permission", ["read", "none"])
    def test_read_or_none_is_no_write_access_not_a_failed_lookup(
        self, permission: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """read and none are expected values: the account is listed as without
        write access, not reported as a failed lookup."""
        fake = _FakeGh(
            comments=[_comment(_verdict("CE"), "outside-reader")],
            permissions={"outside-reader": _perm(permission, "outside-reader")},
        )
        approved, msg, _missing = _check(fake, required_roles={"CE"})
        assert approved is False
        assert "write-access lookup failed" not in msg
        assert "without write access" in capsys.readouterr().out

    @pytest.mark.parametrize("login", ["", "some-app[bot]", "a/../b", "a b"])
    def test_login_outside_github_login_syntax_is_not_looked_up(self, login: str) -> None:
        fake = _FakeGh(comments=[_comment(_verdict("CE"), login)])
        approved, msg, missing = _check(fake, required_roles={"CE"})
        assert approved is False
        assert missing == ["CE"]
        assert fake.permission_lookups == []
        assert "write-access lookup failed" in msg
