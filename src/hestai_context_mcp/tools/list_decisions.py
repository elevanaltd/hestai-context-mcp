"""list_decisions — list AGRs with optional filtering (ADR-RFC-ARCH-004 §3.3).

Pure read (PROD I5), structured return (PROD I4). Returns summary entries sorted
by ``authored_at`` DESCENDING with optional scope/status/tier filters. Errors use
the §3.1.1 envelope: FILTER_INVALID, WORKING_DIR_INVALID.

§3.3 incompleteness handling: a file that IS a DECISION_RECORD but fails to
parse its required §1.2 fields is NOT fatal. The parseable records are returned
and each unparseable one is reported in an explicit ``skipped`` array (with its
path and parse error). This satisfies the §3.3 invariant — consumers MUST be
able to detect that the list is incomplete — without one legacy/malformed record
fail-closing the entire index. Silent drop remains forbidden: a skip is always
surfaced. (The contract names whole-call failure as a *recommended* option; the
hard requirement is detectability, which the ``skipped`` array provides.)

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
        On success: ``{"ok": True, "records": [...], "total": int,
        "skipped": [{"path": str, "parse_error": str}, ...]}`` with ``records``
        sorted by ``authored_at`` DESC. ``skipped`` is always present (empty when
        every in-scope record parsed) and names every DECISION_RECORD that failed
        to parse, so a consumer can detect an incomplete list (§3.3). On input
        failure (bad filter / working_dir): the §3.1.1 error envelope.
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
    skipped: list[dict[str, str]] = []
    for path in agr_read.iter_record_paths(working_path):
        is_agr, parsed = agr_read.classify_file(path)

        # F1 SCOPING: ``.hestai/decisions/`` legitimately co-hosts non-AGR
        # governance artefacts (BUILD_PLAN, SECURITY_DESIGN_REVIEW, arbitration
        # records) per ADR-RFC-ARCH-001. A file that does NOT declare itself a
        # DECISION_RECORD is OUT OF SCOPE — skip silently, never error.
        if not is_agr:
            continue

        # §3.3 INCOMPLETENESS HANDLING: a file that IS a DECISION_RECORD but fails
        # to parse its required §1.2 fields must not be SILENTLY dropped, and must
        # not blind the whole index either. Record it in ``skipped`` — that
        # surfaces the incompleteness (the §3.3 hard requirement) while the rest
        # of the index remains usable. A single legacy/non-conforming record can
        # no longer fail-close the entire call.
        if not agr_read.record_is_parseable(parsed):
            skipped.append(
                {
                    "path": agr_read.rel_path(working_path, path),
                    "parse_error": "missing OCTAVE envelope or required §1.2 field(s)",
                }
            )
            continue

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
    # Stable, deterministic skip order for reproducible consumer diffs.
    skipped.sort(key=lambda s: s["path"])

    return {"ok": True, "records": records, "total": len(records), "skipped": skipped}


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
