---
type: NORTH_STAR
id: hestai-context-mcp-north-star
version: 1.0
status: APPROVED
purpose: Product North Star for hestai-context-mcp — the Memory and Environment service
inherits: system-hestai-north-star
created: 2026-04-17
namespace: PROD
---

# HESTAI-CONTEXT-MCP PRODUCT NORTH STAR

**Product**: hestai-context-mcp
**Purpose**: Persistent memory and environmental context for AI-assisted development sessions
**Phase**: B1 (Phase 1 harvest complete, 4 tools operational)
**Status**: APPROVED
**Approved By**: Human operator (2026-04-17)

---

## COMMITMENT STATEMENT

This North Star document establishes the immutable requirements for **hestai-context-mcp**.

**Authority**: All work on this product (B0-B5 phases) must align with these requirements. Any detected misalignment triggers immediate escalation per the Protection Clause below.

**Amendment Process**: Changes to immutables require formal review and re-approval. This is a binding commitment, not a living suggestion.

**Inheritance**: This document inherits from and must satisfy the System North Star (SYS::I1-I6). Where a PROD immutable conflicts with a SYS immutable, the SYS immutable takes precedence per System Standard section 4.

---

## PROTECTION CLAUSE

If ANY agent (or human) detects misalignment between work and this North Star:

1. **STOP** current work immediately.
2. **CITE** the specific North Star requirement being violated (e.g., PROD::I3).
3. **ESCALATE** to the project lead for resolution.

**Resolution Options**:
- CONFORM work to North Star requirements.
- AMEND North Star (requires formal process).
- ABANDON incompatible implementation path.

---

## SECTION 1: IDENTITY

### Core Purpose

hestai-context-mcp exists to solve one problem: **AI agents have no persistent memory across sessions, and projects need months of accumulated context to be productive.**

This service is the Memory and Environment in a three-service architecture (ADR-0353):
- **Workbench** (Eyes and Hands): UI, dispatch, Payload Compiler
- **Vault** (DNA): Agent definitions, skills, cognitions, standards
- **hestai-context-mcp** (Memory and Environment): THIS SERVICE

The destination: any AI agent, on any provider, dispatched by any mechanism, can clock into a project and immediately receive the full accumulated context of that project -- what has been decided, what has been learned, what the current state is -- without asking a human to explain it.

### What hestai-context-mcp IS

hestai-context-mcp is **the institutional memory of the development environment**.

It is:
- **A session lifecycle manager**: Clean create-and-archive lifecycle for agent work sessions (clock_in / clock_out)
- **A context synthesis engine**: Reads .hestai/ state, North Stars, git state, and project context to return structured environmental awareness
- **A learnings extraction pipeline**: Parses transcripts, redacts credentials, indexes decisions/blockers/learnings for future sessions
- **A review infrastructure**: Structured PR review verdicts with CI gate clearing, multi-role review, dry-run validation
- **A read-only context provider**: The Payload Compiler (Workbench) calls get_context at KVAEPH Position 3 for zero-side-effect context synthesis
- **A stdio MCP server**: Python, JSON-RPC, subprocess transport. The "Git/VS Code" pattern -- no daemon, no ports, no monitoring

**Core Metaphor**: The project's long-term memory. Each session reads from it (context synthesis) and writes back to it (learnings extraction). The memory accumulates. The next agent is smarter than the last because this service remembers what happened.

### What hestai-context-mcp IS NOT

hestai-context-mcp is NOT:
- **NOT an identity/governance system**: Agent definitions, skills, cognitions, and standards binding live in the Vault. This service does not know or care WHO an agent is, only WHAT the project remembers.
- **NOT a UI or dispatch system**: No GUI, no agent dispatch, no CLI spawning. That is the Workbench.
- **NOT a deliberation system**: No debates, no Wind/Wall/Door, no decision records. That is the Debate Hall.
- **NOT a document format system**: No OCTAVE parsing, validation, or grammar compilation. That is octave-mcp.
- **NOT a SaaS product**: Local-first, stdio transport, single-developer tool. No network ports, no authentication, no multi-tenancy.
- **NOT a replacement for hestai-mcp (legacy)**: The legacy system stays operational for A/B comparison. This is a harvest, not a migration.
- **NOT a .hestai-sys/ injector**: The .hestai-sys/ governance library is owned by the Vault/Workbench. This service reads .hestai/ (project state), not .hestai-sys/ (system governance).

---

## SECTION 2: THE UNCHANGEABLES (6 IMMUTABLES)

These requirements are **binding for the entire product**. Each has been evaluated against the Immutability Oath:
1. *Is this truly immutable?*
2. *Would we reject a faster/cheaper solution if it violated this?*
3. *Will this still be true in 3 years?*

---

### I1: SESSION LIFECYCLE INTEGRITY

**Requirement**: Every agent session must have a clean, complete lifecycle: creation (clock_in) and archival (clock_out). A session that is created must be archivable. A session that is archived must have been created. Orphaned sessions are a system failure.

**Technology-Neutral Expression**: Work sessions produce persistent records with defined start and end boundaries. The recording mechanism may change; the lifecycle completeness requirement cannot.

**Rationale**: Without lifecycle integrity, the memory accumulation model collapses. If sessions can be created without archival, learnings are lost. If sessions can be archived without creation, the provenance chain breaks. The entire value proposition of this service depends on sessions being complete units of work with discoverable outcomes.

**Validation Plan**:
- Every clock_in returns a session_id that clock_out can consume
- Active sessions are discoverable via directory scan
- Archived sessions contain session metadata, redacted transcript, and extracted learnings
- No code path allows session creation without a corresponding archival mechanism

---

### I2: CREDENTIAL SAFETY

**Requirement**: No credentials (API keys, tokens, passwords, secrets) may persist in archived session data. The RedactionEngine operates fail-closed: if redaction fails, archival is blocked rather than proceeding with unredacted content.

**Technology-Neutral Expression**: Sensitive authentication material must be removed from persistent records before storage. The removal mechanism may evolve; the fail-closed behavior and zero-persistence guarantee cannot.

**Rationale**: Session transcripts contain whatever the agent and user discussed, including environment variables, API keys pasted in error, and token values. A single leaked credential in an archived transcript is a security incident. The fail-closed design means the system chooses data loss (no archive) over data exposure (unredacted archive). This is the correct trade-off and it is not negotiable.

**Validation Plan**:
- RedactionEngine detects all credential pattern categories (AI API keys, AWS keys, database URIs, generic tokens, etc.)
- Redaction replaces matched content with non-reversible markers
- If RedactionEngine.copy_and_redact raises an exception, clock_out does NOT write an archive file
- Credential patterns are tested against real-world format examples

---

### I3: PROVIDER-AGNOSTIC CONTEXT

**Requirement**: Context synthesis must work identically regardless of which AI provider, model, or CLI tool calls the service. The structured return shape of clock_in and get_context must not contain provider-specific fields, assumptions, or formatting.

**Technology-Neutral Expression**: The context interface must be consumption-agnostic. Any caller that can send JSON-RPC over stdio can use the service. The transport and protocol may evolve; the provider independence cannot.

**Rationale**: The three-service architecture (ADR-0353) separates concerns precisely so that provider choice is a Workbench registry decision, not a context engine dependency. If hestai-context-mcp returns Claude-specific formatting or assumes Codex-specific transcript structures, the entire multi-provider vision collapses. Provider agnosticism has been validated across Claude, Codex, Gemini, and Goose. This immutable protects that validation.

**Validation Plan**:
- Tool return shapes contain no provider-specific fields
- Transcript parsing uses adapter pattern (detect_parser) that supports multiple formats
- get_context returns identical structure regardless of caller identity
- No import or runtime dependency on any specific AI provider SDK

---

### I4: STRUCTURED RETURN SHAPES

**Requirement**: All MCP tool responses must return structured dictionaries with defined fields per the interface contract. Tools must never return unstructured text blobs, raw file contents without wrapping, or inconsistent field shapes between success and error cases.

**Technology-Neutral Expression**: Service interfaces must return self-describing, machine-parseable responses with consistent schema. The specific fields may evolve through versioned contracts; the structural discipline cannot.

**Rationale**: The Payload Compiler (Workbench) programmatically extracts fields from tool responses to assemble KVAEPH payloads. If clock_in returns a blob instead of structured fields, the Compiler cannot extract product_north_star from context.product_north_star. If error responses have different shapes than success responses, every consumer needs special-case handling. Structured returns are the API contract that makes the three-service architecture composable.

**Validation Plan**:
- Every tool function has a documented return type (dict[str, Any] with specified keys)
- Success and error responses share the same top-level field set
- Return values are JSON-serializable without custom encoders
- No tool returns raw file contents without a wrapping dictionary

---

### I5: READ-ONLY CONTEXT QUERY

**Requirement**: get_context must have zero side effects. It must not create sessions, write files, mutate state, or produce any observable change to the project directory. It is a pure read operation.

**Technology-Neutral Expression**: Context query operations must be side-effect-free. The query mechanism may change; the zero-mutation guarantee cannot.

**Rationale**: get_context is the KVAEPH Position 3 call that the Payload Compiler makes during prompt assembly. The Compiler may call it repeatedly, speculatively, or in parallel for multiple agents. If get_context creates sessions or writes state, repeated calls produce session spam, race conditions, and corrupted state. The zero-side-effect guarantee makes get_context safe for any calling pattern. This is a separate tool from clock_in specifically because clock_in HAS side effects (session creation) and get_context must NOT.

**Validation Plan**:
- get_context creates no files or directories
- get_context modifies no existing files
- Calling get_context N times produces identical results (idempotent)
- No SessionManager write methods are called from get_context code path
- Test: snapshot filesystem before get_context, snapshot after, assert identical

---

### I6: LEGACY INDEPENDENCE

**Requirement**: hestai-context-mcp must not import from, depend on, or require the legacy hestai-mcp codebase at runtime or install time. The two systems coexist independently for A/B comparison.

**Technology-Neutral Expression**: New systems must not create runtime dependencies on the systems they replace. The migration strategy may evolve; the independence constraint cannot.

**Rationale**: ADR-0353 chose harvest (new repo from proven code) over subtraction (modifying legacy in place). This was deliberate: the legacy system stays operational so the same agent + same task can be tested under both systems. If hestai-context-mcp imports from hestai-mcp, changes to the legacy system break the new system, and the A/B comparison becomes impossible. Independence also ensures that when the legacy system is eventually deprecated, hestai-context-mcp has no cascading dependency to manage.

**Validation Plan**:
- No import statement references hestai_mcp (the legacy package)
- pyproject.toml has no dependency on hestai-mcp
- The service starts and passes all tests without hestai-mcp installed
- CI runs in an environment where hestai-mcp is not present

---

## SECTION 3: CONSTRAINED VARIABLES

These aspects are important but negotiable within the constraints of the immutables above.

| Area | Immutable Aspect | Flexible Aspect | Negotiable Aspect |
|------|------------------|-----------------|-------------------|
| **Transport** | Stdio JSON-RPC (proven pattern) | Protocol version | Additional transports (SSE, HTTP) |
| **Transcript Parsing** | Provider-agnostic adapter pattern (I3) | Specific parser implementations | Parser discovery heuristics |
| **Archival Format** | Redacted, structured, persistent (I1, I2) | JSONL vs OCTAVE vs other format | Compression strategy |
| **Context Fields** | Structured dict with defined keys (I4) | Specific field names and nesting | Additional context sources |
| **Phase Constraints** | Read from workflow files (read-only) | ContextSteward implementation | Phase naming conventions |
| **Learnings Index** | JSONL append-only index | Index schema fields | Search/query capabilities |
| **Review Roles** | Structured verdict format (I4) | Number and names of roles | Gate-clearing patterns |
| **Coverage** | 85% minimum (CI-enforced) | Specific test strategies | Marker taxonomy |

---

## SECTION 4: ASSUMPTION REGISTER

| ID | Assumption | Source | Risk if False | Confidence | Impact | Validation Plan |
|----|-----------|--------|---------------|-----------|--------|-----------------|
| A1 | Stdio subprocess transport is sufficient for all consumers | ADR-0353 | Need daemon/network transport, adds operational complexity | 85% | HIGH | Workbench integration testing |
| A2 | JSONL learnings index scales to hundreds of sessions | Implementation choice | Need database or indexed storage | 80% | MEDIUM | Load test at 500+ sessions |
| A3 | Transcript parsing adapter pattern covers future providers | Architecture decision | New provider requires new parser, but pattern supports it | 90% | LOW | Add parser when new provider appears |
| A4 | RedactionEngine credential patterns cover real-world leaks | Security design | Undetected credential type persists in archive | 75% | CRITICAL | Periodic audit against new credential formats |
| A5 | get_context response is sufficient for Payload Compiler Position 3 | Interface contract | Compiler needs fields not provided, requires contract revision | 80% | HIGH | First Payload Compiler integration |
| A6 | Single .hestai/ directory structure works for all project layouts | Convention | Monorepo or non-standard layouts need different discovery | 75% | MEDIUM | Test with 3+ project structures |
| A7 | Phase 1 (4 tools) covers the minimum viable context engine | Harvest scope | Missing tool blocks Workbench integration | 85% | HIGH | Workbench Step 3A integration |
| A8 | Focus resolution from branch names provides useful session context | Implementation | Branch names are not meaningful, focus is always "general" | 70% | LOW | Observe focus values in real sessions |

### CRITICAL ASSUMPTIONS (Must validate before next phase)

- **A4**: RedactionEngine coverage is security-critical. A missed credential pattern is a data exposure incident. Periodic audit required.
- **A5**: The Payload Compiler integration (Workbench Step 3A) will be the first real consumer of get_context. If the return shape is insufficient, the interface contract needs revision before Phase 2.

---

## SECTION 5: SUCCESS CRITERIA

### This service is succeeding when:

1. **Context continuity**: An agent clocking into a project immediately knows what happened in the last session without human explanation.
2. **Zero credential exposure**: No archived session transcript contains detectable credentials. Ever.
3. **Provider blindness**: Claude, Codex, Gemini, and Goose agents all receive identical context from get_context.
4. **Payload Compiler integration**: The Workbench calls get_context at KVAEPH Position 3 and programmatically extracts fields without special-case handling.
5. **Learnings accumulation**: The learnings index grows with each session. Decisions, blockers, and learnings from past sessions are discoverable.
6. **Clean lifecycle**: Active sessions count stays bounded. clock_out reliably archives and cleans up. No orphaned session directories accumulate.
7. **Independence proven**: The service runs, tests pass, and agents work without hestai-mcp installed anywhere.

### This service has failed when:

1. A credential appears in an archived transcript.
2. get_context produces different results for different providers.
3. get_context creates files or directories as a side effect.
4. The Payload Compiler cannot programmatically extract context fields from tool responses.
5. Session directories accumulate without archival.
6. A change to hestai-mcp breaks this service.

---

## SECTION 6: CURRENT PHASE ASSESSMENT

**Phase**: B1 (First functional build complete)

**What exists**:
- 4 MCP tools operational: clock_in, clock_out, get_context, submit_review
- Core modules: SessionManager, ContextSteward, RedactionEngine, FocusResolver, GitStateDetector
- Transcript parsing with provider adapter pattern
- 361 tests, 89% coverage, Python 3.11/3.12 CI
- All quality gates green (ruff, black, mypy, pytest)
- Product North Star (this document) established

**What does not yet exist**:
- OCTAVE compression for archived transcripts (Phase 2)
- Full Claude transcript path discovery heuristic (Phase 2)
- Workbench Payload Compiler integration testing (depends on Workbench Step 3A)
- submit_friction_record tool (F2D governance feedback, Phase 2)
- Load testing of learnings index at scale (A2 validation)

**Next milestone**: Workbench Step 3A integration -- the Payload Compiler calls get_context and clock_in, proving the interface contract works in practice.

---

## SECTION 7: ANTI-PATTERNS

These are the specific failure modes this North Star is designed to prevent:

1. **Context creep**: Adding governance, identity, or deliberation logic to this service. Those belong in the Vault, Workbench, and Debate Hall respectively. This service owns memory and environment, nothing more.

2. **Provider coupling**: Adding provider-specific logic (Claude transcript assumptions, Codex-specific formatting) to the context engine. The adapter pattern exists precisely to isolate provider specifics in parsers.

3. **Silent credential leakage**: Weakening the fail-closed redaction guarantee for convenience. If the choice is "lose the archive" or "risk credential exposure," the correct answer is always lose the archive.

4. **Blob returns**: Returning raw file contents, unstructured text, or inconsistent response shapes from tools. Every response must be a structured dictionary that a machine can parse.

5. **Side-effect queries**: Making get_context "smarter" by having it create sessions, update caches, or write state. The zero-side-effect guarantee is what makes it safe for the Payload Compiler to call freely.

6. **Legacy entanglement**: Importing from or depending on hestai-mcp "just for this one utility." Independence is binary. The moment a dependency exists, A/B comparison is compromised.

---

## SECTION 8: COMMITMENT CEREMONY RECORD

**Date**: 2026-04-17
**Approver**: Human operator
**Status**: APPROVED

**Ceremony Transcript**:
> **Architect**: "Do you approve these 6 Immutables as the binding North Star for hestai-context-mcp? Each has been evaluated against the Immutability Oath. The service identity, boundary clarity, and assumption register are documented above."
> **User**: "Both documents reviewed. The 6 immutables are well-chosen and directly map to ADR-0353's architectural decisions. Approved."

**Binding Authority**: This document is the authoritative requirements baseline for all hestai-context-mcp development. Misalignment triggers the Protection Clause.

---

**END OF NORTH STAR**
