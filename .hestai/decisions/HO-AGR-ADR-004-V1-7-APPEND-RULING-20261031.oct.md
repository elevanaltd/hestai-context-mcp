===DECISION_RECORD===
META:
  TYPE::DECISION_RECORD
  VERSION::"1.1"
  TOKEN::HO-AGR-ADR-004-V1-7-APPEND-RULING-20261031
  STATUS::RATIFIED
  TIER::STRATEGIC
  COMPRESSION_TIER::CONSERVATIVE
  LOSS_PROFILE::"[preserve:decision,authority,scope,amended_artefact,IDs;drop:discussion]"
  AUTHORED_AT::"2026-10-31T00:00:00Z"
  RATIFIED_BY::"agent:holistic-orchestrator@hc-control-room (HO-HC-WEEKEND-DELEGATION-20261031)"
  RATIFIED_AT::"2026-10-31T03:28:38Z"
  ISSUE_REF::"repo:hestai-context-mcp#203"
  CEREMONY_REF::c52da839-8daf-4bbc-90f1-a3e5b5bc13c0
  AUTHORING_SESSION::"holistic-orchestrator:read-topic-records"
  RECORD_CLASS::"applies ratified decisions; makes no new decision"
  DECISION::"ADR-RFC-ARCH-004 moves from version 1.6 to 1.7 in place: section 3.5 records submit_governance append_ruling as delivered for quoted-YAML topic records, read at the origin/main commit, checked against the whole-file hash, and filed as one pull request."
  BECAUSE::"The operator approved topic records with append_ruling and ruled YAML for them; slice S2 now ships on the content-mode write path, so the ADR must describe the delivered contract instead of a planned one."
  AUTHORITY::"HO-TOPIC-RECORDS-AND-APPEND-RULING-20261015 (RATIFIED, operator 2026-10-15); HO-TOPIC-RECORDS-YAML-SYNTAX-20261029 (RATIFIED, operator 2026-10-29); operator approval of S2 first-party 2026-10-17; HO-HC-WEEKEND-DELEGATION-20261031 (RATIFIED); HC ratification OK, quoted byte-exact after this colon: HC control room ratifies HO-AGR-ADR-004-V1-7-APPEND-RULING-20261031 under HO-HC-WEEKEND-DELEGATION-20261031 as a record that applies ratified decisions (HO-TOPIC-RECORDS-AND-APPEND-RULING-20261015, HO-TOPIC-RECORDS-YAML-SYNTAX-20261029, #228's contract); the ratification holds only if the content HC verifies before merge matches that class."
  SCOPE::"ADR-RFC-ARCH-004 v1.6 to v1.7 in-place amendment. Section 3.5: append_ruling delivered for YAML topic records (input, single-OID base read, whole-file hash per section 1.1, canonical re-emission, Gate A existing-record skip reachable only from append_ruling, delivery, refusal codes; S3 in-flight append and S4 merge-time recheck not shipped). The status line. The wording in sections 1.1, 1.2, 1.5 and 1.7 that described append_ruling as planned now reads delivered. Section 1.1 hash contract is unchanged"
  AMENDED_ARTEFACTS::".hestai/decisions/rfc-arch/ADR-RFC-ARCH-004-agent-readable-governance-records.md v1.6 to v1.7 in place (issue 203 S2); TOKEN-less, so no AMENDS edge per ADR-RFC-ARCH-004 section 1.6"
  RELATED_DECISIONS::[
    HO-TOPIC-RECORDS-AND-APPEND-RULING-20261015,
    HO-TOPIC-RECORDS-YAML-SYNTAX-20261029,
    HO-AGR-ADR-004-V1-5-YAML-WRITE-PATH-20261031,
    HO-AGR-ADR-004-V1-6-MULTILINE-LISTS-20261031,
    HO-AGR-PLAIN-WORDS-REASONING-20261031,
    HO-HC-WEEKEND-DELEGATION-20261031
  ]
  AFFECTS::[
    "submit_governance append_ruling",
    "ADR-RFC-ARCH-004 sections 1.1, 1.2, 1.5, 1.7, 3.5",
    "hestai-context-mcp#203"
  ]
  REVISION::"2026-10-31: RATIFIED_AT set to the measured in-window time; the date-precision value preceded the HO-HC-WEEKEND-DELEGATION-20261031 window"
===END===
