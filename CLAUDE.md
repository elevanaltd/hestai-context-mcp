# HestAI Context MCP Server

[![CI](https://github.com/elevanaltd/hestai-context-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/elevanaltd/hestai-context-mcp/actions/workflows/ci.yml)

Python MCP server providing session lifecycle, context synthesis, and review infrastructure.

## Quick Commands

**Always use `.venv/bin/python` -- the system `python` does not have project packages.**
The `.venv` is created by `uv sync --all-extras`.

```bash
# Quality gates (run before committing)
.venv/bin/python -m ruff check src tests
.venv/bin/python -m black --check src tests
.venv/bin/python -m mypy src
.venv/bin/python -m pytest

# Fix formatting
.venv/bin/python -m black src tests
.venv/bin/python -m ruff check --fix src tests

# Run specific test markers
.venv/bin/python -m pytest -m smoke       # Fast sanity checks
.venv/bin/python -m pytest -m behavior    # Behavioral tests
.venv/bin/python -m pytest -m contract    # Contract tests
```

## CI Pipeline

GitHub Actions CI runs on push to `main` and all PRs. Three jobs:
- **lint**: `ruff check` + `black --check` (Python 3.11, 3.12)
- **typecheck**: `mypy src` (Python 3.11, 3.12)
- **test**: `pytest --cov-fail-under=85` (Python 3.11, 3.12)

Coverage threshold: **85%** (enforced in CI only, not in local pytest addopts).
Current coverage: ~89%.

## Testing

- **pytest markers**: `smoke`, `unit`, `behavior`, `contract`, `integration`
- Strict markers mode enabled (unknown markers cause errors)
- Coverage: 85% threshold enforced in CI
- Tests live in `tests/` mirroring `src/` structure

```bash
# Run by marker
.venv/bin/python -m pytest -m smoke         # Fast sanity checks
.venv/bin/python -m pytest -m unit          # Unit tests
.venv/bin/python -m pytest -m behavior      # Behavioral tests
.venv/bin/python -m pytest -m contract      # Contract tests
.venv/bin/python -m pytest -m integration   # Integration tests
```

## Core Files

- `src/hestai_context_mcp/server.py` - MCP server setup and tool registration
- `src/hestai_context_mcp/tools/` - MCP tool implementations
- `src/hestai_context_mcp/core/` - Core business logic
- `tests/` - Test suite mirroring src/ structure

## Code Style

- Line length: 100 chars
- Python 3.11+ with full type hints
- Use `ruff` for linting, `black` for formatting
- All public functions need docstrings

## Git Conventions

- Branch from `main`
- Conventional commits: `feat:`, `fix:`, `docs:`, `test:`, `refactor:`
- PRs require CI green

## Octave Tooling

**octave-mcp version in use: v1.15.0**

All `.oct.md` files must be written via `mcp__octave__octave_write` (OCTAVE_WRITE_GATE — never use Write/Edit tools on `.oct.md` files).

Full upgrade detail: `.hestai/decisions/tooling/octave-preserve-mode-upgrade.md`.

**Dependency status:** octave-mcp is a **test-only** optional dependency (`[project.optional-dependencies].test`, `octave-mcp>=1.15`), used only by `tests/unit/governance/test_north_star_upog_compliance.py`. Runtime code does **not** import it — real OCTAVE validation is deferred to a planned "Gate B", per North Star §4 (`document format system — octave-mcp owns`) and PROD::I6. The validator-integration options (test-only / optional `validation` extra / hard runtime dep) are assessed in the decision doc; promoting beyond test-only needs requirements-steward sign-off.

**v1.15.0 (2026-05-31) — ⚠️ HARD BREAK to `octave_write` `changes`-mode value semantics (GH#487):**

- A **bare dict** at a `changes` KEY now **fully replaces** that key — unmentioned children are **DROPPED**. To merge into an existing block you **MUST** send an explicit `{"$op": "MERGE", "value": {…}}`.
- A **bare scalar** over a nested BLOCK = full replace in place (cures the old duplicate-keys footgun).
- A `$op:MERGE` of a scalar over a child BLOCK is **rejected** with `E_OP_TARGET_MISMATCH`.
- Bare dict with a **nested** dict value now emits canonical **BLOCK** form (no more `dict→InlineMap` coercion).
- `$op:APPEND`/`$op:PREPEND` of nested list/dict elements now emit re-parseable OCTAVE (#488).
- Read path (`octave_validate`) is unchanged. This project does not call `changes=` mode in source code, so the break is guidance for agents/skills doing surgical key edits.

**v1.14.0 (2026-05-30) — anchored paths + literal-zone fidelity (#460):**

- `ANCHOR/KEY` anchored-path syntax disambiguates duplicate sibling keys (e.g. `changes={"I2/RATIONALE": …}`).
- Literal-zone fence form is preserved on content edits and `$op MERGE` — content-only edits round-trip byte-identical under `format_style="preserve"` (PROD::I1).
- Anchored-path `$op` descriptors are executed (e.g. `$op DELETE` actually removes), not written as data.

**`format_style` (still current):**

- `format_style='preserve'` is span-aware (clean nodes verbatim, dirty/repaired nodes re-emitted; ≤0.5% diff footprint on single-key edits). **Always pass it explicitly** in `octave_write` calls.
- `format_style='expanded'` retains full canonical re-emit.
- The predicted v1.14.0 "flip the default to `preserve`" did **not** land in the v1.14.0 or v1.15.0 changelogs — the default is unconfirmed, so do not rely on it; pass `'preserve'` explicitly.

**Multi-envelope workaround (RD18 token `HO-OCTAVE-WRITE-MULTI-ENVELOPE-WORKAROUND-20260513`) — still active:**

`octave_write` with older defaults collapsed multi-envelope Facet ABI cards to META-only via `TN_RECONCILE_CANONICAL` (octave-mcp #420). The workaround is to use the direct `Write` tool for FRAME_CARD / CONCEPT_CARD authoring. Neither v1.14.0 nor v1.15.0 claims to fix #420, so treat the workaround as **still active** until empirically retested with `format_style='preserve'`. See `.hestai/decisions/handoff/2026-05-16-rfc-40-mac-b1-carry-forward.md` and octave-mcp #420.
