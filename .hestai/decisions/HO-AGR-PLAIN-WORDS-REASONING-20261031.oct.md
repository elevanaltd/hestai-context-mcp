===DECISION_RECORD===
META:
  TYPE::DECISION_RECORD
  VERSION::"1.1"
  TOKEN::HO-AGR-PLAIN-WORDS-REASONING-20261031
  STATUS::RATIFIED
  TIER::STRATEGIC
  COMPRESSION_TIER::CONSERVATIVE
  LOSS_PROFILE::"[preserve:operator_quote,inner_rule_4_text,retained_limits,amended_clauses,follow_up_surfaces,out_of_scope,IDs;drop:discussion]"
  AUTHORED_AT::"2026-10-31T00:00:00Z"
  RATIFIED_BY::"human:operator<shaunbuswell>"
  RATIFIED_AT::"2026-10-31T00:00:00Z"
  CEREMONY_REF::"625fb59c-a1a2-466b-bb95-608cb4285017"
  AUTHORING_SESSION::"holistic-orchestrator:hc-control-room-20260929"
  AMENDS::[HO-AGR-BYTECODE-FORMAT-TWO-BIRDS-20260620]
  OPERATOR_RULING::"Shaun Buswell, 2026-10-31, HC control room session, first-party, verbatim: 'The writing rules for records should follow this. \"inner rule 4 replaces the compressed-OCTAVE operator clause for DECISION and BECAUSE; the flat-string, forty-word, no-newline limits stay.\" I ratify this decision and you can do this here and do whatever you need to with theb old ruling to stop it being used.'"
  INNER_RULE_4::"From the LANG-ARCH (lang-arch-01, hestai-workbench) message inner-language rules: 'Write relations in plain words, never arrows or symbols.'"
  RULE::"DECISION and BECAUSE carry relations in plain words, never arrows or symbols (no compressed-OCTAVE operators). Unchanged: each is one flat double-quoted string, at most 40 words, no embedded newline, Gate A ADR-RFC-ARCH-004 sec 4.1 #13"
  AMENDED_ARTEFACTS::"HO-AGR-BYTECODE-FORMAT-TWO-BIRDS-20260620, in place in this PR: FORMAT_RULE operator clause replaced by the plain-words rule, DECISION wording aligned, REVISION line added; nested-key rejection, two-birds ADR generation and HUMAN_ADR_REF form unchanged"
  FOLLOW_UP::"One PR after EPIC4 PR-5, sequenced by HW-PROGRAMME, together with HO-RECORDS-YAML-DEFAULT-20261031 prose mode: _COMPRESSION_CONTRACT in tools/governance/intake_context.py and its worked example drop the operator glyphs; Gate A guidance strings in tools/governance/type_checker.py stop recommending operators; ADR-RFC-ARCH-004 sec 1.2 DECISION and BECAUSE rows and sec 1.5 v1.1 paragraph amended in place; tests that assert the glyphs change under this ruling"
  NOT_ENFORCED::"Gate A does not machine-reject glyphs; the rule is authoring guidance like the clause it replaces. Existing records are not rewritten"
  OUT_OF_SCOPE::"elevana-studio HO-DECISION-RECORD-SHAPE-AND-AMENDMENT-DISCIPLINE-20260909 shape law: the ES room decides whether to adopt this on its own authority"
  RE_REVIEW_TRIGGER::"Re-open if new records keep carrying operator glyphs after the follow-up merges, which would justify a Gate A check"
  RELATED_DECISIONS::[
    HO-AGR-BYTECODE-FORMAT-TWO-BIRDS-20260620,
    HO-GOVERNANCE-AMEND-IN-PLACE-20260926,
    HO-RECORDS-YAML-DEFAULT-20261031,
    HO-HC-WEEKEND-DELEGATION-20261031
  ]
  AFFECTS::[
    "DECISION and BECAUSE authoring",
    "intake_context _COMPRESSION_CONTRACT",
    "Gate A guidance text",
    "ADR-RFC-ARCH-004 sec 1.2 and sec 1.5"
  ]
  DECISION::"DECISION and BECAUSE write relations in plain words, never arrows or symbols, replacing the compressed-OCTAVE operator clause; each stays one flat quoted string of at most forty words with no newline."
  BECAUSE::"The operator ratified LANG-ARCH inner rule 4 for records; the reported lookup tests found no gain from operator glyphs, and the density limits alone keep reasoning fields short."
  INTERIM::"Until the FOLLOW_UP PR merges, this record and the amended HO-AGR-BYTECODE-FORMAT-TWO-BIRDS-20260620 take precedence over the operator-glyph recommendation in ADR-RFC-ARCH-004 sec 1.2 and sec 1.5 and over the Gate A guidance strings in tools/governance/type_checker.py and the intake _COMPRESSION_CONTRACT; authors follow the plain-words rule now"
  REVISION::"2026-10-31: INTERIM precedence clause added for Stage-5 SR concern issuecomment-6537231939; AUTHORED_AT and RATIFIED_AT set to date precision, the earlier 01:42Z value was an estimate later than the measured filing time"
===END===
