# L1S Facet Card Corpus — hestai-context-mcp

This directory holds the L1S facet cards for the `hestai-context-mcp` repository per ADR-RFC-ARCH-005 §1.4. Each `.oct.md` file is a single OCTAVE-envelope facet card conforming to the §1.1–§1.8 schema (Concept / Frame / Cluster / Phase kinds; §1.2 envelope; §1.3 ID rules; §1.6 single-envelope-per-file).

## G4 PASS_CRITERION achievement (ADR-RFC-ARCH-005 §4 G4)

**Status: PASS.** ADR-005 §4 G4 requires ≥5 cards across ≥3 of the four kinds. This PR lands **8 new cards across all 4 kinds**:

| Kind | Count | Cards |
|---|---|---|
| Concept | 5 | ENGAGEMENT_UMBRELLA, PROD_MIGRATION_IMMUTABILITY, GHL_RECONCILER, PORTAL_COMMUNICATION, VIDEO_STATUS_CANONICAL_MODEL |
| Frame | 1 | THREE_LAYER_MEDIA_ARCHITECTURE_FRAME |
| Cluster | 1 | FOUNDATIONAL |
| Phase | 1 | PHASE_B1_FOUNDATION_DEFINITION |

Combined with the pre-existing cards on main (CONTEXT_RETRIEVAL_ARCHITECTURE_FRAME, THREE_LAYER_GOVERNANCE_FRAME, ADR_0013, B1_PSS_FOUNDATION, HO_MULTI_MACHINE_COORDINATION_20260429, PROD_I5), the directory now holds 14 facet cards exercising all four kinds plus reserved-prefix variants (`PROD_`, `ADR_`, `PHASE_`).

All cards land with `STATUS::proposed` per the work-order constraint. Ratification flips to `ratified` after G5 validator CLI lands and the CI gate is green.

## Per-card descriptions (new cards in this PR)

- **[ENGAGEMENT_UMBRELLA](./ENGAGEMENT_UMBRELLA.oct.md)** — Concept. Parent data-lifecycle anchor under which sub-projects hang in the elevana-studio client-data model. Clean fit.
- **[PROD_MIGRATION_IMMUTABILITY](./PROD_MIGRATION_IMMUTABILITY.oct.md)** — Concept (PROD_ reserved prefix). Migration-file immutability invariant for the elevana-studio monorepo. Exercises reserved-prefix discipline per §1.3.
- **[GHL_RECONCILER](./GHL_RECONCILER.oct.md)** — Concept (actor). Subsystem boundary that projects portal opportunity state into GHL CRM. **Strain documented** — see strain observations below.
- **[PORTAL_COMMUNICATION](./PORTAL_COMMUNICATION.oct.md)** — Concept (contract surface). Client-facing portal interface contract. **Strain documented** — see strain observations below.
- **[VIDEO_STATUS_CANONICAL_MODEL](./VIDEO_STATUS_CANONICAL_MODEL.oct.md)** — Concept (data model). Enumerated S0..D1 video status lifecycle. Clean fit.
- **[THREE_LAYER_MEDIA_ARCHITECTURE_FRAME](./THREE_LAYER_MEDIA_ARCHITECTURE_FRAME.oct.md)** — Frame. Orientation map for the Mux / Supabase / LucidLink vendor-isolated media pipeline.
- **[FOUNDATIONAL](./FOUNDATIONAL.oct.md)** — Cluster. Curated bundle of foundational governance concepts for elevana-studio onboarding.
- **[PHASE_B1_FOUNDATION_DEFINITION](./PHASE_B1_FOUNDATION_DEFINITION.oct.md)** — Phase. Stable structural definition of the hestai-context-mcp B1 foundation phase (NOT temporal state, per §1.1).

## Strain observations (candidates for future MINOR-bump issues)

### 1. Actor-content strain (GHL_RECONCILER)

The GHL_RECONCILER card encodes actor/behaviour content (polling cadence, idempotence guarantees, retry semantics). The v1 §1.2 envelope has no dedicated section for actor behaviour; this content lands in `===FACETS===.OPERATIONAL_RULES` with `BEHAVIOUR:` prefixes as an authoring convention. The G4 analysis brief §3 anticipated this strain.

**Candidate**: file a MINOR-bump issue against ADR-RFC-ARCH-005 §1.2 proposing a dedicated `===BEHAVIOR===` section (or sub-block within `===FACETS===`) for actor-kind Concept cards. Not blocking v1.

### 2. Contract-surface strain (PORTAL_COMMUNICATION)

The PORTAL_COMMUNICATION card encodes interface-definition content (versioning discipline, directional contract, type-resolution boundary). The v1 §1.2 envelope folds this into `===FACETS===.CONSTRAINTS` and `===FACETS===.OPERATIONAL_RULES` with `CONTRACT:` prefixes — the brief §3 noted this loses strictness compared to a dedicated section. The G4 analysis brief §3 anticipated this strain.

**Candidate**: file a MINOR-bump issue against ADR-RFC-ARCH-005 §1.2 proposing a dedicated `===CONTRACT===` section (or sub-block within `===FACETS===`) for contract-surface Concept cards. Not blocking v1.

### 3. Phase-card substitution (dropped elevana-studio candidate)

The G4 analysis brief §6 candidate #10 was `PHASE_3_PORTAL_AND_IDENTITY_DEFINITION` — an elevana-studio Phase card. The brief §3 flagged this as the deliberate hard case because the elevana-studio DECISIONS corpus encodes phase ACTIVATION as annotation markers (`// ===[active_Phase_3]===`) rather than phase DEFINITION (constraints / gates / success criteria). Fresh authorship of a phase definition from activation markers would require governance work that belongs in elevana-studio's own decision process, not in a G4 corpus PR.

**Substitution**: this PR ships `PHASE_B1_FOUNDATION_DEFINITION` (local to hestai-context-mcp) instead. The local phase has a clean phase-as-definition shape because PROJECT-CONTEXT.oct.md and ADR-0013 already encode the structural invariants (PROD I1/I3/I4/I5/I6, the four MCP tools, the PSS storage substrate, the success criteria). This satisfies the Phase-kind coverage requirement of G4 without forcing the schema to absorb activation-marker semantics.

### 4. Routing deviation: octave-secretary not callable from this dispatch

The G4 brief §7 specifies the IL+octave-secretary handoff: IL drafts prose, octave-secretary compiles to canonical OCTAVE, IL ratifies. In the actual dispatch session, no `Task` (or oa-router) tool was exposed to this IL execution context, so octave-secretary could not be invoked recursively.

The OCTAVE write-gate (CLAUDE.md `===OCTAVE_WRITE_GATE===`) names `mcp__octave__octave_write` as the required write mechanism for `.oct.md` files. Attempted use of that tool against the §1.2 envelope shape produced the documented octave-mcp #420 single-envelope truncation (the tool kept only the first `===META===…===END===` block and discarded all subsequent top-level blocks).

**Workaround used**: cards in this PR were written using the `Write` tool, mirroring the on-disk shape of the existing ratified `CONTEXT_RETRIEVAL_ARCHITECTURE_FRAME.oct.md` (which has the same multi-block §1.2 envelope shape). ADR-RFC-ARCH-005 §1.6 explicitly anticipates this workaround as in force until octave-mcp #420 fixes. Per the work-order's "ADR wins" tiebreak rule, the ADR's envelope shape is the binding target; the write mechanism is the routing detail.

**Candidate**: file an issue against octave-mcp #420 (or follow up if already filed) so that future facet-card authoring can use `mcp__octave__octave_write` directly per the OCTAVE_WRITE_GATE.

### 5. Edge-typology strain (carried forward from brief §5)

The brief §5 documented two real edge gaps surfaced by the elevana-studio corpus:
- `DEPENDS_ON` / `CONSUMES` — directed dependency (e.g. GHL_RECONCILER consumes from PORTAL_COMMUNICATION; the v1 `CONSTRAINS` edge runs in the wrong direction; `RELATED` loses direction).
- `OWNS` / `HAS_PART` — directed composition (e.g. ENGAGEMENT_UMBRELLA owns sub-projects; without it, parent-child topology degrades to undifferentiated parity).

Authoring this corpus did not surface a third edge gap. The two cards (GHL_RECONCILER, PORTAL_COMMUNICATION) currently use `CONSTRAINS` in a slightly contorted direction; in a future MINOR bump with `DEPENDS_ON` / `OWNS` edges available, those `CONSTRAINS` entries should be re-evaluated.

**Candidate**: file a MINOR-bump issue against ADR-RFC-ARCH-005 §1.5 proposing the two edge classes per the brief §5 recommendation. Not blocking v1.

## Dropped candidates from brief §6

- **`LIFECYCLE_LAYERING`** (brief §6 candidate #6, Frame) — dropped. Redundant with `THREE_LAYER_MEDIA_ARCHITECTURE_FRAME` for the G4 stress test. Both are vendor-isolation frames; one Frame card is sufficient to exercise the kind. Authoring left for a follow-up PR if elevana-studio surfaces a distinct retrieval-time need.
- **`PORTAL_IDENTITY`** (brief §6 candidate #9, Cluster) — dropped. Redundant with `FOUNDATIONAL` for the G4 stress test. Both are NAV-bundle-derived Clusters; one Cluster card is sufficient to exercise the kind. Authoring left for a follow-up PR.
- **`PHASE_3_PORTAL_AND_IDENTITY_DEFINITION`** (brief §6 candidate #10, Phase) — dropped, substituted with `PHASE_B1_FOUNDATION_DEFINITION` per strain observation #3 above.

## Authoring discipline notes

- All cards land with `STATUS::proposed` per the work-order. G5 validator ratification flips status to `ratified` in a future PR.
- All `===EDGES===` references are local CARD_IDs (or empty `[]`); cross-repo provenance is quarantined to `===SOURCE_REFS===` using `repo:<repo-id>:<path>#<token>` form per ADR-RFC-ARCH-002 §1.4.1.
- Reserved prefixes used: `PROD_` (PROD_MIGRATION_IMMUTABILITY — product invariant) and `PHASE_` (PHASE_B1_FOUNDATION_DEFINITION — phase definition). Both match §1.3 semantic requirements.
- One envelope per file (§1.6). Optional sections (`===SOURCE_REFS===`, `===AUDIENCE_VIEW_SEEDS===`) are sub-sections within the single envelope, not parallel envelopes.

## References

- ADR-RFC-ARCH-005 §1.1–§1.8 (envelope schema, ID rules, placement, edges, lifecycle): `/.hestai/decisions/rfc-arch/ADR-RFC-ARCH-005-facet-abi-and-retrieval.md`
- G4 analysis brief: `/.hestai/state/orchestration/2026-05-20-g4-analysis-brief.md`
- Existing ratified Frame card (envelope-shape reference): `./CONTEXT_RETRIEVAL_ARCHITECTURE_FRAME.oct.md`
