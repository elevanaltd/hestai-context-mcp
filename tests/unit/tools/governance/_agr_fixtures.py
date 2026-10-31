"""Shared AGR fixture builders for the RFC #40 read-side RED suite.

Helpers to materialise crafted DECISION_RECORD ``.oct.md`` files under a temp
``.hestai/decisions/`` tree so the read tools (lookup_decision / list_decisions
/ trace_supersedure) can be exercised against real on-disk records.

Pure builders: they only write fixtures the tests asked for. The tools under
test are the ones that must stay pure (PROD I5); these helpers set up state.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hestai_context_mcp.core.agent_readable_governance_parser import encode_yaml_scalar

# Non-secret governance identifiers used across the read-side suite.
TOKEN_RATIFIED = "HO-CONTEXT-MCP-DOGFOOD-RATIFIED-20260601"
TOKEN_OLD = "HO-CONTEXT-MCP-CHAIN-OLD-20260101"
TOKEN_MID = "HO-CONTEXT-MCP-CHAIN-MID-20260201"
TOKEN_NEW = "HO-CONTEXT-MCP-CHAIN-NEW-20260301"
TOKEN_CYCLE_A = "HO-CONTEXT-MCP-CYCLE-A-20260401"
TOKEN_CYCLE_B = "HO-CONTEXT-MCP-CYCLE-B-20260402"
TOKEN_BROKEN = "HO-CONTEXT-MCP-BROKEN-HEAD-20260501"
TOKEN_MISSING = "HO-CONTEXT-MCP-NEVER-WRITTEN-20260101"
MALFORMED_TOKEN = "HO-CONTEXT-MCP-MALFORMED-20260601"


def decisions_dir(working_dir: Path) -> Path:
    """Return (and create) the canonical ``.hestai/decisions`` root."""
    root = working_dir / ".hestai" / "decisions"
    root.mkdir(parents=True, exist_ok=True)
    return root


def write_record(
    working_dir: Path,
    *,
    token: str,
    status: str = "RATIFIED",
    tier: str = "STRATEGIC",
    authored_at: str = "2026-06-01T00:00:00Z",
    decision: str = "A binding decision sentence.",
    because: str = "A one-sentence rationale.",
    scope: str | None = None,
    superseded_by: str | None = None,
    group: str | None = None,
    extra_lines: list[str] | None = None,
) -> Path:
    """Write a single DECISION_RECORD AGR and return its path.

    ``group`` writes under ``.hestai/decisions/<group>/`` to exercise §1.1
    sub-grouping (both layouts must resolve identically).
    """
    root = decisions_dir(working_dir)
    if group:
        root = root / group
        root.mkdir(parents=True, exist_ok=True)

    lines = [
        "===DECISION_RECORD===",
        "META:",
        "  TYPE::DECISION_RECORD",
        '  VERSION::"1.0"',
        f"  TOKEN::{token}",
        f"  STATUS::{status}",
        f"  TIER::{tier}",
        f'  AUTHORED_AT::"{authored_at}"',
        f'  DECISION::"{decision}"',
        f'  BECAUSE::"{because}"',
    ]
    if scope is not None:
        lines.append(f'  SCOPE::"{scope}"')
    if superseded_by is not None:
        lines.append(f"  SUPERSEDED_BY::{superseded_by}")
    if extra_lines:
        lines.extend(extra_lines)
    lines.append("===END===")

    path = root / f"{token}.oct.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def write_supersession_chain(working_dir: Path) -> None:
    """Seed a three-record chain: OLD -> MID -> NEW (NEW terminal/RATIFIED)."""
    write_record(
        working_dir,
        token=TOKEN_OLD,
        status="SUPERSEDED",
        authored_at="2026-01-01T00:00:00Z",
        superseded_by=TOKEN_MID,
    )
    write_record(
        working_dir,
        token=TOKEN_MID,
        status="SUPERSEDED",
        authored_at="2026-02-01T00:00:00Z",
        superseded_by=TOKEN_NEW,
    )
    write_record(
        working_dir,
        token=TOKEN_NEW,
        status="RATIFIED",
        authored_at="2026-03-01T00:00:00Z",
    )


def write_cyclic_pair(working_dir: Path) -> None:
    """Seed a 2-record SUPERSEDED_BY cycle: A -> B -> A (fail-closed test)."""
    write_record(
        working_dir,
        token=TOKEN_CYCLE_A,
        status="SUPERSEDED",
        authored_at="2026-04-01T00:00:00Z",
        superseded_by=TOKEN_CYCLE_B,
    )
    write_record(
        working_dir,
        token=TOKEN_CYCLE_B,
        status="SUPERSEDED",
        authored_at="2026-04-02T00:00:00Z",
        superseded_by=TOKEN_CYCLE_A,
    )


def write_broken_chain(working_dir: Path) -> None:
    """Seed a record whose SUPERSEDED_BY points at a non-existent successor."""
    write_record(
        working_dir,
        token=TOKEN_BROKEN,
        status="SUPERSEDED",
        authored_at="2026-05-01T00:00:00Z",
        superseded_by=TOKEN_MISSING,
    )


def write_malformed_record(working_dir: Path) -> Path:
    """Write a genuinely-malformed DECISION_RECORD (F1 distinction).

    The file DECLARES itself a DECISION_RECORD (canonical sentinel +
    ``TYPE::DECISION_RECORD`` + a valid-format TOKEN, so it is in scope and
    discoverable) but is MISSING required §1.2 fields (no STATUS / TIER /
    DECISION / BECAUSE / AUTHORED_AT). It must therefore trigger
    RECORD_PARSE_FAILED — NOT be silently skipped. This is the "is-an-AGR-but-
    broken" half of the two-way scoping split.
    """
    root = decisions_dir(working_dir)
    path = root / f"{MALFORMED_TOKEN}.oct.md"
    path.write_text(
        "===DECISION_RECORD===\n"
        "META:\n"
        "  TYPE::DECISION_RECORD\n"
        '  VERSION::"1.0"\n'
        f"  TOKEN::{MALFORMED_TOKEN}\n"
        # Required STATUS/TIER/DECISION/BECAUSE/AUTHORED_AT deliberately absent.
        "===END===\n",
        encoding="utf-8",
    )
    return path


def write_non_agr_record(
    working_dir: Path,
    *,
    filename: str,
    sentinel: str = "BUILD_PLAN",
    type_field: str | None = "BUILD_PLAN",
    type_key: str = "TYPE",
    group: str | None = None,
) -> Path:
    """Write a correctly-placed NON-AGR ``.oct.md`` (F1 co-residency case).

    Models the governance artefacts that legitimately co-reside under
    ``.hestai/decisions/`` per ADR-RFC-ARCH-001 (BUILD_PLAN, SECURITY_DESIGN_
    REVIEW, arbitration records). These declare a NON-DECISION_RECORD sentinel
    and/or type (or no type at all) and carry no TOKEN. They are OUT OF SCOPE for
    the AGR read tools and must be skipped silently.

    Args:
        filename: The on-disk basename (e.g. ``BUILD-PLAN.oct.md``).
        sentinel: The opening ``===<sentinel>===`` envelope name.
        type_field: Value for the META type line, or ``None`` to omit it.
        type_key: META key for the type line — defaults to ``TYPE``; pass
            ``DOCUMENT_TYPE`` to model the real BUILD_PLAN convention.
        group: Optional ``<group>/`` subdirectory.
    """
    root = decisions_dir(working_dir)
    if group:
        root = root / group
        root.mkdir(parents=True, exist_ok=True)

    lines = [f"==={sentinel}===", "META:"]
    if type_field is not None:
        lines.append(f"  {type_key}::{type_field}")
    lines.append('  NOTE::"a correctly-placed non-AGR governance artefact"')
    lines.append("===END===")

    path = root / filename
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def snapshot_tree(working_dir: Path) -> dict[str, tuple[float, int]]:
    """Capture {relpath: (mtime_ns_as_float, size)} for every file under root.

    Used by purity tests to prove a tool performed zero writes/mutations
    (PROD I5). Compares before/after a tool call.
    """
    snap: dict[str, tuple[float, int]] = {}
    for p in sorted(working_dir.rglob("*")):
        if p.is_file():
            st = p.stat()
            snap[str(p.relative_to(working_dir))] = (st.st_mtime_ns, st.st_size)
    return snap


def yaml_quote(value: str) -> str:
    """Quote ``value`` with the parser's canonical encoder (valid for control characters too)."""
    return encode_yaml_scalar(value)


def yaml_record_text(
    *,
    token: str,
    status: str = "RATIFIED",
    tier: str = "STRATEGIC",
    authored_at: str = "2026-06-01T00:00:00Z",
    decision: str = "A binding decision sentence.",
    because: str = "A one-sentence rationale.",
    scope: str | None = None,
    topic: str | None = None,
    superseded_by: str | None = None,
    supersedes: str | None = None,
    extra_lines: list[str] | None = None,
    body: str = "# Notes\n\nFree-form markdown body.\n",
    decision_literal: str | None = None,
    eol: str = "\n",
) -> str:
    """Return the text of a quoted-YAML front-matter DECISION_RECORD (PR-4 slice A)."""
    lines = [
        "---",
        f"type: {yaml_quote('DECISION_RECORD')}",
        f"version: {yaml_quote('1.0')}",
        f"token: {yaml_quote(token)}",
        f"status: {yaml_quote(status)}",
        f"tier: {yaml_quote(tier)}",
        f"authored_at: {yaml_quote(authored_at)}",
        f"decision: {decision_literal if decision_literal is not None else yaml_quote(decision)}",
        f"because: {yaml_quote(because)}",
    ]
    if scope is not None:
        lines.append(f"scope: {yaml_quote(scope)}")
    if topic is not None:
        lines.append(f"topic: {yaml_quote(topic)}")
    if superseded_by is not None:
        lines.append(f"superseded_by: {yaml_quote(superseded_by)}")
    if supersedes is not None:
        lines.append(f"supersedes: {yaml_quote(supersedes)}")
    if extra_lines:
        lines.extend(extra_lines)
    lines.append("---")
    return eol.join(lines) + eol + body


def write_yaml_record(
    working_dir: Path,
    *,
    token: str,
    group: str | None = None,
    filename: str | None = None,
    **kwargs: Any,
) -> Path:
    """Write a YAML front-matter DECISION_RECORD as ``<token>.md`` and return its path."""
    root = decisions_dir(working_dir)
    if group:
        root = root / group
        root.mkdir(parents=True, exist_ok=True)
    path = root / (filename or f"{token}.md")
    # newline="" so an explicit ``eol="\r\n"`` reaches the disk unchanged.
    path.write_text(yaml_record_text(token=token, **kwargs), encoding="utf-8", newline="")
    return path


def yaml_topic_lines(
    current: list[tuple[str, str]] | None = None,
    rulings: list[dict[str, str]] | None = None,
) -> list[str]:
    """Return fenced ``current:`` / ``rulings:`` block lines for ``yaml_record_text(extra_lines=…)``.

    ``rulings`` entries are ``{"id": "R2", "rule": …, "verbatim": …, "ruled": …,
    "replaces": …}`` (only the keys present are written, in that order).
    """
    lines: list[str] = []
    if current is not None:
        lines.append("current:")
        lines.extend(f"  {rid}: {yaml_quote(rule)}" for rid, rule in current)
    if rulings is not None:
        lines.append("rulings:")
        for entry in rulings:
            lines.append(f"  {entry['id']}:")
            for key in ("rule", "verbatim", "ruled", "replaces"):
                if key in entry:
                    lines.append(f"    {key}: {yaml_quote(entry[key])}")
    return lines
