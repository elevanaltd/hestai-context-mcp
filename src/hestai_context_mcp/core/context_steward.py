"""Context steward: Phase constraint synthesis from OCTAVE workflow documents.

Reads OCTAVE workflow documents and extracts phase-specific constraints
for agent context injection. Parsing goes through the repo's single OCTAVE
list grammar (``read_octave_fields`` / ``list_items`` in
``agent_readable_governance_parser``), so a workflow written by hand (inline
``KEY::[a,b]`` lists) and the same workflow rewritten by ``octave_write``
(wrapped ``KEY::[`` lists) read identically, for flat lists. Known limitation: a nested
``KEY::`` line inside a wrapped list (octave_write's form of nested lists, e.g.
SCOPE_MATRIX in the bundled workflow) is rejected by the shared grammar as
``unterminated_list`` until the parser follow-up (ADR-004 v1.9, part of #196) lands, so such
a document raises :class:`WorkflowParseError`. No octave-mcp import (PROD::I6).

Harvested from legacy hestai-mcp core/governance/state/context_steward.py.

Phase marker rule
-----------------
A *phase marker* is a field that meets BOTH conditions:

* its key is ``<PHASE>_<WORD>[_<WORD>...]`` where ``<PHASE>`` is one of
  ``D0 D1 D2 D3 B0 B1 B2 B3 B4 B5`` and every ``<WORD>`` is capital letters only
  (``B1_HERMES_COORDINATION``, ``D0_MNEMOSYNE_GENESIS``); and
* its value is a bare SCREAMING_SNAKE identifier (no quotes, no brackets), e.g.
  ``BUILD_EXECUTION_ROADMAP``.

A phase's fields are every field after its marker up to the first *end stop*: the
next phase marker, a column-0 block header (``^[A-Z][A-Z0-9_]*:\\s*$``, e.g.
``ERROR_HANDLING_TAXONOMY:``), or the ``===END===`` envelope. The first marker for
a phase wins. Membership is decided by marker and line order, never by indentation
(only D0 is indented, under ``WORKFLOW_PHASES:``).

Known exclusions (fields that LOOK like markers but are not; each has a negative
test):

* list values: ``B5_CRITERIA::[...]`` is an ordinary field, not a B5 marker;
* digit segments: ``B2_00_REQUIREMENTS::...`` is an ordinary field (letters only);
* keys inside list values: ``B2_USAGE`` inside ``CONTEXT7_LIBRARY_RESEARCH::[...]``
  is part of the list value, never a field key (inline or wrapped).

The tests fail loudly if a workflow edit introduces a marker that breaks this rule
(see ``test_context_steward_octave_grammar.py``: exactly one marker per phase in the
bundled workflow, and every other ``<PHASE>_...`` key is an accounted exclusion).

A malformed list (``unterminated_list`` / ``text_after_list``) raises
:class:`WorkflowParseError` rather than yielding a partial phase.
"""

import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from hestai_context_mcp.core.agent_readable_governance_parser import (
    list_items,
    read_octave_fields,
)

# Phase identifiers used in workflow documents
PHASE_IDS = ["D0", "D1", "D2", "D3", "B0", "B1", "B2", "B3", "B4", "B5"]

_PHASE_MARKER_KEY_RE = re.compile(rf"^(?:{'|'.join(PHASE_IDS)})_[A-Z]+(?:_[A-Z]+)*$")
_BARE_IDENTIFIER_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
_BLOCK_HEADER_LINE_RE = re.compile(r"^[A-Z][A-Z0-9_]*:\s*$")
_ENVELOPE_END = "===END==="


class WorkflowParseError(ValueError):
    """The workflow document has a malformed list, so no phase can be trusted.

    Carries ``file`` (the document), ``line`` (1-based line where the offending list
    opens) and ``construct`` (``unterminated_list`` / ``text_after_list``).
    """

    def __init__(self, file: Path, line: int, construct: str) -> None:
        self.file = file
        self.line = line
        self.construct = construct
        super().__init__(f"Workflow document {file} is malformed: {construct} at line {line}")

    def to_error(self, root: Path) -> dict[str, Any]:
        """Structured tool-response form; ``file`` is relative to ``root``, never absolute."""
        try:
            relative = self.file.relative_to(root)
        except ValueError:
            relative = Path(self.file.name)  # outside the repo: name only, no host path
        return {
            "code": "WORKFLOW_PARSE_FAILED",
            "file": relative.as_posix(),
            "line": self.line,
            "construct": self.construct,
        }


def phase_of_marker(key: str, value: str) -> str | None:
    """Return the phase id (e.g. ``"B1"``) if ``key``/``value`` form a phase marker, else None."""
    if _PHASE_MARKER_KEY_RE.match(key) and _BARE_IDENTIFIER_RE.match(value.strip()):
        return key.split("_", 1)[0]
    return None


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

    Reads fields through the repo's OCTAVE list grammar; see the module docstring
    for the phase-marker rule.
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
            WorkflowParseError: If the document has a malformed list.
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
        """Extract phase-specific fields from OCTAVE content.

        Finds the phase marker (see module docstring) and collects every field up
        to the next phase marker, column-0 block header or ``===END===``.

        Args:
            content: Full OCTAVE workflow content.
            phase: Phase identifier (e.g., 'B1').

        Returns:
            Dict of key-value pairs for the phase, or None if not found.

        Raises:
            WorkflowParseError: If the document has a malformed list.
        """
        fields, reject = read_octave_fields(content)
        if reject is not None:
            raise WorkflowParseError(self.workflow_path, reject["line"], reject["construct"])

        stop_lines = [
            number
            for number, line in enumerate(content.splitlines(), start=1)
            if _BLOCK_HEADER_LINE_RE.match(line) or line.strip() == _ENVELOPE_END
        ]
        phase_data: dict[str, str] = {}
        start: int | None = None
        for field in fields:
            marker = phase_of_marker(field.key, field.value)
            if start is None:
                if marker == phase:
                    start = field.line
                    phase_data[field.key] = field.value
                continue
            if marker is not None or any(start < s <= field.line for s in stop_lines):
                break
            phase_data[field.key] = field.value

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

        Splits with the repo's quote-aware list grammar: ``[a,b]`` (inline or wrapped)
        gives its items, a bare value is a list of one, an empty value is ``[]``.
        """
        for key in keys:
            if key in data:
                return list_items(data[key])
        return []
