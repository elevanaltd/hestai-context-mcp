"""Context steward: Phase constraint synthesis from OCTAVE workflow documents.

Reads OCTAVE workflow documents and extracts phase-specific constraints
for agent context injection. Uses regex-based parsing (no octave_mcp dependency).

Harvested from legacy hestai-mcp core/governance/state/context_steward.py.
"""

import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

# Phase identifiers used in workflow documents
PHASE_IDS = ["D0", "D1", "D2", "D3", "B0", "B1", "B2", "B3", "B4", "B5"]


@dataclass
class PhaseConstraints:
    """Phase-specific governance constraints."""

    phase: str
    purpose: str
    raci: str
    deliverables: list[str]
    entry_criteria: list[str]
    exit_criteria: list[str]
    quality_gates: str | None = None
    subphases: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return asdict(self)


class ContextSteward:
    """Synthesizes phase-specific constraints from workflow documents.

    Uses regex-based OCTAVE parsing to extract phase sections without
    requiring the octave_mcp library dependency.
    """

    def __init__(self, workflow_path: Path) -> None:
        """Initialize with path to workflow document.

        Args:
            workflow_path: Path to OCTAVE workflow file.
        """
        self.workflow_path = workflow_path

    def synthesize_active_state(self, phase: str) -> PhaseConstraints:
        """Extract constraints for a specific phase.

        Args:
            phase: Phase identifier (e.g., 'B1', 'D0').

        Returns:
            PhaseConstraints for the given phase.

        Raises:
            FileNotFoundError: If workflow file doesn't exist.
            ValueError: If phase not found in document.
        """
        if not self.workflow_path.exists():
            raise FileNotFoundError(f"Workflow document not found: {self.workflow_path}")

        content = self.workflow_path.read_text()
        phase_data = self._extract_phase_section(content, phase)

        if not phase_data:
            raise ValueError(f"Phase {phase} not found in workflow document")

        return self._build_constraints(phase, phase_data)

    def _extract_phase_section(self, content: str, phase: str) -> dict[str, str] | None:
        """Extract phase-specific data from OCTAVE content using regex.

        Looks for phase markers like 'B1_BUILD_PLAN::value' and collects
        subsequent key::value pairs until the next phase marker.

        Args:
            content: Full OCTAVE workflow content.
            phase: Phase identifier (e.g., 'B1').

        Returns:
            Dict of key-value pairs for the phase, or None if not found.
        """
        lines = content.split("\n")
        phase_prefix = f"{phase}_"
        phase_data: dict[str, str] = {}
        collecting = False

        for line in lines:
            stripped = line.strip()

            # Check for phase marker (e.g., "B1_BUILD_PLAN::value" or "  B1_BUILD_PLAN::value")
            if "::" in stripped:
                key_part = stripped.split("::")[0].strip()

                # Is this a phase marker?
                is_phase_marker = any(key_part.startswith(f"{p}_") for p in PHASE_IDS)

                if is_phase_marker:
                    if key_part.startswith(phase_prefix):
                        # Found our target phase
                        collecting = True
                        value = stripped.split("::", 1)[1].strip() if "::" in stripped else ""
                        phase_data[key_part] = value
                    elif collecting:
                        # Hit the next phase, stop collecting
                        break
                elif collecting:
                    # Regular key::value pair belonging to current phase
                    key = key_part
                    value = stripped.split("::", 1)[1].strip() if "::" in stripped else ""
                    phase_data[key] = value

        return phase_data if phase_data else None

    def _build_constraints(self, phase: str, phase_data: dict[str, str]) -> PhaseConstraints:
        """Build PhaseConstraints from extracted phase data.

        Args:
            phase: Phase identifier.
            phase_data: Dict of key-value pairs from the phase section.

        Returns:
            Structured PhaseConstraints object.
        """
        # Extract phase marker value (e.g., B1_BUILD_PLAN has value BUILD_PLAN_EXECUTION)
        phase_marker_value = None
        for key, value in phase_data.items():
            if key.startswith(f"{phase}_"):
                phase_marker_value = value
                break

        purpose = self._extract_field(phase_data, ["PURPOSE"])
        if not purpose and phase_marker_value:
            purpose = phase_marker_value

        raci = self._extract_field(phase_data, ["RACI"])
        deliverables = self._extract_list_field(phase_data, ["DELIVERABLE", "DELIVERABLES"])
        entry_criteria = self._extract_list_field(phase_data, ["ENTRY"])
        exit_criteria = self._extract_list_field(phase_data, ["EXIT"])
        quality_gates = self._extract_field(phase_data, ["QUALITY_GATE_MANDATORY", "QUALITY_GATES"])
        subphases = self._extract_field(phase_data, ["SUBPHASES"])

        return PhaseConstraints(
            phase=phase,
            purpose=purpose or f"Phase {phase}",
            raci=raci or "Not specified",
            deliverables=deliverables,
            entry_criteria=entry_criteria,
            exit_criteria=exit_criteria,
            quality_gates=quality_gates,
            subphases=subphases,
        )

    def _extract_field(self, data: dict[str, str], keys: list[str]) -> str | None:
        """Extract a single field value from phase data."""
        for key in keys:
            if key in data:
                value = data[key]
                return value if value else None
        return None

    def _extract_list_field(self, data: dict[str, str], keys: list[str]) -> list[str]:
        """Extract a list field value from phase data.

        Handles OCTAVE list syntax: [item1, item2, item3].
        """
        for key in keys:
            if key in data:
                value = data[key]
                if not value:
                    return []
                # Parse OCTAVE list: [item1, item2]
                list_match = re.match(r"^\[(.+)\]$", value)
                if list_match:
                    items = [item.strip() for item in list_match.group(1).split(",")]
                    return [item for item in items if item]
                # Single value
                return [value]
        return []
