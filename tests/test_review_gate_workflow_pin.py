"""Regression guard: the Review Gate's tooling checkout must pin an immutable commit (#170).

``.github/workflows/review-gate.yml`` is the required check for every repo wired
to org ruleset 12626210. Its "Checkout review-gate tooling" step fetches the
judge (``validate_review.py`` + ``review_formats.py``) from this repository.
When that step tracked a branch (``ref: main``), every merge here changed the
judge of other repos with no release step in between.
HO-REVIEW-GATE-PIN-RELEASE-20261025 pins it to the commit tagged
``review-gate-v1``.

These tests read the workflow as text with the stdlib only. The repository has
no YAML library and this guard does not justify adding one, so the step is
located by its ``- name:`` line and scoped by indentation.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "review-gate.yml"
STEP_NAME = "Checkout review-gate tooling"
FULL_SHA = re.compile(r"[0-9a-f]{40}")
EXPECTED_SPARSE = [
    "scripts/validate_review.py",
    "src/hestai_context_mcp/tools/shared/review_formats.py",
]

_STEP_NAME_LINE = re.compile(r"^(?P<indent>\s*)- name:\s*(?P<name>.+?)\s*$")


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _scalar(raw: str) -> str:
    """Strip an inline comment and surrounding quotes from a YAML scalar."""
    value = raw.split(" #", 1)[0].strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        value = value[1:-1]
    return value


def _tooling_step_lines() -> list[str]:
    """Return the lines of the one step named STEP_NAME, ``- name:`` line included."""
    lines = WORKFLOW.read_text(encoding="utf-8").splitlines()
    starts = [
        (i, len(m.group("indent")))
        for i, line in enumerate(lines)
        if (m := _STEP_NAME_LINE.match(line)) and _scalar(m.group("name")) == STEP_NAME
    ]
    assert len(starts) == 1, f"expected exactly one step named {STEP_NAME!r}, found {len(starts)}"
    start, dash_indent = starts[0]
    end = len(lines)
    for j in range(start + 1, len(lines)):
        line = lines[j]
        if line.strip() and not line.lstrip().startswith("#") and _indent(line) <= dash_indent:
            end = j
            break
    return lines[start:end]


def _step_keys(step: list[str]) -> dict[str, str]:
    """Top-level keys of the step (the ``- name:`` line counts as ``name``)."""
    key_indent = _indent(step[0]) + 2
    keys: dict[str, str] = {"name": _scalar(step[0].split(":", 1)[1])}
    for line in step[1:]:
        if not line.strip() or line.lstrip().startswith("#") or _indent(line) != key_indent:
            continue
        key, _, value = line.strip().partition(":")
        keys[key] = value
    return keys


def _with_block(step: list[str]) -> tuple[dict[str, str], dict[str, list[str]]]:
    """Scalars and block-scalar (``|``) lists inside the step's ``with:`` mapping."""
    key_indent = _indent(step[0]) + 2
    with_at = next(
        (
            i
            for i, line in enumerate(step)
            if _indent(line) == key_indent and line.strip() == "with:"
        ),
        None,
    )
    assert with_at is not None, f"step {STEP_NAME!r} has no with: mapping"
    scalars: dict[str, str] = {}
    blocks: dict[str, list[str]] = {}
    body = step[with_at + 1 :]
    arg_indent = next((_indent(line) for line in body if line.strip()), None)
    assert arg_indent is not None and arg_indent > key_indent, "with: mapping is empty"
    i = 0
    while i < len(body):
        line = body[i]
        i += 1
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if _indent(line) < arg_indent:
            break
        if _indent(line) != arg_indent:
            continue
        key, _, value = line.strip().partition(":")
        if _scalar(value) == "|":
            items: list[str] = []
            while i < len(body) and (not body[i].strip() or _indent(body[i]) > arg_indent):
                if body[i].strip():
                    items.append(body[i].strip())
                i += 1
            blocks[key] = items
        else:
            scalars[key] = _scalar(value)
    return scalars, blocks


@pytest.mark.unit
def test_tooling_checkout_targets_this_repository() -> None:
    scalars, _ = _with_block(_tooling_step_lines())
    assert scalars.get("repository") == "elevanaltd/hestai-context-mcp"


@pytest.mark.unit
def test_tooling_checkout_ref_is_a_full_commit_sha() -> None:
    """A branch or tag name is mutable; only a full 40-hex SHA is immutable."""
    scalars, _ = _with_block(_tooling_step_lines())
    ref = scalars.get("ref", "")
    assert FULL_SHA.fullmatch(
        ref
    ), f"tooling checkout ref must be a full 40-char lowercase hex commit SHA, got {ref!r}"


@pytest.mark.unit
def test_tooling_checkout_is_unconditional() -> None:
    """An if: here once let this repo's PRs be judged by their own tree (#116 P0-1)."""
    keys = _step_keys(_tooling_step_lines())
    assert "if" not in keys, f"step {STEP_NAME!r} must not carry an if: key"


@pytest.mark.unit
def test_tooling_checkout_sparse_set_is_exactly_the_judge() -> None:
    _, blocks = _with_block(_tooling_step_lines())
    assert blocks.get("sparse-checkout") == EXPECTED_SPARSE
