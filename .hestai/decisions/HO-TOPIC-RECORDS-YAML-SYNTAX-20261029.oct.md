===DECISION_RECORD===
META:
  TYPE::DECISION_RECORD
  VERSION::"1.1"
  TOKEN::HO-TOPIC-RECORDS-YAML-SYNTAX-20261029
  STATUS::RATIFIED
  TIER::STRATEGIC
  COMPRESSION_TIER::CONSERVATIVE
  LOSS_PROFILE::"[preserve:decision∧operator_quote∧build_order∧scope_exclusions∧re_review_trigger∧IDs,drop:discussion_prose]"
  AUTHORED_AT::"2026-10-29T00:00:00Z"
  RATIFIED_BY::"human:operator<shaunbuswell>"
  RATIFIED_AT::"2026-10-29T00:00:00Z"
  ISSUE_REF::"repo:hestai-context-mcp#203"
  CEREMONY_REF::"625fb59c-a1a2-466b-bb95-608cb4285017"
  AUTHORING_SESSION::"holistic-orchestrator:hc-control-room-20260929"
  EXTENDS::[HO-TOPIC-RECORDS-AND-APPEND-RULING-20261015]
  OPERATOR_RULING::"Shaun Buswell, 2026-10-29, HC control room session, first-party, answering 'OCTAVE or YAML for topic records' (HC recommendation: YAML): '2. YAML'"
  SCOPE::"Topic-record syntax and build order only. For NEW topic records this supersedes: (1) the OCTAVE CURRENT/RULINGS syntax in ADR-RFC-ARCH-004 v1.3 sec 1.7 (a TOKEN-less ADR, hence EXTENDS rather than AMENDS) and design-note option B sec 3 rendering, adopted under HO-TOPIC-RECORDS-AND-APPEND-RULING-20261015; (2) the slice order S2-after-S1 of design-note option B sec 8 and #203, now PR-4 then PR-5 then S2. Unchanged in HO-TOPIC-RECORDS-AND-APPEND-RULING-20261015: append_ruling broker, ceremony-marker test, the three in-place amendments, the in-flight record ratifications. Existing OCTAVE records stay valid and unmigrated (EPIC4-RECORDS-YAML-BATCH-MERGE-AUTHORITY-20261025 NON_EFFECTS). ADR-RFC-ARCH-004 sec 1.7 YAML form is owed via EPIC4 PR-4"
  DECISION::"Topic records→quoted-YAML records via submit_governance content-mode YAML path[EPIC4 PR-5] ∧ order PR-4→PR-5→topic S2 ∧ PR-4 keeps S1 TOPIC∧current_state for OCTAVE ∧ defines YAML TOPIC/CURRENT/RULINGS form ∧ S2 append_ruling builds on PR-5"
  BECAUSE::"No topic records exist yet; EPIC4 makes quoted-YAML the new write format; one write path avoids building append twice; ruling lists fit YAML∧drop S2 OCTAVE escaping; HC, topic lane∧HW-PROGRAMME concur on order"
  RE_REVIEW_TRIGGER::"Re-open if EPIC4 PR-5 is parked or reverted ∨ a YAML header cannot carry CURRENT/RULINGS under regex-only readers"
  RELATED_DECISIONS::[EPIC4-RECORDS-YAML-BATCH-MERGE-AUTHORITY-20261025,HO-GOVERNANCE-AMEND-IN-PLACE-20260926]
  AFFECTS::[
    "submit_governance append_ruling",
    "lookup_decision current_state",
    "list_decisions topic filter",
    "ADR-RFC-ARCH-004 topic-record section",
    "hestai-context-mcp#203",
    "EPIC4 PR-4 ∧ PR-5"
  ]
  REVISION::"2026-10-29: SCOPE amended in place to name what is superseded (Stage-5 SR concern issuecomment-6501657257) and wording fixes applied (SR issuecomment-6501705355)"
===END===
