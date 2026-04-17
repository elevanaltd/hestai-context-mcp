# HestAI Context MCP Server

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
