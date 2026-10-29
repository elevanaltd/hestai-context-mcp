"""lookup_decision — resolve a single AGR by TOKEN (ADR-RFC-ARCH-004 §3.2).

Pure read (PROD I5), structured return (PROD I4). Returns the full record shape
plus a ``resolution_chain`` populated when STATUS == SUPERSEDED. Errors use the
§3.1.1 envelope: TOKEN_NOT_FOUND, TOKEN_MALFORMED, RECORD_PARSE_FAILED,
WORKING_DIR_INVALID.

Reuses the shared ``tools.governance.agr_read`` primitives (working_dir
validation, §1.3 TOKEN regex, on-disk discovery, structured parsing, chain
walking) — no rebuilt parsing or enumeration logic.
"""

from __future__ import annotations

from typing import Any

from hestai_context_mcp.core.agent_readable_governance_parser import (
    collect_topic_blocks,
    parse_decision_record,
)
from hestai_context_mcp.tools.governance import agr_read

_TOOL = "lookup_decision"
_CONTRACT_REF = "ADR-RFC-ARCH-004 §3.2"

# §3.2 (issue #87): map the walk_supersession_chain outcome to the additive
# ``resolution_chain_status`` completeness signal. ``ok`` (reached a terminal)
# is "complete"; a missing successor TOKEN is "broken"; a detected SUPERSEDED_BY
# cycle is "cyclic". These mirror trace_supersedure's CHAIN_BROKEN /
# CHAIN_CYCLE_DETECTED conditions. A record with no supersession chain (the
# empty-chain / non-SUPERSEDED case) is "complete" — an empty chain is, by
# definition, not truncated.
_CHAIN_STATUS_DEFAULT = "complete"
_WALK_OUTCOME_TO_STATUS = {
    "ok": "complete",
    "broken": "broken",
    "cycle": "cyclic",
}


def lookup_decision(
    working_dir: str,
    token: str,
    audience: str = "agent",
) -> dict[str, Any]:
    """Resolve a single AGR by TOKEN. Pure read.

    Args:
        working_dir: Absolute or repo-rooted project path.
        token: The DECISION_RECORD TOKEN to resolve.
        audience: ``"agent"`` (default) or ``"human"``. The implementation
            always returns the agent-shape record; ``audience`` is accepted for
            contract conformance (§3.2 — consumers must tolerate agent shape).

    Returns:
        On success: ``{"ok": True, "record": {...}, "resolution_chain": [...],
        "resolution_chain_status": "complete"|"broken"|"cyclic"}``. The
        ``resolution_chain_status`` field (additive per §3.1.1, issue #87) is a
        completeness signal derived from the same ``walk_supersession_chain``
        outcome, so a caller can tell a chain that reached its terminal from one
        truncated by a broken link or a cycle.
        ``record["current_state"]`` (additive, ADR-RFC-ARCH-004 v1.3) is
        ``[{"id": str, "rule": str}, ...]`` — the in-force rules from a topic
        record's ``CURRENT`` block, in order — when the record has a ``TOPIC``
        field (an empty list if the block is absent), and ``None`` for a record
        without a TOPIC. All other record keys are unchanged.
        On failure: the §3.1.1 error envelope.
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

    if not agr_read.is_valid_token(token):
        return agr_read.error_envelope(
            code="TOKEN_MALFORMED",
            category="input_validation",
            message=f"TOKEN does not match the ADR-RFC-ARCH-004 §1.3 format: {token!r}",
            tool=_TOOL,
            context={"token": token},
            contract_ref=_CONTRACT_REF,
        )

    path = agr_read.discover_record(working_path, token)
    if path is None:
        return agr_read.error_envelope(
            code="TOKEN_NOT_FOUND",
            category="input_validation",
            message=f"No DECISION_RECORD found for TOKEN: {token}",
            tool=_TOOL,
            context={"token": token},
            contract_ref=_CONTRACT_REF,
        )

    # Read the file ONCE and derive both the parsed fields and the topic blocks
    # from the same text (consistent snapshot). A read failure maps to the
    # §3.1.1 envelope rather than escaping as an exception.
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return agr_read.error_envelope(
            code="RECORD_PARSE_FAILED",
            category="io_failure",
            message="DECISION_RECORD file could not be read.",
            tool=_TOOL,
            context={
                "token": token,
                "path": agr_read.rel_path(working_path, path),
                "parse_error": f"record unreadable: {type(exc).__name__}",
            },
            contract_ref=_CONTRACT_REF,
        )
    parsed = parse_decision_record(text)
    if not agr_read.record_is_parseable(parsed):
        detail = agr_read.parse_failure_detail(text)
        return agr_read.error_envelope(
            code="RECORD_PARSE_FAILED",
            category="schema_violation",
            message="DECISION_RECORD envelope or required fields failed to parse.",
            tool=_TOOL,
            context={
                "token": token,
                "path": agr_read.rel_path(working_path, path),
                "parse_error": agr_read.parse_error_text(detail),
                **(detail or {}),
            },
            contract_ref=_CONTRACT_REF,
        )

    record = {
        "token": parsed["token"],
        "type": parsed["type"],
        "version": parsed["version"],
        "status": parsed["status"],
        "tier": parsed["tier"],
        "decision": parsed["decision"],
        "because": parsed["because"],
        "authored_at": parsed["authored_at"],
        "path": agr_read.rel_path(working_path, path),
        "fields": parsed["fields"],
        "current_state": _current_state(text, parsed["fields"]),
    }

    resolution_chain: list[dict[str, Any]] = []
    resolution_chain_status = _CHAIN_STATUS_DEFAULT
    if parsed["status"] == "SUPERSEDED":
        walk = agr_read.walk_supersession_chain(working_path, token)
        # §3.2: the resolution chain mirrors the trace_supersedure entry shape.
        # A broken/cyclic chain still surfaces the entries gathered so far so the
        # caller sees the partial resolution rather than nothing.
        resolution_chain = walk["chain"]
        # §3.2 (issue #87): derive the completeness signal from the SAME walk
        # outcome — no second read, so PROD I5 purity is preserved. ``ok`` falls
        # back to the default "complete".
        resolution_chain_status = _WALK_OUTCOME_TO_STATUS.get(
            walk["outcome"], _CHAIN_STATUS_DEFAULT
        )

    return {
        "ok": True,
        "record": record,
        "resolution_chain": resolution_chain,
        "resolution_chain_status": resolution_chain_status,
    }


def _current_state(text: str, fields: dict[str, str]) -> list[dict[str, str]] | None:
    """Return the CURRENT block rules for a topic record, else ``None`` (pure)."""
    if "TOPIC" not in fields:
        return None
    return [{"id": e["id"], "rule": e["rule"]} for e in collect_topic_blocks(text)["current"]]
