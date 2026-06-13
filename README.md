# hestai-context-mcp

Memory and Environment MCP server providing session lifecycle, context synthesis, learnings extraction, and review infrastructure via stdio transport.

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
