===DECISION_RECORD===
META:
  TYPE::DECISION_RECORD
  VERSION::"1.0"
  TOKEN::HO-AGR-BYTECODE-FORMAT-TWO-BIRDS-20260620
  STATUS::PROPOSED
  TIER::STRATEGIC
  AUTHORED_AT::"2026-06-20T00:00:00Z"
  ISSUE_REF::"repo:hestai-context-mcp#101"
  HUMAN_ADR_REF::".hestai/decisions/rfc-arch/ADR-RFC-ARCH-004-agent-readable-governance-records.md"
  SCOPE::"hestai-context-mcp"
  AFFECTS::[agr_format,intake_compiler,submit_governance,type_checker,agr_read]
  SCOPE_GUARD::"governs AGR authoring FORMAT ∧ optional ADR generation ONLY; read-parser structure ∧ Gate-A schema-parse logic unchanged"
  FORMAT_RULE::"DECISION∧BECAUSE=flat_strings,compressed_OCTAVE_operators(→⇌∴⊕),≤40_words,no_newline"
  NESTED_KEYS::REJECTED→invisible_to_flat_regex_parser∴breaks_88_parity
  DEPTH_MODEL::"two-birds:optional_agent_adr_prose→dumb_write_docs/adr/<token>.md⊕condensed_AGR_w/HUMAN_ADR_REF_token;absent→standalone_AGR"
  ADR_REF_FORM::greppable_TOKEN→cross_repo_survivable
  GATE_A_GUARD::"add word_count∧newline check(≤40w);NO structural parser change"
  DECISION::"Adopt AGR-as-LLM-bytecode: compressed-OCTAVE flat DECISION∧BECAUSE, nested custom keys REJECTED, optional two-birds ADR generation, HUMAN_ADR_REF as greppable token (ADR-004 v1.1, MINOR-additive)."
  BECAUSE::"AGRs ~99% LLM-read→optimise retrieval∧attention not prose; verbose BECAUSE harms attention∧violates §1.2 one-sentence. Flat-field compression preserves #88 write/read parity∴Wall-safe; severing mandatory-ADR coupling subtracts waste."
===END===
