"""RED tests: Stage-5 is fully fail-soft and submit_review runs off the event loop (#210 rework)."""

from __future__ import annotations

import asyncio
import threading
from typing import Any

import pytest

import hestai_context_mcp.tools.submit_governance as sg

_PR_URL = "https://github.com/elevanaltd/hestai-context-mcp/pull/123"
_HEAD = "0123456789abcdef0123456789abcdef01234567"
_REVIEW: dict[str, Any] = {
    "verdict": "APPROVED",
    "assessment": "assessment text",
    "concerns": [],
    "reviewer_available": True,
    "metrics": {"tokens": 1, "cost": 0.0, "model": "m"},
}


@pytest.fixture
def stubs(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    cap: dict[str, Any] = {}

    async def _fake_review(octave_content: str, **kw: Any) -> dict[str, Any]:
        return _REVIEW

    def _fake_submit(**kw: Any) -> dict[str, Any]:
        cap["submit"] = kw
        cap["submit_thread"] = threading.get_ident()
        return {"status": "ok", "comment_url": "https://x/y#1", "dry_run": False}

    monkeypatch.setattr(sg, "review_governance", _fake_review, raising=True)
    monkeypatch.setattr(sg, "submit_review", _fake_submit, raising=True)
    monkeypatch.setattr(sg, "_resolve_pr_head_sha", lambda repo, n: _HEAD, raising=True)
    return cap


def test_head_sha_executor_exception_degrades_and_still_posts(
    stubs: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(repo: str, n: int) -> str:
        raise RuntimeError("executor exploded")

    monkeypatch.setattr(sg, "_resolve_pr_head_sha", _boom, raising=True)
    out = asyncio.run(sg._run_semantic_review("OCTAVE", _PR_URL))
    assert out["posted"] is True
    assert "commit_sha" not in stubs["submit"]
    assert stubs["submit"]["verdict"] == "APPROVED"


def test_submit_governance_survives_head_sha_executor_exception(
    monkeypatch: pytest.MonkeyPatch, stubs: dict[str, Any]
) -> None:
    def _boom(repo: str, n: int) -> str:
        raise RuntimeError("executor exploded")

    monkeypatch.setattr(sg, "_resolve_pr_head_sha", _boom, raising=True)
    result: dict[str, Any] = {"success": True, "pr_url": _PR_URL}
    out = asyncio.run(sg._maybe_review(result, "OCTAVE", False, True))
    assert out["success"] is True
    assert out["pr_url"] == _PR_URL
    assert out["semantic_review"]["posted"] is True


def test_submit_review_runs_off_the_event_loop_thread(stubs: dict[str, Any]) -> None:
    async def _go() -> int:
        await sg._run_semantic_review("OCTAVE", _PR_URL)
        return threading.get_ident()

    loop_thread = asyncio.run(_go())
    assert stubs["submit_thread"] != loop_thread


def test_submit_review_exception_is_contained(
    stubs: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(**kw: Any) -> dict[str, Any]:
        raise RuntimeError("gh timed out")

    monkeypatch.setattr(sg, "submit_review", _boom, raising=True)
    out = asyncio.run(sg._run_semantic_review("OCTAVE", _PR_URL))
    assert out["posted"] is False
    assert "gh timed out" in out["error"]


def test_head_sha_run_in_executor_scheduling_failure_degrades_and_posts(
    stubs: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """run_in_executor ITSELF raising for the SHA call (not the worker) still posts."""
    real_loop_getter = asyncio.get_running_loop

    class _Loop:
        def __init__(self, inner: asyncio.AbstractEventLoop) -> None:
            self._inner = inner

        def run_in_executor(self, executor: Any, func: Any, *args: Any) -> Any:
            if getattr(func, "__name__", "") == "_resolve_pr_head_sha" or func is (
                sg._resolve_pr_head_sha
            ):
                raise RuntimeError("cannot schedule new futures after shutdown")
            return self._inner.run_in_executor(executor, func, *args)

    monkeypatch.setattr(sg.asyncio, "get_running_loop", lambda: _Loop(real_loop_getter()))
    out = asyncio.run(sg._run_semantic_review("OCTAVE", _PR_URL))
    assert out["posted"] is True
    assert "commit_sha" not in stubs["submit"]
