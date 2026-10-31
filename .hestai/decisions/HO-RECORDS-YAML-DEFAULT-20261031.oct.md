===DECISION_RECORD===
META:
  TYPE::DECISION_RECORD
  VERSION::"1.1"
  TOKEN::HO-RECORDS-YAML-DEFAULT-20261031
  STATUS::RATIFIED
  TIER::STRATEGIC
  COMPRESSION_TIER::CONSERVATIVE
  LOSS_PROFILE::"[preserve:operator_quotes,scope,amended_clause,sequencing,non_effects,IDs;drop:discussion]"
  AUTHORED_AT::"2026-10-31T00:00:00Z"
  RATIFIED_BY::"human:operator<shaunbuswell>"
  RATIFIED_AT::"2026-10-31T00:00:00Z"
  CEREMONY_REF::"625fb59c-a1a2-466b-bb95-608cb4285017"
  AUTHORING_SESSION::"holistic-orchestrator:hc-control-room-20260929"
  EXTENDS::[HO-TOPIC-RECORDS-YAML-SYNTAX-20261029]
  OPERATOR_RULING::"Shaun Buswell, 2026-10-31, HC control room session, first-party: 'I'm also ok with yaml for every new record'. Asked by HC whether that includes records filed from prose (which extends the prose compiler that EPIC4-RECORDS-YAML-BATCH-MERGE-AUTHORITY-20261025 STANDARDS kept OCTAVE), with no migration and OCTAVE filing until the YAML path lands, the operator answered verbatim: '3. Yes'"
  SCOPE::"Every NEW decision record in hestai-context-mcp, content mode and prose mode. Topic records were already ruled by HO-TOPIC-RECORDS-YAML-SYNTAX-20261029, which this record extends to all records"
  AMENDED_ARTEFACTS::"EPIC4-RECORDS-YAML-BATCH-MERGE-AUTHORITY-20261025 STANDARDS, in place: the clause 'the prose compiler is not extended to YAML records' is replaced by a pointer to this record; the rest of STANDARDS and BATCH is unchanged"
  SEQUENCING::"EPIC4 PR-5 ships the content-mode YAML write path at its brief scope. Prose mode emitting YAML is a follow-up PR after PR-5, sequenced by HW-PROGRAMME, and requires a prose-mode fidelity guard for hestai-context-mcp #195, which does not yet exist, to land first; prose mode emits YAML only in the same PR as that guard or after it. Until each path lands, records filed through it stay OCTAVE"
  NON_EFFECTS::"No migration, reformat or deletion of existing .oct.md records; OCTAVE records stay valid and readable; readers are unchanged (dual-syntax since PR #218)"
  RE_REVIEW_TRIGGER::"Re-open if PR-5 is parked or reverted, or if prose-mode YAML cannot pass the #195 fidelity guard once it exists"
  RELATED_DECISIONS::[
    EPIC4-RECORDS-YAML-BATCH-MERGE-AUTHORITY-20261025,
    HO-TOPIC-RECORDS-YAML-SYNTAX-20261029,
    HO-GOVERNANCE-AMEND-IN-PLACE-20260926,
    HO-HC-WEEKEND-DELEGATION-20261031
  ]
  AFFECTS::[
    "submit_governance content mode",
    "submit_governance prose mode",
    "intake compiler",
    "Gate A YAML branch",
    "EPIC4 PR-5 and its follow-up"
  ]
  DECISION::"Every new decision record is written as quoted YAML, from content mode and prose mode alike, once each write path lands; until then records filed through that path stay OCTAVE, and existing OCTAVE records are never migrated."
  BECAUSE::"The operator ruled YAML for every new record and confirmed prose mode is included; one write format avoids two authoring paths, and readers already handle both syntaxes since PR 218 merged."
  REVISION::"2026-10-31: AUTHORED_AT and RATIFIED_AT set to date precision; the earlier 01:40Z value was an estimate later than the measured filing time; 2026-10-31: SEQUENCING and RE_REVIEW_TRIGGER corrected; the cited #195 guard did not exist (HO-RECORDS finding, HC confirmed)"
===END===
