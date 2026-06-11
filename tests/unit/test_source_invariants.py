"""Source-level invariant tests.

These are **structural** assertions that grep the repository source and
fail CI when a product-level invariant is breached:

- **PROD::I6 LEGACY_INDEPENDENCE**: no runtime import of ``hestai_mcp``
  anywhere under ``src/hestai_context_mcp/``.
- **PROD::I3 PROVIDER_AGNOSTIC_CONTEXT**: no provider SDK or vendor
  identifier ever appears inside ``src/hestai_context_mcp/ports/``.
  (Adapters are allowed to name the providers they speak to; the port
  layer is not.)

These tests intentionally live at the `unit` marker level so they run on
every pytest invocation, not only integration runs.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC_ROOT = _REPO_ROOT / "src" / "hestai_context_mcp"
_PORTS_ROOT = _SRC_ROOT / "ports"

# RFC #53 Gate C application-layer modules that must stay provider-agnostic
# (PROD::I3). These are NOT ports, but they orchestrate the AIClient port and
# must never name a provider in source (mirrors TestNoProviderSdkInPorts).
_GATE_C_PROVIDER_AGNOSTIC_FILES: tuple[Path, ...] = (
    _SRC_ROOT / "core" / "intake_compiler.py",
    _SRC_ROOT / "tools" / "governance" / "intake_context.py",
    # Issue #77: the scoped SEMANTIC governance reviewer consumes the AIClient
    # port at the analysis tier; like the other Gate C app modules it must
    # never name a provider/model in source (PROD::I3).
    _SRC_ROOT / "core" / "governance_reviewer.py",
)


def _iter_python_files(root: Path):
    for path in root.rglob("*.py"):
        # Never scan __pycache__ or compiled artefacts.
        if "__pycache__" in path.parts:
            continue
        yield path


class TestNoHestaiMcpImportInSrc:
    """PROD::I6: no runtime import of the legacy ``hestai_mcp`` package."""

    def test_no_hestai_mcp_imports(self):
        offenders: list[tuple[Path, int, str]] = []
        pattern = re.compile(r"^\s*(?:from|import)\s+hestai_mcp\b")
        for py in _iter_python_files(_SRC_ROOT):
            for lineno, line in enumerate(py.read_text().splitlines(), start=1):
                if pattern.search(line):
                    offenders.append((py, lineno, line.strip()))
        assert not offenders, "PROD::I6 violation — hestai_mcp import found:\n" + "\n".join(
            f"  {p}:{n}: {s}" for p, n, s in offenders
        )


class TestNoProviderSdkInPorts:
    """PROD::I3: no provider SDK or vendor name in ``ports/``.

    Adapters (``adapters/``) are the correct location for provider names.
    The port layer must remain provider-agnostic by structural assertion.
    """

    # Patterns chosen to match imports, URL constants, and vendor names —
    # while not false-positiving on benign English words. Each pattern is a
    # regex guaranteed to hit a concrete provider reference.
    _FORBIDDEN_PATTERNS: tuple[re.Pattern[str], ...] = (
        re.compile(r"\bimport\s+anthropic\b"),
        re.compile(r"\bfrom\s+anthropic\b"),
        re.compile(r"\bimport\s+openai\b"),
        re.compile(r"\bfrom\s+openai\b"),
        # Generic vendor-name substrings (case-insensitive) — catches URL
        # constants, comments that leak vendor intent, or docstrings that
        # couple the port contract to a specific provider.
        re.compile(r"openrouter", re.IGNORECASE),
        re.compile(r"api\.openai\.com", re.IGNORECASE),
        re.compile(r"anthropic\.com", re.IGNORECASE),
    )

    def test_ports_contain_no_provider_names(self):
        if not _PORTS_ROOT.exists():
            # The directory must exist post-#5; this assertion is RED
            # pre-implementation.
            raise AssertionError(
                f"ports/ directory missing at {_PORTS_ROOT} — PROD::I3 cannot be asserted"
            )

        offenders: list[tuple[Path, int, str, str]] = []
        for py in _iter_python_files(_PORTS_ROOT):
            for lineno, line in enumerate(py.read_text().splitlines(), start=1):
                for pat in self._FORBIDDEN_PATTERNS:
                    if pat.search(line):
                        offenders.append((py, lineno, pat.pattern, line.strip()))
        assert not offenders, "PROD::I3 violation — provider name in ports/:\n" + "\n".join(
            f"  {p}:{n} matched /{pat}/: {s}" for p, n, pat, s in offenders
        )


class TestGateCBackendIsProviderAgnostic:
    """PROD::I3: RFC #53 Gate C app modules never name a provider in source.

    The prose->OCTAVE compiler and context assembler consume the AIClient
    port; provider/model/credential resolution lives below the port in
    ``adapters/ai_config``. A vendor literal leaking into these files would
    couple the write-side compiler to a provider — the exact coupling the
    read-side ``TestNoProviderSdkInPorts`` forbids for ports.
    """

    _FORBIDDEN_PATTERNS: tuple[re.Pattern[str], ...] = (
        re.compile(r"\bimport\s+anthropic\b"),
        re.compile(r"\bfrom\s+anthropic\b"),
        re.compile(r"\bimport\s+openai\b"),
        re.compile(r"\bfrom\s+openai\b"),
        re.compile(r"openrouter", re.IGNORECASE),
        re.compile(r"api\.openai\.com", re.IGNORECASE),
        re.compile(r"anthropic\.com", re.IGNORECASE),
        re.compile(r"\bgemini\b", re.IGNORECASE),
        re.compile(r"\bdeepseek\b", re.IGNORECASE),
    )

    def test_gate_c_modules_contain_no_provider_names(self):
        offenders: list[tuple[Path, int, str, str]] = []
        for py in _GATE_C_PROVIDER_AGNOSTIC_FILES:
            if not py.exists():
                continue
            for lineno, line in enumerate(py.read_text().splitlines(), start=1):
                for pat in self._FORBIDDEN_PATTERNS:
                    if pat.search(line):
                        offenders.append((py, lineno, pat.pattern, line.strip()))
        assert (
            not offenders
        ), "PROD::I3 violation — provider name in Gate C app module:\n" + "\n".join(
            f"  {p}:{n} matched /{pat}/: {s}" for p, n, pat, s in offenders
        )


class TestGateCContextAssemblerHasNoHardcodedSystemPrompt:
    """A9: the Stage-1 prompt is JIT-compiled from live repo state.

    There must be no module-level hardcoded multi-line system-prompt
    constant in ``intake_context.py`` — the prompt is assembled at call
    time from the live corpus. We assert the absence of a long string
    literal assigned to a SYSTEM_PROMPT-like module constant.
    """

    _CONTEXT_FILE = _SRC_ROOT / "tools" / "governance" / "intake_context.py"
    # A module-level constant named like a baked system prompt.
    _HARDCODED_PROMPT_RE = re.compile(
        r"(?m)^_?[A-Z][A-Z0-9_]*(SYSTEM_PROMPT|JIT_PROMPT|PROMPT_TEMPLATE)\s*[:=]"
    )

    def test_no_module_level_system_prompt_constant(self):
        if not self._CONTEXT_FILE.exists():
            raise AssertionError(
                f"intake_context.py missing at {self._CONTEXT_FILE} — T1 not implemented"
            )
        offenders: list[tuple[int, str]] = []
        for lineno, line in enumerate(self._CONTEXT_FILE.read_text().splitlines(), start=1):
            if self._HARDCODED_PROMPT_RE.match(line):
                offenders.append((lineno, line.strip()))
        assert not offenders, (
            "A9 violation — hardcoded system-prompt constant in intake_context.py "
            "(prompt must be JIT-compiled from live repo state):\n"
            + "\n".join(f"  line {n}: {s}" for n, s in offenders)
        )


class TestCoreDoesNotImportAdaptersAtModuleLoad:
    """DIP boundary: ``core/`` modules must import only from ``ports/``.

    Concrete adapters may be accessed via lazy imports *inside* function
    bodies (composition-root pattern), but module-level ``from
    hestai_context_mcp.adapters...`` in any ``core/`` file would couple
    the application layer to a concrete implementation at import time
    and violate the Dependency Inversion Principle. Prior CRS review
    flagged this as blocking; this test is the structural regression
    guard.
    """

    _CORE_ROOT = _SRC_ROOT / "core"
    _TOP_LEVEL_ADAPTER_IMPORT: re.Pattern[str] = re.compile(
        r"^\s*from\s+hestai_context_mcp\.adapters"
    )

    def test_no_module_level_adapter_import_in_core(self):
        if not self._CORE_ROOT.exists():
            return  # pragma: no cover — core must exist; belt-and-braces

        offenders: list[tuple[Path, int, str]] = []
        for py in _iter_python_files(self._CORE_ROOT):
            inside_function = False
            for lineno, line in enumerate(py.read_text().splitlines(), start=1):
                stripped = line.lstrip()
                # A line inside a function/method body is indented; a
                # module-level statement starts at column 0. This is a
                # conservative structural test — the DIP concern is
                # import-time coupling, so only col-0 imports matter.
                if line.startswith("def ") or line.startswith("async def "):
                    inside_function = True
                    continue
                if line and not line[0].isspace():
                    # back at module scope — reset the flag
                    inside_function = False
                if (
                    not inside_function
                    and self._TOP_LEVEL_ADAPTER_IMPORT.match(line)
                    and stripped == line.lstrip()  # truly at col 0
                    and line == line.lstrip()
                ):
                    offenders.append((py, lineno, line.rstrip()))
        assert not offenders, "DIP violation — module-level adapter import in core/:\n" + "\n".join(
            f"  {p}:{n}: {s}" for p, n, s in offenders
        )
