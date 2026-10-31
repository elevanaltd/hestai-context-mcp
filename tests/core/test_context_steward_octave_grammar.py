"""RED/GREEN tests for issue #196: the phase reader uses the repo's one OCTAVE list grammar.

A workflow written by hand (inline ``KEY::[a,b]``) and the same workflow rewritten by
``octave_write`` (wrapped ``KEY::[`` ... ``]``) must read the same. Four failure modes of
the old line-regex reader, each tested in BOTH forms:

(a) a wrapped list is read in full (old reader: ``['[']``);
(b) nested or prefixed keys are not taken as phase markers;
(c) the last phase stops at the next column-0 block header;
(d) a comma inside a quoted item stays one item.

The module docstring of ``context_steward`` records the marker rule; these tests make a
workflow edit that breaks the rule fail loudly.
"""

import asyncio
import re
from pathlib import Path

import pytest

from hestai_context_mcp.core import context_steward as cs
from hestai_context_mcp.core.agent_readable_governance_parser import read_octave_fields
from hestai_context_mcp.core.context_steward import PHASE_IDS, ContextSteward
from tests.core.legacy_phase_reader import LegacyContextSteward

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
# .hestai-sys is gitignored (absent in CI), so the bundled workflow is pinned as a fixture:
# a byte-for-byte copy of .hestai-sys/standards/workflow/OPERATIONAL-WORKFLOW.oct.md.
BUNDLED = REPO_ROOT / "tests" / "fixtures" / "OPERATIONAL-WORKFLOW.inline.oct.md"
LIVE_BUNDLED = REPO_ROOT / ".hestai-sys" / "standards" / "workflow" / "OPERATIONAL-WORKFLOW.oct.md"
CANONICAL = REPO_ROOT / "tests" / "fixtures" / "OPERATIONAL-WORKFLOW.canonical.oct.md"

FORMS = ["inline", "wrapped"]

B1 = "B1_HERMES_COORDINATION::BUILD_EXECUTION_ROADMAP"
B5 = "B5_PROMETHEUS_EVOLUTION::POST_DELIVERY_ENHANCEMENT"

# Every real marker shape in the bundled OPERATIONAL-WORKFLOW.oct.md (one per phase).
REAL_MARKERS = [
    ("D0", "D0_MNEMOSYNE_GENESIS", "IDEATION_SETUP"),
    ("D1", "D1_APOLLO_ORACLE", "UNDERSTANDING_ESTABLISHMENT"),
    ("D2", "D2_ATHENA_INNOVATION", "SOLUTION_APPROACHES"),
    ("D3", "D3_DAEDALUS_CONSTRUCTION", "TECHNICAL_BLUEPRINT"),
    ("B0", "B0_THEMIS_JUDGMENT", "VALIDATION_GATE"),
    ("B1", "B1_HERMES_COORDINATION", "BUILD_EXECUTION_ROADMAP"),
    ("B2", "B2_HEPHAESTUS_FORGE", "CODE_CONSTRUCTION"),
    ("B3", "B3_HARMONIA_UNIFICATION", "SYSTEM_UNIFICATION"),
    ("B4", "B4_IRIS_HANDOFF", "PRODUCTION_HANDOFF"),
    ("B5", "B5_PROMETHEUS_EVOLUTION", "POST_DELIVERY_ENHANCEMENT"),
]


def render_list(key: str, items: list[str], form: str, indent: str = "") -> str:
    """One list field in the hand-written (inline) or octave_write (wrapped) form."""
    if form == "inline":
        return f"{indent}{key}::[{','.join(items)}]"
    inner = ",\n".join(f"{indent}  {item}" for item in items)
    return f"{indent}{key}::[\n{inner}\n{indent}]"


def doc(*body: str) -> str:
    """A minimal workflow document around ``body`` lines."""
    return (
        "===OPERATIONAL_WORKFLOW===\nMETA:\n  TYPE::WORKFLOW\n" + "\n".join(body) + "\n===END===\n"
    )


def synth(tmp_path: Path, text: str, phase: str) -> cs.PhaseConstraints:
    path = tmp_path / "workflow.oct.md"
    path.write_text(text)
    return ContextSteward(workflow_path=path).synthesize_active_state(phase)


# ---------------------------------------------------------------------------------------
# (a) wrapped lists are read in full; the #196 B1 deliverables reproduction
# ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("form", FORMS)
def test_b1_deliverables_reproduction_from_issue_196(tmp_path, form):
    """Issue #196 probe: inline gave ['a','b','c'], wrapped gave ['[']."""
    text = doc(B1, render_list("DELIVERABLES", ["a", "b", "c"], form))
    assert synth(tmp_path, text, "B1").deliverables == ["a", "b", "c"]


@pytest.mark.parametrize("form", FORMS)
def test_wrapped_list_is_read_in_full_for_all_list_fields(tmp_path, form):
    text = doc(
        B1,
        render_list("DELIVERABLES", ["d1", "d2", "d3"], form),
        render_list("ENTRY", ["e1", "e2"], form),
        render_list("EXIT", ["x1", "x2", "x3", "x4"], form),
    )
    got = synth(tmp_path, text, "B1")
    assert got.deliverables == ["d1", "d2", "d3"]
    assert got.entry_criteria == ["e1", "e2"]
    assert got.exit_criteria == ["x1", "x2", "x3", "x4"]


# ---------------------------------------------------------------------------------------
# (b) nested or prefixed keys are not phase markers: one negative test per exclusion
# ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("form", FORMS)
def test_exclusion_list_value_is_not_a_marker(tmp_path, form):
    """``B5_CRITERIA::[...]`` has a list value: an ordinary field, it does not end B1."""
    text = doc(
        B1,
        render_list("B5_CRITERIA", ["c1", "c2"], form),
        render_list("DELIVERABLES", ["d1", "d2"], form),
    )
    assert synth(tmp_path, text, "B1").deliverables == ["d1", "d2"]
    with pytest.raises(ValueError, match="not found"):
        synth(tmp_path, text, "B5")


@pytest.mark.parametrize("form", FORMS)
def test_exclusion_digit_segment_is_not_a_marker(tmp_path, form):
    """``B2_00_REQUIREMENTS::...`` has a digit segment: an ordinary field."""
    text = doc(
        B1,
        "B2_00_REQUIREMENTS::test_strategy_first",
        render_list("DELIVERABLES", ["d1", "d2"], form),
    )
    assert synth(tmp_path, text, "B1").deliverables == ["d1", "d2"]
    with pytest.raises(ValueError, match="not found"):
        synth(tmp_path, text, "B2")


def test_exclusion_key_inside_list_value_inline(tmp_path):
    """``B2_USAGE`` inside ``CONTEXT7_LIBRARY_RESEARCH::[[[...]]]`` is list content."""
    nested = 'CONTEXT7_LIBRARY_RESEARCH::[[[PATTERN::"p"]],[[D1_USAGE::"u1"]],[[B2_USAGE::"u2"]]]'
    text = doc(B1, nested, render_list("DELIVERABLES", ["d1", "d2"], "inline"))
    assert synth(tmp_path, text, "B1").deliverables == ["d1", "d2"]
    with pytest.raises(ValueError, match="not found"):
        synth(tmp_path, text, "B2")


BLOCKER = (
    "parser follow-up: read_octave_fields indent rule for nested KEY:: items in wrapped lists "
    "(ADR-004 v1.9, separate PR); part of #196"
)


class KnownParserBlocker(Exception):  # noqa: N818 - a marker, not an error type
    """Raised ONLY for the exact known blocker: unterminated_list at the nested-list opener."""


def known_parser_blocker(text: str, opener: str, call):
    """Run ``call``; turn the exact known blocker into :class:`KnownParserBlocker`.

    Used with ``xfail(strict=True, raises=KnownParserBlocker)``: the test is an expected
    failure ONLY for ``unterminated_list`` at ``opener``'s line. Any other exception or
    assertion failure is a real failure, and once the parser handles nested keys the test
    XPASSes, which strict mode turns into a failure (remove the xfail then).
    """
    try:
        return call()
    except ValueError as err:  # WorkflowParseError is a ValueError; its attrs identify it
        opens_at = text.splitlines().index(opener) + 1
        if (getattr(err, "construct", None), getattr(err, "line", None)) == (
            "unterminated_list",
            opens_at,
        ):
            raise KnownParserBlocker(BLOCKER) from err
        raise


xfail_known_blocker = pytest.mark.xfail(strict=True, raises=KnownParserBlocker, reason=BLOCKER)


@xfail_known_blocker
def test_exclusion_key_inside_list_value_wrapped(tmp_path):
    """Same content as the inline test, in the octave_write nested-list form."""
    nested = (
        'CONTEXT7_LIBRARY_RESEARCH::[\n  [\n    [\n      PATTERN::"p"\n    ]\n  ],\n'
        '  [\n    [\n      D1_USAGE::"u1"\n    ]\n  ],\n'
        '  [\n    [\n      B2_USAGE::"u2"\n    ]\n  ]\n]'
    )
    text = doc(B1, nested, render_list("DELIVERABLES", ["d1", "d2"], "wrapped"))

    def check():
        assert synth(tmp_path, text, "B1").deliverables == ["d1", "d2"]
        with pytest.raises(ValueError, match="not found"):
            synth(tmp_path, text, "B2")

    known_parser_blocker(text, "CONTEXT7_LIBRARY_RESEARCH::[", check)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("B5_CRITERIA", "[all_components_have_tasks,risks_mitigated]"),  # list value
        ("B5_CRITERIA", "["),  # wrapped-list opener (octave_write form)
        ("B2_00_REQUIREMENTS", "TEST_STRATEGY"),  # digit segment
        ("B1_HERMES_COORDINATION", '"BUILD_EXECUTION_ROADMAP"'),  # quoted value
        ("B1_HERMES_COORDINATION", "build_execution_roadmap"),  # not SCREAMING_SNAKE
        ("B1_HERMES_COORDINATION", "two words"),  # not an identifier
        ("B6_FUTURE_PHASE", "FUTURE"),  # not a phase id
        ("B1", "BUILD"),  # no <LETTERS> part
        ("B1_", "BUILD"),  # empty <LETTERS> part
        ("X_B1_HERMES", "BUILD"),  # phase id is not the prefix
    ],
)
def test_phase_of_marker_rejects_non_markers(key, value):
    assert cs.phase_of_marker(key, value) is None


@pytest.mark.parametrize(("phase", "key", "value"), REAL_MARKERS)
def test_phase_of_marker_accepts_every_real_marker_shape(phase, key, value):
    assert cs.phase_of_marker(key, value) == phase


# ---------------------------------------------------------------------------------------
# POSITIVE: one per real marker shape (all ten phases), through the whole reader
# ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(("phase", "key", "value"), REAL_MARKERS)
@pytest.mark.parametrize("form", FORMS)
def test_positive_real_marker_shape_starts_its_phase(tmp_path, phase, key, value, form):
    text = doc(
        "WORKFLOW_PHASES:",
        f"  {key}::{value}",
        f"  RACI::raci-{phase}",
        render_list("DELIVERABLES", [f"{phase}-one", f"{phase}-two"], form, indent="  "),
    )
    got = synth(tmp_path, text, phase)
    assert got.phase == phase
    assert got.purpose == value  # no PURPOSE field: falls back to the marker value
    assert got.raci == f"raci-{phase}"
    assert got.deliverables == [f"{phase}-one", f"{phase}-two"]


def test_first_marker_for_a_phase_wins(tmp_path):
    text = doc(B1, "PURPOSE::first", "B1_OTHER_NAME::SECOND_MARKER", "PURPOSE::second")
    # the second B1 marker is the next phase marker: it ends the section
    assert synth(tmp_path, text, "B1").purpose == "first"


def test_next_phase_marker_ends_the_section(tmp_path):
    text = doc(B1, "PURPOSE::b1-purpose", "B2_HEPHAESTUS_FORGE::CODE_CONSTRUCTION", "RACI::b2-raci")
    got = synth(tmp_path, text, "B1")
    assert got.purpose == "b1-purpose"
    assert got.raci == "Not specified"


def test_d0_indented_under_workflow_phases_stops_at_next_marker_and_block_header(tmp_path):
    text = doc(
        "WORKFLOW_PHASES:",
        "  D0_MNEMOSYNE_GENESIS::IDEATION_SETUP",
        "  RACI::d0-raci",
        "  ENTRY::[e1,e2]",
        "OTHER_BLOCK:",
        "  RACI::leaked",
        "  ENTRY::[leaked]",
    )
    got = synth(tmp_path, text, "D0")
    assert got.raci == "d0-raci"
    assert got.entry_criteria == ["e1", "e2"]


def test_loud_every_phase_prefixed_key_in_the_bundled_workflow_is_a_marker():
    """If a workflow edit adds a `<PHASE>_...` field that is not a marker, or a second
    marker for a phase, this fails: the marker rule in the module docstring needs a look."""
    fields, reject = read_octave_fields(BUNDLED.read_text())
    assert reject is None
    prefixed = [f for f in fields if re.match(r"^(D[0-3]|B[0-5])_", f.key)]
    markers = [(cs.phase_of_marker(f.key, f.value), f.key) for f in prefixed]
    assert [m[0] for m in markers] == PHASE_IDS, markers  # one marker per phase, in order
    assert [(m[1]) for m in markers] == [k for _, k, _ in REAL_MARKERS]


# ---------------------------------------------------------------------------------------
# (c) the last phase stops at the next column-0 block header
# ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("form", FORMS)
def test_b5_stops_at_the_next_column_zero_block_header(tmp_path, form):
    text = doc(
        B5,
        "PURPOSE::b5-purpose",
        render_list("DELIVERABLES", ["b5-one", "b5-two"], form),
        "ERROR_HANDLING_TAXONOMY:",
        "  PURPOSE::post-mortem-purpose",
        "  RACI::post-mortem-raci",
        render_list("DELIVERABLES", ["leaked"], form, indent="  "),
    )
    got = synth(tmp_path, text, "B5")
    assert got.purpose == "b5-purpose"
    assert got.raci == "Not specified"
    assert got.deliverables == ["b5-one", "b5-two"]


# ---------------------------------------------------------------------------------------
# (d) a comma inside a quoted item stays one item
# ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("form", FORMS)
def test_comma_and_bracket_inside_a_quoted_item_stay_one_item(tmp_path, form):
    items = ['"first, with comma"', "plain", '"has ] bracket, and comma"']
    text = doc(B1, render_list("DELIVERABLES", items, form))
    assert synth(tmp_path, text, "B1").deliverables == [
        "first, with comma",
        "plain",
        "has ] bracket, and comma",
    ]


# ---------------------------------------------------------------------------------------
# malformed lists fail loudly with file, line and construct
# ---------------------------------------------------------------------------------------


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "workflow.oct.md"
    path.write_text(text)
    return path


def test_unterminated_list_raises_workflow_parse_error_with_line_and_construct(tmp_path):
    body = [B1, "PURPOSE::p", "DELIVERABLES::[", "  a,", "  b", "RACI::next-field-ends-the-list"]
    text = doc(*body)
    path = _write(tmp_path, text)
    opens_at = text.splitlines().index("DELIVERABLES::[") + 1
    with pytest.raises(cs.WorkflowParseError) as excinfo:
        ContextSteward(workflow_path=path).synthesize_active_state("B1")
    err = excinfo.value
    assert err.construct == "unterminated_list"
    assert err.line == opens_at
    assert err.file == path
    assert str(path) in str(err) and "unterminated_list" in str(err) and str(opens_at) in str(err)


def test_text_after_list_raises_workflow_parse_error(tmp_path):
    text = doc(B1, "DELIVERABLES::[", "  a", "] trailing")
    path = _write(tmp_path, text)
    with pytest.raises(cs.WorkflowParseError) as excinfo:
        ContextSteward(workflow_path=path).synthesize_active_state("B1")
    assert excinfo.value.construct == "text_after_list"
    assert excinfo.value.line == text.splitlines().index("DELIVERABLES::[") + 1


def test_workflow_parse_error_is_a_value_error_so_todays_handlers_contain_it():
    assert issubclass(cs.WorkflowParseError, ValueError)


def test_malformed_list_elsewhere_still_raises_not_a_partial_phase(tmp_path):
    """The document is untrustworthy: asking for a clean phase must not silently succeed."""
    text = doc("D0_MNEMOSYNE_GENESIS::IDEATION_SETUP", "PURPOSE::fine", B1, "ENTRY::[", "  x,")
    with pytest.raises(cs.WorkflowParseError):
        synth(tmp_path, text, "D0")


# ---------------------------------------------------------------------------------------
# parity with the frozen old reader, on the bundled (inline) workflow
# ---------------------------------------------------------------------------------------

# Intentional difference 1 (defect c): the old reader's B5 section also absorbed the keys of
# the blocks that follow B5 (ERROR_HANDLING_TAXONOMY ... OPERATIONAL_PATTERNS).
B5_ABSORBED_BY_OLD_READER_FROM_LATER_BLOCKS = {
    "ANALYSIS_PURPOSE", "CANONICAL_REFERENCE", "COLLABORATION_PATTERN", "COMPLEX_ERRORS",
    "COMPONENT_ERRORS", "CONSOLIDATED_FROM", "COORDINATION_SYMLINKS", "DECISION_RECORDS",
    "DESIGN_ERRORS", "DOCUMENT_PLACEMENT_PROTOCOL", "DUAL_ANALYSIS", "EMERGENCY_PROTOCOL",
    "ENHANCEMENT_CRITERIA", "ENHANCEMENT_LIFECYCLE", "ENHANCEMENT_PROCESS",
    "ERROR_CLASSIFICATION", "ESCALATION_ERRORS", "IDEATION_GRADUATION_EXECUTION", "INVOCATION",
    "LIFECYCLE_MODEL", "LINK_STANDARDS", "NEW_PROJECT_TRIGGERS", "PHASE_DEPENDENCIES",
    "PHASE_TRANSITION_CLEANUP", "POST_MORTEM_OUTPUT", "QUICK_FIX_ERRORS", "RACI_ACCOUNTABILITY",
    "RECOVERY_PROFILE_STATUS", "RESOLUTION_PROCESS", "SCOPE_CALIBRATION", "SESSION_LIFECYCLE",
    "SYSTEM_ERRORS", "USER_UNAVAILABILITY_PROTOCOL",
}  # fmt: skip
# Intentional difference 2 (list grammar): list items lose ONE surrounding pair of quotes
# (`list_items`), where the old `.split(",")` kept them: '"B2-TEST-STRATEGY.md"' -> 'B2-TEST-STRATEGY.md'.
LIST_FIELDS = ("deliverables", "entry_criteria", "exit_criteria")


def _strip_one_pair(item: str) -> str:
    return item[1:-1] if len(item) >= 2 and item[0] == item[-1] == '"' else item


@pytest.mark.parametrize("phase", PHASE_IDS)
def test_parity_with_old_reader_on_bundled_workflow(phase):
    old = LegacyContextSteward(BUNDLED).synthesize_active_state(phase).to_dict()
    new = ContextSteward(BUNDLED).synthesize_active_state(phase).to_dict()
    expected = dict(old)
    for field in LIST_FIELDS:
        expected[field] = [_strip_one_pair(item) for item in old[field]]
    assert new == expected


def test_parity_section_keys_differ_only_by_the_b5_absorption_defect():
    text = BUNDLED.read_text()
    old_reader = LegacyContextSteward(BUNDLED)
    new_reader = ContextSteward(BUNDLED)
    for phase in PHASE_IDS:
        old = old_reader._extract_phase_section(text, phase) or {}
        new = new_reader._extract_phase_section(text, phase) or {}
        extra = set(old) - set(new)
        assert set(new) <= set(old), (phase, set(new) - set(old))
        assert extra == (B5_ABSORBED_BY_OLD_READER_FROM_LATER_BLOCKS if phase == "B5" else set())
        assert {k: old[k] for k in new} == new  # same raw values for the shared keys


# ---------------------------------------------------------------------------------------
# the octave_write-canonical form of the real workflow
# ---------------------------------------------------------------------------------------


def test_canonical_fixture_is_what_octave_mcp_writes_today(tmp_path):
    """tests/fixtures/OPERATIONAL-WORKFLOW.canonical.oct.md = octave-mcp WriteTool output of
    the bundled workflow (content=<bundled>, format_style='preserve'). Skipped without octave-mcp.
    """
    write_module = pytest.importorskip("octave_mcp.mcp.write")
    target = tmp_path / "OPERATIONAL-WORKFLOW.oct.md"
    result = asyncio.run(
        write_module.WriteTool().execute(
            target_path=str(target), content=BUNDLED.read_text(), format_style="preserve"
        )
    )
    assert result["status"] == "success"
    assert target.read_text() == CANONICAL.read_text()


def test_canonical_fixture_is_the_wrapped_form_of_the_bundled_workflow():
    assert "DELIVERABLES::[\n" in CANONICAL.read_text()
    assert "DELIVERABLES::[\n" not in BUNDLED.read_text()


@xfail_known_blocker
@pytest.mark.parametrize("phase", PHASE_IDS)
def test_all_ten_phases_equal_between_bundled_and_canonical(phase):
    inline = ContextSteward(BUNDLED).synthesize_active_state(phase)
    text = CANONICAL.read_text()

    def check():
        assert ContextSteward(CANONICAL).synthesize_active_state(phase) == inline

    known_parser_blocker(text, "  SCOPE_MATRIX::[", check)


def test_pinned_inline_fixture_matches_the_live_bundled_workflow_when_present():
    if not LIVE_BUNDLED.exists():
        pytest.skip(".hestai-sys is not installed here (gitignored); fixture is the pin")
    assert BUNDLED.read_text() == LIVE_BUNDLED.read_text()
