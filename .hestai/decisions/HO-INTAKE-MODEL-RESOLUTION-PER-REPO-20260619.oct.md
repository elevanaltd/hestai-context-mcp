===DECISION_RECORD===
META:
  TYPE::DECISION_RECORD
  VERSION::"1.0"
  TOKEN::HO-INTAKE-MODEL-RESOLUTION-PER-REPO-20260619
  STATUS::PROPOSED
  TIER::STRATEGIC
  AUTHORED_AT::"2026-06-19T00:00:00Z"
  ISSUE_REF::"repo:hestai-context-mcp#106"
  HUMAN_ADR_REF::".hestai/decisions/rfc-arch/ADR-RFC-ARCH-004-agent-readable-governance-records.md"
  SCOPE::"hestai-context-mcp"
  CONSTITUTIONAL_BASIS::[PROD_I2,PROD_I3]
  AFFECTS::[intake_compiler,clock_in_synthesis,analysis_tier_reviewer]
  SCOPE_GUARD::"governs AI-model resolution precedence ONLY; provider/credential/keyring resolution unchanged"
  DECISION::"AI-model resolution becomes per-call working_dir-scoped. resolve_model(tier, working_dir) reads ONLY the HESTAI_AI_MODEL[_TIER] keys from the caller repo's .env. Precedence: explicit_tool_arg → working_dir/.env → process_env(launcher_fallback) → DEFAULT_MODEL. Caller .env is parsed for those keys in isolation, NEVER load_dotenv'd into the shared process → zero caller-secret ingress. override=False retained for the server's own .env."
  BECAUSE::"Tool invoked per-repo (working_dir) but model resolved per-process (os.environ fixed at server launch) → calling repo's model never honored. hestai-workbench dispatcher exports a global HESTAI_AI_MODEL into every session ∧ server loads its own .env override=False → launcher value wins ∧ caller .env ignored. override=True rejected: server loads its OWN install-dir .env not the caller's → would relocate the single global default, NOT yield per-repo selection, ∧ would regress secret precedence (stale file value clobbering injected secret → PROD::I2). Per-call working_dir resolution = the only path carrying caller identity into model choice. Model IDs are not secrets → PROD::I2 preserved; model stays a runtime value below the AIClient port → PROD::I3 provider-agnostic preserved."
===END===