"""Shared read primitives for the AGR consumer tools (ADR-RFC-ARCH-004 §3).

Single source of truth for the three pure-read tools (lookup_decision,
list_decisions, trace_supersedure):

* the §3.1.1 common error envelope (PROD I4),
* working_dir validation (WORKING_DIR_INVALID),
* TOKEN-format validation (§1.3) reusing the type_checker regex,
* record discovery on disk (filename↔TOKEN, §1.1 flat + sub-grouped layouts),
* structured parsing via ``core.agent_readable_governance_parser``.

Pure reads (PROD I5): nothing here writes or mutates the filesystem. Regex-only
(North Star §4): no OCTAVE AST parsing, no LLM. Reuses the established Gate-A
primitives (``type_checker._TOKEN_FORMAT_RE`` / ``_extract_token``) rather than
rebuilding them.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from hestai_context_mcp.core.agent_readable_governance_parser import (
    DecisionRecord,
    diagnose_yaml_record,
    extract_yaml_token,
    has_yaml_decision_header,
    is_yaml_front_matter,
    parse_decision_record,
    parse_supersedes_list,
)

# §1.3 TOKEN format + the §1.2 required-field contract + the v1.1 §4.1 #13
# reasoning-density contract — reuse the authoritative Gate-A definitions (do not
# rebuild). ``REQUIRED_META_FIELDS`` is the SINGLE SOURCE OF TRUTH shared with
# the write-side validator so the read-side parse-completeness check
# (``record_is_parseable``) and Gate A's required-field presence check (§4.1 #2)
# can never drift; likewise ``MAX_REASONING_WORDS`` / ``REASONING_FIELDS`` keep
# the read side and the write-side density guard in lockstep on what "compressed
# bytecode" means (issue #88 write/read parity).
from hestai_context_mcp.tools.governance.type_checker import (
    _DECISION_RECORD_TYPE,
    MAX_REASONING_WORDS,  # noqa: F401  (re-export for read/write parity)
    REASONING_FIELDS,  # noqa: F401  (re-export for read/write parity)
    _extract_sentinel,
    _extract_token,
)
from hestai_context_mcp.tools.governance.type_checker import (
    _TOKEN_FORMAT_RE as TOKEN_FORMAT_RE,
)
from hestai_context_mcp.tools.governance.type_checker import (
    REQUIRED_META_FIELDS as _REQUIRED_META_FIELDS,
)

# The §1.2 required fields whose presence proves the OCTAVE envelope parsed,
# expressed as the lowercase DecisionRecord keys. Derived from the shared
# write-side tuple (excluding VERSION, which the parser surfaces but
# record_is_parseable has never gated on — see DecisionRecord/_CORE_FIELDS) so
# the two sides stay in lockstep by construction.
_REQUIRED_FIELDS = tuple(name.lower() for name in _REQUIRED_META_FIELDS if name != "VERSION")

# Read-side TYPE-membership regex: LINE-ANCHORED and EXACT (CRS P2 guard).
# The KEY must be exactly ``TYPE`` at line start — a leading whitespace-only
# indent is allowed (OCTAVE META bodies are indented), but NO other characters
# may precede ``TYPE``. This rejects ``DOCUMENT_TYPE::``/``CONTENT_TYPE::`` and
# any other ``*TYPE::DECISION_RECORD`` substring that Gate-A's unanchored
# ``_TYPE_RE.search()`` would falsely admit. The trailing ``\s*$`` end-anchor
# rejects trailing garbage (e.g. ``TYPE::DECISION_RECORD EXTRA``). This is a
# read-side-only decision; Gate-A's shared ``_TYPE_RE`` is intentionally NOT
# touched (write-side root, tracked separately).
_TYPE_IS_DECISION_RECORD_RE = re.compile(
    r"(?m)^\s*TYPE::" + re.escape(_DECISION_RECORD_TYPE) + r"\s*$"
)


# Shared §3.1.1 wording for a record that is in scope but failed to parse. Names
# BOTH syntaxes (OCTAVE ``.oct.md`` and quoted-YAML front-matter ``.md``).
PARSE_ERROR_WORDING = "missing OCTAVE envelope or YAML front matter, or required §1.2 field(s)"


def parse_failure_detail(content: str) -> dict[str, Any] | None:
    """Return ``{"line": int, "construct": str}`` for a rejected YAML record, else ``None``.

    The B1 loud-reject detail: a YAML record the strict subset refuses is reported
    with its 1-based line and the offending construct, never silently skipped.
    ``None`` for OCTAVE records and for YAML records that are merely incomplete.
    """
    reject = diagnose_yaml_record(content)
    return None if reject is None else {"line": reject["line"], "construct": reject["construct"]}


def parse_failure_detail_for_path(path: Path) -> dict[str, Any] | None:
    """:func:`parse_failure_detail` for a file (``None`` if it cannot be read)."""
    try:
        return parse_failure_detail(path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return None


def parse_error_text(detail: dict[str, Any] | None) -> str:
    """The shared ``parse_error`` string, naming the line/construct when known."""
    if detail is None:
        return PARSE_ERROR_WORDING
    return f"{PARSE_ERROR_WORDING}; rejected at line {detail['line']}: {detail['construct']}"


def is_decision_record(content: str) -> bool:
    """True iff this OCTAVE or YAML document declares itself a DECISION_RECORD (AGR).

    A document opening with a ``---`` fence is judged ONLY by its YAML header
    (``type: "DECISION_RECORD"`` inside the fences); OCTAVE-shaped lines in its
    markdown body can never qualify it.

    Type membership is a SCOPING signal, distinct from parse-completeness
    (``record_is_parseable``). ``.hestai/decisions/`` legitimately co-hosts
    non-AGR governance artefacts (BUILD_PLAN, SECURITY_DESIGN_REVIEW, arbitration
    records) per ADR-RFC-ARCH-001; those are OUT OF SCOPE for the AGR read tools
    and must be skipped silently — never raised as RECORD_PARSE_FAILED.

    A document is a DECISION_RECORD iff its opening sentinel is
    ``===DECISION_RECORD===`` OR a META line is EXACTLY ``TYPE::DECISION_RECORD``
    (§1.1). The two signals are OR-ed. The sentinel branch reuses the Gate-A
    ``_extract_sentinel`` (already ``\\A===…===`` anchored/exact). The TYPE
    branch uses a read-side LINE-ANCHORED regex (``_TYPE_IS_DECISION_RECORD_RE``)
    rather than Gate-A's substring-tolerant ``_TYPE_RE`` so a non-AGR line such
    as ``DOCUMENT_TYPE::DECISION_RECORD`` / ``CONTENT_TYPE::DECISION_RECORD``
    can never qualify (CRS P2 — same failure class as F1).
    """
    if is_yaml_front_matter(content):
        return has_yaml_decision_header(content)
    if _extract_sentinel(content) == _DECISION_RECORD_TYPE:
        return True
    return _TYPE_IS_DECISION_RECORD_RE.search(content) is not None


def error_envelope(
    *,
    code: str,
    category: str,
    message: str,
    tool: str,
    context: dict[str, Any],
    contract_ref: str,
) -> dict[str, Any]:
    """Build the §3.1.1 common error envelope (PROD I4).

    The required keys are fixed; callers MAY pass any tool-specific ``context``
    payload. Opaque-blob errors are forbidden — this is the only error shape the
    AGR tools emit.
    """
    return {
        "ok": False,
        "error": {
            "code": code,
            "category": category,
            "message": message,
            "tool": tool,
            "context": context,
            "contract_ref": contract_ref,
        },
    }


def validate_working_dir(working_dir: str) -> Path | None:
    """Return the resolved decisions-bearing path, or ``None`` if invalid.

    ``None`` signals the caller to emit a WORKING_DIR_INVALID envelope. A path
    that exists and is a directory is valid even when ``.hestai/decisions`` is
    absent (an empty store is a valid empty result, not an error).
    """
    try:
        path = Path(working_dir)
    except (TypeError, ValueError):
        return None
    if not path.exists() or not path.is_dir():
        return None
    return path


def decisions_root(working_dir: Path) -> Path:
    """Return the canonical AGR store root (may not exist yet)."""
    return working_dir / ".hestai" / "decisions"


def _is_yaml_record_file(path: Path) -> bool:
    """True iff ``path`` is a plain ``.md`` carrying the YAML decision header."""
    if path.name.endswith(".oct.md") or not path.is_file():
        return False
    try:
        return has_yaml_decision_header(path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return False


def iter_record_paths(working_dir: Path) -> list[Path]:
    """Return every candidate record under ``.hestai/decisions/**`` (sorted, stable).

    Every ``*.oct.md`` plus every other ``*.md`` that carries the YAML decision
    header (so READMEs and other markdown are never misread as records). Honours
    both the §1.1 flat layout and ``<group>/`` sub-grouping. Read-only.
    """
    root = decisions_root(working_dir)
    if not root.exists():
        return []
    paths = set(root.rglob("*.oct.md"))
    paths.update(p for p in root.rglob("*.md") if _is_yaml_record_file(p))
    return sorted(paths)


def is_valid_token(token: str) -> bool:
    """True iff ``token`` matches the §1.3 TOKEN regex (reused from Gate A)."""
    return bool(TOKEN_FORMAT_RE.match(token))


def rel_path(working_dir: Path, path: Path) -> str:
    """Repo-relative POSIX path string for a record (§3.2/§3.3/§3.4 ``path``)."""
    return path.relative_to(working_dir).as_posix()


def record_is_parseable(parsed: DecisionRecord) -> bool:
    """True iff every §1.2 required field parsed (envelope + fields present)."""
    if parsed.get("type") != "DECISION_RECORD":
        return False
    return all(parsed.get(field) is not None for field in _REQUIRED_FIELDS)


def _is_decision_record_for_token(path: Path, token: str) -> bool:
    """True iff ``path`` is a DECISION_RECORD whose embedded TOKEN == ``token``.

    Both conditions are required: a co-located non-AGR (BUILD_PLAN, etc.) must
    NOT resolve as a record even if its filename collides, and an AGR whose
    filename drifted from its TOKEN must still resolve by content. Read-only.
    """
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    if not is_decision_record(content):
        return False
    if is_yaml_front_matter(content):
        return extract_yaml_token(content) == token
    return _extract_token(content) == token


def discover_record(working_dir: Path, token: str) -> Path | None:
    """Resolve a TOKEN to its on-disk DECISION_RECORD path, or ``None``.

    Resolution is path-first (§1.1 filename↔TOKEN): the canonical filename is
    ``<token>.oct.md`` (else ``<token>.md`` for a YAML record) under the flat root
    or any sub-group. Every candidate is
    verified to be a DECISION_RECORD whose embedded TOKEN equals ``token`` —
    a co-located non-AGR ``.oct.md`` can never resolve as a record (F1 guard).
    As a fallback (a record whose filename drifted from its TOKEN), the store is
    scanned by content. Deterministic for identical filesystem state.

    SECURITY (P1 — fix-the-class path-traversal guard): the ``token`` is
    validated against the §1.3 TOKEN regex BEFORE it is ever joined into a path
    (``root / f"{token}.oct.md"``) or used in an ``rglob`` glob. The §1.3 format
    ``^[A-Z][A-Z0-9_-]{1,126}[A-Z0-9_]-[0-9]{8}$`` admits no ``/``, ``.`` or
    ``..`` sequence, so a traversal-shaped token (e.g. ``../../../etc/passwd``)
    is rejected here — closing the escape for EVERY caller at once, including
    ``trace_supersedure``, which does not pre-validate. Callers that need the
    explicit TOKEN_MALFORMED envelope (lookup_decision) still validate upstream;
    this guard is defence-in-depth and simply returns ``None`` (not found).
    """
    if not is_valid_token(token):
        return None

    root = decisions_root(working_dir)
    if not root.exists():
        return None

    # Fast path: canonical filename match (flat or sub-grouped), type-verified.
    direct = root / f"{token}.oct.md"
    if direct.exists() and _is_decision_record_for_token(direct, token):
        return direct
    for candidate in sorted(root.rglob(f"{token}.oct.md")):
        if _is_decision_record_for_token(candidate, token):
            return candidate
    direct_yaml = root / f"{token}.md"
    if direct_yaml.exists() and _is_decision_record_for_token(direct_yaml, token):
        return direct_yaml
    for candidate in sorted(root.rglob(f"{token}.md")):
        if _is_decision_record_for_token(candidate, token):
            return candidate

    # Fallback: embedded-TOKEN scan (filename drifted from TOKEN), type-verified.
    for path in iter_record_paths(working_dir):
        if _is_decision_record_for_token(path, token):
            return path
    return None


def load_parsed(path: Path) -> DecisionRecord:
    """Read + parse a record file into a structured dict (pure read)."""
    content = path.read_text(encoding="utf-8", errors="replace")
    return parse_decision_record(content)


def classify_file(path: Path) -> tuple[bool, DecisionRecord]:
    """Read a file ONCE and return ``(is_decision_record, parsed)`` (pure read).

    The two-way scoping split for list_decisions (F1):
      * ``is_decision_record`` False  → out of scope (co-located non-AGR): SKIP.
      * ``is_decision_record`` True   → in scope; the caller then checks
        ``record_is_parseable(parsed)`` to distinguish a healthy AGR from a
        genuinely-malformed one (RECORD_PARSE_FAILED).

    Reads the file a single time so type-membership and field-parse share one IO.
    """
    content = path.read_text(encoding="utf-8", errors="replace")
    return is_decision_record(content), parse_decision_record(content)


_EDGE_SOURCE_STATUSES = frozenset({"RATIFIED", "SUPERSEDED"})


def derive_supersession(working_dir: Path) -> dict[str, list[str]]:
    """Map each superseded TOKEN to the sorted tokens of the YAML records that supersede it.

    Edges come ONLY from a parseable YAML record's ``supersedes:`` list, and only
    when that record's own STATUS is RATIFIED or SUPERSEDED (PROPOSED, DRAFT, VOID
    and anything else derive nothing). OCTAVE records (including legacy prose
    ``SUPERSEDES``) and rejected YAML records derive nothing. A pure corpus scan (PROD I5): no file is written, and the
    superseded record's own file is never consulted or touched.
    """
    root = decisions_root(working_dir)
    if not root.exists():
        return {}
    edges: dict[str, set[str]] = {}
    for path in sorted(root.rglob("*.md")):
        if path.name.endswith(".oct.md") or not path.is_file():
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if not is_yaml_front_matter(content):
            continue
        parsed = parse_decision_record(content)
        raw = parsed["fields"].get("SUPERSEDES")
        deriver = parsed["token"]
        if raw is None or deriver is None or not record_is_parseable(parsed):
            continue
        if parsed["status"] not in _EDGE_SOURCE_STATUSES:
            continue
        for target in parse_supersedes_list(raw):
            edges.setdefault(target, set()).add(deriver)
    return {target: sorted(derivers) for target, derivers in sorted(edges.items())}


def successors_of(parsed: DecisionRecord, derived: dict[str, list[str]]) -> list[str]:
    """Sorted distinct successors of a record: its SUPERSEDED_BY plus derived edges.

    More than one means a FORK (never silently resolved to one of them).
    """
    found = set(derived.get(parsed.get("token") or "", []))
    explicit = parsed.get("fields", {}).get("SUPERSEDED_BY")
    if explicit:
        found.add(explicit)
    return sorted(found)


def apply_derived_supersession(
    parsed: DecisionRecord, derived: dict[str, list[str]]
) -> DecisionRecord:
    """Overlay derived supersession on a parsed record (returns a copy; file untouched).

    OR rule: a record with a derived edge reads ``SUPERSEDED`` — except a ``VOID``
    record, which stays ``VOID`` (it outranks SUPERSEDED) while the edge still
    appears in its chain. When it has exactly one successor overall and no explicit
    ``SUPERSEDED_BY``, that successor is surfaced as ``fields["SUPERSEDED_BY"]``.
    On a fork ``fields`` is left exactly as the file has it.
    """
    token = parsed.get("token")
    derived_successors = derived.get(token or "")
    if not derived_successors:
        return parsed
    out: DecisionRecord = {**parsed, "fields": dict(parsed["fields"])}
    if out["status"] != "VOID":
        out["status"] = "SUPERSEDED"
    if "SUPERSEDED_BY" not in out["fields"] and len(derived_successors) == 1:
        out["fields"]["SUPERSEDED_BY"] = derived_successors[0]
    return out


def chain_entry(
    working_dir: Path,
    parsed: DecisionRecord,
    path: Path,
    successors: list[str] | None = None,
) -> dict[str, Any]:
    """Build one §3.4 chain entry from a parsed record + its path.

    On a fork (``successors`` has more than one TOKEN) ``superseded_by`` is
    ``None`` and the entry additionally carries ``fork: True`` and ``successors``.
    """
    entry: dict[str, Any] = {
        "token": parsed.get("token"),
        "status": parsed.get("status"),
        "authored_at": parsed.get("authored_at"),
        "superseded_by": parsed.get("fields", {}).get("SUPERSEDED_BY"),
        "path": rel_path(working_dir, path),
    }
    if successors is not None and len(successors) > 1:
        entry["superseded_by"] = None
        entry["fork"] = True
        entry["successors"] = successors
    return entry


def walk_supersession_chain(
    working_dir: Path, start_token: str, derived: dict[str, list[str]] | None = None
) -> dict[str, Any]:
    """Follow supersession edges from ``start_token`` to the terminal.

    Edges are a record's ``SUPERSEDED_BY`` OR a derived YAML ``supersedes:`` edge.
    Pure read. The caller guarantees ``start_token`` already resolves on disk.

    Returns a structured result (PROD I4) — one of:
      * ``{"outcome": "ok", "chain": [...], "terminal_token", "terminal_status"}``
      * ``{"outcome": "broken", "broken_at_token", "missing_successor_token",
         "chain": [...]}``
      * ``{"outcome": "cycle", "cycle_at_token", "chain": [...]}``
      * ``{"outcome": "unparseable", "token", "path", "detail", "chain"}`` — a YAML
        record on the walk (start or mid-chain) was rejected or incomplete; the walk
        stops rather than half-read it (``detail`` is ``{line, construct}`` or ``{}``).
      * ``{"outcome": "fork", "fork_at_token", "successors": [...], "chain": [...]}``
        — a record with two DIFFERENT successors; the walk stops there and
        reports both rather than picking one. The same successor named by both
        sources is not a fork.

    Cycle detection is fail-closed (visited-set) — never an unbounded walk
    (§3.4).
    """
    if derived is None:
        derived = derive_supersession(working_dir)
    chain: list[dict[str, Any]] = []
    visited: set[str] = set()
    current = start_token

    while True:
        if current in visited:
            # Revisited a TOKEN already in the walk — fail closed (§3.4).
            return {"outcome": "cycle", "cycle_at_token": current, "chain": chain}
        visited.add(current)

        path = discover_record(working_dir, current)
        if path is None:
            # Mid-chain successor missing. The start token is guaranteed to
            # exist by the caller, so a missing ``current`` here is a broken
            # link from the previous entry (§3.4 CHAIN_BROKEN, distinct from
            # TOKEN_NOT_FOUND).
            return {
                "outcome": "broken",
                "broken_at_token": chain[-1]["token"] if chain else start_token,
                "missing_successor_token": current,
                "chain": chain,
            }

        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            # Unreadable mid-walk (permissions, deleted after discovery): stop with the
            # same structured outcome as a rejected record rather than raising.
            return {
                "outcome": "unparseable",
                "token": current,
                "path": rel_path(working_dir, path),
                "detail": {},
                "chain": chain,
            }
        loaded = parse_decision_record(content)
        if is_yaml_front_matter(content) and not record_is_parseable(loaded):
            return {
                "outcome": "unparseable",
                "token": current,
                "path": rel_path(working_dir, path),
                "detail": parse_failure_detail(content) or {},
                "chain": chain,
            }
        parsed = apply_derived_supersession(loaded, derived)
        successors = successors_of(parsed, derived)
        entry = chain_entry(working_dir, parsed, path, successors)
        chain.append(entry)

        if len(successors) > 1:
            return {
                "outcome": "fork",
                "fork_at_token": current,
                "successors": successors,
                "chain": chain,
            }
        successor = entry["superseded_by"]
        if not successor:
            return {
                "outcome": "ok",
                "chain": chain,
                "terminal_token": entry["token"],
                "terminal_status": entry["status"],
            }
        current = successor
