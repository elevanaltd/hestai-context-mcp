# Tool Reference

All tools are exposed over stdio JSON-RPC via the MCP protocol. All return structured dicts
with defined fields — never unstructured blobs (North Star PROD::I4).

---

## `clock_in`

Register the start of an agent session. Returns a full context snapshot the agent can use
immediately without further queries.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `role` | string | yes | Agent role identifier (e.g. `implementation-lead`, `holistic-orchestrator`) |
| `working_dir` | string | yes | Absolute path to the project root |
| `focus` | string | no | Optional focus override (GitHub issue URL, topic string, or branch-derived) |

**Return shape:**

```json
{
  "session_id": "uuid",
  "role": "implementation-lead",
  "focus": "issue #42 — add trace_supersedure tool",
  "focus_source": "explicit | github_issue | branch | default",
  "branch": "feat/trace-supersedure",
  "working_dir": "/path/to/project",
  "phase": "B1_FOUNDATION_COMPLETE",
  "context_paths": ["path/to/north-star.md", "..."],
  "ai_synthesis": "...",
  "context": {
    "product_north_star": "...",
    "project_context": "...",
    "phase_constraints": "...",
    "git_state": { "branch": "...", "modified_files": [], "ahead": 0, "behind": 0 },
    "active_sessions": [],
    "conflicts": []
  },
  "portable_state": {
    "restore_status": "restored | no_artifacts | identity_mismatch",
    "artifact_count": 3
  }
}
```

**Notes:**
- Detects focus conflicts when multiple sessions are active on the same working directory.
- Restores portable session state from prior sessions via the `LocalFilesystemAdapter`.
- Does not fail if North Star or project context files are absent — returns what is available.

---

## `clock_out`

Archive a session. Extracts learnings from the transcript, redacts credentials, and publishes
portable session state for the next agent.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `session_id` | string | yes | UUID returned by `clock_in` |
| `transcript_parser` | string | no | Parser hint: `"claude"` or omit for auto-detection |
| `transcript_content` | string | no | Raw transcript JSON/text to archive |

**Return shape:**

```json
{
  "session_id": "uuid",
  "archive_path": ".hestai/state/sessions/active/{uuid}/transcript-archive/...",
  "learnings": {
    "decisions": ["ADR: decided to use stdio transport because..."],
    "blockers": ["BLOCKER: octave-mcp validation unavailable in CI"],
    "learnings": ["LEARNING: redaction must run before archival, not after"]
  },
  "portable_publication": {
    "restore_status": "published | failed | empty",
    "identity": { "project_id": "...", "workspace_id": "...", "user_id": "..." },
    "artifact_count": 3,
    "snapshot_path": ".hestai/state/portable/pss/...",
    "errors": []
  }
}
```

**Notes:**
- Credential redaction is **fail-closed**: if redaction fails, no archive is written (North Star PROD::I2).
  The tool returns an error rather than writing a potentially-sensitive archive.
- Learnings are extracted by scanning transcript content for `DECISION:`, `BLOCKER:`, and `LEARNING:` markers.
- If `transcript_content` is omitted, archives an empty transcript record (session bookkeeping only).

---

## `get_context`

Pure read — no session created, no files written. Returns the same context structure as
`clock_in` minus session metadata. Safe for repeated and parallel calls (North Star PROD::I5).

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `working_dir` | string | yes | Absolute path to the project root |

**Return shape:**

```json
{
  "working_dir": "/path/to/project",
  "context": {
    "product_north_star": "...",
    "project_context": "...",
    "phase_constraints": "...",
    "git_state": { "branch": "...", "modified_files": [], "ahead": 0, "behind": 0 },
    "active_sessions": []
  }
}
```

**Notes:**
- Intended for the Payload Compiler (Position 3) which may call it repeatedly or in parallel.
- Enforced at source level: `get_context.py` has zero imports from the `storage/` subsystem
  (`PURITY_GUARD::G3`). This is verified by a static test.
- Equivalent to `clock_in` context without focus resolution, conflict detection, or PSS restore.

---

## `submit_review`

Post a structured PR review verdict to GitHub.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `repo` | string | yes | GitHub repo in `owner/repo` format |
| `pr_number` | integer | yes | Pull request number |
| `role` | string | yes | Reviewer role: `CE`, `CIV`, `CRS`, `HO`, `IL`, `PE`, `SR`, or `TMG` |
| `verdict` | string | yes | `APPROVED`, `BLOCKED`, or `CONDITIONAL` |
| `assessment` | string | yes | Prose assessment text |
| `commit_sha` | string | no | Specific commit SHA to review against |
| `dry_run` | boolean | no | If true, validates without posting to GitHub |

**Return shape:**

```json
{
  "success": true,
  "pr_url": "https://github.com/owner/repo/pull/42",
  "role": "CRS",
  "verdict": "APPROVED",
  "would_clear_gate": true,
  "error": null
}
```

**Reviewer roles:**

| Code | Role |
|------|------|
| `CE` | Continuity Evaluator |
| `CIV` | Critical Implementation Validator |
| `CRS` | Code Review Specialist |
| `HO` | Holistic Orchestrator |
| `IL` | Implementation Lead |
| `PE` | Product Evaluator |
| `SR` | Security Reviewer |
| `TMG` | Test Methodology Guardian |

---

## `submit_governance`

Create an Agent-Readable Governance Record (AGR). Accepts raw OCTAVE content (Gate A/B)
or plain prose (Gate C, AI-compiled). Handles validation, TOKEN assignment, and PR creation.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `working_dir` | string | yes | Absolute path to the project root |
| `octave_content` | string | no* | Pre-authored OCTAVE governance record |
| `prose_input` | string | no* | Plain prose description — compiled to OCTAVE by AI |
| `dry_run` | boolean | no | If true, validates without writing files or creating a PR |

*Exactly one of `octave_content` or `prose_input` must be provided.

**Intake pipeline:**

```
octave_content → Gate A (regex check) → Gate B (octave-mcp validation) → link → PR
prose_input    → Stage 1-2 (context + AI compilation) → Gate A → Gate B → Stage 5 (semantic review) → link → PR
```

**Return shape:**

```json
{
  "success": true,
  "token": "HO-MY-DECISION-TITLE-20260613",
  "card_type": "DECISION_RECORD",
  "target_path": ".hestai/decisions/HO-MY-DECISION-TITLE-20260613.oct.md",
  "branch": "governance/HO-MY-DECISION-TITLE-20260613",
  "pr_url": "https://github.com/owner/repo/pull/99",
  "validation_errors": [],
  "octave_validation": { "valid": true, "errors": [] },
  "semantic_review": { "verdict": "APPROVED", "notes": "..." },
  "metrics": { "stage_1_ms": 120, "stage_2_ms": 3400, "total_ms": 3800 },
  "dry_run": false
}
```

**Notes:**
- TOKEN format: `{NAMESPACE}-{SLUG}-{YYYYMMDD}` (e.g. `HO-CREDENTIAL-SAFETY-RATIFIED-20260611`)
- Prose mode requires `OPENROUTER_API_KEY` and `HESTAI_AI_MODEL` to be configured.
- Gate B (real OCTAVE validation) requires the `validation` extra: `uv sync --extra validation`.
  Without it, Gate B is skipped and Gate A (regex) is the only validator.
- `octave_write` is NOT the authoring path for governance records — use this tool.

---

## `list_decisions`

List Agent-Readable Governance Records in the project's decision corpus.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `working_dir` | string | yes | Absolute path to the project root |
| `scope` | string | no | Filter by scope prefix (e.g. `"HO"`, `"ADR-RFC-ARCH"`) |
| `status` | string | no | Filter by status: `"PROPOSED"`, `"RATIFIED"`, or `"SUPERSEDED"` |
| `tier` | string | no | Filter by tier: `"DIRECTIVE"`, `"STANDARD"`, `"GUIDELINE"`, `"PATTERN"` |

**Return shape:**

```json
{
  "ok": true,
  "records": [
    {
      "token": "HO-AGR-SEMANTIC-REVIEWER-ANALYSIS-TIER-20260611",
      "status": "RATIFIED",
      "tier": "DIRECTIVE",
      "decision": "Semantic review runs at analysis tier against the full AGR corpus",
      "authored_at": "2026-06-11",
      "path": ".hestai/decisions/HO-AGR-SEMANTIC-REVIEWER-ANALYSIS-TIER-20260611.oct.md"
    }
  ],
  "total": 1
}
```

**Error envelope (on failure):**

```json
{ "ok": false, "error": "FILTER_INVALID | WORKING_DIR_INVALID | RECORD_PARSE_FAILED", "detail": "..." }
```

**Notes:**
- Pure read. Zero side effects. Sorted by `authored_at` descending.
- Use this as Step 0 of the decision lookup discipline when the TOKEN is unknown.

---

## `lookup_decision`

Resolve a single AGR by TOKEN.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `working_dir` | string | yes | Absolute path to the project root |
| `token` | string | yes | Full TOKEN string (e.g. `HO-AGR-SEMANTIC-REVIEWER-ANALYSIS-TIER-20260611`) |
| `audience` | string | no | `"agent"` (default) or `"human"` — controls verbosity of return |

**Return shape:**

```json
{
  "ok": true,
  "record": {
    "token": "HO-AGR-SEMANTIC-REVIEWER-ANALYSIS-TIER-20260611",
    "type": "DECISION_RECORD",
    "version": "1",
    "status": "RATIFIED",
    "tier": "DIRECTIVE",
    "decision": "Semantic review runs at analysis tier against the full AGR corpus",
    "because": "Analysis-tier reviews surface systemic incoherence that single-record reviewers miss",
    "authored_at": "2026-06-11",
    "path": ".hestai/decisions/...",
    "fields": { "SUPERSEDED_BY": null, "AMENDS": null, "EXTENDS": null }
  },
  "resolution_chain": [],
  "resolution_chain_status": "complete"
}
```

**When STATUS is SUPERSEDED**, `resolution_chain` contains entries describing the supersession path, and `resolution_chain_status` is `"complete"`, `"broken"`, or `"cyclic"`.

---

## `trace_supersedure`

Walk the supersession chain from a TOKEN to the terminal ratified state. Use this as Step 2
of the decision lookup discipline to confirm a record has not been superseded.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `working_dir` | string | yes | Absolute path to the project root |
| `token` | string | yes | Starting TOKEN to trace from |

**Return shape:**

```json
{
  "ok": true,
  "chain": [
    { "token": "HO-OLD-DECISION-20260501", "status": "SUPERSEDED", "decision": "..." },
    { "token": "HO-NEW-DECISION-20260611", "status": "RATIFIED", "decision": "..." }
  ],
  "terminal_token": "HO-NEW-DECISION-20260611",
  "terminal_status": "RATIFIED"
}
```

**Error envelope (on failure):**

```json
{ "ok": false, "error": "TOKEN_NOT_FOUND | CHAIN_BROKEN | CHAIN_CYCLE_DETECTED", "detail": "..." }
```

**Notes:**
- Pure read. Zero side effects.
- Cycle detection is fail-closed: if a cycle is detected, the tool returns an error rather than
  looping indefinitely.
- A `CHAIN_BROKEN` error means a `SUPERSEDED_BY` pointer references a TOKEN that does not
  exist on disk — this is a governance integrity issue requiring human attention.
