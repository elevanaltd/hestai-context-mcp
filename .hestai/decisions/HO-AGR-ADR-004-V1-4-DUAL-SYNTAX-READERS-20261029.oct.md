===DECISION_RECORD===
META:
  TYPE::DECISION_RECORD
  VERSION::"1.1"
  TOKEN::HO-AGR-ADR-004-V1-4-DUAL-SYNTAX-READERS-20261029
  STATUS::RATIFIED
  TIER::STRATEGIC
  COMPRESSION_TIER::CONSERVATIVE
  LOSS_PROFILE::"[preserve:decision∧authority∧scope∧amended_artefact∧IDs∧advisory_rulings,drop:discussion_prose]"
  AUTHORED_AT::"2026-10-29T00:00:00Z"
  ISSUE_REF::"repo:hestai-context-mcp#218"
  CEREMONY_REF::dc383c2c-5edd-4538-931e-98172d48b036
  AUTHORING_SESSION::"holistic-orchestrator:ho-records-1-a9, filed for the HC control room (ceremony 625fb59c-a1a2-466b-bb95-608cb4285017, AGR-standard owner)"
  RECORD_CLASS::"APPLIES ratified decisions; makes no new decision. Operator ratified this record, see OPERATOR_RULING, RATIFIED_BY and RATIFIED_AT"
  DECISION::"ADR-RFC-ARCH-004 v1.3→v1.4 in place: §1.1,§1.6,§1.7,§3.2,§3.4 readers parse quoted-YAML records beside OCTAVE, strict ∧ loud; reader side only, write path→EPIC4 PR-5"
  BECAUSE::"HO-TOPIC-RECORDS-YAML-SYNTAX-20261029 says §1.7 YAML form is owed via EPIC4 PR-4; EPIC4-RECORDS-YAML-BATCH-MERGE-AUTHORITY-20261025 batches readers first; ADR has no TOKEN ∴ in-place edit"
  AUTHORITY::"HO-TOPIC-RECORDS-YAML-SYNTAX-20261029 ∧ EPIC4-RECORDS-YAML-BATCH-MERGE-AUTHORITY-20261025, both RATIFIED; amend-in-place per HO-GOVERNANCE-AMEND-IN-PLACE-20260926"
  SCOPE::"ADR-RFC-ARCH-004 v1.3→v1.4 in-place amendment to §1.1, §1.6, §1.7, §3.2 and §3.4, plus §4.1 #14 wording; reader side only. Write path (submit_governance content mode, Gate A YAML branch) arrives with EPIC4 PR-5. §3.2 resolution_chain_status gains 'forked' and 'unparseable'; lookup_decision adds `successors` and `rejected_at`; trace_supersedure adds CHAIN_FORK_DETECTED (RECORD_PARSE_FAILED reused for chains). Scope extension to (e) TOKEN-list supersedes plus fork reporting, granted by the HC control room"
  ADVISORY_RULINGS::"Epic 4 solution authority, ADVISORY not binding: v9-agent-creation; (a) lowercase keys; (b) strict and loud; (d) lexer <token>.md; (e) TOKEN-list supersedes; escape set; edge scope; fork"
  AMENDED_ARTEFACTS::".hestai/decisions/rfc-arch/ADR-RFC-ARCH-004-agent-readable-governance-records.md v1.3→v1.4 in place (dual-syntax readers, PR #218); TOKEN-less → no AMENDS edge per ADR-RFC-ARCH-004 §1.6"
  RELATED_DECISIONS::[
    HO-TOPIC-RECORDS-YAML-SYNTAX-20261029,
    EPIC4-RECORDS-YAML-BATCH-MERGE-AUTHORITY-20261025,
    HO-GOVERNANCE-AMEND-IN-PLACE-20260926
  ]
  AFFECTS::[
    lookup_decision,
    list_decisions,
    trace_supersedure,
    "ADR-RFC-ARCH-004 sections 1.1, 1.6, 1.7, 3.2, 3.4, 4.1",
    "hestai-context-mcp#218",
    "EPIC4 PR-5"
  ]
  RATIFIED_BY::"human:operator<shaunbuswell>"
  RATIFIED_AT::"2026-10-31T01:18:58Z"
  OPERATOR_RULING::"Shaun Buswell, 2026-10-31, HC control room session (ceremony 625fb59c), first-party operator turn, relayed by the HC control room: '1. Ratify 219'"
  REVISION::"2026-10-31: STATUS PROPOSED→RATIFIED in place, recording the operator ratification relayed from the HC control room; RATIFIED_AT is when this amendment was written (date -u), not the operator's turn time."
===END===
