===DECISION_RECORD===
META:
  TYPE::DECISION_RECORD
  VERSION::"1.1"
  TOKEN::HO-GOVERNANCE-AMEND-IN-PLACE-20260926
  STATUS::PROPOSED
  TIER::STRATEGIC
  COMPRESSION_TIER::CONSERVATIVE
  LOSS_PROFILE::"[preserve:operator_ruling∧in_place_rule∧thin_ruling_record∧no_stacking∧interim_PR_path∧scope∧precedent∧cross_repo_source,drop:discussion]"
  AUTHORED_AT::"2026-09-26T00:00:00Z"
  CEREMONY_REF::"fb3fc134-58b1-4dcf-9861-fe59aa899326"
  AUTHORING_SESSION::"holistic-orchestrator"
  OPERATOR_RULING::"Shaun Buswell, 2026-09-26, holistic-orchestrator session: (1) amend ADR-0013 in place + thin ruling record → yes; (2) adopt in-place amendment rule in hestai-context-mcp → yes; (3) open issue for propose_decision_amendment broker → yes"
  SCOPE::"hestai-context-mcp only"
  APPLIES_TO::"merged decision records under .hestai/decisions ∧ human ADRs under docs/adr"
  RELATED::"elevana-studio HO-DECISION-RECORD-SHAPE-AND-AMENDMENT-DISCIPLINE-20260909 Rule 2 → adopted here, extended to human ADRs; cross-repo, related not amended"
  THIN_RULING_RECORD::"each amendment ruling → submit_governance record carrying who∧when∧why∧what_changed + pointer to amended artefact; never restates amended content"
  INTERIM_PATH::"until ADR-RFC-ARCH-004 §3.5 propose_decision_amendment broker exists → in-place edit travels as normal human-reviewed PR"
  SCOPE_GUARD::"human merge sole semantic gate ∧ no auto-merge ∧ TOKEN uniqueness unchanged"
  FIRST_APPLICATION::"ADR-0013 R1 gains COORDINATION_DOCUMENT class → edited in place ⊕ own thin ruling record"
  DECISION::"Amend governance artefacts in place → replace clause ∧ bump VERSION ∧ one-line REVISION; git = correction log; thin ruling record per amendment; no stacking"
  BECAUSE::"SOURCE_FIDELITY → in-place, no versioned copies; AMENDS refines without retiring ∴ stacking forces reassembly ∧ leaves original misleading; ADR-RFC-ARCH-004 v1.1 in-place precedent"
===END===