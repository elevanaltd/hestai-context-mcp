"""Failure containment for phase constraints (#196, HC ruling D).

A malformed list in the workflow document must not take the other positions down. Both
tools return everything else, ``phase_constraints`` None, and a NEW OPTIONAL
``context.phase_constraints_error`` naming the repo-relative file, line and construct.
The key is present only on that failure.
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from hestai_context_mcp.tools.clock_in import clock_in
from hestai_context_mcp.tools.get_context import get_context

pytestmark = pytest.mark.unit

WORKFLOW_REL = ".hestai/workflow/OPERATIONAL-WORKFLOW.oct.md"
SYS_WORKFLOW_REL = ".hestai-sys/standards/workflow/OPERATIONAL-WORKFLOW.oct.md"

GOOD = """===WORKFLOW===
B1_BUILD_PLAN::BUILD_PLAN_EXECUTION
PURPOSE::"Execute build plan with TDD"
DELIVERABLES::[
  code,
  tests
]
===END==="""

UNTERMINATED = """===WORKFLOW===
B1_BUILD_PLAN::BUILD_PLAN_EXECUTION
PURPOSE::"Execute build plan with TDD"
DELIVERABLES::[
  code,
  tests
RACI::"IL[R]"
===END==="""
UNTERMINATED_LINE = 4  # the `DELIVERABLES::[` opener

TEXT_AFTER_LIST = """===WORKFLOW===
B1_BUILD_PLAN::BUILD_PLAN_EXECUTION
DELIVERABLES::[
  code
] trailing
===END==="""


@pytest.fixture(autouse=True)
def offline_ai(monkeypatch):
    from hestai_context_mcp.core import synthesis as synthesis_mod

    monkeypatch.setattr(
        synthesis_mod, "build_default_ai_client", lambda *_a, **_kw: None, raising=True
    )


def seed(root: Path, workflow: str | None, rel: str = WORKFLOW_REL) -> None:
    """A project with real other positions plus an optional workflow document."""
    ctx = root / ".hestai" / "state" / "context"
    ctx.mkdir(parents=True)
    (ctx / "PROJECT-CONTEXT.oct.md").write_text("PHASE::B1_BUILD\nPROJECT::seeded\n")
    if workflow is not None:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(workflow)


def call_get_context(root: Path) -> dict:
    with patch("hestai_context_mcp.tools.get_context.get_git_state", return_value=None):
        return get_context(working_dir=str(root))


def call_clock_in(root: Path) -> dict:
    with patch("hestai_context_mcp.tools.clock_in.get_current_branch", return_value="main"):
        return clock_in(role="implementation-lead", working_dir=str(root), focus="test-focus")


TOOLS = [
    pytest.param(call_get_context, id="get_context"),
    pytest.param(call_clock_in, id="clock_in"),
]


@pytest.mark.parametrize("call", TOOLS)
def test_unterminated_list_is_contained_and_reported(tmp_path, call):
    seed(tmp_path, UNTERMINATED)
    result = call(tmp_path)
    ctx = result["context"]
    assert ctx["phase_constraints"] is None
    assert ctx["phase_constraints_error"] == {
        "code": "WORKFLOW_PARSE_FAILED",
        "file": WORKFLOW_REL,
        "line": UNTERMINATED_LINE,
        "construct": "unterminated_list",
    }
    # every other position is still returned
    assert "PROJECT::seeded" in ctx["project_context"]
    assert ctx["git_state"] is not None
    assert isinstance(ctx["active_sessions"], list)
    assert "product_north_star" in ctx


@pytest.mark.parametrize("call", TOOLS)
def test_error_never_leaks_an_absolute_host_path(tmp_path, call):
    seed(tmp_path, UNTERMINATED)
    ctx = call(tmp_path)["context"]
    blob = json.dumps(ctx["phase_constraints_error"])
    assert str(tmp_path) not in blob and str(tmp_path.resolve()) not in blob
    assert not Path(ctx["phase_constraints_error"]["file"]).is_absolute()
    assert str(tmp_path.resolve()) not in json.dumps(
        {k: v for k, v in ctx.items() if k != "project_context"}
    )


@pytest.mark.parametrize("call", TOOLS)
def test_text_after_list_construct_is_reported(tmp_path, call):
    seed(tmp_path, TEXT_AFTER_LIST)
    err = call(tmp_path)["context"]["phase_constraints_error"]
    assert err["construct"] == "text_after_list"
    assert err["line"] == 3


@pytest.mark.parametrize("call", TOOLS)
def test_bundled_workflow_path_is_reported_repo_relative(tmp_path, call):
    seed(tmp_path, UNTERMINATED, rel=SYS_WORKFLOW_REL)
    err = call(tmp_path)["context"]["phase_constraints_error"]
    assert err["file"] == SYS_WORKFLOW_REL


@pytest.mark.parametrize("call", TOOLS)
def test_error_key_absent_on_success(tmp_path, call):
    seed(tmp_path, GOOD)
    ctx = call(tmp_path)["context"]
    assert ctx["phase_constraints"]["deliverables"] == ["code", "tests"]
    assert "phase_constraints_error" not in ctx


@pytest.mark.parametrize("call", TOOLS)
def test_error_key_absent_when_no_workflow(tmp_path, call):
    seed(tmp_path, None)
    ctx = call(tmp_path)["context"]
    assert ctx["phase_constraints"] is None
    assert "phase_constraints_error" not in ctx


@pytest.mark.parametrize("call", TOOLS)
def test_phase_not_found_is_unchanged_none_and_no_error_key(tmp_path, call):
    seed(tmp_path, "===WORKFLOW===\nB5_PROMETHEUS_EVOLUTION::POST_DELIVERY_ENHANCEMENT\n===END===")
    ctx = call(tmp_path)["context"]
    assert ctx["phase_constraints"] is None
    assert "phase_constraints_error" not in ctx


@pytest.mark.parametrize(
    ("call", "target"),
    [
        pytest.param(call_get_context, "hestai_context_mcp.tools.get_context", id="get_context"),
        pytest.param(call_clock_in, "hestai_context_mcp.tools.clock_in", id="clock_in"),
    ],
)
def test_file_not_found_is_unchanged_none_and_no_error_key(tmp_path, call, target):
    seed(tmp_path, GOOD)
    with patch(f"{target}.ContextSteward.synthesize_active_state", side_effect=FileNotFoundError):
        ctx = call(tmp_path)["context"]
    assert ctx["phase_constraints"] is None
    assert "phase_constraints_error" not in ctx


def test_get_context_stays_pure_on_a_malformed_workflow(tmp_path):
    """Containment must not write anything: fs snapshot is identical before and after."""

    def snapshot(root: Path) -> dict[str, tuple[int, int]]:
        return {
            str(p.relative_to(root)): (p.stat().st_mtime_ns, p.stat().st_size)
            for p in root.rglob("*")
            if p.is_file()
        }

    seed(tmp_path, UNTERMINATED)
    before = snapshot(tmp_path)
    call_get_context(tmp_path)
    assert snapshot(tmp_path) == before
