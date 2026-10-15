"""RED tests: Stage-5 maps the WORDING reviewer outcome to SR APPROVED + fixes."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

import hestai_context_mcp.tools.submit_governance as sg

_PR_URL = "https://github.com/elevanaltd/hestai-context-mcp/pull/123"
_HEAD = "0123456789abcdef0123456789abcdef01234567"


@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch):
    cap: dict[str, Any] = {}

    def install(review: dict[str, Any], head: str | None = _HEAD):
        async def _fake_review(octave_content: str, **kw: Any) -> dict[str, Any]:
            return review

        def _fake_submit(**kw: Any) -> dict[str, Any]:
            cap["submit"] = kw
            return {"status": "ok", "comment_url": "https://x/y#1", "dry_run": False}

        monkeypatch.setattr(sg, "review_governance", _fake_review, raising=True)
        monkeypatch.setattr(sg, "submit_review", _fake_submit, raising=True)
        monkeypatch.setattr(sg, "_resolve_pr_head_sha", lambda repo, n: head, raising=True)

    cap["install"] = install
    return cap


def _review(verdict: str, **extra: Any) -> dict[str, Any]:
    return {
        "verdict": verdict,
        "assessment": "assessment text",
        "concerns": [],
        "reviewer_available": True,
        "metrics": {"tokens": 1, "cost": 0.0, "model": "m"},
        **extra,
    }


def _run() -> dict[str, Any]:
    return asyncio.run(sg._run_semantic_review("OCTAVE", _PR_URL))


def test_wording_maps_to_sr_approved_with_fixes_and_head_sha(captured):
    captured["install"](_review("WORDING", wording_fixes=["Soften X", "Move cite"]))
    out = _run()
    sub = captured["submit"]
    assert sub["role"] == "SR"
    assert sub["verdict"] == "APPROVED"
    assert sub["wording_fixes"] == ["Soften X", "Move cite"]
    assert sub["commit_sha"] == _HEAD
    assert out["posted"] is True
    assert out["gate_verdict"] == "APPROVED"
    assert out["review_verdict"] == "WORDING"
    assert out["wording_fixes"] == ["Soften X", "Move cite"]


def test_wording_without_fixes_never_approves(captured):
    captured["install"](_review("WORDING", wording_fixes=[]))
    _run()
    assert captured["submit"]["verdict"] == "BLOCKED"
    assert not captured["submit"].get("wording_fixes")


@pytest.mark.parametrize("verdict,gate", [("CONCERNS", "BLOCKED"), ("BLOCKED", "BLOCKED")])
def test_concerns_blocked_mapping_unchanged(captured, verdict, gate):
    captured["install"](_review(verdict))
    _run()
    assert captured["submit"]["verdict"] == gate
    assert not captured["submit"].get("wording_fixes")


def test_approved_passes_head_sha_without_fixes(captured):
    captured["install"](_review("APPROVED"))
    _run()
    assert captured["submit"]["verdict"] == "APPROVED"
    assert captured["submit"]["commit_sha"] == _HEAD
    assert not captured["submit"].get("wording_fixes")


def test_head_sha_unresolvable_still_posts(captured):
    captured["install"](_review("APPROVED"), head=None)
    out = _run()
    assert out["posted"] is True
    assert not captured["submit"].get("commit_sha")


def test_gate_verdict_map_has_wording():
    assert sg._GATE_VERDICT_MAP["WORDING"] == "APPROVED"
