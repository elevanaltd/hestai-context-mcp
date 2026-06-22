===DECISION_RECORD===
META:
  TYPE::DECISION_RECORD
  VERSION::"1.0"
  TOKEN::HO-INTAKE-MODEL-RESOLUTION-PER-REPO-20260619
  STATUS::RATIFIED
  TIER::STRATEGIC
  AUTHORED_AT::"2026-06-19T00:00:00Z"
  RATIFIED_BY::"human:operator"
  RATIFIED_AT::"2026-06-20T00:00:00Z"
  ISSUE_REF::"repo:hestai-context-mcp#106"
  HUMAN_ADR_REF::".hestai/decisions/rfc-arch/ADR-RFC-ARCH-004-agent-readable-governance-records.md"
  SCOPE::"hestai-context-mcp"
  CONSTITUTIONAL_BASIS::[PROD_I2,PROD_I3]
  AFFECTS::[intake_compiler,clock_in_synthesis,analysis_tier_reviewer]
  SCOPE_GUARD::"governs AI-model resolution precedence ONLY; provider/credential/keyring resolution unchanged"
  DECISION::"AI-model resolution becomes per-call working_dir-scoped: resolve_model(tier,working_dir) reads HESTAI_AI_MODEL[_TIER] from caller .env in isolation (never load_dotenv'd→zero secret ingress). Precedence: tool_arg→working_dir/.env→process_env→DEFAULT_MODEL."
  BECAUSE::"Tool invoked per-repo but model resolved per-process→caller model never honored; workbench exports global HESTAI_AI_MODEL∧server .env override=False→launcher wins. override=True rejected: server loads its OWN .env→relocates global default≠per-repo∧regresses secret precedence→PROD::I2. Per-call working_dir=only path carrying caller identity; model IDs∉secrets→PROD::I2∧PROD::I3 preserved."
===END===
