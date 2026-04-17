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
.venv/bin/python -m pytest -m smoke         # Fast sanity checks (~20 tests)
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
