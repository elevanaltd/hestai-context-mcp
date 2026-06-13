"""trace_supersedure — supersession chain for a TOKEN (ADR-RFC-ARCH-004 §3.4).

Pure read (PROD I5), structured return (PROD I4). Follows SUPERSEDED_BY pointers
from the requested token to the terminal record. Errors use the §3.1.1 envelope:
TOKEN_NOT_FOUND, CHAIN_BROKEN, CHAIN_CYCLE_DETECTED (fails closed — never an
infinite loop), WORKING_DIR_INVALID.

Reuses the shared ``tools.governance.agr_read`` chain walker (which reuses the
``lineage`` SUPERSEDED_BY semantics via the parser's ``fields`` map) — no rebuilt
traversal logic.
"""

from __future__ import annotations

from typing import Any

from hestai_context_mcp.tools.governance import agr_read

_TOOL = "trace_supersedure"
_CONTRACT_REF = "ADR-RFC-ARCH-004 §3.4"


def trace_supersedure(working_dir: str, token: str) -> dict[str, Any]:
    """Return the supersession chain for ``token``. Pure read.

    Args:
        working_dir: Project path.
        token: The starting DECISION_RECORD TOKEN.

    Returns:
        On success: ``{"ok": True, "chain": [...], "terminal_token",
        "terminal_status"}``. On failure: the §3.1.1 error envelope.
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

    # A missing START token is TOKEN_NOT_FOUND (distinct from a missing
    # mid-chain successor, which the walker reports as CHAIN_BROKEN).
    if agr_read.discover_record(working_path, token) is None:
        return agr_read.error_envelope(
            code="TOKEN_NOT_FOUND",
            category="input_validation",
            message=f"No DECISION_RECORD found for starting TOKEN: {token}",
            tool=_TOOL,
            context={"token": token},
            contract_ref=_CONTRACT_REF,
        )

    walk = agr_read.walk_supersession_chain(working_path, token)
    outcome = walk["outcome"]

    if outcome == "cycle":
        return agr_read.error_envelope(
            code="CHAIN_CYCLE_DETECTED",
            category="schema_violation",
            message="SUPERSEDED_BY traversal revisited a TOKEN already in the chain.",
            tool=_TOOL,
            context={"cycle_at_token": walk["cycle_at_token"]},
            contract_ref=_CONTRACT_REF,
        )

    if outcome == "broken":
        return agr_read.error_envelope(
            code="CHAIN_BROKEN",
            category="schema_violation",
            message="A record's SUPERSEDED_BY points at a TOKEN that does not exist.",
            tool=_TOOL,
            context={
                "broken_at_token": walk["broken_at_token"],
                "missing_successor_token": walk["missing_successor_token"],
            },
            contract_ref=_CONTRACT_REF,
        )

    return {
        "ok": True,
        "chain": walk["chain"],
        "terminal_token": walk["terminal_token"],
        "terminal_status": walk["terminal_status"],
    }
