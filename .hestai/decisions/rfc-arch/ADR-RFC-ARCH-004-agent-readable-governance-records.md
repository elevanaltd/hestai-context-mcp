# ADR-RFC-ARCH-004 — Agent-Readable Governance Records (AGR) — Format, Lifecycle, Tool Contracts

- **Status**: RATIFIED — 2026-06-11 (SR + CIV stamped close-out; see §13). **Schema v1.1** — MINOR-additive amendment transcribing HO-AGR-BYTECODE-FORMAT-TWO-BIRDS-20260620 (#101, RATIFIED): §1.2 `DECISION`/`BECAUSE` bytecode density (≤40 words, no newline), §1.5 v1.1 semantics, §4.1 #13 value-level guard, `HUMAN_ADR_REF` greppable-TOKEN form. No structural parser change; v1.0 records remain valid. **Schema v1.2** — MINOR-additive amendment transcribing HO-GOVERNANCE-AMEND-IN-PLACE-20260926 (2026-09-26, operator-ruled): §1.2 optional `REVISION` field (one line per in-place amendment; never bumps `VERSION`), §1.6 in-place-amendment reading of the `AMENDS` edge, §0.2 intro reworded from "immutable in PR-D scope and not re-debated" to "fixed inputs for PR-D scope; amendable later only via proper governance" (no live clause claims permanent immutability). No structural parser change; v1.0/v1.1 records remain valid. **Schema v1.3** — MINOR-additive amendment transcribing issue #203 (operator ruling, 2026-10-15, approved in the HC control room and confirmed first-party in the `read-topic-records` session): topic records. §1.2 optional `TOPIC` field; §1.7 optional `CURRENT` and `RULINGS` blocks (one long-running record per topic; in-force one-line rules plus each ruling's verbatim operator words) and the new §4.1 #14 and #15 Gate A invariants; §3.2/§3.3 read additions (`lookup_decision` `current_state`, `list_decisions` `topic` filter). §3.5 delivery of rulings via `append_ruling` is PLANNED (slice S2 of #203), not shipped by v1.3. v1.0–v1.2 records remain valid. **Schema v1.4** — MINOR-additive amendment transcribing HO-TOPIC-RECORDS-YAML-SYNTAX-20261029 (operator ruling, 2026-10-29) and EPIC4-RECORDS-YAML-BATCH-MERGE-AUTHORITY-20261025 (operator ruling, 2026-10-25): dual-syntax readers. §1.1 a record is OCTAVE (`<token>.oct.md`) or quoted-YAML (`<token>.md`), read strictly; §1.6 and §3.4 supersession edges derived at read time from YAML `supersedes:`, with fork reporting; §1.7 the YAML form of `CURRENT` / `RULINGS`. Reader side only: the YAML write path (`submit_governance` content mode, Gate A YAML branch) was NOT shipped by v1.4; v1.5 ships it. Gate A was unchanged in v1.4. v1.0–v1.3 records remain valid and are not migrated. **Schema v1.5** — MINOR-additive amendment transcribing EPIC4-RECORDS-YAML-BATCH-MERGE-AUTHORITY-20261025 and HO-TOPIC-RECORDS-YAML-SYNTAX-20261029 (EPIC4 PR-5): the quoted-YAML write path. §1.1 `submit_governance` content mode accepts a quoted-YAML record and writes `.hestai/decisions/<token>.md` canonically (front matter canonicalised, markdown body verbatim); prose mode still emits OCTAVE; §4.1 Gate A gains a YAML branch with TOKEN uniqueness across `.oct.md` and `.md`; Gate B is not applied to YAML. No required field is added and no existing record changes meaning. **Schema v1.6** — MINOR-additive amendment transcribing the HC ruling on hestai-context-mcp#224 under HO-HC-WEEKEND-DELEGATION-20261031 (issue #224): the OCTAVE reader learns multi-line list fields. §1.1 a list field may be wrapped over several lines (`KEY::[` … `]`) and is read as the compact `[A,B]` form, edge fields included; an unterminated list makes the record unparseable (`unterminated_list`, `text_after_list`); §1.6 and §3.4 a bracketed `SUPERSEDED_BY` is read by item, and several distinct items are a read-time fork of a record that did not arrive through Gate A; §4.1 Gate A errors on an unterminated list, rejects more than one distinct `SUPERSEDED_BY` item, and warns on a multi-line edge field. Single-line lists read exactly as before. No required field is added and no existing record changes meaning. **Schema v1.7** — MINOR-additive amendment transcribing issue #203 slice S2 (HO-TOPIC-RECORDS-AND-APPEND-RULING-20261015; HO-TOPIC-RECORDS-YAML-SYNTAX-20261029): §3.5 `submit_governance` `append_ruling` delivered for quoted-YAML topic records. It reads the record at the `origin/main` OID, checks `expected_record_hash` against the §1.1 whole-file hash, re-emits through the canonical emitter, refuses with structured errors, and opens one PR. In-flight append (S3) and the merge-time recheck (S4) are not shipped. No field is added and no existing record changes meaning. **Schema v1.8** — MINOR-additive amendment transcribing HO-AGR-PLAIN-WORDS-REASONING-20261031 (operator ruling, 2026-10-31; amends HO-AGR-BYTECODE-FORMAT-TWO-BIRDS-20260620): §1.2 and §1.5 `DECISION` and `BECAUSE` carry relations in plain words, never arrows or symbols, replacing the compressed-OCTAVE operator recommendation; the flat-string, ≤40-word, no-newline limits and §4.1 #13 are unchanged. Gate A does not machine-reject glyphs: the rule is authoring guidance, and existing records are not rewritten. Ordered after the v1.7 append_ruling amendment (hestai-context-mcp #234, record HO-AGR-ADR-004-V1-7-APPEND-RULING-20261031).
- **Ratified-by**: standards-reviewer + critical-implementation-validator (stamped close-out 2026-06-11), HO-orchestrated, operator-authorised
- **Date**: 2026-05-19
- **Scope**: `hestai-context-mcp` repository. Specifies the L1 AGR record format and consumer-side MCP tool contracts. Specification only; code implementation is deferred to a successor PR (PR-D′ / PR-H) routed via oa-router to implementation-lead.
- **Sequence**: PR-D in the RFC-arch series. Subordinate to ADR-RFC-ARCH-002 (PR-B IA Contract §1.5 routing rules, §3 governance-class TYPE registry) and ADR-RFC-ARCH-001 (PR-α placement invariant). Adjacent to ADR-RFC-ARCH-003 (PR-E ledger schema, ephemerality preserved).
- **Related**: RFC #40 (Agent-Readable Governance Records — operator-ratified direction, 2026-05-13); RFC #38 (Facet ABI, peer projection layer); ADR-0013 (PSS substrate ruling); Mac B#1 carry-forward `.hestai/decisions/handoff/2026-05-16-rfc-40-mac-b1-carry-forward.md` (RD15 / RD17 / RD18 promotion candidates).
- **Reconciles**: Issue #25 (Decision Journal Light — SUPERSEDED-BY this ADR on direction; see §7).
- **Authority**: HOLISTIC_ORCHESTRATOR drafting; RFC #40 operator-ratification 2026-05-13; convergent L0–L5 architecture (debate-hall 2026-05-16, carried forward via PR-B).
- **Invariants invoked**: PROD::I1 (SESSION_LIFECYCLE_INTEGRITY), PROD::I3 (PROVIDER_AGNOSTIC_CONTEXT), PROD::I4 (STRUCTURED_RETURN_SHAPES), PROD::I5 (READ_ONLY_CONTEXT_QUERY), PROD::I6 (LEGACY_INDEPENDENCE applied as opt-in adoption discipline), SYS::I1 (CONTEXT_INTEGRITY), SYS::I6 (scope boundary discipline).
- **Implementation owners (deferred)**: PR-D′ / PR-H — implementation-lead via oa-router. D1–D6 preflight gates (§9) are binding preconditions for code authorisation.

## 0. Reading guide

This ADR contains four governance artefacts in one document:

- **§1 — Schema v1** defines the record format, OCTAVE or quoted-YAML (fields, types, lifecycle, supersession DAG semantics).
- **§2 — Placement, layer mapping, and projection rules** locate AGRs in the L0–L5 topology and rule on derived projections.
- **§3 — MCP tool contracts** specify three read tools and one optional write broker, all PROD::I4-conformant and PROD::I5-conformant where applicable.
- **§4 — Validator CLI** specifies the invariants the validator enforces.

§§5–10 close the invariant chain, verify the ADR itself, reconcile issue #25, name out-of-scope items, list preflight gates, and enumerate operator-direction open questions.

### 0.1 Defense-in-depth note

The AGR layer composes with PR-B's defenses: AGR files inherit governance-class TYPE registration (PR-B §3.2.2) via `META.TYPE::DECISION_RECORD`, so any future fail-fast tool (PR-F) automatically rejects governance-class writes to non-authoritative paths. The CI gate (PR-G) treats `.hestai/decisions/**` as the only authoritative AGR root.

### 0.2 Immutable operator-ratified inputs

The following are fixed inputs for PR-D scope; amendable later only via proper governance:

1. **RFC #40's three-layer model**: L0 human ADRs (unchanged), L1 AGRs (this ADR), L1S Facet ABI (RFC #38 / PR-B). Operator-ratified 2026-05-13.
2. **Substrate-not-registry binding** (ADR-0013): the AGR canonical store is plain committed files at `.hestai/decisions/`; PSS is substrate, never the registry. Any write tool is a broker that creates a PR; no tool mutates the canonical store directly.
3. **Schema-superset commitment** (RFC #40): the v1 schema MUST be a syntactic superset of elevana-studio's existing HO-token convention so legacy records validate verbatim.
4. **Opt-in adoption**: consumer repos adopt voluntarily; non-adopters remain fully supported indefinitely.

## 1. Schema v1

### 1.1 File layout

An AGR record is a single document, OCTAVE or (v1.4) quoted-YAML, committed at:

```
.hestai/decisions/<token>.oct.md
```

for an OCTAVE record, or at `.hestai/decisions/<token>.md` for a quoted-YAML record (below), where `<token>` is the record's `TOKEN` value (see §1.2). Sub-grouping under `.hestai/decisions/<group>/<token>.oct.md` (or `<token>.md`) is admissible when a coherent group exists (e.g. `.hestai/decisions/rfc-arch/HO-ARCH-…`); the validator MUST treat both layouts as equivalent and resolve `<token>` to whichever path holds it. In v1.4 this applies to the read tools; Gate A still validates `.oct.md` only, and YAML validation is deferred to EPIC4 PR-5.

OCTAVE envelope (canonical form is **bare** `TOKEN`):

```
===DECISION_RECORD===
META:
  TYPE::DECISION_RECORD
  VERSION::"1.0"
  TOKEN::<TOKEN>
  AUTHORED_AT::"<ISO-8601-UTC>"
…
===END===
```

The opening sentinel `===DECISION_RECORD===` and closing `===END===` are required; they signal governance-class to PR-B §3.2.2.

**Canonical TOKEN form (AGR canonical-form convergence)**: `TOKEN` is written **bare** — `TOKEN::<TOKEN>`, not `TOKEN::"<TOKEN>"`. This reconciles §1.1 with §1.6, where the `AMENDS` / `EXTENDS` (and `SUPERSEDED_BY`) edge references are bare TOKENs; a record's own `TOKEN` declaration and the TOKENs it cites in its lineage edges therefore share one canonical form. Gate A readers are **quote-optional**: the legacy quoted form `TOKEN::"<TOKEN>"` continues to validate verbatim (preserving the §0.2 schema-superset commitment over elevana-studio's existing HO-token convention), but bare is canonical for new records. The §1.3 TOKEN-format regex constrains the value identically in either form — quote-optionality does not relax §1.3.

**OCTAVE list fields (v1.6)**: a list-valued field may be written on one line (`KEY::[A,B]`) or wrapped over several. A wrapped list opens with a line whose value is exactly `[` (`KEY::[`), has one item per line (a trailing comma is allowed; blank lines and `//` comment lines inside the list are ignored), and closes with `]` on its own line. Quotes protect commas and `]` inside an item. The reader returns a wrapped list as the compact single-line form `[A,B]`, so a wrapped list and the same list written compactly read identically; a list written on one line is returned exactly as written, as before. A value that opens `[` without being exactly `[` keeps the one-line reading. One grammar serves every list field, the edge fields (`SUPERSEDES`, `SUPERSEDED_BY`, `AMENDS`, `EXTENDS`) included. A wrapped list that is never closed makes the record unparseable (construct `unterminated_list`), as does text after the closing `]` (`text_after_list`); the existing `RECORD_PARSE_FAILED` envelope reports the line where the list opens and the construct, so no new error code is added. **Deploy note**: the interim rule "edge fields stay on one line" remains in force until the operator restarts the MCP server, because the running server keeps the previous reader; the HC control room retires the rule after the restart is confirmed.

**Quoted-YAML form (v1.4)**: a YAML record is `<token>.md` whose first line is `---`. The fields sit between that fence and the closing `---`; the markdown body after it is never read as record content.

```
---
type: "DECISION_RECORD"
version: "1.4"
token: "<TOKEN>"
status: "RATIFIED"
tier: "STRATEGIC"
authored_at: "<ISO-8601-UTC>"
decision: "<…>"
because: "<…>"
---
```

- Keys are lowercase on disk (`[a-z][a-z0-9_]*`) and map to the uppercase §1.2 fields (`authored_at` is `AUTHORED_AT`). The §1.2 required set is unchanged.
- Every scalar is one line and double-quoted. The only structure besides `key: "value"` is the §1.7 blocks.
- The escape set is exactly `\\`, `\"`, `\n`, `\r`, `\t` and `\uXXXX`, in canonical form only: `\u` is used solely for a control character with no short escape (U+0000–U+001F, U+007F), with four lowercase hex digits. Surrogate escapes are invalid, and every other character, non-BMP included, is written literally. A literal control character (C0 or DEL, a TAB included) inside a quoted value is invalid; a TAB must be written `\t`. The reader accepts only the canonical escape spellings the scalar encoder emits.
- The scoping signal is a `type:` line naming `DECISION_RECORD` inside the fences, the analogue of `META.TYPE`. Quoted, unquoted or single-quoted all make the file a candidate record, and only the double-quoted form then parses: an unquoted or single-quoted `type:` is loudly rejected (`unquoted_value`), never silently out of scope. The test also accepts text after the value (a comment or trailing garbage) and a leading UTF-8 BOM (rejected at line 1 as `invalid_key`), and a `<token>.md` whose `token:` scalar cannot be read is still found by its filename and reported. A `.md` file without such a line stays invisible, so READMEs and other markdown are never misread.
- **Strict and loud rejection**: a record outside this subset is never half-read and never silently skipped. Rejected constructs include an unquoted value, a block or multi-line scalar, a flow collection, an anchor, alias or tag, a comment, a sequence item, indentation, a duplicate key, any other escape spelling, and a missing closing fence. `lookup_decision` returns `RECORD_PARSE_FAILED` (§3.2) with `context.path`, `context.parse_error`, `context.line` (1-based) and `context.construct` (a stable name such as `unquoted_value`, `bad_escape`, `noncanonical_escape`, `duplicate_key`, `missing_closing_fence`). `list_decisions` reports the same `line` and `construct` on the record's `skipped` entry (§3.3). A well-formed record that lacks a §1.2 required field is reported the same way, without `line` and `construct`.
- A TOKEN resolves to `<token>.oct.md` first, then `<token>.md`, then by embedded TOKEN. The deterministic TOKEN lookup (§1.6) sees `<token>.md` as well as `<token>.oct.md`: a YAML record declares its TOKEN by its fenced `token:` line, whether or not the whole record parses. Block lines and the markdown body never declare a TOKEN.
- **Extension/syntax pairing is strict**: `<token>.oct.md` is read only as OCTAVE and `<token>.md` only as YAML. A file whose content does not match its extension is not a record: it is not resolved, listed, indexed or declared as a TOKEN.
- **Write path (v1.5)**: `submit_governance` content mode accepts a quoted-YAML record, recognised by a first line of exactly `---`, and writes it to `.hestai/decisions/<token>.md`. Gate A's YAML branch judges it (§4.1); Gate B, the OCTAVE validator, is not applied to YAML. Prose mode still emits OCTAVE only.
- **The write canonicalises**: the front matter is parsed, gated by a round trip (every decoded value of the re-emitted bytes must equal the submitted one, otherwise `round_trip_mismatch`), and re-emitted canonically (fixed key order, LF line endings, canonical scalars and block indentation). The markdown body after the closing fence is kept VERBATIM. The file bytes written are exactly the canonical bytes, and canonical emission is idempotent: re-emitting a written record yields the same bytes. A hash over the whole file bytes (the §3.5 `expected_record_hash`) therefore covers the body as well as the front matter. A record hand-authored before v1.5 is hashed as its bytes; it becomes canonical only when a canonicalising write rewrites it, which content mode does not do (it writes new records only); `append_ruling` (v1.7, §3.5) now rewrites an existing YAML topic record through the same canonicalising write. After the write the linker re-reads the file and fails the write if the reader would reject it.

**Revision**: 2026-10-29: §1.1 widened from OCTAVE-only to dual syntax and the quoted-YAML form, escape set, strict rejection and candidate detection and extension/syntax pairing recorded (HO-TOPIC-RECORDS-YAML-SYNTAX-20261029; EPIC4-RECORDS-YAML-BATCH-MERGE-AUTHORITY-20261025). 2026-10-31: the quoted-YAML write path (content mode), its canonical-write contract and the Gate B exemption recorded (EPIC4-RECORDS-YAML-BATCH-MERGE-AUTHORITY-20261025; HO-TOPIC-RECORDS-YAML-SYNTAX-20261029). 2026-10-31: multi-line OCTAVE list fields and the deploy note recorded (HC ruling on hestai-context-mcp#224 under HO-HC-WEEKEND-DELEGATION-20261031).

### 1.2 Fields

#### Required (every record, every lifecycle state)

| Field | Type | Notes |
|---|---|---|
| `TYPE` | literal | MUST be `DECISION_RECORD` |
| `VERSION` | semver-2-segment | `MAJOR.MINOR` per §1.5. Current: `1.8` (records authored before the v1.1/v1.2/v1.3/v1.4/v1.5/v1.6/v1.7/v1.8 amendments remain valid at `1.0`; v1.1, v1.2, v1.3, v1.4, v1.5, v1.6, v1.7 and v1.8 are all MINOR-additive — see §1.5). |
| `TOKEN` | string | Globally unique identifier within the repository (see §1.3) |
| `STATUS` | enum | One of `PROPOSED`, `RATIFIED`, `SUPERSEDED`, `VOID` (see §1.4) |
| `TIER` | enum | One of `STRATEGIC`, `TACTICAL`, `OPERATIONAL`. Semantic gravity per the cited research brief. |
| `DECISION` | string | One-sentence statement of what is binding. Mandatory even on `PROPOSED`. **v1.1 flat-line form**: a single double-quoted flat line. §4.1 #13 **machine-enforces** AT MOST 40 words and NO embedded newline (per HO-AGR-BYTECODE-FORMAT-TWO-BIRDS-20260620). **v1.8 plain words** (per HO-AGR-PLAIN-WORDS-REASONING-20261031): write relations in plain words, never arrows or symbols; this is authoring guidance, not machine-checked. Nested custom keys are excluded by the flat-string grammar (the structural parse), not by #13. |
| `BECAUSE` | string | One-sentence rationale. Mandatory even on `PROPOSED`. **v1.1 flat-line form**: same as `DECISION` — §4.1 #13 machine-enforces ≤40 words + no-newline; the plain-words rule (relations in words, never arrows or symbols) is authoring guidance (v1.8), not enforced. |
| `AUTHORED_AT` | ISO-8601 timestamp | UTC. Set once at record creation; never edited. |

#### Optional (any record, any lifecycle state)

| Field | Type | Notes |
|---|---|---|
| `ISSUE_REF` | string | GitHub issue URL or `repo:<repo-id>#<n>` shorthand. Optional on `PROPOSED`/`RATIFIED`; recommended on `SUPERSEDED`/`VOID` if origin is on issue tracker. |
| `HUMAN_ADR_REF` | string | Reference to a human ADR. Optional; records without a human ADR are first-class. **v1.0**: a repository-relative path (resolved by §4.1 #11). **v1.1**: a greppable cross-repo-survivable TOKEN is the canonical form (per HO-AGR-BYTECODE-FORMAT-TWO-BIRDS-20260620 `ADR_REF_FORM::greppable_TOKEN`); a path remains accepted for back-compat and is path-resolved under §4.1 #11 only when it is path-shaped. |
| `SUPERSEDED_BY` | string | TOKEN of the superseding record (a one-item bracketed list is read the same). Required iff `STATUS == SUPERSEDED`. |
| `EXTENDS` | list of TOKENs | Records this record extends (additive, not replacing). May be empty. |
| `AMENDS` | list of TOKENs | Records this record amends (partial replacement; or, under in-place amendment practice — see §1.6 — full in-place edit of the cited artefact by a thin ruling record). May be empty. |
| `REVISION` | string | One line per in-place amendment: `<YYYY-MM-DD>: <what changed>`. Optional; never changes schema `VERSION` (§1.5) — logs a record's own in-place edits instead of a version bump. Introduced in schema v1.2 (HO-GOVERNANCE-AMEND-IN-PLACE-20260926). |
| `TOPIC` | string | Slug naming the topic a record belongs to (e.g. `client-access`). Optional. A record with `TOPIC` MAY carry the `CURRENT`/`RULINGS` blocks (§1.7). `list_decisions(topic=)` filters on it by exact match. Introduced in schema v1.3 (#203). |
| `SCOPE` | string or list | Free-form scope qualifier (e.g. `"hestai-context-mcp"`, `["L1", "AGR"]`). Optional. |
| `EFFECTIVE_FROM` | ISO-8601 timestamp | When the decision takes effect; defaults to `AUTHORED_AT` if absent. |
| `EFFECTIVE_UNTIL` | ISO-8601 timestamp | When the decision lapses (independent of supersession). Optional. |
| `ORIGIN_SESSION` | string | UUID of the session in which the decision was ratified, when known. Citations to control-room ledger SESSION_IDs land here. |
| `ORIGIN_LEDGER_RD` | string | `RD<n>` identifier from the originating ledger, when known. Used by PR-E §2.5 promotion-by-citation pattern. |
| `RATIFIED_BY` | string | Identity of the human or agent that ratified the record (e.g. `human:shaun.buswell@elevana.com`, `agent:HOLISTIC_ORCHESTRATOR`). Optional on `PROPOSED`. The validator (§4.1) emits a **warning** when `STATUS != PROPOSED` and `RATIFIED_BY` is absent. Recommended but not required for non-`PROPOSED` records (operator may close the loophole in a MINOR bump if TOKEN-squatting becomes a real problem; see §11 Q5). |
| `RATIFIED_AT` | ISO-8601 timestamp | When the record entered its current non-`PROPOSED` STATUS. Optional. Independent of `AUTHORED_AT` (records may be authored as `PROPOSED` and ratified later). |

#### Reserved (not yet defined; MUST NOT appear in v1.x records)

`DEPENDS_ON`, `CONFLICTS_WITH`, `ARCHIVED_AT`. These names are reserved against future MINOR additions; v1.x validators MUST reject records carrying them.

**Revision**: 2026-10-31: `SUPERSEDED_BY` type notes that a one-item bracketed list is read the same (HC ruling on hestai-context-mcp#229 under HO-HC-WEEKEND-DELEGATION-20261031). 2026-10-31: `DECISION` and `BECAUSE` rows replace the compressed-OCTAVE operator recommendation with the plain-words rule (HO-AGR-PLAIN-WORDS-REASONING-20261031).

### 1.3 TOKEN format

`TOKEN` MUST match the regular expression:

```
^[A-Z][A-Z0-9_-]{1,126}[A-Z0-9_]-[0-9]{8}$
```

Three semantic parts, joined by `-`:

1. Prefix: uppercase letters, digits, underscores, and internal hyphens (hyphens are admissible as word-separators, e.g. `HO-DECISION-GOVERNANCE`); 3–128 chars total before the trailing date separator; MUST start with an uppercase letter and MUST NOT end with a hyphen (so the trailing `-` before the date is unambiguous). Examples: `HO-CONTEXT-MCP-OWNS-AGR-STANDARD`, `HO-OCTAVE-WRITE-MULTI-ENVELOPE-WORKAROUND`.
2. Hyphen separator.
3. Date suffix: `YYYYMMDD` (UTC). MUST equal the UTC date portion of `AUTHORED_AT` — the validator (§4.1) enforces this consistency.

This regex is a syntactic superset of elevana-studio's existing HO-token convention (e.g. `HO-DECISION-GOVERNANCE-GRAVITY-TIERED-20260428`); legacy tokens validate verbatim, including those whose prefix contains multiple hyphens.

Uniqueness is enforced repo-wide by the validator (§4). A token collision is a hard error.

### 1.4 Lifecycle states and transitions

The `STATUS` enum and its admissible transitions:

```
            ┌──── VOID  (terminal; never returns)
            │
PROPOSED ───┼──── RATIFIED ───┬──── SUPERSEDED  (terminal for this token; chain continues via SUPERSEDED_BY)
            │                 │
            └──── VOID        └──── VOID
```

Rules:

1. A new record starts in `PROPOSED` or `RATIFIED`. Authoring straight to `RATIFIED` is permitted when the operator/HO ratifies in the authoring session.
2. `PROPOSED → RATIFIED` is the standard adoption transition.
3. `RATIFIED → SUPERSEDED` is the standard evolution transition; `SUPERSEDED_BY` MUST point to a record that is itself `PROPOSED` or `RATIFIED` (not `SUPERSEDED` or `VOID`) at the moment of transition. The validator does not re-check this on every read; it checks on write.
4. `PROPOSED → VOID` / `RATIFIED → VOID` / `SUPERSEDED → VOID` are all admissible (e.g. when a decision is retracted entirely). `VOID` records remain on disk for provenance.
5. No transition out of `VOID`. A `VOID` record is dead.
6. The `STATUS` field is mutable in-place per SYS §1 LAW SOURCE_FIDELITY (no versioned copies). Mutation is a normal git commit; history lives in git, not in the record.

### 1.5 Version semantics

`VERSION` is `MAJOR.MINOR`:

- **MAJOR bump** — breaking. Any of: required-field rename, required-field removal, type change, enum value removal, tightening of an existing field's regex. Parsers written against `MAJOR=N` MUST refuse to parse `MAJOR=N+1` records.
- **MINOR bump** — additive. New optional fields, new admissible enum values for non-required fields, new reserved names. Parsers written against `MAJOR=N.MINOR=K` MUST tolerate `MAJOR=N.MINOR>K` by ignoring unknown optional fields.
- No patch level. Spec corrections land at the next MINOR.

Current schema is `1.8`. Future additive extensions become `1.9`, `1.10`, etc.

**v1.1 (MINOR-additive, per HO-AGR-BYTECODE-FORMAT-TWO-BIRDS-20260620 / #101)**: AGRs are treated as LLM "bytecode". The reasoning-bearing fields `DECISION` and `BECAUSE` are constrained to a single flat line of ≤40 words with no embedded newline (new value-level invariant §4.1 #13; no structural parser change). *Amended in place by v1.8 (HO-AGR-PLAIN-WORDS-REASONING-20261031, amending HO-AGR-BYTECODE-FORMAT-TWO-BIRDS-20260620): the original clause recommending compressed-OCTAVE operators for connectives is replaced by the plain-words rule, relations in plain words and never arrows or symbols; the v1.1 density limits are unchanged.* `HUMAN_ADR_REF` gains a greppable-TOKEN canonical form alongside the legacy path form. Both are MINOR-additive: a `1.0` record that already satisfies the ≤40-word/no-newline density (as every conforming one-sentence `DECISION`/`BECAUSE` does) remains valid, and v1.1 introduces no new required field. Parsers written against `1.0` continue to parse `1.1` records (the structural grammar is unchanged).

**v1.2 (MINOR-additive, per HO-GOVERNANCE-AMEND-IN-PLACE-20260926, 2026-09-26)**: ecosystem-wide in-place amendment practice is adopted for governance artefacts. Records gain the optional `REVISION` field (§1.2) — one line per in-place amendment, `<YYYY-MM-DD>: <what changed>` — logged instead of a schema `VERSION` bump; `VERSION` stays the schema-version identifier, never a per-record edit counter. `AMENDS` (§1.6) gains an in-place-amendment reading: a thin ruling record's `AMENDS` edge may mean the ruling amended the cited artefact in place rather than only a partial-replacement stack. Both readings are MINOR-additive: no existing record's structural parse changes, and a `1.0`/`1.1` record without `REVISION` remains fully valid. Parsers written against `1.0`/`1.1` continue to parse `1.2` records by ignoring the unknown optional field.

**v1.3 (MINOR-additive, per issue #203, operator ruling 2026-10-15)**: topic records. The optional `TOPIC` field (§1.2) and the optional top-level `CURRENT` / `RULINGS` blocks (§1.7) are added, with two new value-level Gate A invariants (§4.1 #14, #15). No required field is added, and no existing record's parse changes: a `1.0`–`1.2` record carries none of the new names and remains fully valid, and the core fields (§1.2 required set) parse identically under a `1.2` reader. A `1.2` reader does NOT ignore the blocks: its flat line-anchored parser surfaces every nested assignment (`R2`, `RULE`, `VERBATIM`, …, first match wins) in `fields`, and a nested core key could shadow a core field there. That is why §4.1 #14 forbids core keys inside the blocks, so a `1.2` reader still resolves the core fields correctly. v1.3 readers exclude block lines from `fields`.

**v1.4 (MINOR-additive, per HO-TOPIC-RECORDS-YAML-SYNTAX-20261029 and EPIC4-RECORDS-YAML-BATCH-MERGE-AUTHORITY-20261025, 2026-10-29)**: dual-syntax readers. A record is OCTAVE (`.oct.md`) or quoted-YAML (`.md`, §1.1); the three read tools and the deterministic TOKEN lookup read both. Supersession edges are derived at read time from YAML `supersedes:` (§1.6, §3.4), and topic blocks gain a YAML spelling (§1.7). No required field is added, no OCTAVE record is migrated or changes meaning, and the §1.2 field set is unchanged. Reader side only: the YAML write path (`submit_governance` content mode, Gate A YAML branch) was NOT shipped by v1.4; v1.5 ships it. Gate A was unchanged in v1.4.

**v1.5 (MINOR-additive, per EPIC4-RECORDS-YAML-BATCH-MERGE-AUTHORITY-20261025 and HO-TOPIC-RECORDS-YAML-SYNTAX-20261029, EPIC4 PR-5)**: the quoted-YAML write path. `submit_governance` content mode writes a quoted-YAML record as `.hestai/decisions/<token>.md`, canonicalising the front matter and keeping the markdown body verbatim (§1.1); Gate A gains a YAML branch (§4.1). No required field is added, no existing record changes meaning, and OCTAVE records and prose mode are unchanged.

**v1.6 (MINOR-additive, per the HC ruling on hestai-context-mcp#224 under HO-HC-WEEKEND-DELEGATION-20261031, issue #224)**: multi-line OCTAVE list fields (§1.1). The reader reads a list wrapped over several lines as the compact single-line form, edge fields included; an unterminated list is an unparseable record, and Gate A errors on it and warns on a multi-line edge field (§4.1). A bracketed `SUPERSEDED_BY` is read by item; Gate A rejects more than one distinct item on write, and the reader still reports several distinct items as a fork on read (§1.6, §3.4, §4.1 #8). No required field is added, single-line lists read exactly as before, and no existing record changes meaning.

**v1.7 (MINOR-additive, per HO-TOPIC-RECORDS-AND-APPEND-RULING-20261015 and HO-TOPIC-RECORDS-YAML-SYNTAX-20261029, issue #203 S2)**: `append_ruling` delivered for quoted-YAML topic records (§3.5). It rewrites an existing YAML topic record through the §1.1 canonicalising write, checks an optional `expected_record_hash` against the whole-file hash as a stale-base check, and opens one PR. No field is added and no existing record changes meaning; OCTAVE records are not appended to.

**v1.8 (MINOR-additive, per HO-AGR-PLAIN-WORDS-REASONING-20261031, amending HO-AGR-BYTECODE-FORMAT-TWO-BIRDS-20260620)**: plain-words `DECISION` and `BECAUSE`. Both fields carry relations in plain words, never arrows or symbols; each remains one flat double-quoted string of at most 40 words with no embedded newline, enforced by §4.1 #13. Gate A does NOT machine-reject glyphs (the rule is authoring guidance, as the clause it replaces was), and existing records are not rewritten. No required field is added and no existing record changes meaning.

**Revision**: 2026-10-31: v1.1 operator clause replaced by the plain-words rule and the v1.8 paragraph added (HO-AGR-PLAIN-WORDS-REASONING-20261031; amends HO-AGR-BYTECODE-FORMAT-TWO-BIRDS-20260620).

**Spec-only period (CLOSED)**: Between this ADR's merge and the code landing, AGR records were authored by hand and conformed to §1.1–§1.6 as if the validator (§4) were running. The validator has now landed: Gate A (`type_checker.validate_octave_content`) enforces the §4.1 invariants against every record under `.hestai/decisions/**/*.oct.md`, regardless of authoring date — the **v1.0 envelope PLUS the v1.1 additive §4.1 #13 density invariant** (≤40 words, no embedded newline on `DECISION`/`BECAUSE`). There is no grandfather clause: every record, old or new, MUST satisfy the currently-enforced invariant set (the three pre-existing verbose records were migrated to compliant bytecode when #13 landed).

### 1.6 Supersession DAG semantics

`SUPERSEDED_BY`, `EXTENDS`, and `AMENDS` together form three **edge-typed** directed graphs over TOKENs. Acyclicity is enforced **per edge-type**, not globally — the three edge classes have distinct semantics and a record may legitimately appear in cycles when only the union graph is considered.

- The validator (§4) MUST detect cycles **within each edge-type independently** and reject the offending write:
  - `SUPERSEDED_BY` subgraph MUST be acyclic and MUST form a chain (every `SUPERSEDED` record points at exactly one successor); the chain MUST terminate at a `PROPOSED`, `RATIFIED`, or `VOID` record.
  - `EXTENDS` subgraph MUST be acyclic. Arbitrary DAG shapes within `EXTENDS` are admissible.
  - `AMENDS` subgraph MUST be acyclic. Arbitrary DAG shapes within `AMENDS` are admissible.
- **Cross-edge interactions are NOT treated as cycles.** Specifically: an old record carrying `SUPERSEDED_BY=NEW` combined with the new record carrying `AMENDS=OLD` is **admissible** and is the canonical pattern for "this new record supersedes the old one and explicitly amends what it changed." The validator MUST NOT flag this as a cycle.
- `EXTENDS` does not imply `SUPERSEDED_BY`; an extension is additive — both records remain live (`RATIFIED`).
- `AMENDS` does not by itself supersede; an amendment refines the cited record without retiring it. Combined `AMENDS` + `SUPERSEDED_BY` (as above) is admissible.
- **In-place amendment practice (HO-GOVERNANCE-AMEND-IN-PLACE-20260926, schema v1.2)**: when an amendment is applied in place — the amended record or human ADR is edited directly rather than stacked — the amending thin ruling record's `AMENDS` edge means "this ruling amended that artefact in place"; the ruling record MUST NOT restate the amended content (per HO-GOVERNANCE-AMEND-IN-PLACE-20260926's own `THIN_RULING_RECORD` field). This is a reading of the existing `AMENDS` edge type, not a new edge type: the acyclicity rule above and the admissible `AMENDS` + `SUPERSEDED_BY` combination are unchanged. An artefact with no TOKEN (e.g. a human ADR outside the AGR store, or this ADR itself) cannot be an `AMENDS` target — lineage resolution (§4.1 #8) requires the cited identifier to resolve via the deterministic TOKEN lookup; such amendments are recorded via a free-form pointer field (e.g. `AMENDED_ARTEFACTS`) instead.
- Edges MUST reference TOKENs that exist in the same repository (cross-repo edges are out of scope for §1.6 enforcement; see §4.1 invariant #8 scoping note).
- **Edges derived from YAML `supersedes:` (v1.4)**: a YAML record (§1.1) may carry `supersedes: "<TOKEN>, <TOKEN>"`, a quoted, comma-separated list of TOKENs only. Each entry must match §1.3; an empty entry, a duplicate, the record's own TOKEN or prose rejects the whole record (`invalid_supersedes`). `supersedes_note:` is ignored and never read as an edge. Edges are derived at read time, from the `supersedes:` of YAML records that parse completely and from nothing else; no file is written and the superseded record's own file is never modified. A YAML record derives edges only if its own `status` is `RATIFIED` or `SUPERSEDED`; a `PROPOSED`, `VOID` or any other status derives none. A record named by a derived edge reads as `SUPERSEDED` in `lookup_decision` and `list_decisions`, whatever its file says, except a `VOID` record: it stays `VOID` (VOID outranks SUPERSEDED), and its derived edge still appears in its chain. With a single successor, that successor is surfaced as `SUPERSEDED_BY`. OCTAVE `SUPERSEDED_BY` semantics are unchanged, and either source marks a record `SUPERSEDED`. A YAML successor can therefore retire an OCTAVE predecessor without editing it. Two different successors, from either source, form a **fork**: both are reported, sorted, and neither is picked; the same successor named by both sources is not a fork. A bracketed OCTAVE `SUPERSEDED_BY` (§1.1, v1.6) names its successors by item: one item is an edge, and duplicates of one TOKEN collapse to it. Several DISTINCT items are rejected by Gate A on write (§4.1 #8), so a written record cannot declare a fork; the fork stays a read-time diagnosis of conflicting sources, which the reader still reports for a record that arrived other than through Gate A. A fork is a read-time finding; the `SUPERSEDED_BY` chain rule above is not extended to YAML in v1.4. Legacy OCTAVE prose `SUPERSEDES` produces no edges (a known limit; migrating such records is out of scope).

**Revision**: 2026-10-29: YAML `supersedes:` edges derived at read time, with fork reporting, added to the supersession semantics (HO-TOPIC-RECORDS-YAML-SYNTAX-20261029; EPIC4-RECORDS-YAML-BATCH-MERGE-AUTHORITY-20261025). 2026-10-31: a bracketed `SUPERSEDED_BY` read by item (HC ruling on hestai-context-mcp#224 under HO-HC-WEEKEND-DELEGATION-20261031). 2026-10-31: several distinct items are rejected on write and remain a read-time fork only (HC ruling on hestai-context-mcp#229 under HO-HC-WEEKEND-DELEGATION-20261031).

### 1.7 Topic records — `CURRENT` and `RULINGS` blocks (v1.3)

A **topic record** is one long-running `DECISION_RECORD` per topic. It keeps `TYPE::DECISION_RECORD` (so v1.0–v1.2 readers and Gate A still work), declares `TOPIC::<slug>` in `META`, and may add two top-level blocks after `META`:

```
CURRENT:
  R2::"<one-line rule in force>"
  R3::"<one-line rule in force>"
RULINGS:
  R2:
    RULE::"<same one-line rule>"
    VERBATIM::"<the operator's words, byte-exact>"
    RULED::"<who, when, session/ceremony>"
    REPLACES::R1
```

- `CURRENT` lists the rules currently in force, in order, one `R<n>::"<rule>"` line each. It restates the live `RULE` lines mechanically and is never hand-edited.
- `RULINGS` holds one nested entry per in-force ruling: `RULE`, `VERBATIM`, `RULED`, and optional `REPLACES` (the `R<n>` it replaced).
- A replaced ruling is removed in place and logged with a `REVISION` line (§1.2); git keeps the old text. The record does not grow a history section.
- A block opens only at a header in column 0 and runs until the next non-blank line indented no deeper than the header. A header-shaped line indented deeper is an ordinary line of the enclosing block (or of `META`) and can neither open nor reset a block. Lines inside a block are not `META`: the read parser excludes them from `fields`, so a nested key cannot shadow a `META` field.
- **Key-collision rule (§4.1 #14)**: the read parser keeps the FIRST match of each key, so a top-level reserved key nested inside a block could take over the record. Entries inside `CURRENT` and `RULINGS` MUST NOT use `VERSION`, `TOKEN`, `ID`, `TYPE`, `STATUS`, `TIER`, `DECISION`, `BECAUSE`, `AUTHORED_AT` or `SUPERSEDED_BY` as a key. Gate A also extracts every invariant input from the block-excluded text, so a nested line can never satisfy or override a check.

Delivery of rulings into these blocks through `append_ruling` is **planned (slice S2 of #203) and not shipped by v1.3**; until then topic records are authored through the existing `submit_governance` modes. The blocks are collected by a regex-only helper (North Star §4; no AST, no LLM) and read by the tools in §3.2 and §3.3.

**YAML form (v1.4, HO-TOPIC-RECORDS-YAML-SYNTAX-20261029)**: a quoted-YAML topic record (§1.1) declares `topic: "<slug>"` and carries the same two blocks, with lowercase headers at column 0 inside the fences:

```
topic: "<slug>"
current:
  R2: "<one-line rule in force>"
rulings:
  R2:
    rule: "<same one-line rule>"
    verbatim: "<the operator's words>"
    ruled: "<who, when, session/ceremony>"
    replaces: "R1"
```

- The same indent rule applies: a block opens only at a column-0 `current:` or `rulings:` header and runs until the next non-blank line at column 0 (a new key or the closing fence). A header takes no value and appears at most once. Entry ids are `R<n>` at two-space indent; `rulings` fields (`rule`, `verbatim`, `ruled`, `replaces`) sit at four-space indent, each at most once per entry, and no other field name is admitted. Every value is a one-line double-quoted scalar under §1.1, so `replaces` is quoted. Anything else rejects the record.
- Block lines are not front-matter fields: they never enter `fields`, so a nested key cannot shadow a front-matter field.
- The lowercase spellings of the key-collision rule are forbidden inside blocks: `version`, `token`, `id`, `type`, `status`, `tier`, `decision`, `because`, `authored_at` and `superseded_by` reject the record (`reserved_key_in_block`).
- A `current:` or `rulings:` line in the markdown body after the closing fence is never a block.
- `lookup_decision` `current_state` and the `list_decisions` `topic` filter (§3.2, §3.3) behave identically for both syntaxes.
- Writing YAML blocks (v1.5): `submit_governance` content mode accepts a YAML topic record carrying these blocks and writes them in the canonical indentation above (§1.1). `append_ruling` builds on that write path and is delivered in v1.7 (§3.5).

**Revision**: 2026-10-29: YAML form of the `CURRENT` / `RULINGS` blocks added; the OCTAVE form is unchanged. 2026-10-31: YAML block writing ships in v1.5 (EPIC4-RECORDS-YAML-BATCH-MERGE-AUTHORITY-20261025; HO-TOPIC-RECORDS-YAML-SYNTAX-20261029).

## 2. Placement, layer mapping, and projection rules

### 2.1 Placement

AGR records live in the `committed_governance` category (PR-α §2 / PR-B §1.2):

```
committed_governance::.hestai/decisions/**/*.{md,oct.md}
```

Specifically, AGRs land at `.hestai/decisions/<token>.oct.md`, `.hestai/decisions/<token>.md` (quoted-YAML, v1.4) or the same under `.hestai/decisions/<group>/` per §1.1. They are L1 (Phase governance) in the convergent L0–L5 topology per PR-B §1.1.

AGRs MUST NOT live in `.hestai/state/sessions/` (L4 ephemeral per PR-α / PR-E), `.hestai/state/cache/` (L2 cache per PR-α), or anywhere outside `.hestai/decisions/`. This invariant is enforced by PR-B §3.3 (tool-boundary fail-fast on the `DECISION_RECORD` TYPE) and PR-B §2 (CI gate).

**Revision**: 2026-10-30: `.hestai/decisions/<token>.md` named as a quoted-YAML AGR location (HO-TOPIC-RECORDS-YAML-SYNTAX-20261029; EPIC4-RECORDS-YAML-BATCH-MERGE-AUTHORITY-20261025).

### 2.2 ADR-0013 substrate ruling

AGRs are not stored in PSS. PSS is substrate (per ADR-0013); AGRs are content. The AGR canonical store is plain committed files; any retrieval acceleration over AGRs lives at L2 (optional cache) and is non-authoritative.

### 2.3 Derived projections

A consumer repo MAY generate a monolithic projection (e.g. `DECISIONS.oct.md` or `decisions.index.json`) from the atomic AGR files. Projections are `DERIVED_PROJECTION` per ADR-0013's vocabulary; they are:

1. Non-authoritative. Reads MUST resolve canonically against atomic AGR files. The projection is a convenience, not the truth.
2. Rebuildable. The projection MUST be reproducible from the atomic files plus the schema; no information is lost on deletion.
3. Out of scope for fail-fast. PR-B §3 does not apply to derived projections at non-governance paths (e.g. `.hestai/state/cache/decisions.index.json`).

Generation of projections is OPTIONAL and may be performed by the validator CLI (§4.4) or by a separate tool. The choice is implementation-lane; this ADR does not legislate.

### 2.4 Cross-repo AGR references

A cross-repo AGR reference resolves per PR-B §1.4.1: `repo:<repo-id>:<repo-relative-path>@<rev>` or `pin:<url>@<rev>`. Bare URLs are not authoritative references. Cross-repo reciprocity is advisory per PR-B §1.4.3 — this ADR does not impose AGR obligations on other repositories.

## 3. MCP tool contracts

### 3.1 Tools introduced

PR-D names four MCP tools:

| Tool | Kind | I5? | I4? |
|---|---|---|---|
| `lookup_decision` | read | yes (pure read) | yes (structured return) |
| `list_decisions` | read | yes (pure read) | yes (structured return) |
| `trace_supersedure` | read | yes (pure read) | yes (structured return) |
| `propose_decision_amendment` | write **broker** (creates a PR; never mutates canonical store) | n/a (the broker is not a read tool; the canonical store remains read-only at the tool boundary) | yes (structured return) |

`get_context` is **not** modified by PR-D. PROD::I5 on `get_context` is preserved unconditionally.

#### 3.1.1 Common error envelope (PROD::I4)

Every tool in §3 — read or broker — MUST return errors in this envelope. The envelope is mandatory; opaque-blob errors are forbidden.

```
{
  "ok": false,
  "error": {
    "code": "<error-code-from-tool-specific-list>",
    "category": "input_validation" | "schema_violation" | "io_failure" | "concurrency" | "broker_failure",
    "message": "<one-line human-readable explanation>",
    "tool": "lookup_decision" | "list_decisions" | "trace_supersedure" | "propose_decision_amendment",
    "context": { /* tool-specific structured payload — e.g. token, path, current_hash, broken_chain */ },
    "contract_ref": "ADR-RFC-ARCH-004 §3.<n>"
  }
}
```

Implementations MAY add fields to `error` (e.g. timing, tool_version) but MUST NOT remove or rename the required keys. The same envelope shape applies to per-tool error lists below.

### 3.2 `lookup_decision(working_dir, token, audience?)`

Resolves a single AGR by `TOKEN`. Pure read.

**Input** (PROD::I4-conformant):

```
{
  "working_dir": "<absolute or repo-rooted path>",
  "token": "<TOKEN string>",
  "audience": "agent" | "human"  // optional; default "agent"
}
```

`audience` controls return verbosity. `"agent"` returns the structured record verbatim. `"human"` MAY additionally include rendered prose where the spec is unambiguous (e.g. resolved supersession chain summarised in English). Implementations MAY ignore `audience` and always return `"agent"` shape; consumers MUST tolerate this.

**Return shape** (PROD::I4-conformant):

```
{
  "ok": true,
  "record": {
    "token": "<TOKEN>",
    "type": "DECISION_RECORD",
    "version": "1.0",
    "status": "PROPOSED" | "RATIFIED" | "SUPERSEDED" | "VOID",
    "tier": "STRATEGIC" | "TACTICAL" | "OPERATIONAL",
    "decision": "<DECISION string>",
    "because": "<BECAUSE string>",
    "authored_at": "<ISO-8601>",
    "path": "<repo-relative path to the .oct.md file, or to the <token>.md file for a YAML record>",
    "fields": { /* all other present fields, key→value */ },
    "current_state": [ { "id": "R2", "rule": "<one-line rule>" }, … ] | null   // additive (v1.3, §1.7)
  },
  "resolution_chain": [ /* see trace_supersedure shape; populated when STATUS == SUPERSEDED */ ],
  "resolution_chain_status": "complete" | "broken" | "cyclic" | "forked" | "unparseable"  // additive (issue #87; "forked"/"unparseable" v1.4); see note below
}
```

The `current_state` field (additive per §3.1.1; v1.3) carries the in-force rules from a topic record's `CURRENT` block (§1.7), in order, as `{id, rule}` entries. It is a list (empty when the block is absent) when the record declares `TOPIC`, and `null` otherwise. All other record keys are unchanged. Like the rest of the record it is derived by a pure read (PROD::I5). The record file is read once; an unreadable file returns the `RECORD_PARSE_FAILED` code with category `io_failure` (§3.1.1) rather than raising.

The `resolution_chain_status` field (additive per §3.1.1; issue #87) is a completeness signal so a caller can distinguish a `resolution_chain` that reached its terminal from one truncated by a broken link or a cycle. It is derived from the same `walk_supersession_chain` outcome that produces `resolution_chain`, with **no** extra read:

- `"complete"` — the walk reached a terminal record (walk outcome `ok`). This is also the value for a non-`SUPERSEDED` record, whose `resolution_chain` is empty and therefore not truncated.
- `"broken"` — a successor `TOKEN` referenced by `SUPERSEDED_BY` does not exist on disk (walk outcome `broken`, the same condition `trace_supersedure` reports as `CHAIN_BROKEN`). The partial chain gathered so far is still returned.
- `"cyclic"` — a `SUPERSEDED_BY` cycle was detected by fail-closed cycle detection (walk outcome `cycle`, the same condition `trace_supersedure` reports as `CHAIN_CYCLE_DETECTED`). The partial chain is still returned; the walk never runs unbounded.
- `"forked"` (v1.4) — a record on the walk has two different successors (walk outcome `fork`, the same condition `trace_supersedure` reports as `CHAIN_FORK_DETECTED`, §3.4). The result gains a top-level `successors` key (sorted list of both TOKENs), present only on a fork. The chain stops at the fork entry.
- `"unparseable"` (v1.4) — the walk met a rejected record (a YAML record the strict reader rejects, or, from v1.6, an OCTAVE record with an unterminated wrapped list), or an incomplete one, mid-chain, after the requested record itself parsed (walk outcome `unparseable`, the same condition `trace_supersedure` reports as `RECORD_PARSE_FAILED`). The result gains a top-level `rejected_at` key, `{token, path, line?, construct?}` (`line` and `construct` only for a record the strict YAML subset rejects, §1.1, or an OCTAVE list the reader rejects, `unterminated_list` or `text_after_list`), present only in this case. The chain stops before that record; it is never half-read.

A `VOID` record named by a derived edge (§1.6) is walked as well, so `resolution_chain` is populated for it although its `status` stays `VOID`.

The field is **always present** (a defined PROD::I4 key) and never removes or renames an existing key; a consumer that ignores it is unaffected. `trace_supersedure` remains the authoritative source for the broken/cyclic *error*; `resolution_chain_status` is an in-band observability signal on `lookup_decision` that agrees with it. A rejected or incomplete REQUESTED record is not this status: `lookup_decision` returns the `RECORD_PARSE_FAILED` error (above). `successors` and `rejected_at` are conditional keys: absent unless the status is `"forked"` or `"unparseable"` respectively.

**Revision**: 2026-10-29: `resolution_chain_status` gains `"forked"` and `"unparseable"`, with the conditional `successors` and `rejected_at` keys (HO-TOPIC-RECORDS-YAML-SYNTAX-20261029; EPIC4-RECORDS-YAML-BATCH-MERGE-AUTHORITY-20261025). 2026-10-31: the `"unparseable"` status, `rejected_at` and trace's `RECORD_PARSE_FAILED` also cover a rejected OCTAVE record (v1.6; HC ruling on hestai-context-mcp#224 under HO-HC-WEEKEND-DELEGATION-20261031).

**Error cases** (per §3.1.1 envelope):

- `TOKEN_NOT_FOUND` (category: `input_validation`) — no record at the requested TOKEN; `context.token` echoed.
- `TOKEN_MALFORMED` (`input_validation`) — TOKEN does not match §1.3 regex.
- `RECORD_PARSE_FAILED` (`schema_violation`) — file found but OCTAVE envelope or required fields fail to parse; `context.path` and `context.parse_error` populated. Implementation choice: treat as fatal for the read, do NOT silently skip. If the file cannot be read at all (I/O error after discovery), the same code is returned with category `io_failure` and `context.parse_error` naming the exception class.
- `WORKING_DIR_INVALID` (`io_failure`) — path does not exist or is not a directory.

### 3.3 `list_decisions(working_dir, scope?, status?, tier?, topic?)`

Lists AGRs with optional filtering. Pure read.

**Input**:

```
{
  "working_dir": "<path>",
  "scope": "<string or null>",     // matches SCOPE field exactly when provided; null = no filter
  "status": "PROPOSED" | "RATIFIED" | "SUPERSEDED" | "VOID" | null,
  "tier": "STRATEGIC" | "TACTICAL" | "OPERATIONAL" | null,
  "topic": "<string or null>"      // v1.3; matches the TOPIC field exactly when provided; null = no filter
}
```

**Return shape**:

```
{
  "ok": true,
  "records": [
    {
      "token": "<TOKEN>",
      "status": "<status>",
      "tier": "<tier>",
      "decision": "<short>",
      "authored_at": "<ISO-8601>",
      "path": "<repo-relative path>",
      "topic": "<TOPIC>"           // additive (v1.3); present ONLY on records that declare TOPIC
    },
    …
  ],
  "total": <integer>,
  "skipped": [
    {
      "path": "<repo-relative path>",
      "parse_error": "<reason the record could not be parsed>"
    },
    …
  ]
}
```

The list is sorted by `authored_at` descending. No paging in v1; implementations MUST handle the full set in a single response. If repository scale requires paging, that is a MINOR schema addition for v1.1.

`skipped` (additive per §3.1.1) is ALWAYS present — an empty array when every in-scope record parsed. It names every file that IS a `DECISION_RECORD` but failed to parse its required §1.2 fields, so a consumer can detect that the listing is incomplete and exactly which records are missing. Entries are sorted by `path` for deterministic output.

**Error cases** (per §3.1.1 envelope):

- `FILTER_INVALID` (`input_validation`) — `status` or `tier` is non-null and not a member of the admissible enum; `context.field` and `context.value` populated.
- `WORKING_DIR_INVALID` (`io_failure`) — as in §3.2.

**Incompleteness handling**: a record under `.hestai/decisions/**` that IS a `DECISION_RECORD` but fails to parse does NOT fail the whole call. It is reported in the `skipped` array (above) — never silently dropped, and never blinding the rest of the index. This satisfies the hard requirement (consumers MUST be able to detect that the list is incomplete) while a single legacy or non-conforming record no longer makes the tool appear dead. (An earlier revision named whole-call `RECORD_PARSE_FAILED` as the recommended choice; the `skipped`-array form is the chosen implementation — detectability is preserved, resilience is improved. `lookup_decision` §3.2 still returns `RECORD_PARSE_FAILED` because a by-TOKEN read targets exactly one record.)

### 3.4 `trace_supersedure(working_dir, token)`

Returns the supersession chain for a token. Pure read.

**Input**:

```
{ "working_dir": "<path>", "token": "<TOKEN>" }
```

**Return shape**:

```
{
  "ok": true,
  "chain": [
    {
      "token": "<TOKEN>",
      "status": "<status>",
      "authored_at": "<ISO-8601>",
      "superseded_by": "<TOKEN or null>",
      "path": "<repo-relative path>"
    },
    …
  ],
  "terminal_token": "<TOKEN of the chain end>",
  "terminal_status": "PROPOSED" | "RATIFIED" | "VOID"
}
```

The chain starts at the requested token and follows `SUPERSEDED_BY` pointers to a record whose `SUPERSEDED_BY` is null. `terminal_status` is never `SUPERSEDED` (chain follows further) and is `VOID` only if the chain ends in retraction.

**Error cases** (per §3.1.1 envelope):

- `TOKEN_NOT_FOUND` (`input_validation`) — starting TOKEN does not exist.
- `CHAIN_BROKEN` (`schema_violation`) — a record in the chain points `SUPERSEDED_BY` at a TOKEN that does not exist; `context.broken_at_token` and `context.missing_successor_token` populated. Distinct from `TOKEN_NOT_FOUND` so consumers can distinguish missing-start from missing-middle.
- `CHAIN_CYCLE_DETECTED` (`schema_violation`) — `SUPERSEDED_BY` traversal revisited a TOKEN already in the chain; `context.cycle_at_token` populated. This SHOULD be unreachable if the validator (§4.1 #8) has been run, but the tool MUST fail closed rather than infinite-loop.
- `CHAIN_FORK_DETECTED` (`schema_violation`, v1.4) — a record in the chain has two different successors, from `SUPERSEDED_BY` (several distinct items of a bracketed `SUPERSEDED_BY`, a record that did not arrive through Gate A, count as several successors) and/or edges derived from YAML `supersedes:` (§1.6); `context.fork_at_token`, `context.successors` (sorted, both TOKENs) and `context.chain` (the entries gathered so far) populated. The walk stops at the fork and never picks one successor.
- `RECORD_PARSE_FAILED` (`schema_violation`, v1.4) — the existing §3.2 code, reused for chains: the starting record or one mid-chain is rejected (a YAML record the strict reader rejects, or, from v1.6, an OCTAVE record with an unterminated wrapped list), or is incomplete (`lookup_decision` returns it only for the requested record; a rejected record mid-chain is its in-band `"unparseable"` status). `context.token`, `context.path`, `context.parse_error` and the chain gathered so far (`context.chain`) are populated, plus `context.line` and `context.construct`, both OPTIONAL as in `lookup_decision` (§3.2): present for a record the strict YAML subset rejects (§1.1) or an OCTAVE list the reader rejects (`unterminated_list`, `text_after_list`, §1.1), absent for a syntactically valid but incomplete record and for one that cannot be read. The tool never returns a half-read entry for it.
- `WORKING_DIR_INVALID` (`io_failure`) — as in §3.2.

When the requested token is found but has no `SUPERSEDED_BY` (it is itself terminal), the chain contains exactly one entry and `terminal_token == token`.

**Derived edges and forks (v1.4)**: the chain follows a record's `SUPERSEDED_BY` pointer or the successor derived at read time from a YAML record's `supersedes:` (§1.6). A record that a derived edge names reads `status: SUPERSEDED` in its chain entry, except a `VOID` record, which keeps `VOID` while its edge is still followed (§1.6). At a fork the final chain entry carries `superseded_by: null`, `fork: true` and `successors`. `lookup_decision` reports the fork and the rejected-record conditions in-band as `resolution_chain_status` `"forked"` and `"unparseable"` (§3.2).

**Revision**: 2026-10-29: `CHAIN_FORK_DETECTED`, `RECORD_PARSE_FAILED` for chains, and the derived-edge reading of the chain added (HO-TOPIC-RECORDS-YAML-SYNTAX-20261029; EPIC4-RECORDS-YAML-BATCH-MERGE-AUTHORITY-20261025). 2026-10-31: a bracketed `SUPERSEDED_BY` yields its successors by item (HC ruling on hestai-context-mcp#224 under HO-HC-WEEKEND-DELEGATION-20261031). 2026-10-31: a multi-item fork can only come from a record that did not pass Gate A (HC ruling on hestai-context-mcp#229 under HO-HC-WEEKEND-DELEGATION-20261031). 2026-10-31: the `"unparseable"` status, `rejected_at` and trace's `RECORD_PARSE_FAILED` also cover a rejected OCTAVE record (v1.6; HC ruling on hestai-context-mcp#224 under HO-HC-WEEKEND-DELEGATION-20261031).

### 3.5 `propose_decision_amendment(working_dir, token, patch, expected_record_hash)` — OPTIONAL broker

Creates a pull request proposing an amendment to an AGR. **Does not mutate the canonical store.** Per ADR-0013 substrate ruling; cited in §0.2.

> **v1.7 (issue #203 S2): delivered for quoted-YAML topic records as `submit_governance` `append_ruling`.** This is the narrowed form of the broker for topic records (§1.7). The general `propose_decision_amendment` below is still OPTIONAL and not shipped, and its contract is unchanged.
>
> - **Input**: `append_ruling: {topic_token, rulings: [{rule, verbatim, ruled, replaces?}], expected_record_hash?}`, mutually exclusive with `octave_content` and `prose_input`. `rule` is one line of at most 40 words in plain words, never arrows or symbols (HO-AGR-PLAIN-WORDS-REASONING-20261031). `verbatim` is kept exactly as given. Several rulings in one call produce one PR.
> - **Base read**: the tool fetches once and resolves `origin/main` to an OID once. Every later read uses that OID, never the ref name: locating the record by its declared TOKEN, reading its bytes, the TOKEN uniqueness check, the in-flight check and the branch base. **Uniqueness is decided at that OID.** It considers only record files, `.md` and `.oct.md`, under `.hestai/decisions` and `.hestai/context/concepts`: the file types `lookup_token_deterministic` scans (that lookup reads only `.oct.md` under concepts; this check reads `.md` there too). Non-record files (e.g. `.txt`) never count. Within those files the check is deliberately broader than the lexer's lookup, so it fails closed. A file other than the record being rewritten counts if it declares the TOKEN or is named `<TOKEN>.md` / `<TOKEN>.oct.md`. "Declares" means exactly what `declares_token` means on the raw text. Text that opens with a `---` fence declares only through its fenced `token:` line, and only when the fences also hold the `type:` DECISION_RECORD header. Any other text, a header-less `.md` included, declares through a top-level `TOKEN::`/`ID::` line. This applies whether or not the file parses and whether or not its syntax matches its extension. A mere citation does not count. So an unparseable or mis-paired twin, or a header-less `.md` with a top-level `TOKEN::` line, still refuses the append; a fenced `token:` line without the header does not. MANIFEST rows are not consulted. Any match refuses the call with `TOKEN_AMBIGUOUS_AT_MAIN`, naming every match. A non-zero exit from a base read (`fetch`, `rev-parse`, `ls-tree`, `cat-file`) is `BASE_UNDETERMINED`; a non-zero exit during the in-flight check is `IN_FLIGHT_UNDETERMINED`. Either way the call is refused.
> - **Hash**: `from_record_hash` and `to_record_hash` are `sha256:<hex>` over the whole file bytes, front matter and body, as §1.1 defines. `expected_record_hash` is optional; when given, it must equal `from_record_hash`. This is a stale-base check, not a lock: it refuses a caller who read an older record, but two requests that observed the same hash both pass it, and a request without the hash is not checked. Protection at merge time is slice S4.
> - **Rendering**: the record is parsed by the reader and re-emitted only through the §1.1 canonical emitter, the same bytes content mode would write. New ids are `R<max+1>` onward, in call order. `replaces` removes the replaced entries in place. `current` is rebuilt from the live `rule` lines in id order. A dated plain-words line is prepended to `revision` (one line per amendment, newest first), and `version` never changes. The markdown body is kept byte for byte, and every `verbatim` reads back byte-exact. A record written before v1.5 becomes canonical on its first append (§1.1).
> - **Validation**: Gate A's YAML branch judges the rendered bytes against the caller's checkout. Its TOKEN uniqueness check (§4.1 #4) accepts the file being rewritten as the TOKEN's one match, and nothing else: any other record file (`.md` or `.oct.md`) that declares the TOKEN or is named for it (an `.oct.md` twin, a second `.md`, a same-name file under concepts) still fails. Zero local matches (a checkout behind `main`) are accepted only because the main-OID check above is the authority for uniqueness. Only this mode can relax the check that far; content mode still refuses an existing TOKEN. The other Gate A lookups, including whether `supersedes` / `superseded_by` targets exist, still read the caller's checkout, not the main OID; moving them is tracked in #232. Gate B is not applied, as for any YAML record.
> - **Delivery**: one branch `governance/<UTC-date>-<token-slug>-r<first-new-n>` cut from the OID, `MANIFEST` unchanged, one commit and one PR against `main`. `dry_run` returns the rendered bytes and both hashes and creates no branch or PR. Stage 5 reviews only each `rule` against its `verbatim` and returns APPROVED or CONCERNS.
> - **Refusals** (`error_code`, PROD::I4): `APPEND_INPUT_INVALID`; `APPEND_MODE_CONFLICT`; `TOKEN_NOT_FOUND_AT_MAIN`; `TOKEN_AMBIGUOUS_AT_MAIN`; `BASE_UNDETERMINED`; `NOT_YAML_TOPIC_RECORD` (an OCTAVE record: "append_ruling writes YAML topic records only"); `NOT_A_TOPIC_RECORD`; `RECORD_UNREADABLE`; `EXPECTED_HASH_MISMATCH` (carries both hashes); `TOPIC_RECORD_IN_FLIGHT` (names the branches and PRs) and `IN_FLIGHT_UNDETERMINED`; `TOPIC_BLOCKS_MALFORMED`; `REPLACES_UNKNOWN_ID`; `RENDER_REJECTED`; `VALIDATION_FAILED`; `LINKER_FAILED`.
> - **Not yet shipped**: appending to an in-flight record (slice S3) and the merge-time staleness recheck (slice S4, defense (a) below). Until S4 lands, two appends cut from the same base can both merge; the hash check above only catches a caller who read an older record.

**Revision**: 2026-10-31: the v1.3 planned note replaced by `append_ruling` as delivered for YAML topic records (v1.7, issue #203 S2; HO-TOPIC-RECORDS-AND-APPEND-RULING-20261015; HO-TOPIC-RECORDS-YAML-SYNTAX-20261029).

**Input**:

```
{
  "working_dir": "<path>",
  "token": "<TOKEN of the record to amend>",
  "patch": { "field": "value", … },                       // partial field updates
  "expected_record_hash": "sha256:<64-hex-digits>"        // optimistic concurrency — per-record content hash
}
```

`expected_record_hash` is a SHA-256 over the canonical UTF-8 bytes of the AGR file as the proposer last read it (the full `.oct.md` file content, byte-for-byte, including OCTAVE envelope). The broker recomputes the hash from current on-disk content **on the default/protected branch HEAD** (NOT from an arbitrary worktree state) and rejects on mismatch (concurrent edit detected — proposer must re-read and recompute). Schema `VERSION` is **not** suitable here — it tracks schema-level breaking changes, not per-record edits, so two simultaneous amendments under the same `VERSION` (e.g. both `1.0`) would not be detected by a version-equality check. The content hash is the per-record CAS primitive.

**Behaviour (proposal-time)**: the broker:

1. Fetches the repository's default/protected branch HEAD (configured at broker init; typically `main`).
2. Reads the AGR file at that HEAD and computes its content hash; rejects with `EXPECTED_HASH_MISMATCH` if it differs from `expected_record_hash` (proposer is stale).
3. Creates a git branch **from default-branch HEAD** (never from an arbitrary local state).
4. Applies the patch, commits with a conventional-commits message.
5. Opens a pull request via the `gh` CLI (or equivalent) **against the default/protected branch** (PR target is not caller-controlled — the broker pins it).
6. Returns the PR URL plus the `from_record_hash` / `to_record_hash` pair.

The broker MUST NOT write to the canonical store path on the base branch directly. The broker MUST NOT accept a caller-supplied PR target (no `branch_target` parameter); this prevents bypass via PR against a long-lived feature branch.

**Behaviour (merge-time staleness)**: the proposal-time hash check is necessary but not sufficient — between PR open and merge, another PR could land that changes the same AGR file. PR-D′ / PR-H MUST land one of these two merge-time defenses:

- **(a) Required merge-time recheck** — a GitHub Action triggered on `pull_request` events for paths under `.hestai/decisions/**/*.oct.md` that re-reads the touched AGRs at PR HEAD and at base branch HEAD, recomputes content hashes, and fails the PR check if the PR's claimed `from_record_hash` no longer equals the base-branch hash. This forces rebase-and-retest. **Recommended.**
- **(b) Branch protection requiring up-to-date base** — GitHub branch protection setting "require branches to be up to date before merging" applied to the default branch. Coarser-grained than (a) (rebases on any change, not just AGR conflicts) but simpler.

PR-D′ / PR-H MUST implement (a) OR document operator selection of (b). The choice is implementation-lane, but one of the two MUST be in force; without it the broker CAS protects only against simultaneous proposals, not against sequential stale merges.

**Return shape**:

```
{
  "ok": true,
  "pr_url": "<URL>",
  "branch": "<branch name>",
  "head_sha": "<git commit sha of the proposal branch HEAD>",
  "token": "<TOKEN>",
  "from_record_hash": "sha256:<64-hex>",                  // hash that matched expected_record_hash
  "to_record_hash":   "sha256:<64-hex>"                   // hash of the file after the patch was applied
}
```

Error cases (PROD::I4-conformant):

- `EXPECTED_HASH_MISMATCH` — concurrent edit detected; returned with the current on-disk hash so the proposer can re-read.
- `TOKEN_NOT_FOUND`.
- `PATCH_REJECTED` — patch violates schema (e.g. would create cycle in supersession DAG, would introduce reserved field name, would change immutable fields such as `TOKEN` or `AUTHORED_AT`).
- `GH_BROKER_FAILED` — wrapper for any `gh` CLI failure; includes upstream error message.

This tool is OPTIONAL in PR-D′ / PR-H. Adopters MAY ship read tools only. The optionality is intentional — the broker is sugar over `gh pr create`; a workflow that pushes directly via standard git tooling remains supported.

### 3.6 Provider agnosticism (PROD::I3)

All four tool contracts MUST yield identical results across providers (Claude / Codex / Gemini / Goose / others). OCTAVE's deterministic parsing is the operational basis. Provider-specific behaviour at any of these tools is a PROD::I3 violation.

## 4. Validator CLI

The validator is a CLI tool (name suggestion: `validate_agent_readable_governance_records` — abbreviated `validate_agr`) that enforces the schema invariants. It is run pre-commit, in CI, and on demand.

### 4.1 Invariants checked

**Multi-line list fields (v1.6)**: Gate A rejects an OCTAVE record with a list that is never closed or has text after its closing `]` (§1.1) as an error naming the line where the list opens and the construct. A multi-line edge field (`SUPERSEDES`, `SUPERSEDED_BY`, `AMENDS`, `EXTENDS`) produces a WARNING, never an error, because `octave_write` may wrap a list and the record must stay amendable. Each item of a bracketed `SUPERSEDED_BY` must name an existing TOKEN, as a single `SUPERSEDED_BY` does (#8); more than one DISTINCT item is an error (#8).

**Gate A YAML branch (v1.5)**: a quoted-YAML submission (§1.1) is validated by a YAML branch of Gate A. The reader's strict rejection is surfaced with its line and construct; the same required-field, `VERSION` shape, enum, TOKEN (format and date), reserved-name, density, ratification-provenance and `ISSUE_REF` invariants apply to the decoded front-matter values, and `SUPERSEDED_BY` and `supersedes:` targets must exist. TOKEN uniqueness (#4) is enforced across `.oct.md` and `.md`. Gate B, the OCTAVE validator, is not applied to YAML. The numbered invariants below are stated in OCTAVE terms; #1 (OCTAVE envelope) and #15 (core key ahead of `META:`) have no YAML counterpart beyond the reader's strict subset.

1. **OCTAVE envelope** — `===DECISION_RECORD===` / `===END===` present, `META.TYPE::DECISION_RECORD`, `META.VERSION` is a parseable `MAJOR.MINOR` string.
2. **Required fields present** — TYPE, VERSION, TOKEN, STATUS, TIER, DECISION, BECAUSE, AUTHORED_AT.
3. **TOKEN format and date consistency** — matches §1.3 regex AND the `YYYYMMDD` suffix equals the UTC date portion of `AUTHORED_AT` (per the §1.3 MUST). Mismatch is a hard error.
4. **TOKEN uniqueness** — every TOKEN appears exactly once across `.hestai/decisions/**/*.oct.md`. The read tools also scan YAML `*.md` records (§1.1). Cross-syntax uniqueness (one TOKEN as both `.oct.md` and `.md`) is enforced from v1.5 by the Gate A YAML branch, which rejects a submission whose TOKEN already exists in either syntax or whose `<token>.md` / `<token>.oct.md` file is already present. A repository that already holds such a pair (it predates v1.5) is resolved by `lookup_decision` and `trace_supersedure` to `<token>.oct.md` before `<token>.md`.
5. **STATUS enum** — one of the four admissible values.
6. **TIER enum** — one of the three admissible values.
7. **Reserved names** — `DEPENDS_ON`, `CONFLICTS_WITH`, `ARCHIVED_AT` MUST NOT appear in v1.x records.
8. **Supersession DAG (same-repo only)** — `SUPERSEDED_BY`, `EXTENDS`, `AMENDS` references resolve to TOKENs that exist **in the same repository**; per §1.6 each edge-type subgraph is acyclic independently (cross-edge interactions per §1.6 are admissible and NOT cycles); `SUPERSEDED_BY` chain is a chain not a tree. Cross-repo edges (per §2.4) are **out of scope** for automated validation — the validator does not fetch remote repositories. This is consistent with ADR-RFC-ARCH-002 PE amendment 1 (CI gate scoped to LOCAL repo-relative paths only) and §2.4's "cross-repo reciprocity is advisory" stance. Cross-repo edge correctness is enforced by editorial review. **`SUPERSEDED_BY` has exactly one successor on write (v1.6)**: a bracketed `SUPERSEDED_BY` naming more than one DISTINCT TOKEN is rejected, citing this invariant; `[X]` and `[X, X]` are accepted like a bare `X` (duplicates collapse). The reader still reports a fork on read for a record that arrived other than through Gate A (§1.6).
9. **`SUPERSEDED_BY` invariant** — present iff `STATUS == SUPERSEDED`.
10. **`ISSUE_REF` shape** — when present, parses as a GitHub URL or `repo:<repo-id>#<n>`.
11. **`HUMAN_ADR_REF` form (v1.1)** — when present, the ref is EITHER a well-formed greppable TOKEN (matches the §1.3 TOKEN regex; the v1.1 canonical cross-repo-survivable form per HO-AGR-BYTECODE-FORMAT-TWO-BIRDS-20260620 — validated as a token, NOT path-resolved) OR a v1.0 path that resolves to a file under the repository. The §1.3 TOKEN pattern admits no path separator and no `.`, so the two forms are mutually exclusive: token-form is matched first; anything else is treated as a path and must resolve under the repo. A ref that is neither is a hard error.
12. **Ratification provenance (warning)** — when `STATUS != PROPOSED` and `RATIFIED_BY` is absent, the validator emits a **warning** (not error) per §4.2. Closes a portion of the TOKEN-squatting / lookalike-record gap without forcing legacy `HO-*` records into rework. May be promoted to error in a MINOR bump (see §11 Q5).
13. **Reasoning-field density (v1.1)** — `DECISION` and `BECAUSE` are each AT MOST 40 words and contain NO embedded newline (the v1.1 flat-line form, §1.2; relations in plain words per v1.8, which Gate A does not machine-check). A value-level check ONLY: the structural flat-regex parse is unchanged (no structural parser change), so write/read parity (the shared `type_checker` ↔ `agr_read` constants) is preserved. Per HO-AGR-BYTECODE-FORMAT-TWO-BIRDS-20260620 (#101). Severity: error.
14. **Topic-block key collision (v1.3)** — inside a `CURRENT` or `RULINGS` block (§1.7) no line may use a top-level reserved key (`VERSION`, `TOKEN`, `ID`, `TYPE`, `STATUS`, `TIER`, `DECISION`, `BECAUSE`, `AUTHORED_AT`, `SUPERSEDED_BY`) as its key. All other invariants (#1–#13) are evaluated over the record with CURRENT/RULINGS lines excluded, matching the read parser. Every offending line is reported with the key and the block named. Regex-only; a no-op for records without these blocks. Severity: error. The lowercase YAML equivalents (§1.7) are rejected by the YAML reader (`reserved_key_in_block`); from v1.5 Gate A's YAML branch surfaces that rejection with its line and construct.
15. **Core key ahead of META (v1.3)** — none of the top-level core keys named in #14 may appear before the `META:` header (outside the blocks). The parser and Gate A keep the first match of each key over the whole record, so an earlier copy would override the value declared in META. Placement after the META block, and later nested repeats, remain admissible (some records declare `STATUS`/`TIER`/`DECISION` after META; a later copy cannot win first-match). A no-op when no `META:` header exists. Severity: error.

**Revision**: 2026-10-30: YAML records noted in the uniqueness corpus; cross-syntax enforcement deferred to PR-5 (HO-TOPIC-RECORDS-YAML-SYNTAX-20261029; EPIC4-RECORDS-YAML-BATCH-MERGE-AUTHORITY-20261025). 2026-10-31: Gate A YAML branch and cross-syntax TOKEN uniqueness ship in v1.5 (EPIC4-RECORDS-YAML-BATCH-MERGE-AUTHORITY-20261025; HO-TOPIC-RECORDS-YAML-SYNTAX-20261029). 2026-10-31: the unterminated-list error and the multi-line edge-field warning added (HC ruling on hestai-context-mcp#224 under HO-HC-WEEKEND-DELEGATION-20261031). 2026-10-31: more than one distinct `SUPERSEDED_BY` item rejected on write (HC ruling on hestai-context-mcp#229 under HO-HC-WEEKEND-DELEGATION-20261031). 2026-10-31: #13 wording aligned with the plain-words rule, no check changed (HO-AGR-PLAIN-WORDS-REASONING-20261031).

### 4.2 Severities

- **error** — hard block on commit / CI fail. All §4.1 invariants.
- **warning** — advisory only. Future MINOR additions may introduce warning-level checks (e.g. `BECAUSE` field too short, `TOKEN` semantically unclear).

### 4.3 Outputs

- **Default**: human-readable diagnostic plus non-zero exit on error.
- **`--json`**: PROD::I4-conformant structured output suitable for CI consumption.
- **`--quiet`**: exit code only; no stdout output.

### 4.4 Optional projection generation

The validator MAY ship with a `--emit-projection` flag that produces a `DECISIONS.oct.md` projection from the atomic records. The projection is `DERIVED_PROJECTION` per §2.3 and is written to a non-authoritative path (default: `.hestai/state/cache/decisions/DECISIONS.oct.md`). This flag is OPTIONAL; PR-D′ / PR-H choose whether to ship it in the first implementation.

## 5. Invariant chain

- **PROD::I1 SESSION_LIFECYCLE_INTEGRITY** — AGRs preserve decision provenance across sessions. The `ORIGIN_SESSION` + `ORIGIN_LEDGER_RD` optional fields are the citation pattern for content lifted out of ephemeral ledgers (per PR-E §2.5 promotion-by-citation, not by copy).
- **PROD::I3 PROVIDER_AGNOSTIC_CONTEXT** — OCTAVE deterministic parsing + identical tool contracts across providers yields identical reads.
- **PROD::I4 STRUCTURED_RETURN_SHAPES** — every tool return is a structured dictionary with defined fields; opaque blobs are forbidden. Error shapes mirror PR-B §3.4 conventions.
- **PROD::I5 READ_ONLY_CONTEXT_QUERY** — `lookup_decision`, `list_decisions`, and `trace_supersedure` are pure reads. `propose_decision_amendment` is a broker, not a writer to the canonical store; the canonical store remains read-only at the tool boundary.
- **PROD::I6 LEGACY_INDEPENDENCE** — interpreted as opt-in adoption discipline per RFC #40: consumer repos adopt voluntarily; non-adopters remain fully supported indefinitely; no consumer is forced to migrate.
- **SYS::I1 CONTEXT_INTEGRITY** — `META.TYPE::DECISION_RECORD` declares governance-class at the artefact level; PR-B §3.2.2 picks this up automatically.
- **SYS::I6 (scope boundary)** — PR-D specifies AGR records and consumer-side tool contracts within hestai-context-mcp. Vault (agent definitions, skills), Workbench (UI, dispatch), DebateHall (deliberation records), and octave-mcp (grammar) lanes are not encroached.

## 6. Verification of this ADR

This ADR is governance specification with no code attached. Verification is review-only:

- **Tier**: TIER_3
- **Facets**: GOVERNANCE
- **Gate**: CIV + SR per `/review` skill
- **Debate-hall escalation**: discretionary, recommended if reviewers find §1.4 (lifecycle transitions), §1.6 (supersession DAG), or §3.5 (broker pattern) ambiguous in practice.

Enforcement of the AGR contract itself begins on this ADR's merge:

- **By review discipline** until PR-D′/PR-H lands — PR authors authoring new AGR records by hand follow §1; reviewers verify against §4.1.
- **By tool boundary** once PR-F (PR-B §3) lands and PR-D′/PR-H lands — `octave_write` rejects `DECISION_RECORD` writes outside `.hestai/decisions/**` via PR-B §3.2.2; the validator CLI enforces §4.1.

## 7. Reconciliation with issue #25 (Decision Journal Light)

Issue #25 proposed an append-only `DECISION-JOURNAL.oct.md` extracted by `clock_out` from `#DECISION` tags. PR-D supersedes issue #25 on direction.

**Reasons**:

1. The journal's "audit-only, no blocking" model is incompatible with AGRs being authoritative for "what is currently binding". A reader cannot tell whether the journal records a decision that is binding now or one that has been superseded since.
2. The journal's tag-extraction pattern (`#DECISION:` in session content) is provider-coupled and PROD::I3-fragile: providers that strip or rewrite tags break the audit trail. AGRs require explicit authorship and validate against §4.1; provider variance does not corrupt them.
3. The journal's flat append model has no supersession semantics. AGRs supersede via `SUPERSEDED_BY` with full DAG enforcement (§1.6).
4. Issue #40's three-layer model (operator-ratified 2026-05-13) reserves "what was decided and why" to L1 AGRs and "stable structure" to L1S Facet ABI. The journal is neither; it is an orphaned design.

**Status of issue #25**: PR-D, on merge, reduces issue #25 to a closeable issue with disposition `SUPERSEDED-BY RFC #40 / ADR-RFC-ARCH-004`. The operator may close it post-merge with a short comment citing this section.

**Migration**: there is no in-place migration of historical session content. The `#DECISION` tag pattern is retired. Session content that contained ratified decisions during the journal's brief life can be promoted by hand to AGR records by citing the originating session (`ORIGIN_SESSION`) — same pattern as PR-E §2.5.

## 8. Promotion path for Mac B#1 RD15 / RD17 / RD18

Mac B#1's carry-forward (`.hestai/decisions/handoff/2026-05-16-rfc-40-mac-b1-carry-forward.md` §"Decision-record promotion candidates for PR-D") names three durable decision substances from the v1.4 ledger that should land as AGR records once PR-D ratifies.

PR-D **does not author** the three records here — that authorship is the first concrete use of the schema and is performed by a follow-up PR (operator-discretionary, may be bundled with PR-D′/PR-H or kept separate). PR-D instead specifies the **shape** of those records so the follow-up is mechanical:

| Candidate | Suggested TOKEN | Suggested STATUS at authoring | `ORIGIN_SESSION` | `ORIGIN_LEDGER_RD` |
|---|---|---|---|---|
| RD17 — AGR Standard Ownership Ruling | `HO-CONTEXT-MCP-OWNS-AGR-STANDARD-20260513` (verbatim from carry-forward) | `RATIFIED` | `646ddcc6-7ba4-48f5-b55f-fa16e26ca8bb` | `RD17` |
| RD18 — OCTAVE_WRITE multi-envelope workaround (provisional) | `HO-OCTAVE-WRITE-MULTI-ENVELOPE-WORKAROUND-20260513` (verbatim) | `RATIFIED` (with note: VOID-on-#420-land) | same | `RD18` |
| RD15 — Decisions-as-Context platform scope (historical) | `HO-DECISIONS-AS-CONTEXT-PLATFORM-SCOPE-20260505` (verbatim) | `RATIFIED` with explicit `SUPERSEDED_BY` set when the IA Contract umbrella token lands (per carry-forward §"Status after umbrella") | same | `RD15` |

These three TOKENs validate against §1.3 regex verbatim. None require schema extension.

Substance flows by citation, not verbatim copy, per PR-E §2.5: each record's `DECISION` and `BECAUSE` are authored fresh from the ledger's RD substance, and the originating ledger is cited via `ORIGIN_SESSION` + `ORIGIN_LEDGER_RD`.

## 9. Preflight gates (D1–D6 — binding for PR-D′ / PR-H code authorisation)

Issue #40 §"Preflight empirical gates" enumerates six gates. PR-D carries them forward verbatim as binding preconditions for code authorisation in the implementation PR. PR-D itself is the spec; the gates do not need to execute before PR-D merges, but the implementation PR MUST NOT bypass them.

| Gate | Pass condition | Owner |
|---|---|---|
| **D1** Schema audit | Survey elevana-studio's `DECISIONS.oct.md` schema + our existing ADR header conventions. Confirm §1 schema is syntactic superset. | implementation-lead, pre-code |
| **D2** First-record migration | Hand-author one AGR record here (recommend `HO-ADR-0013.oct.md`). | implementation-lead, pre-code |
| **D3** Cross-link with L0 / L1S | Confirm optional `HUMAN_ADR_REF` → `docs/adr/` resolves; confirm a CONCEPT_CARD can cite the AGR via EDGES. | implementation-lead with RFC #38 consumer |
| **D4** Validator CLI | Implement `validate_agr` before any retrieval tool. | implementation-lead |
| **D5** Retrieval benchmark | Hand-author 5 gold-set retrieval tasks, including cross-repo / cross-layer queries. Measure precision/recall. | implementation-lead |
| **D6** Cross-repo dry run | A consumer repo (operator-authorised, not assumed) authors 3 AGR records using the standard. | implementation-lead with operator-named consumer repo |

The "consumer repo" in D6 is **explicitly gated on operator approval per consumer**; this ADR does not pre-authorise elevana-studio or any other repo.

## 10. Out of scope (do not infer from PR-D)

PR-D does **not** define, decide, or constrain:

- **Code implementation.** Deferred to PR-D′ / PR-H, owner implementation-lead via oa-router.
- **CI gate implementation, MCP-tool fail-fast implementation.** Owned by PR-G and PR-F respectively, per PR-B.
- **Ledger schema.** Owned by PR-E (ADR-RFC-ARCH-003); the ledger is L4 ephemeral and never an AGR canonical store.
- **Placement invariant rules.** Owned by PR-α / PR-B.
- **Routing rules between RFC #38 and RFC #40.** Owned by PR-B §1.5; PR-D conforms.
- **PSS substrate or registry use.** ADR-0013 substrate ruling stands; PR-D does not invoke PSS.
- **Agent definitions, skill definitions, standards documents.** Vault lane.
- **UI, dispatch, payload compiler design.** Workbench lane.
- **Debate-hall artefact format.** DebateHall lane.
- **OCTAVE grammar additions or changes.** octave-mcp lane.
- **Authorship of the RD15 / RD17 / RD18 AGR records.** Specified in §8; authorship is operator-discretionary follow-up.
- **Closure of issue #25.** §7 specifies disposition; operator closes the issue.
- **Session-extraction workflow (session-ledger → AGR promotion).** Deferred. The placement-layer fix (PR-α / PR-B) prevents *new* session content from being treated as authoritative, but operators making binding decisions mid-session still have no automated on-ramp to `.hestai/decisions/`. Until that workflow exists (separate PR, separate SKILL update), operators must manually author committed AGR records per §1; `ho-control-room` SKILL §3 already marks ledger content as ephemeral, which is the operational defense. The risk if this remains unfixed is that the issue #25 pattern reappears by accident — an operator writes a decision into the ledger, the session ends, the decision substance is provenance-only. Acceptable risk for PR-D ratification; tracked as an open workflow gap.

## 11. Open questions for the operator (non-blocking)

These do not block PR-D ratification. Operator answers may land as MINOR additions (`1.1`, `1.2`).

1. **Token prefix convention** — §1.3 admits any uppercase-letter-led prefix. Is there value in canonising a small set of recommended prefixes (e.g. `HO-`, `OP-`, `ADR-`)? Current draft does not; legacy `HO-` tokens remain valid by regex.
2. **`ISSUE_REF` on `RATIFIED`** — current draft makes `ISSUE_REF` optional even on `RATIFIED`. Should it be required when the originating decision was filed on the issue tracker? Recommendation: keep optional; mandatory would block hand-ratified HO-tokens that have no issue.
3. **`EFFECTIVE_FROM` vs `AUTHORED_AT` divergence** — current draft permits `EFFECTIVE_FROM > AUTHORED_AT` (future-dated decisions). Acceptable, or should the validator reject as a foot-gun? Recommendation: permit; useful for staged rollouts.
4. **Monolithic projection generation** — should the validator CLI ship `--emit-projection` in v1, or defer to a separate tool? Current draft leaves it OPTIONAL; PR-D′ / PR-H chooses.
5. **TOKEN namespace authority / reserved prefixes** — §1.3 admits any uppercase-letter-led prefix and §4.1 #12 warns (not errors) on missing `RATIFIED_BY`. Should specific prefixes be reserved (e.g. `HO-` may only be authored by `agent:HOLISTIC_ORCHESTRATOR`; `OP-` only by `human:*`) with validator hard-error enforcement? Current draft does not; uniqueness + `RATIFIED_BY` warning is the operational floor. Promotion to a hard rule is a MINOR addition if TOKEN-squatting becomes observable.
6. **Session-extraction workflow** — see §10 closing entry. When (if ever) the workflow exists, what is its shape: an `extract_decisions` tool in this service, a SKILL update in the Vault lane, or a manual operator-driven pattern? Operator decision; not specced here.

## 12. Supersession

This ADR is **subordinate to**:

- ADR-RFC-ARCH-001 (PR-α placement invariant) — AGR placement category derives from PR-α §2.
- ADR-RFC-ARCH-002 (PR-B IA Contract) — AGRs are queried via PR-B §1.5 `lookup_decision` routing; AGRs inherit governance-class fail-fast via PR-B §3.2.2; AGR placement is bounded by PR-B §1.2.

This ADR is **adjacent to** ADR-RFC-ARCH-003 (PR-E ledger schema) — AGRs and ledgers are disjoint artefact classes; the ledger never holds AGR records, and AGRs never substitute for the ledger's session-local provenance role.

This ADR **supersedes on direction** issue #25 (Decision Journal Light) per §7.

A future v2.x AGR ADR would supersede §1 by explicit field-by-field breaking-change list, per §1.5 MAJOR-bump rules.

## 13. Ratification record (2026-06-11)

ADR-004 is **RATIFIED** via a stamped SR + CIV close-out. The substantive matter ruled was not merely the v1 schema but its convergence with the cross-repo AGR canonical form and the TIER projection.

### 13.1 What changed before ratification

- **§1.1 canonical form → BARE TOKEN** (merged PR #68, `396b888`). The operator-sanctioned writer `octave_write` dequotes identifiers under every `format_style`, so a quoted `TOKEN::"…"` is un-writable by the actual toolchain. Canonical form is therefore bare; Gate A readers (`type_checker`, `lexer`, `manifest`) are quote-optional and end-anchored (reject trailing-garbage TOKEN/ID lines). This heals the §1.1↔§1.6 split (§1.6 already used bare `AMENDS`/`EXTENDS`).
- **§4.1 #8 lineage guard enforced** in the linker (`governance/lineage.py`): in-repo `AMENDS`/`EXTENDS`/`SUPERSEDED_BY` edges must resolve; dangling same-repo edges are reported as a structured finding (PROD I4), never a crash; cross-repo edges remain advisory (§2.4); cohort-isolation is a handled expected case.

### 13.2 TIER crosswalk (3-row) — ratified

The AGR `TIER` enum (semantic gravity: STRATEGIC/TACTICAL/OPERATIONAL) receives a projection from elevana-studio's storage/process-gravity tiers, defined by *their* RATIFIED gravity-tiered decision (`HO-DECISION-GOVERNANCE-GRAVITY-TIERED-20260428`). The crosswalk **EXTENDS** HestAI-MCP ADR-0060 (RFC/ADR alignment + ISSUE_REF compliance); it does **not** amend it — AGR retains `ISSUE_REF` and the cohort carries it, so ADR-0060's compliance contract is preserved. Amendment authority for the tier vocabulary sits on the elevana-studio side.

| Source (process/storage gravity) | → AGR TIER (semantic gravity) | Empirical status |
|---|---|---|
| ARCHITECTURAL (issue + ISSUE_REF) | STRATEGIC | **PROVEN** — 5 cohort tokens, Gate-A clean |
| CONVENTION (inline-only) | TACTICAL | ruled-by-reasoning (unexercised) |
| MICRO (tooling + ENFORCEMENT_REF) | OPERATIONAL | ruled-by-reasoning (unexercised) |

CONVENTION→TACTICAL and MICRO→OPERATIONAL are ratified **by reasoning** with empirically-unexercised status; the first CONVENTION/MICRO AGR record is the natural validation point.

### 13.3 Evidence

Post-#68 anchored readers re-validated against the real 5-token elevana-studio cohort (2026-06-11): all 5 bare-canonical tokens validate clean; lineage guard reports the dangling same-repo `AMENDS` edge as a structured finding by default and as expected cohort-isolation when declared. Full suite 1070 green; governance coverage `lineage` 100% / `lexer` 100% / `manifest` 94% / `type_checker` 95%.

### 13.4 Sign-off

- **SR (standards-reviewer)** — APPROVED: schema complete and non-contradictory; 3-row crosswalk structurally sound (monotone co-ranking preserves ordinal gravity); ADR-0060 preserved via EXTENDS + ISSUE_REF retention.
- **CIV (critical-implementation-validator)** — APPROVED: merged implementation matches the spec (anchored quote-optional readers, lineage structured findings, ISSUE_REF retained); empirical cohort green; ready to ratify.

Authority pack: `.hestai/state/coordination/2026-06-11-agr-tier-crosswalk-authority-pack.md`. Downstream: elevana-studio D6 gate unblocks on this RATIFIED status.
