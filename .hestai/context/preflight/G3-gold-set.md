# G3 — Gold Set (RFC #38 pre-flight gate)

**Executor**: ho-liaison via pal_clink(goose, ho-liaison)
**Date**: 2026-05-08
**Purpose**: Frozen benchmark of 10 representative agent retrieval tasks. Each task names the concept IDs that SHOULD be returned. Becomes the recall measurement target for G6.

## TASK_001
- **Scenario**: implementation-lead about to modify `get_context.py` to expose active focuses needs to know what architectural rules govern the file.
- **Role**: IL
- **Phase**: B1
- **Focus**: `src/hestai_context_mcp/tools/get_context.py`
- **Token budget**: medium ~6k
- **Expected concept IDs**: `[PROD_I5, get_context_purity]`
- **Expected frame card**: `CONTEXT_RETRIEVAL_ARCHITECTURE_FRAME`
- **Rationale**: get_context.py has frozen purity constraints and must remain totally side-effect free, requiring these specific architectural guardrails.

## TASK_002
- **Scenario**: code-review-specialist reviewing a PR touching `storage/local_filesystem.py` needs the binding rulings for credential redaction and session persistence.
- **Role**: CRS
- **Phase**: post-merge
- **Focus**: `storage/*.py`
- **Token budget**: medium ~6k
- **Expected concept IDs**: `[PROD_I2, ADR_0013, B1_PSS_FOUNDATION]`
- **Expected frame card**: `REVIEW_GATE_TIER_3`
- **Rationale**: Changes to storage immediately trigger PROD_I2 (Credential Safety) and must comply with the ADR-0013 Portable Session State design.

## TASK_003
- **Scenario**: fresh agent on day one needs full orientation on what HestAI Context MCP is and what problems it solves in the overall three-service model.
- **Role**: fresh-agent
- **Phase**: D2
- **Focus**: project orientation and north star purpose
- **Token budget**: large ~15k
- **Expected concept IDs**: `[PROD_I1, PROD_I2, PROD_I3, PROD_I4, PROD_I5, PROD_I6]`
- **Expected frame card**: `CONTEXT_RETRIEVAL_ARCHITECTURE_FRAME`
- **Rationale**: A new agent needs all immutables and the overarching architectural frame to avoid proposing out-of-scope features.

## TASK_004
- **Scenario**: implementation-lead building the Portable Session State namespace layout needs the exact namespace boundaries and identity tuple definition.
- **Role**: IL
- **Phase**: B2
- **Focus**: ADR_0013
- **Token budget**: small ~2k
- **Expected concept IDs**: `[ADR_0013, B1_PSS_FOUNDATION]`
- **Expected frame card**: NONE
- **Rationale**: ADR-0013 owns the identity tuple and namespace layout definitions critical for this specific implementation task.

## TASK_005
- **Scenario**: holistic-orchestrator evaluating whether to delegate cross-machine session syncing needs to know if multi-machine coordination is currently supported.
- **Role**: HO
- **Phase**: D2
- **Focus**: `HO_MULTI_MACHINE_COORDINATION_20260429`
- **Token budget**: large ~15k
- **Expected concept IDs**: `[HO_MULTI_MACHINE_COORDINATION_20260429, PROD_I6]`
- **Expected frame card**: `CONTEXT_RETRIEVAL_ARCHITECTURE_FRAME`
- **Rationale**: The HO must align with established limits on legacy dependencies and specifically the multi-machine coordination boundary decision before delegation.

## TASK_006
- **Scenario**: continuous-integration-validator on day one needs to understand the project's coverage rules and behavioral invariants to run tests correctly.
- **Role**: CIV
- **Phase**: post-merge
- **Focus**: `CLAUDE.md`
- **Token budget**: small ~2k
- **Expected concept IDs**: `[get_context_purity, PROD_I5]`
- **Expected frame card**: NONE
- **Rationale**: The CIV needs the explicit testing constraints from CLAUDE.md and the critical purity invariants to properly orient to the CI pipeline requirements and strict markers.

## TASK_007
- **Scenario**: critical-engineer validating a B2 phase gate payload needs to ensure structural return shapes are strictly compliant with payload compiler expectations.
- **Role**: CE
- **Phase**: B2
- **Focus**: return shape extraction payload compiler
- **Token budget**: large ~15k
- **Expected concept IDs**: `[PROD_I4, REVIEW_GATE_TIER_3, B1_PSS_FOUNDATION]`
- **Expected frame card**: `REVIEW_GATE_TIER_3`
- **Rationale**: Validating phase gates requires the Tier 3 review frame and the specific I4 immutable dictating structured returns for KVAEPH integration.

## TASK_008
- **Scenario**: implementation-lead refactoring transcript parsing to support a new AI provider adapter needs to extract only provider-agnostic elements.
- **Role**: IL
- **Phase**: B1
- **Focus**: `src/hestai_context_mcp/core/*_adapter.py`
- **Token budget**: medium ~6k
- **Expected concept IDs**: `[PROD_I3, PROD_I2]`
- **Expected frame card**: NONE
- **Rationale**: Transcript parsing is heavily constrained by provider-agnosticism (I3) and credential redaction safety (I2).

## TASK_009
- **Scenario**: threat-modeling-guard assessing a proposed feature for adversarial prompt injection during transcript parsing needs to evaluate redaction safety.
- **Role**: TMG
- **Phase**: B2
- **Focus**: redaction safety credential leak
- **Token budget**: medium ~6k
- **Expected concept IDs**: `[PROD_I2, REVIEW_GATE_TIER_3]`
- **Expected frame card**: `REVIEW_GATE_TIER_3`
- **Rationale**: Evaluates the fail-closed redaction boundary to ensure credential safety is maintained under adversarial conditions.

## TASK_010
- **Scenario**: octave-secretary formatting the B2 operational workflow document needs to establish constraints around discoverability and structural persistence.
- **Role**: octave-secretary
- **Phase**: D2
- **Focus**: workflow phase constraints and discoverable persistence
- **Token budget**: small ~2k
- **Expected concept IDs**: `[PROD_I1, B1_PSS_FOUNDATION]`
- **Expected frame card**: NONE
- **Rationale**: Managing workflow document structure relies on the session lifecycle integrity rules and fundamental PSS standards to maintain artifact records.

## Distribution check

- **IL/code-author**: TASK_001, TASK_004, TASK_008, TASK_010
- **Reviewer**: TASK_002, TASK_007
- **Onboarding**: TASK_003, TASK_006
- **Governance/HO**: TASK_005, TASK_009

## Notes

Aspirational concept IDs not yet present in the current corpus:
- `HO_MULTI_MACHINE_COORDINATION_20260429` — authored as a facet card in G4, but not yet published in elevana-studio canonical
- `CONTEXT_RETRIEVAL_ARCHITECTURE_FRAME` — authored as a frame card in G4 (RFC #38)
- `REVIEW_GATE_TIER_3` — used in TASK_002, TASK_007, TASK_009 but no card authored yet; suggests an additional G4 deliverable
- `B1_PSS_FOUNDATION` — authored as a phase card in G4

Task 005 successfully exposes a gap in the current corpus: there is no explicit bounds policy document for cross-machine coordination versus relying on general multi-agent bounds. This is precisely what RFC #38 + the elevana-studio orchestration doc address.

Across the 10 tasks, semantic retrieval is highly indexed on retrieving behavioral invariants (PROD_I1–I6) and architectural frames rather than raw files. This establishes that `query_context` must prioritise constraint retrieval for successful agent operation, and the L1S facet ABI design (with EXACT.PROD_IMMUTABLES and FACETS.CONSTRAINTS as first-class fields) is well-aligned to that need.

## Implication for RFC #38

This gold set proves three things about the architecture:
1. **Frame cards are not optional** — 5 of 10 tasks expect a frame card in addition to concept cards. RFC #38's first-class FRAME_CARD type is empirically required.
2. **PROD immutables (I1–I6) are the most-retrieved category** — supports the standard-tier debate verdict that EXACT.PROD_IMMUTABLES belongs as a structured field, not embedded prose.
3. **Audience-aware projection matters** — TASK_003 (fresh-agent, large budget, all immutables) vs TASK_006 (CIV, small budget, two specific concepts) require very different output shapes from the same underlying card corpus. Standard-tier's AUDIENCE_VIEW_SEEDS schema is empirically justified.

This gold set is **frozen**. Any future change requires re-running G6 retrieval benchmark.
