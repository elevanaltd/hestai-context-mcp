"""PR-4 slice B6: byte-equal parity of the three read tools across the two syntaxes.

The SAME logical record stored as OCTAVE (``<token>.oct.md``) and as quoted YAML
(``<token>.md``) must produce IDENTICAL ``lookup_decision`` / ``list_decisions`` /
``trace_supersedure`` output. The only fields allowed to differ are listed in
``PATH_FIELDS`` (the on-disk path, which carries the file extension).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from hestai_context_mcp.tools.list_decisions import list_decisions
from hestai_context_mcp.tools.lookup_decision import lookup_decision
from hestai_context_mcp.tools.trace_supersedure import trace_supersedure

from ._agr_fixtures import write_record, write_yaml_record, yaml_topic_lines

pytestmark = pytest.mark.unit

# EXPLICIT EXCEPTIONS to byte-equality: only the repo-relative file path, which
# necessarily differs (".oct.md" vs ".md"). Everything else must be identical.
PATH_FIELDS = frozenset({"path"})

OLD = "HO-PARITY-OLD-20260101"
MID = "HO-PARITY-MID-20260201"
NEW = "HO-PARITY-NEW-20260301"
TOPIC_TOKEN = "TOPIC-PARITY-ACCESS-20261015"
PLAIN = "HO-PARITY-PLAIN-20260601"

CURRENT = [("R2", "Access is granted per project."), ("R3", "Offboarding isn't deferred: é ✓")]
RULINGS = [
    {
        "id": "R2",
        "rule": "Access is granted per project.",
        "verbatim": "Access per project.",
        "ruled": "Operator, 2026-10-15",
        "replaces": "R1",
    },
    {"id": "R3", "rule": "Offboarding isn't deferred: é ✓", "ruled": "Operator, 2026-10-16"},
]


def _octave_topic_lines() -> list[str]:
    lines = ['  TOPIC::"client-access"', "CURRENT:"]
    lines += [f'  {rid}::"{rule}"' for rid, rule in CURRENT]
    lines.append("RULINGS:")
    for entry in RULINGS:
        lines.append(f"  {entry['id']}:")
        for key in ("rule", "verbatim", "ruled", "replaces"):
            if key in entry:
                lines.append(f'    {key.upper()}::"{entry[key]}"')
    return lines


def _seed_octave(root: Path) -> None:
    write_record(
        root, token=PLAIN, scope="repo", tier="TACTICAL", authored_at="2026-06-01T00:00:00Z"
    )
    write_record(
        root,
        token=TOPIC_TOKEN,
        authored_at="2026-10-15T00:00:00Z",
        extra_lines=_octave_topic_lines(),
    )
    write_record(
        root, token=OLD, status="SUPERSEDED", authored_at="2026-01-01T00:00:00Z", superseded_by=MID
    )
    write_record(
        root, token=MID, status="SUPERSEDED", authored_at="2026-02-01T00:00:00Z", superseded_by=NEW
    )
    write_record(root, token=NEW, authored_at="2026-03-01T00:00:00Z")


def _seed_yaml(root: Path) -> None:
    write_yaml_record(
        root, token=PLAIN, scope="repo", tier="TACTICAL", authored_at="2026-06-01T00:00:00Z"
    )
    write_yaml_record(
        root,
        token=TOPIC_TOKEN,
        authored_at="2026-10-15T00:00:00Z",
        topic="client-access",
        extra_lines=yaml_topic_lines(CURRENT, RULINGS),
    )
    write_yaml_record(
        root, token=OLD, status="SUPERSEDED", authored_at="2026-01-01T00:00:00Z", superseded_by=MID
    )
    write_yaml_record(
        root, token=MID, status="SUPERSEDED", authored_at="2026-02-01T00:00:00Z", superseded_by=NEW
    )
    write_yaml_record(root, token=NEW, authored_at="2026-03-01T00:00:00Z")


def _scrub(value: Any) -> Any:
    """Drop ONLY the named path fields (recursively); everything else is compared as-is."""
    if isinstance(value, dict):
        return {k: _scrub(v) for k, v in value.items() if k not in PATH_FIELDS}
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    return value


def _paths(value: Any) -> list[str]:
    if isinstance(value, dict):
        out = [v for k, v in value.items() if k in PATH_FIELDS]
        for v in value.values():
            out += _paths(v)
        return out
    if isinstance(value, list):
        return [p for v in value for p in _paths(v)]
    return []


def _canonical(value: Any) -> str:
    return json.dumps(_scrub(value), sort_keys=True, ensure_ascii=False)


@pytest.fixture
def repos(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    octave_root = tmp_path_factory.mktemp("octave")
    yaml_root = tmp_path_factory.mktemp("yaml")
    _seed_octave(octave_root)
    _seed_yaml(yaml_root)
    return octave_root, yaml_root


def _assert_equal_modulo_paths(octave_result: Any, yaml_result: Any) -> None:
    assert _canonical(yaml_result) == _canonical(octave_result)
    octave_paths, yaml_paths = _paths(octave_result), _paths(yaml_result)
    assert len(octave_paths) == len(yaml_paths)
    for oct_path, yaml_path in zip(octave_paths, yaml_paths, strict=True):
        assert oct_path.removesuffix(".oct.md") == yaml_path.removesuffix(".md")
        assert oct_path.endswith(".oct.md") and yaml_path.endswith(".md")


@pytest.mark.parametrize("token", [PLAIN, TOPIC_TOKEN, OLD, MID, NEW])
def test_lookup_decision_is_identical_across_syntaxes(repos: tuple[Path, Path], token: str) -> None:
    octave_root, yaml_root = repos
    octave_result = lookup_decision(str(octave_root), token)
    yaml_result = lookup_decision(str(yaml_root), token)
    assert octave_result["ok"] is True
    _assert_equal_modulo_paths(octave_result, yaml_result)


def test_topic_record_parity_covers_current_state_and_fields(repos: tuple[Path, Path]) -> None:
    octave_root, yaml_root = repos
    record = lookup_decision(str(yaml_root), TOPIC_TOKEN)["record"]
    assert record["current_state"] == [{"id": rid, "rule": rule} for rid, rule in CURRENT]
    assert record["fields"] == {"TOPIC": "client-access"}
    assert (
        record["current_state"]
        == lookup_decision(str(octave_root), TOPIC_TOKEN)["record"]["current_state"]
    )


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"status": "SUPERSEDED"},
        {"status": "RATIFIED"},
        {"tier": "TACTICAL"},
        {"scope": "repo"},
        {"topic": "client-access"},
        {"topic": "nope"},
    ],
)
def test_list_decisions_is_identical_across_syntaxes(
    repos: tuple[Path, Path], kwargs: dict[str, str]
) -> None:
    octave_root, yaml_root = repos
    octave_result = list_decisions(str(octave_root), **kwargs)
    yaml_result = list_decisions(str(yaml_root), **kwargs)
    assert octave_result["ok"] is True
    _assert_equal_modulo_paths(octave_result, yaml_result)


@pytest.mark.parametrize("token", [OLD, MID, NEW, PLAIN])
def test_trace_supersedure_is_identical_across_syntaxes(
    repos: tuple[Path, Path], token: str
) -> None:
    octave_root, yaml_root = repos
    _assert_equal_modulo_paths(
        trace_supersedure(str(octave_root), token), trace_supersedure(str(yaml_root), token)
    )


def test_not_found_and_malformed_envelopes_are_identical(repos: tuple[Path, Path]) -> None:
    octave_root, yaml_root = repos
    for token in ("HO-PARITY-MISSING-20260101", "not-a-token"):
        assert (
            lookup_decision(str(yaml_root), token) == lookup_decision(str(octave_root), token) | {}
        )
    for token in ("HO-PARITY-MISSING-20260101",):
        assert trace_supersedure(str(yaml_root), token) == trace_supersedure(
            str(octave_root), token
        )


def test_supersedes_derived_chain_equals_the_explicit_octave_chain(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    """A frozen OCTAVE chain, re-expressed as YAML ``supersedes:`` edges, traces identically."""
    explicit = tmp_path_factory.mktemp("explicit")
    write_record(
        explicit,
        token=OLD,
        status="SUPERSEDED",
        authored_at="2026-01-01T00:00:00Z",
        superseded_by=MID,
    )
    write_record(
        explicit,
        token=MID,
        status="SUPERSEDED",
        authored_at="2026-02-01T00:00:00Z",
        superseded_by=NEW,
    )
    write_record(explicit, token=NEW, authored_at="2026-03-01T00:00:00Z")

    derived = tmp_path_factory.mktemp("derived")
    write_record(derived, token=OLD, authored_at="2026-01-01T00:00:00Z")  # frozen: RATIFIED on disk
    write_record(derived, token=MID, authored_at="2026-02-01T00:00:00Z")  # frozen: RATIFIED on disk
    write_yaml_record(
        derived, token=NEW, authored_at="2026-03-01T00:00:00Z", supersedes=f"{OLD},{MID}"
    )

    # Both corpora walk MID -> NEW; compare that hop entry by entry.
    explicit_trace = trace_supersedure(str(explicit), MID)
    derived_trace = trace_supersedure(str(derived), MID)
    assert _scrub(derived_trace["chain"]) == _scrub(explicit_trace["chain"])
    assert derived_trace["terminal_token"] == explicit_trace["terminal_token"]
    assert derived_trace["terminal_status"] == explicit_trace["terminal_status"]
