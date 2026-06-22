# hestai-context-mcp

Persistent memory and environmental context for AI-assisted development. An MCP server that gives any AI agent instant project awareness — decisions made, learnings accumulated, current git and project state — without human explanation.

## Overview

`hestai-context-mcp` is the **Memory and Environment** service in the HestAI three-service architecture:

| Service | Role |
|---------|------|
| **Workbench** | Eyes and Hands — UI, dispatch, agent orchestration |
| **Vault** | DNA — agent definitions, skills, governance standards |
| **hestai-context-mcp** | Memory and Environment — session state, context synthesis, learnings, governance records |

Each development session reads from accumulated memory (decisions, learnings, git state, project context) and writes back to it (learnings extraction, governance records). The next agent session starts smarter than the last.

## Quick Start

**Prerequisites:** Python 3.11+, `uv`, Git

```bash
# Clone and install
git clone https://github.com/elevanaltd/hestai-context-mcp.git
cd hestai-context-mcp
uv sync                      # core dependencies only
uv sync --extra validation   # adds real OCTAVE validator (recommended)

# Register with your AI clients
bash setup_local_configs.sh  # registers with Claude Code, Gemini CLI, Codex, Goose
```

The server runs over stdio JSON-RPC. No daemon, no ports — your AI client spawns it per session via the MCP protocol.

## MCP Tools

Eight tools, all returning structured dicts with defined fields. See [`docs/tools.md`](docs/tools.md) for full parameter and return-shape reference.

### Session Lifecycle

| Tool | Description |
|------|-------------|
| `clock_in(role, working_dir, focus?)` | Start a session. Discovers North Stars, project context, phase constraints, and git state. Restores portable session state from prior sessions. |
| `clock_out(session_id, transcript_parser?, transcript_content?)` | End a session. Extracts learnings, redacts credentials (fail-closed), archives transcript, publishes portable state. |

### Context Synthesis

| Tool | Description |
|------|-------------|
| `get_context(working_dir)` | Pure read. Same context structure as `clock_in` without session creation. Zero side effects — safe for repeated or parallel calls. |

### Review Infrastructure

| Tool | Description |
|------|-------------|
| `submit_review(repo, pr_number, role, verdict, assessment, commit_sha?, dry_run?)` | Post a structured PR review verdict (8 reviewer roles, 3 verdicts: APPROVED / BLOCKED / CONDITIONAL). |

### Governance

| Tool | Description |
|------|-------------|
| `submit_governance(working_dir, octave_content?, prose_input?, dry_run?)` | Create a governance record. Accepts raw OCTAVE or plain prose (AI-compiled). Handles validation, token assignment, and PR creation automatically. |
| `list_decisions(working_dir, scope?, status?, tier?)` | List Agent-Readable Governance Records (AGRs) with optional filtering by scope, status, or tier. |
| `lookup_decision(working_dir, token, audience?)` | Resolve a single AGR by TOKEN. Returns the full record and supersession resolution chain. |
| `trace_supersedure(working_dir, token)` | Walk the supersession chain from a TOKEN to its terminal ratified state. Detects cycles and broken links. |

## Configuration

The server loads configuration at startup from these sources, in priority order:

1. Process environment variables
2. Keyring (service name: `ai_config`)
3. `.env` file in the repo root or current working directory

**Variables:**

| Variable | Purpose | Required |
|----------|---------|----------|
| `OPENROUTER_API_KEY` | AI provider key for prose-mode governance compilation | Only if using `prose_input` in `submit_governance` |
| `HESTAI_AI_MODEL` | Model for prose compilation / synthesis (e.g. `openai/gpt-4o`); optional `HESTAI_AI_MODEL_ANALYSIS` / `HESTAI_AI_MODEL_CRITICAL` per tier | Only if using prose mode |
| `PER_REPO_OVERRIDE` | When set truthy (`true`/`1`/`yes`/`on`) in a **caller repo's** `.env`, AI-model resolution uses that repo's own `HESTAI_AI_MODEL[_TIER]`; otherwise the model is centralized (the launching process environment wins, consistent across all repos). See `HO-INTAKE-MODEL-RESOLUTION-CENTRALIZED-20260620`. | Optional (per-repo opt-in) |
| `GITHUB_TOKEN` | GitHub PAT for `submit_review` and `submit_governance` PR creation | For governance and review tools |

## Claude / Agent Configuration

Add the following block to `~/.claude/CLAUDE.md` (applies to all repos) to wire up
the decision lookup discipline and governance record exception:

```
===DECISION_LOOKUP_DISCIPLINE===
⚠️::BLOCKING_DIRECTIVE
SCOPE::ALL_repos[hestai-context_enabled]
TRIGGER::before_work[architectural∨scope_affecting∨security∨db_schema]
PRECONDITION:
  STEP_0::[token_unknown→mcp__hestai-context__list_decisions[working_dir]→identify_relevant_token]
  STEP_1::mcp__hestai-context__lookup_decision[token∧working_dir]
  STEP_2::[token_resolves→mcp__hestai-context__trace_supersedure[token∧working_dir]→terminal_ratified_state]
RESULT_HANDLING::[honour_ratified_decisions∧NO_relitigate→escalate_requirements-steward]
CREATION_PATH::[new_decisions→mcp__hestai-context__submit_governance[prose_input∧working_dir]]
===END_DECISION_LOOKUP_DISCIPLINE===
```

If your project also uses the `octave` MCP server, add this exception line inside your
existing `===OCTAVE_WRITE_GATE===` block (after `MAIN_AUTHOR::octave-secretary`):

```
EXCEPTION_DECISION_RECORD::[.hestai/decisions/[DECISION_RECORD]→mcp__hestai-context__submit_governance[prose_input∧working_dir]∧NOT_octave_write]
```

**What this does:**
- Before any architectural, scope, security, or DB-schema work: scan the decision
  corpus (`list_decisions`), resolve a specific record (`lookup_decision`), walk the
  supersedure chain to the terminal ratified state (`trace_supersedure`)
- Ratified decisions are binding — no re-litigation without escalating to
  requirements-steward
- New decisions are authored via `submit_governance(prose_input, working_dir)` —
  the tool handles OCTAVE compilation, token assignment, and PR creation
- `octave_write` is NOT used for governance records

## Design Principles

Six immutable constraints govern this service. Any change that violates one requires
escalation to the requirements steward — they are not negotiable at implementation time.

1. **Session Lifecycle Integrity** — Every session has a clean create-and-archive lifecycle. Orphaned sessions are failures, not acceptable state.
2. **Credential Safety** — Zero credentials persist in archives. Redaction is fail-closed: no archive rather than an unredacted one.
3. **Provider Agnostic Context** — Context synthesis is identical across Claude, Codex, Gemini, and Goose. No provider-specific fields.
4. **Structured Return Shapes** — All tools return structured dicts with defined fields, never unstructured blobs.
5. **Read-Only Context Query** — `get_context` has zero side effects. Pure read, idempotent, safe for parallel calls.
6. **Legacy Independence** — No runtime dependency on the legacy `hestai-mcp` package, enabling A/B comparison without cascade.

## Development

```bash
# Lint and type check
.venv/bin/python -m ruff check src
.venv/bin/python -m mypy src

# Run tests
.venv/bin/python -m pytest

# With coverage report
.venv/bin/python -m pytest --cov=hestai_context_mcp --cov-report=term-missing
```

CI enforces 85% coverage minimum, strict mypy, ruff, and black on every push.

## Further Reading

- [`docs/tools.md`](docs/tools.md) — Full tool reference: parameters, return shapes, error envelopes
- [`docs/architecture.md`](docs/architecture.md) — Module layout, internal abstractions, key design decisions
- [`.hestai/north-star/000-HESTAI-CONTEXT-MCP-NORTH-STAR.md`](.hestai/north-star/000-HESTAI-CONTEXT-MCP-NORTH-STAR.md) — Full product North Star (immutables, assumptions, gates, escalation)
- [`.hestai/decisions/rfc-arch/ADR-RFC-ARCH-004-agent-readable-governance-records.md`](.hestai/decisions/rfc-arch/ADR-RFC-ARCH-004-agent-readable-governance-records.md) — AGR format spec and tool contracts
