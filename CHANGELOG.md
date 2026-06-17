# Changelog

All notable changes to `hestai-context-mcp` are documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [Unreleased]

---

## [0.9.0] — 2026-06-17 — Real Cost Accounting & Truncation Resilience

### Added
- `AIClientTruncationError` in the AIClient port taxonomy — models output-token budget exhaustion (provider `finish_reason="length"`) distinctly from a malformed response, carrying the real `consumed_tokens` (issue #96)
- Config-sourced provider upstream-routing pin: `HESTAI_AI_PROVIDER_ORDER` (comma-separated upstream slugs, OpenRouter) and `HESTAI_AI_PROVIDER_ROUTING=off` to disable. Defaults to a preferred order with `allow_fallbacks` preserved (prefer, not require), so a preferred-upstream outage degrades gracefully (issue #96)
- `CompletionResult` in the AIClient port — `complete_text` returns content plus the provider's real token usage and real cost (vendor-free) so callers report accurate metrics (issue #98)
- `metrics.cost_is_estimate` flag on `submit_governance` prose-mode and governance-review results — `true` when the cost is a flat-rate local estimate (provider reported none), so an estimate is never mistaken for a billed actual (issue #98)

### Changed
- `metrics.cost` and `metrics.tokens` now report the provider's **real** figures from the OpenRouter response (via `usage: {include: true}`) instead of local estimates. Previously `cost` overstated real spend by ~15× (flat $0.01/1k) and `tokens` were char-estimated. The flat-rate estimate is retained only for the pre-call cost-projection / abort guard, and as a clearly-labelled fallback when the provider reports no cost (issue #98)
- `list_decisions` no longer fail-closes the entire index when one record is unparseable. It returns the parseable records plus an always-present `skipped` array naming each malformed `DECISION_RECORD` and why it failed. A single legacy/non-conforming file (e.g. a pre-schema ADR) can no longer make the whole tool appear dead. Detectability of an incomplete list — the ADR-RFC-ARCH-004 §3.3 hard requirement — is preserved via `skipped`; silent dropping remains forbidden. `lookup_decision` (by-TOKEN) still returns `RECORD_PARSE_FAILED`, since it targets exactly one record (ADR-RFC-ARCH-004 §3.3)

### Fixed
- Stage-2 prose→OCTAVE (`submit_governance` prose mode) no longer fails non-deterministically when OpenRouter routes a reasoning model onto an upstream that truncates at the token cap: the pin reduces routing nondeterminism and `finish_reason="length"` is now surfaced as an actionable truncation error instead of an opaque protocol error (issue #96)
- Truncated/budget-exhausted AI calls now record the **real** tokens and cost in the returned failure metrics instead of `tokens:0 / cost:0`; truncation is not retried (an identical re-issue would re-truncate and burn budget). Applies to `compile_prose_to_octave` and `review_governance` (issue #96)

---

## [0.8.0] — 2026-06-15 — AGR Read-Side & Gate-A Hardening

### Added
- AGR read-side tools: `list_decisions`, `lookup_decision`, `trace_supersedure` — query Agent-Readable Governance Records directly from the MCP server (PR #83)
- AGR parser: tokeniser + linker for DECISION_RECORD-typed `.oct.md` files (PR #83)
- Security: token validation in `discover_record` to prevent path traversal (PR #83)
- AGR semantic review integration: analysis-tier reviewer wired into AGR PR flow (PR #77)
- Scoped semantic AGR reviewer agent at the analysis tier (PR #77)
- `.env` loaded at server startup so Gate C prose mode resolves credentials
- `resolution_chain_status` completeness signal in `lookup_decision` response — indicates whether the decision chain is terminal, superseded, or unresolved (PR #93, issue #87)
- Gate-A ISSUE_REF shape enforcement in type checker — validates org/repo/number format (ADR-004 §4.1)

### Fixed
- `list_decisions` scoped to DECISION_RECORD-typed files only; co-located non-AGR artifacts excluded (PR #83)
- TYPE detection line-anchored to exclude `*TYPE::-suffixed` non-AGR fields (PR #83)
- GitGuardian false positive on AGR token fixtures neutralised in CI
- Gate-A `_TOKEN_RE`/`_SUPERSEDED_BY_RE` anchored; class-guard meta-test added — closes full `*FIELD::` substring-leak class (PR #91, issue #85)
- Gate-A `TYPE`/`REPO_ID`/lexer-field extractors line-anchored to prevent `*FIELD::` substring leaks (PR #91, issue #85)
- `_ISSUE_REF_RE` anchored; ISSUE_REF presence detector hardened; duplicate field rejected (ADR-004 §4.1)
- ISSUE_REF trailing-garbage bypass closed (ADR-004 §4.1)
- `ISSUE_REF_SHAPE_RE` org/repo segment character class tightened (ADR-004 §4.1)
- Setup: skip import check in dry-run mode
- Setup: run `uv sync --extra validation` before client registration

### Refactored
- Gate-A ISSUE_REF extractor+detector pair collapsed to single greedy regex (ADR-004 §4.1)

### Chore
- Setup: fix stale 0/4 step label to 0/5

### Docs
- Comprehensive README rewrite with supplementary docs (PR #94)
- Claude / Agent Configuration section added to README (PR #94)
- `UnavailableOctaveValidator` class name corrected in architecture example (PR #94)

### Records Added
- `HO-AGR-SEMANTIC-REVIEWER-ANALYSIS-TIER-20260611`
- `HO-AGR-DETERMINISTIC-REVIEW-CONVENTION-20260611`
- `HO-CONTEXT-MCP-ADOPTS-AGR-DOGFOOD-20260611`

---

## [0.7.0] — 2026-06-11 — Gate C Intake Pipeline

### Added
- `submit_governance` Gate C — full five-stage intake pipeline (RFC #53):
  - Stage 1: few-shot + JIT context assembler (T1)
  - Stage 2: prose → OCTAVE backend with cost caps (T2)
  - Stage 3: validate → retry → abort pipeline (T3)
  - Stage 4: validated OCTAVE → PR linker (T4)
  - Stage 5: `prose_input` mode with exactly-one-of guard (T5)
- `OctaveValidator` port — real in-process `octave-mcp` adapter with fail-soft fallback
- `octave-mcp` optional `validation` extra dependency
- `linker` AMENDS/EXTENDS in-repo edge-resolution guard
- Quote-optional TOKEN/ID readers supporting BARE canonical form
- ADR-RFC-ARCH-004 ratified (SR + CIV stamped close-out)

### Fixed
- Intake: prose sent once; double-counting of output tokens eliminated (PR #71)
- GitGuardian false positive on AGR TOKEN fixtures cleared (PR #71)
- `run_linker`: push branch before `gh pr create` to avoid missing-ref failure (PR #73)
- `end-anchor` quote-optional TOKEN/ID readers (cubic P2)
- Whitespace-only env GitHub token treated as absent

### Refactored
- Shared GitHub token resolution extracted to `tools/shared/github_auth`

---

## [0.6.0] — 2026-05-31 — submit_governance Gate A

### Added
- `submit_governance` tool with Gate A rails (RFC #53) — structured governance record intake

### Fixed
- Governance: slug validation, error guard, ID fallback (cubic P1/P2 findings)

---

## [0.5.0] — 2026-05-30 — Redaction Engine Hardening

### Fixed
- Redaction G1: multi-line PEM stream detection hardened
- Redaction G2: GitHub PAT pattern widened
- Redaction G7: `sk-` prefix detection widened
- `copy_and_redact`: pre-existing destination preserved via atomic temp-write
- North Star summary migrated to UPOG grammar with regression guard

---

## [0.4.0] — 2026-05-05 — submit_review Hardening & GitHub Token Fallback

### Added
- `submit_review`: top-level `commit_sha` and `error_type` fields in all response shapes (issue #30)
- GitHub CLI token fallback when `GITHUB_TOKEN` env var is unset (issue #34)
- Shape validation on `gh auth token` output before accepting
- Support for `github_pat_` fine-grained PAT prefix in token-shape guard

### Fixed
- Server entry point and `scripts` entry added to `pyproject.toml`
- Behavioural verification of server entry points improved

---

## [0.3.0] — 2026-04-26–29 — Portable Session State (ADR-0013)

This milestone implements the full ADR-0013 Portable Session State specification across 15 TDD groups.

### Added
- `StorageAdapter` protocol (GROUP_001–002): `@runtime_checkable` protocol with typed signatures
- `IdentityTuple` validation + `RestoreError` (GROUP_003)
- Schema versioning + migration framework (GROUP_004)
- Redaction provenance + engine versioning (GROUP_005)
- `LocalFilesystemAdapter` (GROUP_006): full write/read/tombstone lifecycle
- Durable outbox queue (GROUP_007)
- Named-session snapshots (GROUP_008)
- State classification helpers (GROUP_009)
- Projection builder + tombstone round-trip (GROUP_010)
- `clock_in` PSS restore + named snapshot (GROUP_011)
- `clock_out` PSS publish + outbox integration (GROUP_012)
- `get_context` purity guard (`PURITY_GUARD::G3`) (GROUP_013)
- `LocalFilesystemAdapter.is_local_only()` canonical marker (GROUP_014)
- `storage.B1_LAYERING_FROZEN` canonical marker (GROUP_015)
- `clock_in` response now includes distinct `conflicts` field (issue #7)

### Fixed
- PSS path layout aligned with ADR-0013 abstract path (RISK_006)
- `clock_out` fail-closed publish on redaction failure (RISK_010)
- `clock_in` snapshot construction wrapped in `try/except` (cubic P1 #1)
- `identity._check_string_component` rejects non-string types fail-closed (cubic P1 #2)
- `clock_out` cleanup handler initialises `dest` before `try` block (cubic P1 #3)
- `list_artifacts` pagination uses canonical sort key (cubic P1 #4)
- `state_schema_version` rejects `bool` explicitly (cubic P1 #5)
- `identity_resolver` fail-closed on non-string identity fields (cubic P2 #6)
- `classify_state_path` enforces strict PSS segment count (cubic P2 #7)
- `outbox.list_entries` wraps all decode errors as `OutboxParseError` (cubic P2 #9)
- `clock_in` `artifact_count` reads post-tombstone projection refs (cubic P2)

### Docs
- ADR-0013 Portable Session State via Storage Adapters ratified

---

## [0.2.0] — 2026-04-20–21 — Provider-Agnostic AIClient & North Star Extraction

### Added
- `AIClient` port with provider-agnostic adapter and keyring migration (issue #5)
- `ai_synthesis` field in `clock_in` response; phase string normalised
- North Star structured constraint extraction in `get_context`

### Refactored
- Core → adapter dependency inverted via composition-root factory
- `clock_out` redesigned with provider adapter pattern

### Fixed
- Keyring self-heal, prompt injection guard, HTTP 408 handling (CE blockers)
- CRLF/Unicode bypass in protected-block marker escaping
- `context_summary` marker escape and port/adapter typing tightened
- Phase decode errors hardened; fallback synthesis focus sanitised
- North Star section token match anchored to prevent substring corruption

---

## [0.1.0] — 2026-04-17 — Bootstrap

### Added
- `submit_review` tool with `RedactionEngine` — posts structured PR verdicts to GitHub
- `clock_in` tool — session lifecycle open with context synthesis
- `clock_out` tool — session lifecycle close with redacted archival
- `get_context` tool — read-only context synthesis (zero side-effects)
- CI pipeline via GitHub Actions (pytest, ruff, mypy, black)
- `.hestai/` governance directory structure
- Product North Star document established
- Provider-agnostic design: stdio JSON-RPC transport via `python -m hestai_context_mcp`

### Fixed
- `.hestai/state` three-tier symlink convention enforced in `SessionManager`
- Symlink target validated in `ensure_hestai_structure`
- Plain-file collision at `.hestai/state` handled
- CI: `setup-uv` `python-version` flag corrected; workflow hardening applied

---

[Unreleased]: https://github.com/elevanaltd/hestai-context-mcp/compare/v0.9.0...HEAD
[0.9.0]: https://github.com/elevanaltd/hestai-context-mcp/compare/v0.8.0...v0.9.0
[0.8.0]: https://github.com/elevanaltd/hestai-context-mcp/compare/v0.7.0...v0.8.0
