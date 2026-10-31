===DECISION_RECORD===
META:
  TYPE::DECISION_RECORD
  VERSION::"1.1"
  TOKEN::HO-AGR-ADR-004-V1-9-NESTED-LIST-ITEMS-20261031
  STATUS::RATIFIED
  TIER::STRATEGIC
  COMPRESSION_TIER::CONSERVATIVE
  LOSS_PROFILE::"[preserve:decision,authority,scope,amended_artefact,reader_behaviour_change,IDs;drop:discussion]"
  AUTHORED_AT::"2026-10-31T06:10:01Z"
  RATIFIED_BY::"agent:holistic-orchestrator@hc-control-room (HO-HC-WEEKEND-DELEGATION-20261031)"
  RATIFIED_AT::"2026-10-31T06:10:01Z"
  ISSUE_REF::"repo:hestai-context-mcp#196"
  CEREMONY_REF::"625fb59c-a1a2-466b-bb95-608cb4285017"
  AUTHORING_SESSION::"holistic-orchestrator:ho-records-1-a3, filed for the HC control room (AGR-standard owner)"
  RECORD_CLASS::"applies ratified decisions; makes no new decision"
  DECISION::"ADR-RFC-ARCH-004 moves from version 1.8 to 1.9 in place: the shared OCTAVE reader treats a line indented deeper than a wrapped list's opener as a list item, so nested keyed items stay list text, never record fields."
  BECAUSE::"The octave_write tool writes lists of keyed items in nested form, and the reader took those lines as record fields; the HC control room chose one indent rule in the shared reader, keeping a single list grammar."
  AUTHORITY::"HC control room ruling on hestai-context-mcp#196, option i: an indent rule in the shared reader, one list grammar, 2026-10-31, under HO-HC-WEEKEND-DELEGATION-20261031 (RATIFIED); sequenced by HW-PROGRAMME under HW-PROGRAMME-WEEKEND-AUTHORITY-20261031"
  SCOPE::"ADR-RFC-ARCH-004 v1.8 to v1.9 in-place amendment (PR #239): section 1.1 OCTAVE list fields. A line indented deeper than the opener is an item. A break requires a line at the opener's indentation or shallower, not inside an open quote, that is a KEY:: field, a block header or an equals-sign envelope line. A closing bracket at the opener's indent closes the list. Tabs count as width four. A nested key item is list text, never a record field. The rest is the version markers in the Status line and sections 1.2 and 1.5. Reader behaviour change: the file layout that octave_write writes (the canonical workflow-file form) now reads the same as the inline form"
  AMENDED_ARTEFACTS::".hestai/decisions/rfc-arch/ADR-RFC-ARCH-004-agent-readable-governance-records.md v1.8 to v1.9 in place (nested list items, PR #239); TOKEN-less, so no AMENDS edge per ADR-RFC-ARCH-004 section 1.6"
  RELATED_DECISIONS::[
    HO-AGR-ADR-004-V1-6-MULTILINE-LISTS-20261031,
    HO-AGR-ADR-004-V1-8-PLAIN-WORDS-REASONING-20261031,
    HO-HC-WEEKEND-DELEGATION-20261031,
    HO-GOVERNANCE-AMEND-IN-PLACE-20260926
  ]
  AFFECTS::[
    "OCTAVE decision-record reader",
    "ADR-RFC-ARCH-004 sections 1.1, 1.2, 1.5",
    "hestai-context-mcp#196",
    "hestai-context-mcp#239"
  ]
===END===