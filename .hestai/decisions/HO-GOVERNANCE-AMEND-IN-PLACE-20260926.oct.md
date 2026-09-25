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
  CEREMONY_REF::fb3fc134-58b1-4dcf-9861-fe59aa899326
  AUTHORING_SESSION::holistic-orchestrator
  OPERATOR_RULING::"Shaun Buswell, 2026-09-26, holistic-orchestrator session: (1) amend ADR-0013 in place + thin ruling record → yes; (2) adopt in-place amendment rule → yes, across the ecosystem; (3) open issue for propose_decision_amendment broker → yes (#189); (4) verbatim: 'No rule should be immutable. Everything is worth of change, especially if it goes throug the right review. Change isn't the issue. Proper governance is.'"
  SCOPE::"HestAI ecosystem → every repo carrying governance artefacts; standard owned by hestai-context-mcp (AGR standard, RFC #40)"
  APPLIES_TO::"merged decision records ∧ human ADRs ∧ ratified standards ∧ clauses self-declared immutable∨supersession-only[e.g. ADR-RFC-ARCH-002 §0.2]"
  RELATED::"provenance only: elevana-studio HO-DECISION-RECORD-SHAPE-AND-AMENDMENT-DISCIPLINE-20260909 Rule 2; THIS record is normative ecosystem-wide ∴ drift in the source record does not change this rule"
  THIN_RULING_RECORD::"each amendment ruling → submit_governance record carrying who∧when∧why∧what_changed + pointer to amended artefact; never restates amended content"
  INTERIM_PATH::"until ADR-RFC-ARCH-004 §3.5 propose_decision_amendment broker exists → in-place edit travels as normal human-reviewed PR"
  SCOPE_GUARD::"human merge sole semantic gate ∧ no auto-merge ∧ TOKEN uniqueness unchanged"
  FIRST_APPLICATION::"ADR-0013 R1 gains COORDINATION_DOCUMENT class → applied in PR #190[ADR-0013 v1.1 edited in place ⊕ thin ruling record HO-ADR-0013-COORDINATION-DOCUMENT-CLASS-20260926]"
  DECISION::"Ecosystem-wide: amend governance artefacts in place → replace clause ∧ one-line REVISION entry; git = correction log; thin ruling record per amendment; no stacking; nothing immutable"
  BECAUSE::"SOURCE_FIDELITY → in-place, no versioned copies; stacking forces reassembly ∧ misleads; change is not the risk, ungoverned change is ∴ reviewed PR ∧ human merge = the control; ADR-RFC-ARCH-004 v1.1 precedent"
  AMENDMENT_GATE::"no artefact immutable → any clause amendable via proper governance: reviewed PR ∧ human merge ∧ human-authority gates retained where a standard requires them; the control is governance, not immutability"
  REVISION_CONVENTION::"AGR → META REVISION field, one line per amendment[date: what changed]; META VERSION stays the ADR-RFC-ARCH-004 schema version → never bumped per edit; human ADR → header **Version** bump ∧ **Revision** line[date: what changed]"
  ADOPTION::"Standard is ecosystem-wide; binding in a consumer repo once that repo adopts it[pointer in its instructions∨decision index] per ADR-RFC-ARCH-004 §0.2 #4 opt-in adoption; rollout to other repos deferred by operator 2026-09-26"
===END===
