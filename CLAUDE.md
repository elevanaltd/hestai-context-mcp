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

**octave-mcp version in use: v1.13.1**

All `.oct.md` files must be written via `mcp__octave__octave_write` (OCTAVE_WRITE_GATE — never use Write/Edit tools on `.oct.md` files).

**v1.13.1 note:** v1.13.1 is a pure internal refactor — the `write.py` god-object was decomposed into five peer modules (`write_detection`, `write_metrics`, `write_format`, `write_mutation`) with **zero behaviour change, byte-identical output, and an unchanged `octave_write` API**. No project usage changes; all v1.13.0 guidance below still applies verbatim.

**v1.13.0 key changes (still current):**

- `format_style='preserve'` is now available (Strategy A, GH#377). Span-aware mode that keeps clean nodes verbatim and only re-emits dirty/repaired nodes. Diff footprint ≤0.5% of file size on single-key edits. **Use this going forward.**
- `format_style='expanded'` retains the old full canonical re-emit behaviour.
- `format_style=null` (explicit) now emits a `DeprecationWarning`. Omitting the parameter silently accepts the future default.
- **v1.14.0 will flip the default** from full canonical re-emit to `preserve`. To be safe: always pass `format_style='preserve'` explicitly in new octave_write calls.

**Multi-envelope workaround (RD18 token `HO-OCTAVE-WRITE-MULTI-ENVELOPE-WORKAROUND-20260513`):**

`octave_write` with older defaults collapsed multi-envelope Facet ABI cards to META-only via `TN_RECONCILE_CANONICAL`. The workaround was to use direct `Write` tool for FRAME_CARD / CONCEPT_CARD authoring. With v1.13.0 `preserve` mode landing, this should be **retested** — `preserve` mode's span-aware approach may resolve the collapse. Until confirmed fixed, treat the workaround as still active. See `.hestai/decisions/handoff/2026-05-16-rfc-40-mac-b1-carry-forward.md` and octave-mcp #420.
