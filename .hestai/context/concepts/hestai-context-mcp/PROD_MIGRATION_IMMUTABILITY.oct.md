===META===
TYPE::CONCEPT_CARD
REPO_ID::hestai-context-mcp
ID::PROD_MIGRATION_IMMUTABILITY
STATUS::proposed
CARD_SCHEMA_VERSION::1
GENERATED_AT_COMMIT::"2909a8b"
SOURCE_HASH::"N/A_pending_G2_baseline"
===END===

===EXACT===
IDS::[PROD_MIGRATION_IMMUTABILITY,MIGRATION_IMMUTABILITY,MONOREPO_GOVERNANCE]
PROD_IMMUTABLES::[]
ADR_REFS::[]
ISSUE_REFS::[]
TOOL_NAMES::[]
FILE_PATHS::[]
MUST_PRESERVE::[
  "A migration that has run in any environment MUST NEVER be edited in-place — only forward migrations roll the schema",
  "Migration filenames are append-only; renaming or deletion is forbidden once committed",
  "The migration history is the ground truth of schema evolution; database state without migration provenance is invalid",
  "Branch merges that introduce out-of-order migration numbers require explicit reconciliation, not silent renumbering"
]
===END===

===FACETS===
INTENT::"PROD_MIGRATION_IMMUTABILITY ratifies migration-file immutability as a product-level invariant of the elevana-studio monorepo. Once a migration has executed against any environment, the migration file is frozen; schema evolution proceeds exclusively through new forward migrations. This card encodes the invariant as the load-bearing constraint that protects schema-history integrity across multi-environment deployments, branching workflows, and rollback scenarios."
CONSTRAINTS::[
  "Edit-in-place of a committed migration is FORBIDDEN — the file is append-only",
  "Migration ordering (timestamp or sequence prefix) MUST be monotonic; out-of-order arrivals require explicit reconciliation migrations",
  "Renaming a migration file after it has executed in any environment is treated as deletion + recreation and FORBIDDEN",
  "Rollback is achieved by a forward 'down' migration, never by reverting the file",
  "CI MUST verify that no previously-recorded migration has changed content hash between branches"
]
FAILURE_MODES::[
  "Editing a migration after staging environment ran it — production diverges silently; schema drift becomes invisible",
  "Renaming for cosmetic reasons — breaks every environment's migration ledger and forces ledger-rebuild risk",
  "Squashing migrations during a branch rebase — destroys the history that documents intent and review",
  "Treating a failed migration as 'reset and retry' rather than 'forward fix migration' — accumulates undocumented schema state"
]
OPERATIONAL_RULES::[
  "To fix a bad migration, author a NEW forward migration that corrects it; never edit the original",
  "Migration file naming MUST include the immutable timestamp or sequence prefix at the start",
  "Pull requests MUST be rejected if `git diff` against main shows modifications to any file under the migrations directory whose path existed on main",
  "Database resets in dev environments are tolerated; in staging/prod they require operator approval and a written reason"
]
INTEGRATION_POINTS::[
  "FOUNDATIONAL — migration immutability is one of the foundational governance invariants for the monorepo",
  "MONOREPO_GOVERNANCE — this card is the migration-specific specialisation of the monorepo governance principle",
  "CI gate enforcement (out-of-scope here; implemented in the elevana-studio repo)"
]
CURRENT_STATUS::"proposed — authored as part of the G4 facet-card corpus (ADR-RFC-ARCH-005 §4 G4). Awaits ratification once G5 validator CLI lands and CI gate green. Reserved-prefix usage of PROD_ signals product-level invariant per ADR-RFC-ARCH-005 §1.3."
WHEN_TO_LOAD::[
  "elevana-studio database schema change question",
  "migration authoring or review",
  "branch merge with migration conflicts",
  "rollback strategy question",
  "monorepo governance audit"
]
WHEN_NOT_TO_LOAD::[
  "application-code refactor question without schema implications",
  "non-elevana-studio repo (this is product-specific to elevana-studio)",
  "test-database seed strategy (orthogonal concern)"
]
===END===

===EDGES===
EXTENDS::[]
CONSTRAINS::[]
IMPLEMENTED_BY::[]
TESTED_BY::[]
RELATED::[FOUNDATIONAL]
CONFLICTS_WITH::[]
PART_OF_FRAME::[]
===END===

===SOURCE_REFS===
[
  "repo:elevana-studio:.hestai/decisions/DECISIONS.oct.md#HO-MIGRATION-GOVERNANCE-20251107",
  "repo:elevana-studio:.hestai/decisions/DECISIONS.oct.md#HO-MONOREPO-GOVERNANCE-20251107"
]
===END===

===VALIDATION===
SOURCE_REF_RESOLVES::true
MARKERS_RESOLVE_TO_CARD::N/A
CHANGED_MARKED_FILE_REQUIRES_REVIEW::false
===END===
