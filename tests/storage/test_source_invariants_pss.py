"""GROUP_015: SOURCE_INVARIANTS — RED-first tests.

Static invariant tests for the PSS storage layer per BUILD-PLAN
§TDD_TEST_LIST GROUP_015 (TEST_159..TEST_168) plus the CIV G1 acyclic
storage-layering chain.

These are **structural** assertions that grep / parse the repository
source and fail CI when a load-bearing invariant drifts. Behavior is
covered by ``tests/integration/test_pss_lifecycle_local_filesystem.py``
and ``tests/integration/test_get_context_purity.py``; this file is the
mechanical guard.

Binding rulings exercised:

- R5: ``get_context.py`` has no StorageAdapter or LocalFilesystemAdapter
  imports / symbols (G3, also asserted from a different angle in
  test_get_context_purity.py).
- R7: only ``clock_out.py`` may publish portable state.
- R11: no custom Git ref tokens (refs/hestai/*) in storage source.
- R12: no remote-adapter SDK imports (requests, httpx, boto, gitpython).
- G1: storage layering chain is acyclic and ordered:
    types <- protocol <- provenance <- local_filesystem <-
    outbox <- snapshots <- projection <- classification.
- INVARIANT_002: full suite is independent of remote adapters.
- B2_START_BLOCKER_003: no remote adapter / config / wire schema.
- B2_START_BLOCKER_005: no custom Git refs.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC_ROOT = _REPO_ROOT / "src" / "hestai_context_mcp"
_STORAGE_ROOT = _SRC_ROOT / "storage"
_TOOLS_ROOT = _SRC_ROOT / "tools"


def _iter_python_files(root: Path):
    for path in root.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        yield path


def _read_module_imports(path: Path) -> set[str]:
    """Return the set of internal `hestai_context_mcp.X.Y` modules imported."""
    out: set[str] = set()
    pattern = re.compile(
        r"^\s*(?:from|import)\s+(hestai_context_mcp\.[\w\.]+)",
        re.MULTILINE,
    )
    for match in pattern.finditer(path.read_text(encoding="utf-8")):
        out.add(match.group(1))
    return out


# ---------- TEST_159 ----------


class TestNoRemoteAdapterClassNames:
    """TEST_159 — No remote adapter class names under storage/."""

    _FORBIDDEN_CLASS_PATTERNS: tuple[re.Pattern[str], ...] = (
        re.compile(r"\bclass\s+RemoteHttp\w*Adapter\b"),
        re.compile(r"\bclass\s+S3\w*Adapter\b"),
        re.compile(r"\bclass\s+GcsAdapter\b"),
        re.compile(r"\bclass\s+AzureAdapter\b"),
        re.compile(r"\bclass\s+GitRefAdapter\b"),
    )

    def test_no_remote_adapter_class_names_under_storage_package(self) -> None:
        offenders: list[tuple[Path, int, str]] = []
        for py in _iter_python_files(_STORAGE_ROOT):
            for lineno, line in enumerate(py.read_text().splitlines(), start=1):
                # R12 docstrings are allowed to reference R12 by name; we
                # only forbid actual class definitions.
                for pat in self._FORBIDDEN_CLASS_PATTERNS:
                    if pat.search(line):
                        offenders.append((py, lineno, line.strip()))
        assert (
            not offenders
        ), "R12 / B2_START_BLOCKER_003 violation — remote adapter class found:\n" + "\n".join(
            f"  {p}:{n}: {s}" for p, n, s in offenders
        )


# ---------- TEST_160 ----------


class TestNoRemoteSdkImports:
    """TEST_160 — No requests/httpx/boto/gitpython imports in storage/."""

    _FORBIDDEN_IMPORT_PATTERNS: tuple[re.Pattern[str], ...] = (
        re.compile(r"^\s*(?:from|import)\s+requests\b"),
        re.compile(r"^\s*(?:from|import)\s+httpx\b"),
        re.compile(r"^\s*(?:from|import)\s+boto3?\b"),
        re.compile(r"^\s*(?:from|import)\s+google\.cloud\b"),
        re.compile(r"^\s*(?:from|import)\s+azure\b"),
        re.compile(r"^\s*(?:from|import)\s+git\b"),  # gitpython
    )

    def test_no_remote_sdk_imports_in_storage(self) -> None:
        offenders: list[tuple[Path, int, str, str]] = []
        for py in _iter_python_files(_STORAGE_ROOT):
            for lineno, line in enumerate(py.read_text().splitlines(), start=1):
                for pat in self._FORBIDDEN_IMPORT_PATTERNS:
                    if pat.search(line):
                        offenders.append((py, lineno, pat.pattern, line.strip()))
        assert not offenders, "R12 violation — remote SDK import in storage/:\n" + "\n".join(
            f"  {p}:{n} matched /{pat}/: {s}" for p, n, pat, s in offenders
        )


# ---------- TEST_161 ----------


class TestNoCustomGitRefStrings:
    """TEST_161 — No custom Git ref tokens in storage source."""

    _GIT_REF_TOKENS: tuple[str, ...] = (
        "refs/hestai",
        "refs/heads/hestai",
        "refs/tags/hestai",
    )

    def test_no_custom_git_ref_strings_in_storage_implementation(self) -> None:
        offenders: list[tuple[Path, int, str, str]] = []
        for py in _iter_python_files(_STORAGE_ROOT):
            for lineno, line in enumerate(py.read_text().splitlines(), start=1):
                for token in self._GIT_REF_TOKENS:
                    if token in line:
                        offenders.append((py, lineno, token, line.strip()))
        assert not offenders, (
            "R11 / B2_START_BLOCKER_005 violation — custom Git ref token in storage/:\n"
            + "\n".join(f"  {p}:{n} matched '{tok}': {s}" for p, n, tok, s in offenders)
        )


# ---------- TEST_162 ----------


class TestGetContextHasNoStorageAdapterImports:
    """TEST_162 — get_context.py forbids adapter imports."""

    _FORBIDDEN_IMPORT_PATTERNS: tuple[re.Pattern[str], ...] = (
        re.compile(r"^\s*(?:from|import)\s+hestai_context_mcp\.storage\.local_filesystem"),
        re.compile(r"^\s*(?:from|import)\s+hestai_context_mcp\.storage\.outbox"),
        re.compile(r"^\s*(?:from|import)\s+hestai_context_mcp\.storage\.protocol"),
        re.compile(r"^\s*(?:from|import)\s+hestai_context_mcp\.storage\.snapshots"),
    )

    def test_get_context_has_no_storage_adapter_imports(self) -> None:
        path = _TOOLS_ROOT / "get_context.py"
        source = path.read_text(encoding="utf-8")
        offenders: list[tuple[int, str, str]] = []
        for lineno, line in enumerate(source.splitlines(), start=1):
            for pat in self._FORBIDDEN_IMPORT_PATTERNS:
                if pat.search(line):
                    offenders.append((lineno, pat.pattern, line.strip()))
        assert (
            not offenders
        ), "R5 / G3 violation — get_context.py has storage adapter imports:\n" + "\n".join(
            f"  {n} matched /{pat}/: {s}" for n, pat, s in offenders
        )


# ---------- TEST_163 ----------


class TestOnlyClockInRestoresPortableState:
    """TEST_163 — clock_in is the only tool allowed to restore PSS."""

    def test_clock_in_is_only_tool_allowed_to_restore_portable_state(self) -> None:
        # Restore is mediated by build_projection / read_artifact pulled in
        # via clock_in's lazy import path. We assert that no OTHER tool
        # imports the projection builder or the LocalFilesystemAdapter.
        forbidden_in_other_tools = re.compile(
            r"hestai_context_mcp\.storage\.(?:projection|local_filesystem)\b"
        )
        offenders: list[tuple[Path, int, str]] = []
        for py in _iter_python_files(_TOOLS_ROOT):
            if py.name in {"clock_in.py", "clock_out.py"}:
                # clock_in restores; clock_out publishes — both legal.
                continue
            for lineno, line in enumerate(py.read_text().splitlines(), start=1):
                if forbidden_in_other_tools.search(line):
                    offenders.append((py, lineno, line.strip()))
        assert (
            not offenders
        ), "R5 violation — non-clock_in tool references restore plumbing:\n" + "\n".join(
            f"  {p}:{n}: {s}" for p, n, s in offenders
        )


# ---------- TEST_164 ----------


class TestOnlyClockOutPublishesPortableState:
    """TEST_164 — clock_out is the only tool allowed to publish PSS."""

    def test_clock_out_is_only_tool_allowed_to_publish_portable_state(self) -> None:
        # Publish path uses LocalFilesystemAdapter.write_artifact and
        # OutboxStore.enqueue. No other tool may reference these.
        forbidden_in_other_tools = (
            re.compile(r"\.write_artifact\b"),
            re.compile(r"OutboxStore\b"),
        )
        offenders: list[tuple[Path, int, str, str]] = []
        for py in _iter_python_files(_TOOLS_ROOT):
            if py.name == "clock_out.py":
                continue
            # clock_in is allowed to mention OutboxStore for status checks.
            if py.name == "clock_in.py":
                continue
            for lineno, line in enumerate(py.read_text().splitlines(), start=1):
                for pat in forbidden_in_other_tools:
                    if pat.search(line):
                        offenders.append((py, lineno, pat.pattern, line.strip()))
        assert (
            not offenders
        ), "R5 / R7 violation — non-clock_out tool references publish plumbing:\n" + "\n".join(
            f"  {p}:{n} matched /{pat}/: {s}" for p, n, pat, s in offenders
        )


# ---------- TEST_165 ----------


class TestStorageProtocolHasNoProviderSdkImports:
    """TEST_165 — storage/protocol.py is provider-agnostic."""

    def test_storage_protocol_has_no_provider_sdk_imports(self) -> None:
        path = _STORAGE_ROOT / "protocol.py"
        source = path.read_text(encoding="utf-8")
        # The protocol must depend only on stdlib + storage.types.
        bad_imports = re.compile(
            r"^\s*(?:from|import)\s+"
            r"(?:requests|httpx|boto3?|google\.cloud|azure|anthropic|openai)\b",
            re.MULTILINE,
        )
        assert not bad_imports.search(
            source
        ), "R2 / R12 violation — storage/protocol.py imports a provider SDK"


# ---------- TEST_166 ----------


class TestLocalFilesystemAdapterHasNoKeyringImport:
    """TEST_166 — Local adapter never imports keyring or platform secrets."""

    def test_local_filesystem_adapter_has_no_keyring_import(self) -> None:
        path = _STORAGE_ROOT / "local_filesystem.py"
        source = path.read_text(encoding="utf-8")
        bad_imports = re.compile(
            r"^\s*(?:from|import)\s+(?:keyring|secretstorage|win32cred)\b",
            re.MULTILINE,
        )
        assert not bad_imports.search(
            source
        ), "R12 violation — local_filesystem.py imports a credential store SDK"


# ---------- TEST_167 ----------


class TestNoNewToolRegistration:
    """TEST_167 — server.py registers exactly the four B1 tools."""

    def test_no_new_tool_registration_for_publish_or_restore(self) -> None:
        path = _SRC_ROOT / "server.py"
        source = path.read_text(encoding="utf-8")
        # Count mcp.tool(...) registrations.
        registrations = re.findall(r"^\s*mcp\.tool\(([\w_]+)\)", source, re.MULTILINE)
        assert sorted(registrations) == sorted(
            ["clock_in", "clock_out", "get_context", "submit_review"]
        ), (
            "B2_START_BLOCKER_002 / R5 violation — server.py must register exactly "
            f"the four B1 tools; got {registrations}"
        )

    def test_server_does_not_import_publish_or_restore_helpers(self) -> None:
        path = _SRC_ROOT / "server.py"
        source = path.read_text(encoding="utf-8")
        bad = re.compile(r"publish_portable_state|restore_portable_state")
        assert not bad.search(
            source
        ), "R5 violation — server.py must not register publish/restore tools in B1"


# ---------- TEST_168 ----------


class TestNoHestaiMcpImportsAddedByPss:
    """TEST_168 — PSS storage modules never import the legacy hestai_mcp pkg."""

    def test_no_hestai_mcp_imports_added_by_pss(self) -> None:
        bad = re.compile(r"^\s*(?:from|import)\s+hestai_mcp\b", re.MULTILINE)
        offenders: list[tuple[Path, int, str]] = []
        for py in _iter_python_files(_STORAGE_ROOT):
            for lineno, line in enumerate(py.read_text().splitlines(), start=1):
                if bad.search(line):
                    offenders.append((py, lineno, line.strip()))
        assert (
            not offenders
        ), "PROD::I6 / R10 violation — hestai_mcp import in storage/:\n" + "\n".join(
            f"  {p}:{n}: {s}" for p, n, s in offenders
        )


# ---------- G1: layering acyclicity ----------


class TestStorageLayeringAcyclic:
    """G1 (CIV) — storage modules form an acyclic dependency chain.

    Allowed dependency direction (lower depends on higher only):

        types
          ^
          |
        protocol
          ^
          |
        identity / identity_resolver / schema / provenance
          ^
          |
        local_filesystem
          ^
          |
        outbox
          ^
          |
        snapshots
          ^
          |
        projection
          ^
          |
        classification

    Concretely we encode a strict per-module allow-list of internal
    storage imports. Any module-level import outside its allow-list is a
    layering violation.
    """

    # Per-module allowed internal storage dependencies. A module may
    # also import its own __init__ (re-export); those are not enumerated.
    _ALLOWED: dict[str, set[str]] = {
        "types": set(),
        "protocol": {"types"},
        "identity": {"types"},
        "identity_resolver": {"identity", "types"},
        "schema": {"types"},
        "provenance": {"types"},
        "local_filesystem": {"identity", "provenance", "types"},
        "outbox": {"types"},
        "snapshots": {"identity", "types"},
        "projection": {"identity", "types"},
        "classification": {"types"},
    }

    def test_storage_layering_is_acyclic(self) -> None:
        offenders: list[tuple[str, str]] = []
        for py in _iter_python_files(_STORAGE_ROOT):
            mod_name = py.stem
            if mod_name == "__init__":
                continue
            allowed = self._ALLOWED.get(mod_name)
            if allowed is None:
                # Unknown module — must be added explicitly to the
                # allow-list so layering is decided, not inferred.
                offenders.append(
                    (mod_name, "module is not in the G1 allow-list; add it explicitly")
                )
                continue
            imports = _read_module_imports(py)
            internal_storage = {
                name.split(".")[2]
                for name in imports
                if name.startswith("hestai_context_mcp.storage.")
            }
            # Self-imports are not possible at module-level here; ignore.
            internal_storage.discard(mod_name)
            forbidden = internal_storage - allowed
            if forbidden:
                offenders.append(
                    (mod_name, f"forbidden imports {sorted(forbidden)}; allowed: {sorted(allowed)}")
                )
        assert not offenders, "G1 layering violation:\n" + "\n".join(
            f"  storage/{m}.py: {msg}" for m, msg in offenders
        )

    def test_storage_classification_is_a_leaf_consumer(self) -> None:
        """``classification.py`` is the final consumer; nothing imports it."""
        offenders: list[tuple[Path, int, str]] = []
        bad = re.compile(r"^\s*(?:from|import)\s+hestai_context_mcp\.storage\.classification")
        for py in _iter_python_files(_STORAGE_ROOT):
            if py.stem == "classification":
                continue
            for lineno, line in enumerate(py.read_text().splitlines(), start=1):
                if bad.search(line):
                    offenders.append((py, lineno, line.strip()))
        assert (
            not offenders
        ), "G1 violation — storage.classification must remain a leaf:\n" + "\n".join(
            f"  {p}:{n}: {s}" for p, n, s in offenders
        )

    def test_storage_package_exposes_b1_layering_frozen_constant(self) -> None:
        """G1 — the storage package declares ``B1_LAYERING_FROZEN = True``.

        The constant is the canonical positive marker that the B1
        layering chain is sealed for the B1 phase. The post-B2 quality
        gate chain (TMG -> CRS -> CE -> CIV) introspects it at runtime
        to confirm B1's structural invariants are the ones currently in
        force. Future B2 work that adds adapters MUST flip this constant
        to False (or, preferably, replace it with a version-tagged
        equivalent) so the quality gate chain catches the layering
        change instead of silently accepting drift.
        """
        from hestai_context_mcp import storage

        assert hasattr(storage, "B1_LAYERING_FROZEN"), (
            "G1 violation: storage package must declare B1_LAYERING_FROZEN "
            "constant so the post-B2 quality gate chain can introspect "
            "structural invariants."
        )
        assert (
            storage.B1_LAYERING_FROZEN is True
        ), "G1 violation: storage.B1_LAYERING_FROZEN must be True in B1."
