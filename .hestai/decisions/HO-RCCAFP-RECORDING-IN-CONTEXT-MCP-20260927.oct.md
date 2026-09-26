===DECISION_RECORD===
META:
  TYPE::DECISION_RECORD
  VERSION::"1.0"
  TOKEN::HO-RCCAFP-RECORDING-IN-CONTEXT-MCP-20260927
  STATUS::RATIFIED
  TIER::STRATEGIC
  COMPRESSION_TIER::CONSERVATIVE
  LOSS_PROFILE::"[preserve:decision∧causal_basis∧scope_exclusions∧re_review_trigger∧named_entities∧IDs∧thresholds,drop:stopwords∧discussion_prose]"
  AUTHORED_AT::"2026-09-27T00:00:00Z"
  RATIFIED_BY::"human:operator<shaunbuswell>"
  RATIFIED_AT::"2026-09-26T00:00:00Z"
  ISSUE_REF::"repo:hestai-context-mcp#193"
  SCOPE::"RCCAFP placement only; Integrity Engine/debt-lock half of debate-hall-mcp#192 remains open and unowned; RCCAFP schema locked at RCCAFP-ERROR-RECOVERY-SPEC.md §2.2; no enforcement or dispatch build"
  DECISION::"Host submit_rccafp_record as recording-only capability inside hestai-context-mcp → schema RCCAFP-ERROR-RECOVERY-SPEC.md §2.2 locked → append {working_dir}/.hestai/state/error-metrics.jsonl with trusted-root path validation → v1 record+return, no dispatch/debt locks → no athena-amend-mcp server → retain HestAI-MCP copy until parity, then hard-deprecate"
  BECAUSE::"§3B→Governance Engine placement+no dispatch; move absent→HestAI-MCP-only tool unreachable; evidence: 1 misapplied record, 0 transcript calls→new server unjustified; Workbench trigger unbuilt→enforcement deferred ∴ option(b) chosen 2026-09-26, filed 2026-09-27"
  RE_REVIEW_TRIGGER::"Re-open when Workbench Reanchoring Upload+escalation dispatch ship ∨ debate-hall-mcp#192 debt-lock decision requires RCCAFP co-location"
  AFFECTS::[
    "submit_rccafp_record",
    "hestai-context-mcp tool surface",
    "HestAI-MCP#445",
    "debate-hall-mcp#192",
    "hestai-context-mcp#18"
  ]
===END===