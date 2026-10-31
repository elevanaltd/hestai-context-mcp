===DECISION_RECORD===
META:
  TYPE::DECISION_RECORD
  VERSION::"1.1"
  TOKEN::HO-AGR-ADR-004-V1-6-MULTILINE-LISTS-20261031
  STATUS::RATIFIED
  TIER::STRATEGIC
  COMPRESSION_TIER::CONSERVATIVE
  LOSS_PROFILE::"[preserve:decision,authority,scope,amended_artefact,deploy_note,IDs;drop:discussion]"
  AUTHORED_AT::"2026-10-31T03:04:48Z"
  RATIFIED_BY::"agent:holistic-orchestrator@hc-control-room (HO-HC-WEEKEND-DELEGATION-20261031)"
  RATIFIED_AT::"2026-10-31T03:04:48Z"
  ISSUE_REF::"repo:hestai-context-mcp#224"
  CEREMONY_REF::"625fb59c-a1a2-466b-bb95-608cb4285017"
  AUTHORING_SESSION::"holistic-orchestrator:ho-records-1-a3, filed for the HC control room (AGR-standard owner)"
  RECORD_CLASS::"applies ratified decisions; makes no new decision"
  DECISION::"ADR-RFC-ARCH-004 moves from version 1.5 to 1.6 in place: the OCTAVE reader reads list fields wrapped over several lines, edge fields included, with one grammar, and Gate A warns on a wrapped edge field."
  BECAUSE::"The octave_write tool wraps long lists in every format style, and the reader returned only an opening bracket for them; the HC control room ruled that the reader should learn the wrapped form."
  AUTHORITY::"HC control room ruling on hestai-context-mcp#224, 2026-10-31: option 2, the reader learns multi-line lists; design (a), one grammar for all list fields including edge fields, and Gate A warns on multi-line edge fields. Made under HO-HC-WEEKEND-DELEGATION-20261031 (RATIFIED); sequenced by HW-PROGRAMME under HW-PROGRAMME-WEEKEND-AUTHORITY-20261031"
  SCOPE::"ADR-RFC-ARCH-004 v1.5 to v1.6 in-place amendment (PR #229): section 1.1 (multi-line list grammar; unterminated list and text after the closing bracket make a record unparseable), section 1.2 VERSION row and section 1.5 version paragraph, section 1.6 (a bracketed SUPERSEDED_BY is read by item, several items are a fork), sections 3.2 and 3.4 (unparseable wording now also covers a rejected OCTAVE record), section 4.1 (Gate A error on an unterminated list, warning on a multi-line edge field, each bracketed SUPERSEDED_BY item must exist). Two reader behaviour changes are named explicitly: (1) a single-line bracketed SUPERSEDED_BY such as [X] now resolves to its successor, and two or more items mean a fork; (2) a rejected OCTAVE record (an unterminated wrapped list) met in the middle of a supersession chain now gives the unparseable outcome with rejected_at, the same as a rejected YAML record"
  AMENDED_ARTEFACTS::".hestai/decisions/rfc-arch/ADR-RFC-ARCH-004-agent-readable-governance-records.md v1.5 to v1.6 in place (multi-line list fields, PR #229); TOKEN-less, so no AMENDS edge per ADR-RFC-ARCH-004 section 1.6"
  DEPLOY_NOTE::"The interim rule that edge fields stay on one line remains in force until the operator restarts the hestai-context-mcp MCP server, because the running server keeps the old reader. The HC control room retires the rule after the restart is confirmed"
  RELATED_DECISIONS::[
    HO-HC-WEEKEND-DELEGATION-20261031,
    HO-AGR-ADR-004-V1-5-YAML-WRITE-PATH-20261031,
    HO-AGR-PLAIN-WORDS-REASONING-20261031,
    HO-GOVERNANCE-AMEND-IN-PLACE-20260926
  ]
  AFFECTS::[
    "OCTAVE decision-record reader",
    "Gate A list checks",
    "ADR-RFC-ARCH-004 sections 1.1, 1.2, 1.5, 1.6, 3.2, 3.4, 4.1",
    "hestai-context-mcp#224",
    "hestai-context-mcp#229"
  ]
===END===
