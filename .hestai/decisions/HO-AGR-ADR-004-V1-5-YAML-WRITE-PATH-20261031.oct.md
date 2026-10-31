===DECISION_RECORD===
META:
  TYPE::DECISION_RECORD
  VERSION::"1.1"
  TOKEN::HO-AGR-ADR-004-V1-5-YAML-WRITE-PATH-20261031
  STATUS::RATIFIED
  TIER::STRATEGIC
  COMPRESSION_TIER::CONSERVATIVE
  LOSS_PROFILE::"[preserve:decision,authority,scope,amended_artefact,conditions,IDs;drop:discussion]"
  AUTHORED_AT::"2026-10-31T02:19:58Z"
  RATIFIED_BY::"agent:holistic-orchestrator@hc-control-room (HO-HC-WEEKEND-DELEGATION-20261031)"
  RATIFIED_AT::"2026-10-31T02:19:58Z"
  ISSUE_REF::"repo:hestai-context-mcp#226"
  CEREMONY_REF::"625fb59c-a1a2-466b-bb95-608cb4285017"
  AUTHORING_SESSION::"holistic-orchestrator:ho-records-1-a3, filed for the HC control room (AGR-standard owner)"
  RECORD_CLASS::"applies ratified decisions; makes no new decision"
  DECISION::"ADR-RFC-ARCH-004 moves from version 1.4 to 1.5 in place: submit_governance content mode writes quoted-YAML records, saving canonical front matter plus the body verbatim, so the file bytes are the canonical bytes and the record hash covers the whole file."
  BECAUSE::"The ratified Epic 4 batch orders the YAML write path after the readers, and the YAML default ruling makes it the format for new records; the HC conditions require a round trip gate, one hash contract and repeatable output."
  AUTHORITY::"EPIC4-RECORDS-YAML-BATCH-MERGE-AUTHORITY-20261025 (RATIFIED); HO-RECORDS-YAML-DEFAULT-20261031 (RATIFIED, merged 094938f7); HW-PROGRAMME ruling C of 2026-10-31 under HW-PROGRAMME-WEEKEND-AUTHORITY-20261031: canonical re-emitted front matter plus the body verbatim, with record_hash as the hash of the file bytes; HC conditions C1 to C3 of 2026-10-31 under HO-HC-WEEKEND-DELEGATION-20261031 (merged 0d65c135): C1 per-field round-trip gate, C2 ADR section 1.1 hash contract, C3 idempotent emission"
  SCOPE::"ADR-RFC-ARCH-004 v1.4 to v1.5 in-place amendment (PR #226): section 1.1 (write path ships; canonical front matter plus verbatim body; file bytes equal canonical bytes; record hash covers the whole file; pre-v1.5 records canonicalise only when rewritten, which arrives with S2), section 1.2 VERSION row, section 1.5 v1.5 paragraph, section 4.1 (Gate A YAML branch; cross-syntax TOKEN uniqueness). Prose mode stays OCTAVE"
  AMENDED_ARTEFACTS::".hestai/decisions/rfc-arch/ADR-RFC-ARCH-004-agent-readable-governance-records.md v1.4 to v1.5 in place (YAML write path, PR #226); TOKEN-less, so no AMENDS edge per ADR-RFC-ARCH-004 section 1.6"
  RELATED_DECISIONS::[
    EPIC4-RECORDS-YAML-BATCH-MERGE-AUTHORITY-20261025,
    HO-RECORDS-YAML-DEFAULT-20261031,
    HO-HC-WEEKEND-DELEGATION-20261031,
    HO-AGR-PLAIN-WORDS-REASONING-20261031,
    HO-AGR-ADR-004-V1-4-DUAL-SYNTAX-READERS-20261029
  ]
  AFFECTS::[
    "submit_governance content mode",
    "Gate A YAML branch",
    "ADR-RFC-ARCH-004 sections 1.1, 1.2, 1.5, 4.1",
    "hestai-context-mcp#226",
    "EPIC4 PR-5"
  ]
===END===