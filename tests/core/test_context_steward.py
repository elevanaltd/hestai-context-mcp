"""Tests for ContextSteward phase constraint synthesis."""

import pytest

from hestai_context_mcp.core.context_steward import ContextSteward, PhaseConstraints


class TestPhaseConstraints:
    """Test the PhaseConstraints data structure."""

    def test_to_dict(self):
        """PhaseConstraints serializes to dictionary."""
        constraints = PhaseConstraints(
            phase="B1",
            purpose="Build plan execution",
            raci="implementation-lead[R], critical-engineer[A]",
            deliverables=["Implementation code", "Test artifacts"],
            entry_criteria=["Approved build plan"],
            exit_criteria=["All tests passing"],
            quality_gates="TDD, code review",
            subphases=None,
        )
        result = constraints.to_dict()
        assert result["phase"] == "B1"
        assert result["purpose"] == "Build plan execution"
        assert len(result["deliverables"]) == 2
        assert result["quality_gates"] == "TDD, code review"

    def test_to_dict_with_none_optional_fields(self):
        """PhaseConstraints handles None optional fields."""
        constraints = PhaseConstraints(
            phase="D0",
            purpose="Ideation",
            raci="Not specified",
            deliverables=[],
            entry_criteria=[],
            exit_criteria=[],
        )
        result = constraints.to_dict()
        assert result["quality_gates"] is None
        assert result["subphases"] is None


class TestContextSteward:
    """Test ContextSteward workflow parsing and constraint extraction."""

    def test_workflow_file_not_found_raises(self, tmp_path):
        """Raises FileNotFoundError when workflow file doesn't exist."""
        steward = ContextSteward(workflow_path=tmp_path / "nonexistent.oct.md")
        with pytest.raises(FileNotFoundError):
            steward.synthesize_active_state("B1")

    def test_phase_not_found_raises_value_error(self, tmp_path):
        """Raises ValueError when phase is not in the workflow document."""
        workflow_file = tmp_path / "workflow.oct.md"
        workflow_file.write_text("""===WORKFLOW===
META:
  TYPE::WORKFLOW
===END===
""")
        steward = ContextSteward(workflow_path=workflow_file)
        with pytest.raises(ValueError, match="not found"):
            steward.synthesize_active_state("B1")

    def test_extracts_phase_constraints_from_workflow(self, tmp_path):
        """Extracts correct constraints for a given phase."""
        workflow_file = tmp_path / "workflow.oct.md"
        # Minimal OCTAVE workflow with a B1 phase section
        workflow_file.write_text("""===OPERATIONAL_WORKFLOW===
META:
  TYPE::WORKFLOW

WORKFLOW_PHASES:
  B1_BUILD_PLAN::BUILD_PLAN_EXECUTION
  PURPOSE::Validated architecture to actionable implementation plan
  RACI::implementation-lead[R] critical-engineer[A]
  DELIVERABLE::[Implementation code, Test artifacts]
  ENTRY::[Approved build plan]
  EXIT::[All tests passing, Code reviewed]

===END===
""")
        steward = ContextSteward(workflow_path=workflow_file)
        constraints = steward.synthesize_active_state("B1")

        assert constraints.phase == "B1"
        assert (
            "implementation" in constraints.purpose.lower() or "BUILD_PLAN" in constraints.purpose
        )
        assert constraints.raci != "Not specified"

    def test_returns_phase_constraints_type(self, tmp_path):
        """synthesize_active_state returns PhaseConstraints instance."""
        workflow_file = tmp_path / "workflow.oct.md"
        workflow_file.write_text("""===OPERATIONAL_WORKFLOW===
META:
  TYPE::WORKFLOW

WORKFLOW_PHASES:
  D0_IDEATION::IDEATION_SETUP
  PURPOSE::Initial ideation phase

===END===
""")
        steward = ContextSteward(workflow_path=workflow_file)
        result = steward.synthesize_active_state("D0")
        assert isinstance(result, PhaseConstraints)
