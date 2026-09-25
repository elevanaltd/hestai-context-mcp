===DECISION_RECORD===
META:
  TYPE::DECISION_RECORD
  VERSION::"1.1"
  TOKEN::HO-ADR-0013-COORDINATION-DOCUMENT-CLASS-20260926
  STATUS::PROPOSED
  TIER::STRATEGIC
  COMPRESSION_TIER::CONSERVATIVE
  LOSS_PROFILE::"[preserve:operator_ruling∧never_shared_data_class∧screening_pass∧allowlist∧per_writer∧amended_artefact∧scope,drop:discussion∧measurement_detail]"
  AUTHORED_AT::"2026-09-26T00:00:00Z"
  AMENDS::[ADR_0013]
  CEREMONY_REF::"fb3fc134-58b1-4dcf-9861-fe59aa899326"
  AUTHORING_SESSION::"holistic-orchestrator"
  OPERATOR_RULING::"Shaun Buswell, 2026-09-25 → amend ADR-0013 with a coordination-document class; 2026-09-26 → option (b): client∧personal∧financial data never shared; 'put a single cheap agent pass on anything before it hits any published space'"
  AMENDED_ARTEFACT::"docs/adr/adr-0013-portable-session-state-via-storage-adapters.md v1.0→v1.1, edited in place per HO-GOVERNANCE-AMEND-IN-PLACE-20260926"
  WHAT_CHANGED::"R1 gains COORDINATION_DOCUMENT row ∧ eligibility rules; Decision paragraph ∧ vocabulary ∧ R6 ∧ R12 aligned"
  SCOPE::"hestai-context-mcp ADR-0013 only; no build authorised; carrier choice remains a later build decision"
  SCOPE_GUARD::"Class S raw sync stays rejected ∧ unlisted paths stay LOCAL_MUTABLE ∧ human merge sole semantic gate"
  DECISION::"Coordination documents may cross carriers only if allowlisted ∧ text-only ∧ per-writer append-only ∧ free of client, personal, financial data ∧ passed by cheap agent screening pass"
  BECAUSE::"Coordination docs unclassified → never synced; 2026-09-25 scan found financial figures∧external emails in queue, briefs, reports → allowlist insufficient ∴ never-share data class ⊕ fail-closed screen"
===END===