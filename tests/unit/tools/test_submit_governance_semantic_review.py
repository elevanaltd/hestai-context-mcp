"""Tests for the Stage-5 scoped-semantic review integration (issue #77).

When ``submit_governance`` opens a REAL AGR PR (``pr_url`` present, NOT
``dry_run``) and ``review=True`` (the default), it runs the analysis-tier
scoped-semantic reviewer (``core.governance_reviewer.review_governance``) over
the authored OCTAVE and posts an ``SR`` verdict on the PR via the EXISTING
``submit_review`` post path. The reviewer verdict is mapped onto the gate:

    review_governance APPROVED            -> submit_review "APPROVED" (clears)
    review_governance CONCERNS | BLOCKED  -> submit_review "BLOCKED"  (human)

A new additive ``semantic_review`` field is added to the return. The change is:

  * additive (the octave_content return is byte-stable beyond ``semantic_review``),
  * fail-soft (a review/post failure leaves the PR open + ``success`` true and is
    surfaced under ``semantic_review.error`` — it never undoes the PR),
  * tier-independent (the reviewer runs at the ``analysis`` tier — a different
    model from the default-tier author),
  * human-terminal (the gate informs the human; it NEVER auto-merges).

dry_run and ``review=False`` skip Stage 5 entirely.

The author model (default tier) and the reviewer model (analysis tier) differ —
this independence is asserted via the tier passed to ``review_governance`` and
the model annotation posted by ``submit_review``.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

import hestai_context_mcp.tools.submit_governance as sg
from hestai_context_mcp.tools.submit_governance import submit_governance

# Non-secret AGR governance TOKEN fixture. Built from a plainly-named module
# constant (NOT token/secret/key-named) and woven into the OCTAVE via an
# f-string, so no `TOKEN::"<literal>"` / `token="<literal>"` quoted-literal
# adjacency remains for GitGuardian's generic high-entropy detector to flag as a
# possible secret (false positive; #63/#71 policy carry-forward). A narrow
# per-literal match-ignore is also registered in .gitguardian.yaml; the detector
# stays live on this file (no path-ignore).
RECORD_TOKEN = "HO-CONTEXT-MCP-SR-20260612"

_VALID_OCTAVE = (
    "===DECISION_RECORD===\n"
    "META:\n"
    "  TYPE::DECISION_RECORD\n"
    f'  TOKEN::"{RECORD_TOKEN}"\n'
    "===END===\n"
)

_PR_URL = "https://github.com/elevanaltd/hestai-context-mcp/pull/123"


def _review_result(verdict: str, *, concerns: list[str] | None = None) -> dict[str, Any]:
    """Build a ReviewResult-shaped dict for the stubbed reviewer."""
    return {
        "verdict": verdict,
        "assessment": f"semantic assessment ({verdict})",
        "concerns": concerns or [],
        "metrics": {"tokens": 100, "cost": 0.01, "model": "analysis-tier-model"},
    }


def _linker_pr_ok() -> dict[str, Any]:
    """A successful linker output that opened a real PR."""
    return {
        "token": RECORD_TOKEN,
        "card_type": "DECISION_RECORD",
        "target_path": f".hestai/decisions/{RECORD_TOKEN}.oct.md",
        "branch": "governance/20260612-ho-context-mcp-sr-20260612",
        "pr_url": _PR_URL,
        "error": None,
    }


@pytest.fixture
def stub_octave_pr(monkeypatch: pytest.MonkeyPatch):
    """Make the octave_content path open a (fake) real PR.

    Patches the validators + linker so ``_submit_octave_content`` reaches a
    successful real-PR state WITHOUT touching git or octave-mcp.
    """

    class _Validation:
        valid = True
        errors: list[str] = []

    class _OctaveResult:
        ok = True
        available = True

        def to_dict(self) -> dict[str, Any]:
            return {"ok": True, "available": True, "errors": []}

    monkeypatch.setattr(sg, "validate_working_dir", lambda wd: Path(wd), raising=True)
    monkeypatch.setattr(sg, "validate_octave_content", lambda wd, oc: _Validation(), raising=True)
    monkeypatch.setattr(
        sg,
        "get_octave_validator",
        lambda: type("V", (), {"validate": lambda self, oc: _OctaveResult()})(),
        raising=True,
    )
    monkeypatch.setattr(sg, "run_linker", lambda **kw: _linker_pr_ok(), raising=True)


@pytest.fixture
def capture_review(monkeypatch: pytest.MonkeyPatch):
    """Stub review_governance + submit_review, capturing their call args."""

    captured: dict[str, Any] = {"review": None, "submit": None}

    def _install(
        verdict: str, *, concerns: list[str] | None = None, post_status: str = "ok"
    ) -> None:
        async def _fake_review(octave_content: str, **kwargs: Any) -> dict[str, Any]:
            captured["review"] = {"octave_content": octave_content, "kwargs": kwargs}
            return _review_result(verdict, concerns=concerns)

        def _fake_submit(**kwargs: Any) -> dict[str, Any]:
            captured["submit"] = kwargs
            if post_status == "raise":
                raise RuntimeError("post boundary blew up")
            return {"status": post_status, "comment_url": "https://x/y#1", "dry_run": False}

        monkeypatch.setattr(sg, "review_governance", _fake_review, raising=True)
        monkeypatch.setattr(sg, "submit_review", _fake_submit, raising=True)

    _install.captured = captured  # type: ignore[attr-defined]
    return _install


# ---------------------------------------------------------------------------
# octave_content mode: Stage 5 runs on a real PR
# ---------------------------------------------------------------------------


class TestOctaveContentStage5:
    def test_real_pr_runs_review_and_posts_sr(self, tmp_path, stub_octave_pr, capture_review):
        capture_review("APPROVED")
        result = asyncio.run(
            submit_governance(working_dir=str(tmp_path), octave_content=_VALID_OCTAVE)
        )

        assert result["success"] is True
        assert result["pr_url"] == _PR_URL
        # Reviewer ran over the AUTHORED octave at the analysis tier.
        review_call = capture_review.captured["review"]
        assert review_call is not None
        assert review_call["octave_content"] == _VALID_OCTAVE
        assert review_call["kwargs"].get("tier") == "analysis"
        # Posted an SR verdict via the existing submit_review path.
        submit_call = capture_review.captured["submit"]
        assert submit_call is not None
        assert submit_call["role"] == "SR"
        assert submit_call["repo"] == "elevanaltd/hestai-context-mcp"
        assert submit_call["pr_number"] == 123
        # semantic_review field added to the return.
        assert result["semantic_review"]["posted"] is True
        assert result["semantic_review"]["review_verdict"] == "APPROVED"
        assert result["semantic_review"]["gate_verdict"] == "APPROVED"

    def test_approved_maps_to_approved_gate(self, tmp_path, stub_octave_pr, capture_review):
        capture_review("APPROVED")
        result = asyncio.run(
            submit_governance(working_dir=str(tmp_path), octave_content=_VALID_OCTAVE)
        )
        assert capture_review.captured["submit"]["verdict"] == "APPROVED"
        assert result["semantic_review"]["gate_verdict"] == "APPROVED"

    def test_concerns_maps_to_blocked_gate(self, tmp_path, stub_octave_pr, capture_review):
        capture_review("CONCERNS", concerns=["precedence unclear"])
        result = asyncio.run(
            submit_governance(working_dir=str(tmp_path), octave_content=_VALID_OCTAVE)
        )
        assert capture_review.captured["submit"]["verdict"] == "BLOCKED"
        assert result["semantic_review"]["gate_verdict"] == "BLOCKED"
        assert result["semantic_review"]["review_verdict"] == "CONCERNS"
        # Concerns are included in the posted assessment.
        assert "precedence unclear" in capture_review.captured["submit"]["assessment"]

    def test_blocked_maps_to_blocked_gate(self, tmp_path, stub_octave_pr, capture_review):
        capture_review("BLOCKED", concerns=["contradicts ratified decision"])
        result = asyncio.run(
            submit_governance(working_dir=str(tmp_path), octave_content=_VALID_OCTAVE)
        )
        assert capture_review.captured["submit"]["verdict"] == "BLOCKED"
        assert result["semantic_review"]["gate_verdict"] == "BLOCKED"

    def test_reviewer_model_annotated_for_audit(self, tmp_path, stub_octave_pr, capture_review):
        capture_review("APPROVED")
        asyncio.run(submit_governance(working_dir=str(tmp_path), octave_content=_VALID_OCTAVE))
        # The analysis-tier model is annotated on the SR comment for audit, and
        # it differs from a default-tier author model (independence).
        assert capture_review.captured["submit"]["model_annotation"] == "analysis-tier-model"

    def test_return_is_byte_stable_beyond_semantic_review(
        self, tmp_path, stub_octave_pr, capture_review
    ):
        capture_review("APPROVED")
        result = asyncio.run(
            submit_governance(working_dir=str(tmp_path), octave_content=_VALID_OCTAVE)
        )
        post_70_keys = {
            "success",
            "token",
            "card_type",
            "target_path",
            "adr_target_path",
            "branch",
            "pr_url",
            "validation_errors",
            "octave_validation",
            "dry_run",
        }
        # Additive top-level keys: semantic_review (#77) and the #108.4 Option-L
        # real_validation_available signal. No pre-existing key is removed or
        # renamed (byte-stable contract beyond purely additive fields).
        assert set(result.keys()) == post_70_keys | {
            "semantic_review",
            "real_validation_available",
        }


# ---------------------------------------------------------------------------
# Skip conditions: dry_run, review=False, no PR
# ---------------------------------------------------------------------------


class TestStage5SkipConditions:
    def test_dry_run_skips_stage5(self, tmp_path, capture_review):
        capture_review("APPROVED")
        result = asyncio.run(
            submit_governance(working_dir=str(tmp_path), octave_content=_VALID_OCTAVE, dry_run=True)
        )
        # No review, no post, no semantic_review key (byte-stable dry_run shape).
        assert capture_review.captured["review"] is None
        assert capture_review.captured["submit"] is None
        assert "semantic_review" not in result

    def test_review_false_skips_stage5(self, tmp_path, stub_octave_pr, capture_review):
        capture_review("APPROVED")
        result = asyncio.run(
            submit_governance(working_dir=str(tmp_path), octave_content=_VALID_OCTAVE, review=False)
        )
        assert capture_review.captured["review"] is None
        assert capture_review.captured["submit"] is None
        assert "semantic_review" not in result

    def test_failed_pr_skips_stage5(self, tmp_path, monkeypatch, capture_review):
        capture_review("APPROVED")

        class _Validation:
            valid = True
            errors: list[str] = []

        class _OctaveResult:
            ok = True
            available = True

            def to_dict(self) -> dict[str, Any]:
                return {"ok": True, "available": True, "errors": []}

        def _linker_fail(**kw: Any) -> dict[str, Any]:
            return {
                "token": None,
                "card_type": None,
                "target_path": None,
                "branch": None,
                "pr_url": None,
                "error": "gh failed",
            }

        monkeypatch.setattr(sg, "validate_working_dir", lambda wd: Path(wd), raising=True)
        monkeypatch.setattr(
            sg, "validate_octave_content", lambda wd, oc: _Validation(), raising=True
        )
        monkeypatch.setattr(
            sg,
            "get_octave_validator",
            lambda: type("V", (), {"validate": lambda self, oc: _OctaveResult()})(),
            raising=True,
        )
        monkeypatch.setattr(sg, "run_linker", _linker_fail, raising=True)

        result = asyncio.run(
            submit_governance(working_dir=str(tmp_path), octave_content=_VALID_OCTAVE)
        )
        assert result["success"] is False
        # No PR opened -> Stage 5 does not run.
        assert capture_review.captured["review"] is None
        assert "semantic_review" not in result


# ---------------------------------------------------------------------------
# Fail-soft: a review/post failure leaves the PR open + successful
# ---------------------------------------------------------------------------


class TestStage5FailSoft:
    def test_review_exception_is_fail_soft(self, tmp_path, stub_octave_pr, monkeypatch):
        async def _boom_review(octave_content: str, **kwargs: Any) -> dict[str, Any]:
            raise RuntimeError("no analysis key configured")

        monkeypatch.setattr(sg, "review_governance", _boom_review, raising=True)

        result = asyncio.run(
            submit_governance(working_dir=str(tmp_path), octave_content=_VALID_OCTAVE)
        )
        # PR stays open + successful; error surfaced, PR NOT undone.
        assert result["success"] is True
        assert result["pr_url"] == _PR_URL
        assert result["semantic_review"]["posted"] is False
        assert "no analysis key configured" in result["semantic_review"]["error"]

    def test_post_exception_is_fail_soft(self, tmp_path, stub_octave_pr, capture_review):
        capture_review("APPROVED", post_status="raise")
        result = asyncio.run(
            submit_governance(working_dir=str(tmp_path), octave_content=_VALID_OCTAVE)
        )
        assert result["success"] is True
        assert result["semantic_review"]["posted"] is False
        assert "post boundary blew up" in result["semantic_review"]["error"]

    def test_post_error_status_is_fail_soft(self, tmp_path, stub_octave_pr, capture_review):
        # submit_review returns an error status (e.g. auth) -> recorded, not raised.
        capture_review("APPROVED", post_status="error")
        result = asyncio.run(
            submit_governance(working_dir=str(tmp_path), octave_content=_VALID_OCTAVE)
        )
        assert result["success"] is True
        assert result["semantic_review"]["posted"] is False

    def test_unparseable_pr_url_is_fail_soft(self, tmp_path, monkeypatch, capture_review):
        capture_review("APPROVED")

        class _Validation:
            valid = True
            errors: list[str] = []

        class _OctaveResult:
            ok = True
            available = True

            def to_dict(self) -> dict[str, Any]:
                return {"ok": True, "available": True, "errors": []}

        def _linker_weird_url(**kw: Any) -> dict[str, Any]:
            out = _linker_pr_ok()
            out["pr_url"] = "not-a-real-url"
            return out

        monkeypatch.setattr(sg, "validate_working_dir", lambda wd: Path(wd), raising=True)
        monkeypatch.setattr(
            sg, "validate_octave_content", lambda wd, oc: _Validation(), raising=True
        )
        monkeypatch.setattr(
            sg,
            "get_octave_validator",
            lambda: type("V", (), {"validate": lambda self, oc: _OctaveResult()})(),
            raising=True,
        )
        monkeypatch.setattr(sg, "run_linker", _linker_weird_url, raising=True)

        result = asyncio.run(
            submit_governance(working_dir=str(tmp_path), octave_content=_VALID_OCTAVE)
        )
        assert result["success"] is True
        assert result["semantic_review"]["posted"] is False
        assert result["semantic_review"]["error"]


# ---------------------------------------------------------------------------
# Human Primacy: Stage 5 NEVER auto-merges
# ---------------------------------------------------------------------------


class TestHumanPrimacy:
    def test_stage5_never_auto_merges(self):
        import inspect

        src = inspect.getsource(sg)
        lowered = src.lower()
        assert "pr merge" not in lowered
        assert "pulls/{" not in lowered or "/merge" not in lowered
        assert "auto_merge" not in lowered
