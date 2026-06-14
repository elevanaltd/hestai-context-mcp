# Architecture

## Role in the HestAI Ecosystem

`hestai-context-mcp` is the **Memory and Environment** service in the HestAI three-service model (ADR-0353):

```
┌─────────────────────────────────────────────────────────┐
│                    AI Agent (any provider)               │
└────────────────┬──────────────────┬─────────────────────┘
                 │ MCP (stdio)      │ MCP (stdio)
        ┌────────▼───────┐  ┌───────▼────────┐
        │    Workbench   │  │      Vault     │
        │  Eyes & Hands  │  │      DNA       │
        │  UI, dispatch  │  │  agent defs,   │
        │  orchestration │  │  skills, stds  │
        └────────────────┘  └────────────────┘
                 │ MCP (stdio)
        ┌────────▼───────────────────────────┐
        │       hestai-context-mcp           │
        │       Memory & Environment         │
        │  sessions, context, learnings,     │
        │  governance records                │
        └────────────────────────────────────┘
```

The memory service accumulates over time. When an agent calls `clock_in`, it receives
the full project context — North Stars, decisions, git state, phase constraints, and
portable state from prior sessions — without any human explanation.

## Transport

Stdio JSON-RPC (MCP protocol). The server is spawned per invocation by the AI client.
No daemon, no ports, no persistent process. Configuration is loaded once at startup
from environment variables, keyring, and `.env`.

## Module Layout

```
src/hestai_context_mcp/
├── server.py                    # FastMCP instance, tool registration, .env loading
├── tools/                       # MCP tool implementations (thin layer, delegates to core/)
│   ├── clock_in.py
│   ├── clock_out.py
│   ├── get_context.py           # PURITY_GUARD::G3 — zero storage/ imports allowed here
│   ├── submit_review.py
│   ├── submit_governance.py
│   ├── list_decisions.py
│   ├── lookup_decision.py
│   ├── trace_supersedure.py
│   ├── governance/              # AGR read primitives and write pipeline
│   │   ├── agr_read.py          # Shared: TOKEN resolution, chain walking, OCTAVE parsing
│   │   ├── type_checker.py      # Gate A: regex content validation
│   │   ├── linker.py            # AMENDS/EXTENDS edge resolution, PR creation
│   │   ├── manifest.py          # .hestai/MANIFEST.md TOKEN index generation
│   │   ├── lexer.py             # OCTAVE tokenization
│   │   └── lineage.py           # SUPERSEDED_BY edge tracking
│   └── shared/
│       ├── github_auth.py       # GitHub token: env → gh CLI → error
│       └── review_formats.py    # Review comment formatting, gate-clear checks
├── core/                        # Domain logic
│   ├── session.py               # SessionManager: lifecycle, focus conflict detection
│   ├── synthesis.py             # AI synthesis seam (provider-agnostic AIClient port)
│   ├── context_steward.py       # Phase-constraint extraction from workflow files
│   ├── git_state.py             # Branch, ahead/behind, modified files
│   ├── north_star_parser.py     # Extracts scope_boundaries and immutables from North Star
│   ├── focus.py                 # Focus resolution: explicit > GitHub issue > branch > default
│   ├── phase.py                 # Phase resolution from .hestai state
│   ├── redaction.py             # Credential redaction (7 patterns, fail-closed)
│   ├── intake_pipeline.py       # Gate C prose mode: Stage 1-2 (context + AI compilation)
│   ├── intake_compiler.py       # AI prose→OCTAVE compilation with cost capping
│   ├── governance_reviewer.py   # Stage 5: async semantic review at analysis tier
│   ├── agent_readable_governance_parser.py  # OCTAVE DECISION_RECORD parsing, UPOG compliance
│   └── transcript/
│       ├── base.py              # TranscriptMessage value type
│       ├── claude.py            # Claude-format transcript parser
│       └── registry.py         # detect_parser: multi-provider adapter factory
├── ports/                       # Dependency-inversion boundary (protocols only, no impl)
│   ├── ai_client.py             # AIClient protocol: CompletionRequest, CompletionResponse
│   └── octave_validator.py      # OctaveValidator port: feature-detects octave-mcp, degrades gracefully
├── adapters/                    # Implementations of ports
│   ├── openai_compat_ai_client.py  # OpenAI-compat HTTP client via httpx
│   └── ai_config.py             # Credential resolution: env → keyring → .env
└── storage/                     # Portable Session State (ADR-0013)
    ├── protocol.py              # StorageAdapter @runtime_checkable Protocol
    ├── local_filesystem.py      # LocalFilesystemAdapter: append-first, hash-validated
    ├── identity.py              # IdentityTuple validation
    ├── identity_resolver.py     # Resolves identity from project context
    ├── schema.py                # Artifact schema validation, version negotiation
    ├── types.py                 # PortableMemoryArtifact, TombstoneArtifact, unions
    ├── projection.py            # Applies tombstones → derives active artifact set
    ├── snapshots.py             # Named session snapshots bound to session_id
    ├── outbox.py                # Durable outbox for failed publishes (R7)
    └── provenance.py            # Redaction source tracking, fail-closed (RISK_010)
```

## Key Abstractions

### Ports and Adapters

External dependencies (AI providers, OCTAVE validator) are hidden behind protocol interfaces
in `ports/`. Adapters in `adapters/` provide the implementations. This is what makes the
server provider-agnostic (North Star PROD::I3) and legacy-independent (PROD::I6).

```
tools/ → core/ → ports/AIClient ←→ adapters/openai_compat_ai_client.py
                  ports/OctaveValidator ←→ (optional) octave-mcp
```

### Storage and Portable Session State

The `storage/` subsystem implements Portable Session State (ADR-0013). When `clock_out`
runs, it writes `PortableMemoryArtifact` objects to the local filesystem. When `clock_in`
runs in a subsequent session, it restores those artifacts, giving the new agent continuity
with prior sessions.

Tombstones (`TombstoneArtifact`) mark deleted artifacts. `projection.py` applies tombstones
to derive the active set. Failed writes go to a durable outbox (`outbox.py`) for manual retry.

### AGR Read Primitives

`tools/governance/agr_read.py` is the single source of truth for working with
Agent-Readable Governance Records on disk:

- `iter_record_paths(working_dir)` — yields all `.oct.md` files under `.hestai/decisions/`
- `discover_record(working_dir, token)` — finds a specific record by TOKEN
- `load_parsed(path)` — parses OCTAVE DECISION_RECORD content into structured fields
- `walk_supersession_chain(working_dir, token)` — follows SUPERSEDED_BY pointers to terminal state

All three read tools (`list_decisions`, `lookup_decision`, `trace_supersedure`) delegate to
these primitives. The primitives are pure read — no writes, no side effects.

### Governance Intake Pipeline

`submit_governance` supports two mutually-exclusive modes:

```
Mode A (octave_content):
  Raw OCTAVE → Gate A (regex) → Gate B (octave-mcp, optional) → link edges → PR

Mode C (prose_input):
  Prose → Stage 1 (context assembly) → Stage 2 (AI compilation) →
  Gate A → Gate B → Stage 5 (semantic review) → link edges → PR
```

Gate B requires the `validation` extra (`uv sync --extra validation`). Without it, Gate B
is skipped — Gate A (regex) is always enforced. This preserves PROD::I6: octave-mcp is
optional, not a hard dependency.

## Design Decisions

### Fail-Closed Credential Redaction

`clock_out` runs the `RedactionEngine` against the transcript before writing the archive.
If redaction raises an exception or detects that it would produce an unsafe output, the
archive write is blocked. The session record shows an error rather than writing a
potentially-sensitive file. This implements PROD::I2 (Credential Safety): data loss is
preferred over data exposure.

Seven credential patterns are detected: AI API keys, AWS credentials, database URIs
(Postgres, MySQL, Redis), GitHub PATs, generic high-entropy tokens, and common API key
patterns.

### Pure Read Enforcement for `get_context`

`get_context` is called by the Payload Compiler (Position 3), which may invoke it
repeatedly, in parallel, or speculatively. It must have zero side effects (PROD::I5).

This is enforced at two levels:
1. **Source-level**: `get_context.py` imports nothing from `storage/`. A static test
   (`tests/storage/test_source_invariants_pss.py`) verifies this assertion.
2. **Design-level**: The function is a pure computation over files it reads — no writes,
   no session creation, no PSS restoration.

### Supersession DAG

Governance records can supersede prior records via the `SUPERSEDED_BY` field. This creates
a directed acyclic graph of decisions. `trace_supersedure` walks this DAG to find the
terminal ratified state for any given token.

Cycle detection is fail-closed: the tool tracks visited tokens and returns
`CHAIN_CYCLE_DETECTED` if a token appears twice, rather than looping indefinitely.
A broken link (`CHAIN_BROKEN`) signals a governance integrity problem — a `SUPERSEDED_BY`
pointer references a token that does not exist on disk.

### Optional octave-mcp Integration

The OCTAVE validator runs inside the governance intake pipeline (Gate B). It is exposed
as a port (`OctaveValidator`) and feature-detected at runtime:

```python
# ports/octave_validator.py — simplified
try:
    from octave_mcp import validate
    return RealOctaveValidator(validate)
except ImportError:
    return UnavailableOctaveValidator()  # Gate B skipped, Gate A (regex) still enforced
```

This means the server works without octave-mcp installed. Installing `--extra validation`
enables stricter governance record checking.

### Provider Agnostic Transcript Parsing

`core/transcript/registry.py` implements `detect_parser(transcript_content)`. It inspects
the transcript structure and returns the appropriate parser:

- Claude Code JSONL format → `ClaudeTranscriptParser`
- (Future providers: Gemini, Codex, Goose parsers can be added without changing callers)

Callers in `clock_out` never reference a specific parser — they call `detect_parser` and
receive an adapter. This preserves PROD::I3.

## `.hestai/` Directory

The `.hestai/` directory is both consumed and written by this server. Key paths:

```
.hestai/
  north-star/            # Product North Star (OCTAVE) — read by get_context, clock_in
  decisions/             # AGR corpus — read by list/lookup/trace, written by submit_governance
    rfc-arch/            # Architectural ADRs (OCTAVE and prose)
    security/            # Security design records
  state/
    sessions/active/     # Live session metadata and transcripts
    portable/pss/        # Portable session state artifacts
    outbox/              # Failed publish queue
  context/
    PROJECT-CONTEXT.oct.md  # Project state summary — read by clock_in, get_context
  workflow/
    OPERATIONAL-WORKFLOW.oct.md  # Phase constraints — read by ContextSteward
  MANIFEST.md            # TOKEN index (auto-generated by submit_governance)
```

The server never writes to `north-star/` or `workflow/` — those are human-maintained.
It writes to `state/`, `decisions/`, and `MANIFEST.md`.
