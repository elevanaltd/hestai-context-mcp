"""Shared AGR fixture builders for the RFC #40 read-side RED suite.

Helpers to materialise crafted DECISION_RECORD ``.oct.md`` files under a temp
``.hestai/decisions/`` tree so the read tools (lookup_decision / list_decisions
/ trace_supersedure) can be exercised against real on-disk records.

Pure builders: they only write fixtures the tests asked for. The tools under
test are the ones that must stay pure (PROD I5); these helpers set up state.
"""

from __future__ import annotations

from pathlib import Path

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
    """Write a file with a valid-format TOKEN but a broken OCTAVE envelope.

    Used to exercise RECORD_PARSE_FAILED: the file is discoverable but its
    required fields / envelope do not parse.
    """
    root = decisions_dir(working_dir)
    path = root / f"{MALFORMED_TOKEN}.oct.md"
    # No sentinel, no required fields — envelope is broken.
    path.write_text(
        f"this is not a valid OCTAVE record\nTOKEN::{MALFORMED_TOKEN}\n",
        encoding="utf-8",
    )
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
