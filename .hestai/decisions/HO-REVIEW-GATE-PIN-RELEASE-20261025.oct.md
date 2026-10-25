===DECISION_RECORD===
META:
  TYPE::DECISION_RECORD
  VERSION::"1.1"
  TOKEN::HO-REVIEW-GATE-PIN-RELEASE-20261025
  STATUS::RATIFIED
  TIER::STRATEGIC
  COMPRESSION_TIER::CONSERVATIVE
  LOSS_PROFILE::"[preserve:decision∧causal_basis∧operator_quote∧release_procedure∧format_coupling∧re_review_trigger∧IDs,drop:discussion_prose]"
  AUTHORED_AT::"2026-10-25T00:00:00Z"
  RATIFIED_BY::"human:operator<shaunbuswell>"
  RATIFIED_AT::"2026-10-25T00:00:00Z"
  ISSUE_REF::"repo:hestai-context-mcp#170"
  CEREMONY_REF::"625fb59c-a1a2-466b-bb95-608cb4285017"
  AUTHORING_SESSION::"holistic-orchestrator:hc-control-room-20260929"
  OPERATOR_RULING::"Shaun Buswell: (1) 2026-10-17, hestai-workbench control room session, relayed to HC: 'yes to pin'; (2) 2026-10-25, HC control room session, first-party: 'Go with recs on pinning'"
  SCOPE::"Org Review Gate release mechanics only: review-gate.yml tooling checkout ref ∧ org ruleset 12626210 workflow sha; gate behaviour unchanged at pin time; hestai-context-mcp classic branch protection (#169) unchanged; validate_review.py ∧ review_formats.py content unchanged"
  DECISION::"review-gate.yml tooling ref→full commit SHA[tag review-gate-v1 in comment] ∧ pytest asserts 40-hex SHA∧no if: → operator pins ruleset 12626210 sha→pin-PR merge commit → release=tag+workflow PR+ruleset re-point ∧ review_formats format change ships with re-pin"
  BECAUSE::"8 gate-file merges since 2026-09-01 went live in 3 consuming repos at merge, unstaged, no rollback; tags mutable∴SHA; review_formats shared by submit_review[main]∧gate[pinned]∴paired release; #170 item 1 asked"
  RE_REVIEW_TRIGGER::"Re-open when per-release ruleset edits become friction (switch to a protected release branch) ∨ a format change ships without a re-pin ∨ review-gate tier 2 provenance spine lands"
  AFFECTS::[
    ".github/workflows/review-gate.yml",
    "org ruleset 12626210",
    "hestai-context-mcp#170",
    "hestai-workbench",
    "elevana-studio",
    "HestAI-MCP"
  ]
===END===