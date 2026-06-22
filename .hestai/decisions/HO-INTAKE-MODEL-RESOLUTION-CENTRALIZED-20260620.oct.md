===DECISION_RECORD===
META:
  TYPE::DECISION_RECORD
  VERSION::"1.0"
  TOKEN::HO-INTAKE-MODEL-RESOLUTION-CENTRALIZED-20260620
  STATUS::PROPOSED
  TIER::STRATEGIC
  COMPRESSION_TIER::CONSERVATIVE
  LOSS_PROFILE::"[preserve:superseded_relationship_and_PROD_I2_credential_safety_and_PROD_I3_provider_agnostic,drop:narrative_history_of_model_resolution_debate]"
  AUTHORED_AT::"2026-06-20T00:00:00Z"
  ISSUE_REF::"repo:hestai-context-mcp#106"
  SUPERSEDES::["HO-INTAKE-MODEL-RESOLUTION-PER-REPO-20260619"]
  SCOPE::"hestai-context-mcp"
  AFFECTS::[resolve_model,submit_governance,clock_in,intake_compiler,governance_reviewer,build_default_ai_client]
  SCOPE_GUARD::"governs AI model resolution logic ∧ caller environment parsing ONLY; actual LLM provider API calls are EXCLUDED"
  DECISION::"Centralize AI model resolution by default via process environment HESTAI_AI_MODEL, allowing explicit per-repo opt-in via PER_REPO_OVERRIDE in caller .env with threaded working_dir."
  BECAUSE::"Centralized default ensures consistent governance ∧ context synthesis quality ⊕ opt-in override preserves repo-specific flexibility ⇌ requires threading working_dir through tool entry points ∧ parsing caller .env without load_dotenv to preserve PROD I2."
===END===