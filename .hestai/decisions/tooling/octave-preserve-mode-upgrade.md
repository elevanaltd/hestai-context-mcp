---
topic: octave-mcp upgrade
octave_version: "1.15.0"
date: "2026-06-01"
branch: update-octave-dependency
status: active
---

# octave-mcp Upgrade: v1.15.0

octave-mcp has moved 1.13.0 → 1.13.1 → 1.14.0 → 1.15.0 (latest, 2026-05-31). This
project now pins `octave-mcp>=1.15` (test extra). The headline change since v1.13.x is
a **hard break** to `octave_write` `changes`-mode value semantics in v1.15.0, plus
anchored-path and literal-zone fidelity fixes in v1.14.0. `format_style='preserve'`
remains the recommended write mode and must still be passed explicitly (see below).

## v1.15.0 (2026-05-31) — ⚠️ HARD BREAK: `changes`-mode value semantics (GH#487)

STRATEGY_S3 extracted a single `DocumentMutator` layer that now owns all transition
logic and structural AST synthesis; the emitter stays the sole canonicalizer-to-bytes.
The behavioural break only affects callers that pass `changes=` to `octave_write`:

| Pattern | Old behaviour | New behaviour (v1.15.0) |
|---|---|---|
| Bare dict at a `changes` KEY | Implicit MERGE — unmentioned children preserved, new child appended | **FULL REPLACE** — unmentioned children **DROPPED** |
| Bare scalar over a nested BLOCK | Duplicate-keys footgun (block left in place AND flat scalar appended) | **FULL REPLACE in place** — exactly one key emitted |
| `$op:MERGE` of a scalar over a child BLOCK | (silently honoured in places) | **REJECT** with `E_OP_TARGET_MISMATCH` |
| Bare dict with a **nested** dict value | `dict→InlineMap` coercion (re-parsed to `E_NESTED_INLINE_MAP`) | Emits canonical **BLOCK** form; logged `TRANSFORM::INLINE_MAP_TO_BLOCK` |
| `$op:APPEND`/`$op:PREPEND` of nested list/dict element (#488) | Python repr that failed strict re-parse (E005) but reported success | Normalised to re-parseable OCTAVE |

**Migration (one line):** to MERGE into an existing block you **MUST** now send an
explicit `{"$op": "MERGE", "value": {…}}`. A bare dict replaces the whole key. Flat
dicts (all scalar/list values) still emit as a re-parseable inline map — unchanged.

**Read path unchanged:** `octave_validate` still ACCEPTs inline maps and reports
`W_INLINE_ARRAY_ROOT` without mutating source (PROD::I5).

**Project impact:** This project does not currently call `octave_write` with `changes=`
mode in source code (all `.oct.md` authoring goes through full-document
`mcp__octave__octave_write`). The break is guidance for agents/skills doing surgical
key edits — never rely on bare-dict merge; pass `$op:MERGE` explicitly.

## v1.14.0 (2026-05-30) — anchored paths + literal-zone fidelity

- **`ANCHOR/KEY` anchored-path syntax (#460).** Disambiguates duplicate sibling keys
  (e.g. five sibling `RATIONALE` keys) by targeting "the `KEY` assignment following the
  `ANCHOR` key in document order": `changes={"I2/RATIONALE": …}`. Resolution is local to a
  sibling list and never crosses a container boundary. Resolve-literal-first keeps a real
  key containing `/` mutated in place. Indexed `KEY[N]` addressing stays rejected with
  `E_UNRESOLVABLE_PATH`. Anchored paths accept the full `$op` surface with the same
  target-type validation as bare keys.
- **Literal-zone fence form preserved on content edits and `$op MERGE` (#460).** Editing a
  child whose value is a fenced (```` ``` ````) literal zone now re-wraps to preserve the
  fence form (marker + info tag retained, only inner content changed) instead of
  downgrading to a quoted scalar. Content-only edits round-trip **byte-identical** under
  `format_style="preserve"`. Restores PROD::I1 (Syntactic Fidelity).
- **Anchored-path `$op` descriptors are executed, not written as data (#460).** `$op DELETE`
  on an anchored sibling actually removes it (was a silent-success no-op); `$op APPEND`/
  `PREPEND`/`MERGE` apply with loud `E_OP_TARGET_MISMATCH` on type mismatch.
- **Worktree `.venv` dev toolchain (#462).** octave-mcp added a PEP-735
  `[dependency-groups].dev` group so `uv sync` installs the dev toolchain by default. (Their
  repo hygiene; no action for this project — we already use `uv sync --all-extras`.)

### Note on the predicted v1.14.0 default flip

Earlier guidance (from the v1.13.0 notes) predicted v1.14.0 would **flip the default
`format_style` from full canonical re-emit to `preserve`**. That flip does **not** appear in
the published v1.14.0 or v1.15.0 changelogs. Treat the default as **unconfirmed** and
continue to pass `format_style='preserve'` **explicitly** on every `octave_write` call.
`format_style='expanded'` retains full canonical re-emit if deterministic full-normalisation
is ever needed.

## v1.13.1 (2026-05-28) — internal refactor, no behaviour change

Pure internal refactor: `write.py` god-object decomposed into peer modules
(`write_detection`, `write_metrics`, `write_format`, `write_mutation`). Zero behaviour
change, byte-identical output, unchanged `octave_write` API. Retained here for the version
trail.

## `format_style` reference (still current)

| Value | Behaviour |
|---|---|
| `'preserve'` | Span-aware. Clean nodes slice verbatim from baseline bytes; dirty/repaired nodes re-emit canonically. Diff footprint ≤0.5% on single-key edits. **Recommended — pass explicitly.** |
| `'expanded'` | Full canonical re-emit (former default). Use for deterministic full-normalisation. |
| `'compact'` | Collapses atom-only Blocks to inline-map form. Comment-bearing subtrees vetoed with `W_COMPACT_REFUSED`. |
| `null` (explicit) | DeprecationWarning. Avoid. |
| omitted | Silently accepts the package default. Not explicit — prefer passing `'preserve'`. |

## Dependency status & validator-integration assessment

### Current state

octave-mcp is a **test-only** optional dependency:

```toml
[project.optional-dependencies]
test = ["octave-mcp>=1.15"]
```

It is imported only by `tests/unit/governance/test_north_star_upog_compliance.py`
(`octave_mcp.parse_with_warnings`, `octave_mcp.LexerError`) — the strict lexer is the only
reliable detector for North Star UPOG grammar regressions. Runtime source code does **not**
import octave-mcp. The governance modules (`type_checker.py`, `linker.py`, `manifest.py`,
`submit_governance.py`) explicitly document this and defer real OCTAVE validation to a
planned **"Gate B"** (wire the octave-mcp validator over stdio). This is deliberate, anchored
to:

- **North Star §4 SCOPE_BOUNDARIES — IS_NOT** "document format system (octave-mcp owns)".
- **PROD::I6 LEGACY_INDEPENDENCE** (interpreted as scope-boundary discipline per §4).

### What "use the validator and other aspects" would need

octave-mcp ships a rich, importable Python API (verified against the installed 1.15.0):
`Validator`, `ValidationError`, `parse` / `parse_with_warnings`, `tokenize`, `emit`,
`project`, `repair`, `extract_schema_from_document`, `seal_document` / `verify_seal`, plus the
full CST node set (`Document`, `Section`, `Block`, `Assignment`, …). So the validator is
available **in-process as a library**, not only over MCP/stdio. The "Gate B over stdio" plan
predates this and is now only one of two viable integration shapes.

### Runtime OCTAVE usage map (review findings, 2026-06-01)

The system consumes the OCTAVE **format** at runtime in five places, but depends on the
octave-mcp **library** in none of them — it hand-rolls regex extractors. Distinguish "uses
the format" (a notation we read) from "depends on the implementation" (the library). The
table below records which consumers would genuinely benefit from the real parser:

| Runtime consumer | OCTAVE operation | Needs octave-mcp? | Why |
|---|---|---|---|
| `core/north_star_parser.py` | Extract `IMMUTABLES` / `SCOPE_BOUNDARIES` | No | Shallow field extraction on project-controlled docs already canonicalized by `octave_write`. |
| `core/context_steward.py` | Extract phase constraints from workflow docs | No | Same — targeted `KEY::value` / `[…]` pulls, not full AST. |
| `core/phase.py` | Extract `PHASE::` declaration | No | Single line read. |
| `tools/governance/lexer.py` | Token/ID existence lookup across `.oct.md` | No | String/regex search, not parsing. |
| `tools/governance/type_checker.py` → **`submit_governance` (LIVE MCP tool)** | **Validate** operator-submitted OCTAVE (sentinel/TYPE/TOKEN, regex-only) | **YES** | Self-documented as "intentionally dumb by design"; defers real validation to "Gate B → octave-mcp over stdio". |

**Conclusion:** exactly one runtime concern genuinely needs the real parser — **trustworthy
validation of operator-submitted governance content** (`submit_governance` Gate A → Gate B).
The four extraction consumers do not; regex is defensible there because inputs are
project-authored (written through the OCTAVE_WRITE_GATE) and the extractions are shallow.

**Live risk:** `submit_governance` is a registered, shipping MCP tool (`mcp.tool(submit_governance)`
in `server.py`). Its Gate A checker can pass a regex-valid-but-semantically-broken OCTAVE doc
and commit it — the same false-green class the pyproject test comment warns about ("the
bundled regex validator … reports the data-losing legacy form as valid"). No North Star
violation today (Gate A is documented as approximate), but this is the concrete motivation for
scheduling Gate B, and Gate B is the point at which octave-mcp must leave the `test` extra.

### Options (decision deferred — not taken this pass)

1. **Test-only pin bump (DONE this pass).** Keep octave-mcp test-only, pinned `>=1.15`.
   Zero runtime coupling. Preserves §4 / PROD::I6 exactly as written. **Chosen for this
   pass** — promotes nothing without requirements-steward sign-off.
2. **Optional `validation` extra.** Add octave-mcp to a NEW
   `[project.optional-dependencies].validation` group; runtime code imports the validator
   only when the extra is installed (feature-detect / fail-soft when absent). Soft coupling;
   keeps the default install provider-agnostic and §4-clean. Lowest-risk path to a real
   Gate B.
3. **Hard runtime dependency.** Move octave-mcp into `[project].dependencies`. Validator
   always in-process. **Strongest coupling — directly crosses the §4 scope boundary and the
   Gate B plan; requires requirements-steward sign-off** before adoption (per North Star §7
   escalation: immutable / scope-boundary question → requirements_steward).

### Recommendation

Take Option 1 now (done). When Gate B is actually scheduled, prefer **Option 2** (optional
`validation` extra with in-process library import and fail-soft) over the original
stdio-subprocess sketch: same capability, no subprocess management, and it keeps the default
install free of octave-mcp so PROD::I6 independence holds for anyone not opting into
validation. Option 3 should not be adopted without an explicit requirements-steward decision
recorded against §4. The dependency *declaration* (Options 1–3) is orthogonal to the
integration *transport* analysed next — decide both.

### Gate B integration shape (transport) — do NOT cargo-cult "over stdio"

`type_checker.py`, `submit_governance.py`, and `governance/__init__.py` all carry the comment
"Gate B (future) will wire the REAL OCTAVE validator to octave-mcp **over stdio**." That phrase
predates the fact that octave-mcp ships a clean importable library API, and as written it means
*this MCP server spawning the octave-mcp MCP server as a subprocess and speaking JSON-RPC to it*
— one MCP server calling another. For a pure, deterministic, CPU-bound `text → result`
validation function that is the **worst option**, and it should not be carried forward
unexamined. Three shapes, ranked:

1. **Client-side composition (PREFERRED default).** Neither server calls the other. The host/
   agent already has both `mcp__octave__*` and `mcp__hestai-context__*` connected, so the
   orchestrator calls `octave_validate` first and `submit_governance` only on a clean result.
   Zero new coupling in this repo; §4-purest (octave-mcp owns validation, this server owns
   placement/commit). Trade-off: not a self-guarding commit boundary — a caller can skip the
   validate step.
2. **In-process library import behind a port (use IF the commit boundary must self-guard).**
   `submit_governance` calls `octave_mcp.Validator` / `parse_with_warnings` in-process for
   defense-in-depth, via a thin internal `OctaveValidator` protocol (mirroring the existing
   `ports/ai_client.py` adapter seam) so the rest of the code never imports `octave_mcp`
   directly. Pairs with Option 2's optional `validation` extra + fail-soft. One process, one
   failure domain, typed returns, trivially testable.
3. **stdio server-to-server subprocess (REJECT).** Worst of both worlds: octave-mcp must still
   be installed to be spawned (so the dependency is NOT avoided), *plus* you take on subprocess
   lifecycle, stdio framing, JSON-RPC handshake, timeouts/hangs, and zombie cleanup — while
   gaining none of MCP's actual value (capability discovery, host-mediated consent/auth), which
   only applies at a host↔server boundary, not server↔server. More cost, more failure surface,
   harder tests, for a plain function call.

**Decision rule:** validation as a caller-orchestrated pre-step → Shape 1; validation as an
enforced invariant of the commit boundary → Shape 2 (+ optional extra, behind a port); never
Shape 3. When Gate B is scheduled, update the three `over stdio` code comments to match the
chosen shape.

## Impact on RD18 — Multi-envelope workaround (still active)

**Token**: `HO-OCTAVE-WRITE-MULTI-ENVELOPE-WORKAROUND-20260513`

The RD18 workaround (direct `Write` tool for FRAME_CARD / CONCEPT_CARD authoring) was needed
because `octave_write` collapsed multi-envelope content to META-only via
`TN_RECONCILE_CANONICAL` (octave-mcp #420). Neither the v1.14.0 nor v1.15.0 changelog
mentions #420 as resolved, so **the workaround remains active**. v1.14.0's literal-zone fence
preservation and v1.15.0's DocumentMutator extraction are adjacent improvements but do not
claim to fix #420.

**Current status**: Still pending. Re-test procedure when ready:

1. Author a FRAME_CARD or CONCEPT_CARD with multiple envelopes using
   `octave_write(format_style='preserve')`.
2. Verify all envelopes survive (not collapsed to META-only).
3. If confirmed fixed: `VOID` the RD18 token and remove the direct-write exception from
   CLAUDE.md.

**References**: octave-mcp #420, #460, #487, #488;
`.hestai/decisions/handoff/2026-05-16-rfc-40-mac-b1-carry-forward.md` (RD18 candidate).
