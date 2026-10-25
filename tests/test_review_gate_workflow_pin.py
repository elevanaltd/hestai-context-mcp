"""Regression guard: the Review Gate's judge must come from a pinned, trusted checkout (#170).

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

Each guard is a function of the workflow text. ``MUTATIONS`` applies realistic
edits to the real workflow and asserts the named guard catches each one;
``EQUIVALENT_EDITS`` asserts that harmless rewrites are not rejected.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

import pytest

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "review-gate.yml"
STEP_NAME = "Checkout review-gate tooling"
FULL_SHA = re.compile(r"[0-9a-f]{40}")
EXPECTED_SPARSE = [
    "scripts/validate_review.py",
    "src/hestai_context_mcp/tools/shared/review_formats.py",
]
TRUSTED_ROOT = ".review-gate-tools"
TRUSTED_VALIDATOR = f"{TRUSTED_ROOT}/scripts/validate_review.py"

_STEP_NAME_LINE = re.compile(
    r"""^(?P<indent>\s*)-\s+(?P<q>['"]?)name(?P=q)\s*:\s*(?P<name>.+?)\s*$"""
)
# A path-like token naming the validator, in any spelling (file, module, absolute).
_VALIDATOR_REF = re.compile(r"""[^\s"'=()$;|&<>`]*validate_review[^\s"'();|&<>`]*""")
_SCRIPT_PATH_ASSIGN = re.compile(
    r"""(?:^|[\s;&|(])(?:(?:export|local|readonly|declare(?:\s+-\w+)*)\s+)?"""
    r"""SCRIPT_PATH\+?=(?P<value>"[^"]*"|'[^']*'|\S*)"""
)
_PYTHON_RUN = re.compile(r"""\bpython[0-9.]*\s+(?P<target>"[^"]*"|'[^']*'|\S+)""")
_CHDIR = re.compile(r"(?:^|[;&|(]\s*)(?:cd|pushd)\b")
_SCRIPT_PATH_VAR = {"$SCRIPT_PATH", "${SCRIPT_PATH}"}


def _workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _scalar(raw: str) -> str:
    """Strip an inline comment and surrounding quotes from a YAML scalar."""
    value = raw.split(" #", 1)[0].strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        value = value[1:-1]
    return value


def _key(raw: str) -> str:
    """Normalise a mapping key: YAML reads ``if``, ``'if'``, ``"if"`` and ``if :`` alike."""
    return _scalar(raw)


def _split_key(line: str) -> tuple[int, str, str] | None:
    """``(key indent, normalised key, raw value)`` of a mapping line; ``- `` items allowed."""
    if not line.strip() or line.lstrip().startswith("#"):
        return None
    indent = _indent(line)
    rest = line[indent:]
    if rest.startswith("- "):
        after = rest[2:]
        indent += 2 + _indent(after)
        rest = after.lstrip(" ")
    key, sep, value = rest.partition(":")
    if not sep:
        return None
    return indent, _key(key), value


def _block_bodies(lines: list[str], key: str) -> list[list[tuple[int, str]]]:
    """Code lines ``(index, text)`` under every ``key:`` (block scalar or one-line value)."""
    bodies: list[list[tuple[int, str]]] = []
    i = 0
    while i < len(lines):
        parsed = _split_key(lines[i])
        i += 1
        if parsed is None or parsed[1] != key:
            continue
        key_indent, _, raw = parsed
        value = _scalar(raw)
        if not re.fullmatch(r"[|>][-+0-9]*", value):
            bodies.append([(i - 1, value)] if value else [])
            continue
        body: list[tuple[int, str]] = []
        while i < len(lines) and (not lines[i].strip() or _indent(lines[i]) > key_indent):
            code = lines[i].strip()
            if code and not code.startswith("#"):
                body.append((i, code))
            i += 1
        bodies.append(body)
    return bodies


def _tooling_step_span(text: str) -> range:
    """Line indices of the one step named STEP_NAME, ``- name:`` line included."""
    lines = text.splitlines()
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
    return range(start, end)


def _tooling_step_lines(text: str) -> list[str]:
    span = _tooling_step_span(text)
    return text.splitlines()[span.start : span.stop]


def _step_keys(step: list[str]) -> dict[str, str]:
    """Top-level keys of the step (the ``- name:`` line counts as ``name``)."""
    key_indent = _indent(step[0]) + 2
    keys: dict[str, str] = {"name": _scalar(step[0].split(":", 1)[1])}
    for line in step[1:]:
        if not line.strip() or line.lstrip().startswith("#") or _indent(line) != key_indent:
            continue
        key, _, value = line.strip().partition(":")
        keys[_key(key)] = value
    return keys


def _with_block(step: list[str]) -> tuple[dict[str, str], dict[str, list[str]]]:
    """Scalars and block-scalar (``|``) lists inside the step's ``with:`` mapping."""
    key_indent = _indent(step[0]) + 2
    with_at = next(
        (
            i
            for i, line in enumerate(step)
            if _indent(line) == key_indent
            and (parsed := _split_key(line)) is not None
            and parsed[1] == "with"
            and not _scalar(parsed[2])
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
        key = _key(key)
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


# --- Guards: each raises AssertionError when the workflow violates its rule ---


def _guard_repository(text: str) -> None:
    scalars, _ = _with_block(_tooling_step_lines(text))
    assert scalars.get("repository") == "elevanaltd/hestai-context-mcp"


def _guard_ref(text: str) -> None:
    """A branch or tag name is mutable; only a full 40-hex SHA is immutable."""
    scalars, _ = _with_block(_tooling_step_lines(text))
    ref = scalars.get("ref", "")
    assert FULL_SHA.fullmatch(
        ref
    ), f"tooling checkout ref must be a full 40-char lowercase hex commit SHA, got {ref!r}"


def _guard_unconditional(text: str) -> None:
    """An if: here once let this repo's PRs be judged by their own tree (#116 P0-1)."""
    keys = _step_keys(_tooling_step_lines(text))
    assert "if" not in keys, f"step {STEP_NAME!r} must not carry an if: key"


def _guard_sparse(text: str) -> None:
    _, blocks = _with_block(_tooling_step_lines(text))
    assert blocks.get("sparse-checkout") == EXPECTED_SPARSE


def _guard_tooling_path(text: str) -> None:
    """The trusted judge lands where the validator invocation looks for it."""
    scalars, _ = _with_block(_tooling_step_lines(text))
    assert scalars.get("path") == TRUSTED_ROOT


def _guard_validator_invocation(text: str) -> None:
    """The validator runs from the trusted checkout only (#170 item 2).

    validate_review.py loads review_formats.py from its own directory, so pinning
    where the script runs from pins both halves of the judge.
    """
    lines = text.splitlines()
    exempt = set(_tooling_step_span(text))  # the sparse list names the PR-relative path
    exempt |= {i for body in _block_bodies(lines, "script") for i, _ in body}  # JS, not shell
    for i, line in enumerate(lines):
        if i in exempt or line.lstrip().startswith("#"):
            continue
        for ref in _VALIDATOR_REF.findall(line):
            assert ref == TRUSTED_VALIDATOR, f"line {i + 1} names the validator as {ref!r}"
        # A relative SCRIPT_PATH resolves against the cwd, and an env-supplied one is not ours.
        if (parsed := _split_key(line)) is not None:
            assert parsed[1] not in {
                "working-directory",
                "SCRIPT_PATH",
            }, f"line {i + 1} sets {parsed[1]!r}"
    runs = 0
    for body in _block_bodies(lines, "run"):
        assigned = False
        body_runs = 0
        for i, code in body:
            for m in _SCRIPT_PATH_ASSIGN.finditer(code):
                value = _scalar(m["value"])
                assert value == TRUSTED_VALIDATOR, f"line {i + 1} sets SCRIPT_PATH to {value!r}"
                assigned = True
            if re.match(r"(?:echo|printf)\b", code):
                continue
            for m in _PYTHON_RUN.finditer(code):
                target = m["target"].strip("\"'")
                if target in _SCRIPT_PATH_VAR:
                    assert assigned, f"line {i + 1} runs $SCRIPT_PATH before assigning it"
                else:
                    assert target == TRUSTED_VALIDATOR, f"line {i + 1} runs python on {target!r}"
                body_runs += 1
        assert not (
            body_runs and any(_CHDIR.search(code) for _, code in body)
        ), "a run block that invokes the validator changes directory"
        runs += body_runs
    assert runs >= 1, "no run block invokes the validator"


GUARDS: dict[str, Callable[[str], None]] = {
    "repository": _guard_repository,
    "ref": _guard_ref,
    "unconditional": _guard_unconditional,
    "sparse": _guard_sparse,
    "tooling_path": _guard_tooling_path,
    "validator_invocation": _guard_validator_invocation,
}


def _guards_tripped(text: str) -> list[str]:
    tripped = []
    for name, guard in GUARDS.items():
        try:
            guard(text)
        except AssertionError:
            tripped.append(name)
    return tripped


# --- Mutations of the real workflow ---

Mutation = Callable[[str], str]


def _sub(old: str, new: str) -> Mutation:
    def apply(text: str) -> str:
        assert text.count(old) == 1, f"mutation anchor must occur exactly once: {old!r}"
        return text.replace(old, new)

    return apply


def _sub_re(pattern: str, repl: str | Callable[[re.Match[str]], str]) -> Mutation:
    def apply(text: str) -> str:
        mutated, count = re.subn(pattern, repl, text, flags=re.MULTILINE)
        assert count == 1, f"mutation pattern must match exactly once: {pattern!r}"
        return mutated

    return apply


def _chain(*mutations: Mutation) -> Mutation:
    def apply(text: str) -> str:
        for mutation in mutations:
            text = mutation(text)
        return text

    return apply


_NAME = "      - name: Checkout review-gate tooling\n"
_CONE = "          sparse-checkout-cone-mode: false\n"
_REF = r"^(?P<lead>\s+)ref:(?P<gap>\s*)(?P<sha>[0-9a-f]{40})[ \t]*$"
_SCRIPT_PATH = '          SCRIPT_PATH=".review-gate-tools/scripts/validate_review.py"\n'
_RUN = '          OUTPUT=$(python3 "$SCRIPT_PATH" 2>&1)\n'

MUTATIONS = [
    # ref: anything but a full lowercase SHA
    pytest.param(_sub_re(_REF, r"\g<lead>ref: main"), "ref", id="ref-branch"),
    pytest.param(_sub_re(_REF, r"\g<lead>ref: review-gate-v1"), "ref", id="ref-tag-name"),
    pytest.param(
        _sub_re(_REF, lambda m: f"{m['lead']}ref: {m['sha'].upper()}"), "ref", id="ref-uppercase"
    ),
    pytest.param(
        _sub_re(_REF, lambda m: f"{m['lead']}ref: {m['sha'][:12]}"), "ref", id="ref-short-sha"
    ),
    pytest.param(_sub_re(_REF, r"\g<lead>ref: 'main'"), "ref", id="ref-quoted-branch"),
    pytest.param(
        _sub_re(_REF, r"\g<lead>ref: ${{ github.event.pull_request.head.sha }}"),
        "ref",
        id="ref-pr-head-expression",
    ),
    pytest.param(_sub_re(_REF + r"\n", ""), "ref", id="ref-removed"),
    pytest.param(_sub_re(_REF, r"\g<lead>'ref': main"), "ref", id="ref-quoted-key-branch"),
    # repository
    pytest.param(
        _sub(
            "repository: elevanaltd/hestai-context-mcp", "repository: attacker/hestai-context-mcp"
        ),
        "repository",
        id="repository-fork",
    ),
    pytest.param(
        _sub(
            "repository: elevanaltd/hestai-context-mcp",
            '"repository": attacker/hestai-context-mcp',
        ),
        "repository",
        id="repository-quoted-key-fork",
    ),
    # if: on the tooling checkout, in every key spelling YAML accepts
    pytest.param(_sub(_NAME, _NAME + "        if: false\n"), "unconditional", id="if-first-key"),
    pytest.param(_sub(_CONE, _CONE + "        if: always()\n"), "unconditional", id="if-last-key"),
    pytest.param(
        _sub(_NAME, _NAME + "        'if': false\n"), "unconditional", id="if-single-quoted-key"
    ),
    pytest.param(
        _sub(_NAME, _NAME + '        "if": false\n'), "unconditional", id="if-double-quoted-key"
    ),
    pytest.param(
        _sub(_NAME, _NAME + "        if : false\n"), "unconditional", id="if-space-before-colon"
    ),
    pytest.param(
        _sub(_NAME, "      - if: false\n        name: Checkout review-gate tooling\n"),
        "unconditional",
        id="if-before-name",
    ),
    # sparse set
    pytest.param(
        _sub(
            "            src/hestai_context_mcp/tools/shared/review_formats.py\n",
            "            src/hestai_context_mcp/tools/shared/review_formats.py\n"
            "            tests/\n",
        ),
        "sparse",
        id="sparse-extra-path",
    ),
    pytest.param(
        _sub("            scripts/validate_review.py\n", ""),
        "sparse",
        id="sparse-missing-validator",
    ),
    # where the trusted checkout lands
    pytest.param(
        _sub("          path: .review-gate-tools\n", "          path: .tools\n"),
        "tooling_path",
        id="tooling-path-changed",
    ),
    pytest.param(
        _sub("          path: .review-gate-tools\n", "          'path': .tools\n"),
        "tooling_path",
        id="tooling-path-quoted-key",
    ),
    # validator invocation redirected away from the trusted checkout
    pytest.param(
        _sub(_SCRIPT_PATH, '          SCRIPT_PATH="scripts/validate_review.py"\n'),
        "validator_invocation",
        id="script-path-pr-tree",
    ),
    pytest.param(
        _sub(
            _SCRIPT_PATH,
            '          SCRIPT_PATH=".review-gate-tools/../scripts/validate_review.py"\n',
        ),
        "validator_invocation",
        id="script-path-traversal",
    ),
    pytest.param(
        _sub(
            _SCRIPT_PATH, '          SCRIPT_PATH="$GITHUB_WORKSPACE/scripts/validate_review.py"\n'
        ),
        "validator_invocation",
        id="script-path-workspace-root",
    ),
    pytest.param(
        _sub(
            _SCRIPT_PATH,
            _SCRIPT_PATH + '          SCRIPT_PATH="${SCRIPT_PATH#.review-gate-tools/}"\n',
        ),
        "validator_invocation",
        id="script-path-reassigned",
    ),
    pytest.param(
        _sub(_SCRIPT_PATH, ""), "validator_invocation", id="script-path-assignment-removed"
    ),
    pytest.param(
        _chain(
            _sub(_SCRIPT_PATH, ""),
            _sub(
                "          CI: true\n", "          CI: true\n          SCRIPT_PATH: scripts/x.py\n"
            ),
        ),
        "validator_invocation",
        id="script-path-from-env",
    ),
    pytest.param(
        _sub(_RUN, "          OUTPUT=$(python3 scripts/validate_review.py 2>&1)\n"),
        "validator_invocation",
        id="run-line-pr-tree",
    ),
    pytest.param(
        _sub(_RUN, "          OUTPUT=$(python3 -m scripts.validate_review 2>&1)\n"),
        "validator_invocation",
        id="run-line-module",
    ),
    pytest.param(
        _sub(_RUN, '          OUTPUT=$(python3 "$JUDGE" 2>&1)\n'),
        "validator_invocation",
        id="run-line-other-variable",
    ),
    pytest.param(
        _sub(_RUN, _RUN + "          python3 scripts/validate_review.py || true\n"),
        "validator_invocation",
        id="extra-pr-tree-invocation",
    ),
    pytest.param(_sub(_RUN, ""), "validator_invocation", id="invocation-removed"),
    pytest.param(
        _sub(_RUN, '          cd "$RUNNER_TEMP"\n' + _RUN),
        "validator_invocation",
        id="cd-before-invocation",
    ),
    pytest.param(
        _sub(
            "        id: review_check\n",
            "        id: review_check\n        working-directory: sub\n",
        ),
        "validator_invocation",
        id="working-directory-on-step",
    ),
    pytest.param(
        _sub(
            "    runs-on: ubuntu-latest\n",
            "    runs-on: ubuntu-latest\n    defaults:\n      run:\n        working-directory: sub\n",
        ),
        "validator_invocation",
        id="defaults-working-directory",
    ),
]

EQUIVALENT_EDITS = [
    pytest.param(_sub_re(_REF, r"\g<lead>'ref': \g<sha>"), id="ref-quoted-key"),
    pytest.param(_sub_re(_REF, r'\g<lead>ref: "\g<sha>"'), id="ref-quoted-value"),
    pytest.param(
        _sub(
            "repository: elevanaltd/hestai-context-mcp",
            "'repository': elevanaltd/hestai-context-mcp",
        ),
        id="repository-quoted-key",
    ),
    pytest.param(
        _sub(
            _RUN, "          OUTPUT=$(python3 .review-gate-tools/scripts/validate_review.py 2>&1)\n"
        ),
        id="run-line-trusted-literal",
    ),
    pytest.param(
        _sub(_RUN, '          OUTPUT=$(python3 "${SCRIPT_PATH}" 2>&1)\n'), id="run-line-braced"
    ),
]


@pytest.mark.unit
@pytest.mark.parametrize("guard", list(GUARDS))
def test_guard_holds_on_current_workflow(guard: str) -> None:
    GUARDS[guard](_workflow_text())


@pytest.mark.unit
@pytest.mark.parametrize(("mutate", "expected_guard"), MUTATIONS)
def test_mutation_is_caught(mutate: Mutation, expected_guard: str) -> None:
    tripped = _guards_tripped(mutate(_workflow_text()))
    assert (
        expected_guard in tripped
    ), f"mutation slipped past the {expected_guard!r} guard; guards that fired: {tripped}"


@pytest.mark.unit
@pytest.mark.parametrize("mutate", EQUIVALENT_EDITS)
def test_equivalent_edit_is_accepted(mutate: Mutation) -> None:
    assert _guards_tripped(mutate(_workflow_text())) == []
