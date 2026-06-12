"""list_decisions — list AGRs with optional filtering (ADR-RFC-ARCH-004 §3.3).

Pure read (PROD I5), structured return (PROD I4). Returns summary entries sorted
by ``authored_at`` DESCENDING with optional scope/status/tier filters. Errors use
the §3.1.1 envelope: FILTER_INVALID, WORKING_DIR_INVALID, RECORD_PARSE_FAILED
(a single unparseable record fails the WHOLE call — no silent drop).

Reuses the shared ``tools.governance.agr_read`` primitives (enumeration via
``iter_record_paths``, structured parsing) — no rebuilt logic.
"""

from __future__ import annotations

from typing import Any

from hestai_context_mcp.tools.governance import agr_read

_TOOL = "list_decisions"
_CONTRACT_REF = "ADR-RFC-ARCH-004 §3.3"

_VALID_STATUS = ("PROPOSED", "RATIFIED", "SUPERSEDED", "VOID")
_VALID_TIER = ("STRATEGIC", "TACTICAL", "OPERATIONAL")


def list_decisions(
    working_dir: str,
    scope: str | None = None,
    status: str | None = None,
    tier: str | None = None,
) -> dict[str, Any]:
    """List AGRs with optional filtering. Pure read.

    Args:
        working_dir: Project path.
        scope: Exact-match SCOPE filter, or ``None`` for no filter.
        status: One of the STATUS enum values, or ``None``.
        tier: One of the TIER enum values, or ``None``.

    Returns:
        On success: ``{"ok": True, "records": [...], "total": int}`` sorted by
        ``authored_at`` DESC. On failure: the §3.1.1 error envelope.
    """
    working_path = agr_read.validate_working_dir(working_dir)
    if working_path is None:
        return agr_read.error_envelope(
            code="WORKING_DIR_INVALID",
            category="io_failure",
            message=f"working_dir does not exist or is not a directory: {working_dir}",
            tool=_TOOL,
            context={"working_dir": working_dir},
            contract_ref=_CONTRACT_REF,
        )

    if status is not None and status not in _VALID_STATUS:
        return _filter_invalid("status", status)
    if tier is not None and tier not in _VALID_TIER:
        return _filter_invalid("tier", tier)

    records: list[dict[str, Any]] = []
    for path in agr_read.iter_record_paths(working_path):
        parsed = agr_read.load_parsed(path)
        if not agr_read.record_is_parseable(parsed):
            # §3.3: fail the whole call rather than silently dropping; consumers
            # MUST be able to detect that the list is incomplete.
            return agr_read.error_envelope(
                code="RECORD_PARSE_FAILED",
                category="schema_violation",
                message="A DECISION_RECORD under .hestai/decisions failed to parse.",
                tool=_TOOL,
                context={
                    "path": agr_read.rel_path(working_path, path),
                    "parse_error": "missing OCTAVE envelope or required §1.2 field(s)",
                },
                contract_ref=_CONTRACT_REF,
            )

        if status is not None and parsed["status"] != status:
            continue
        if tier is not None and parsed["tier"] != tier:
            continue
        if scope is not None and parsed["fields"].get("SCOPE") != scope:
            continue

        records.append(
            {
                "token": parsed["token"],
                "status": parsed["status"],
                "tier": parsed["tier"],
                "decision": parsed["decision"],
                "authored_at": parsed["authored_at"],
                "path": agr_read.rel_path(working_path, path),
            }
        )

    # §3.3: sorted by authored_at DESCENDING.
    records.sort(key=lambda r: r["authored_at"] or "", reverse=True)

    return {"ok": True, "records": records, "total": len(records)}


def _filter_invalid(field: str, value: str) -> dict[str, Any]:
    """Build the §3.3 FILTER_INVALID envelope for a bad enum filter."""
    return agr_read.error_envelope(
        code="FILTER_INVALID",
        category="input_validation",
        message=f"Filter {field}={value!r} is not a member of the admissible enum.",
        tool=_TOOL,
        context={"field": field, "value": value},
        contract_ref=_CONTRACT_REF,
    )
