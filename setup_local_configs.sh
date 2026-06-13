#!/bin/bash
# Install hestai-context-mcp and register it in Claude Code, Gemini CLI, Codex, and Goose.
#
# Usage: bash setup_local_configs.sh [--dry-run]
#
# Prerequisites:
#   uv  — https://docs.astral.sh/uv/getting-started/installation/
#
# What it does:
#   0. uv sync --extra validation  (creates .venv, installs package + optional OCTAVE validator)
#   1–4. Registers the server entry point in each supported AI client config
#
# Server launched via:
#   <repo>/.venv/bin/python -m hestai_context_mcp
#
# Idempotent — safe to run multiple times.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PYTHON="$REPO_DIR/.venv/bin/python"
SERVER_NAME="hestai-context"

DRY_RUN=false
if [[ "${1:-}" == "--dry-run" ]]; then
    DRY_RUN=true
    echo "--- DRY RUN (no files will be modified) ---"
    echo ""
fi

# ── Preflight ─────────────────────────────────────────────────────────────────

if ! command -v uv &>/dev/null; then
    echo "ERROR: uv not found — install from https://docs.astral.sh/uv/getting-started/installation/"
    exit 1
fi

echo "=== 0/4  Environment  (uv sync) ==="
if $DRY_RUN; then
    echo "  Would run: uv sync --extra validation (from $REPO_DIR)"
else
    (cd "$REPO_DIR" && uv sync --extra validation)
    echo "  ✓ Environment ready"
fi
echo ""

echo "Checking server import..."
"$VENV_PYTHON" -c "import hestai_context_mcp; print('  ✓ Package importable')"
echo ""

# ── 1. Claude Code (~/.claude.json) ──────────────────────────────────────────

echo "=== 1/5  Claude Code  (~/.claude.json) ==="
CLAUDE_JSON="$HOME/.claude.json"

if [ ! -f "$CLAUDE_JSON" ]; then
    echo "  SKIP — $CLAUDE_JSON not found"
else
    if $DRY_RUN; then
        echo "  Would add/update '$SERVER_NAME' entry"
    else
        "$VENV_PYTHON" - <<PYEOF
import json, sys, shutil
from datetime import datetime

path = "$CLAUDE_JSON"
name = "$SERVER_NAME"
python = "$VENV_PYTHON"

with open(path) as f:
    cfg = json.load(f)

servers = cfg.setdefault("mcpServers", {})
entry = {"type": "stdio", "command": python, "args": ["-m", "hestai_context_mcp"]}

if servers.get(name) == entry:
    print(f"  ✓ Already up to date")
else:
    backup = path + ".bak." + datetime.now().strftime("%Y%m%d_%H%M%S")
    shutil.copy2(path, backup)
    servers[name] = entry
    with open(path, "w") as f:
        json.dump(cfg, f, indent=2)
        f.write("\n")
    print(f"  ✓ Updated (backup: {backup})")
PYEOF
    fi
fi
echo ""

# ── 2. Gemini CLI (~/.gemini/settings.json) ───────────────────────────────────

echo "=== 2/5  Gemini CLI  (~/.gemini/settings.json) ==="
GEMINI_JSON="$HOME/.gemini/settings.json"

if [ ! -f "$GEMINI_JSON" ]; then
    echo "  SKIP — $GEMINI_JSON not found"
else
    if $DRY_RUN; then
        echo "  Would add/update '$SERVER_NAME' entry"
    else
        "$VENV_PYTHON" - <<PYEOF
import json, sys, shutil
from datetime import datetime

path = "$GEMINI_JSON"
name = "$SERVER_NAME"
python = "$VENV_PYTHON"

with open(path) as f:
    cfg = json.load(f)

servers = cfg.setdefault("mcpServers", {})
entry = {"command": python, "args": ["-m", "hestai_context_mcp"]}

if servers.get(name) == entry:
    print(f"  ✓ Already up to date")
else:
    backup = path + ".bak." + datetime.now().strftime("%Y%m%d_%H%M%S")
    shutil.copy2(path, backup)
    servers[name] = entry
    with open(path, "w") as f:
        json.dump(cfg, f, indent=2)
        f.write("\n")
    print(f"  ✓ Updated (backup: {backup})")
PYEOF
    fi
fi
echo ""

# ── 3. Codex (~/.codex/config.toml) ──────────────────────────────────────────

echo "=== 3/5  Codex  (~/.codex/config.toml) ==="
CODEX_TOML="$HOME/.codex/config.toml"

if [ ! -f "$CODEX_TOML" ]; then
    echo "  SKIP — $CODEX_TOML not found"
else
    if $DRY_RUN; then
        echo "  Would add/update '[mcp_servers.$SERVER_NAME]' section"
    else
        "$VENV_PYTHON" - <<PYEOF
import sys, shutil, tomllib
from datetime import datetime

path = "$CODEX_TOML"
name = "$SERVER_NAME"
python = "$VENV_PYTHON"

with open(path, "rb") as f:
    cfg = tomllib.load(f)

servers = cfg.get("mcp_servers", {})

# Normalise key: toml allows hyphens; check both forms
existing_keys = {k.lower().replace("_", "-"): k for k in servers}
normalised = name.lower().replace("_", "-")

if normalised in existing_keys:
    existing = servers[existing_keys[normalised]]
    if existing.get("command") == python and existing.get("args") == ["-m", "hestai_context_mcp"]:
        print("  ✓ Already up to date")
        sys.exit(0)
    print("  Updating existing entry (removing old, appending new)...")
    # Read raw text and remove the old section block
    with open(path) as f:
        raw = f.read()
    old_key = existing_keys[normalised]
    # Remove the section header and its lines up to the next section/EOF
    import re
    raw = re.sub(
        r"\[mcp_servers\." + re.escape(old_key) + r"\][^\[]*",
        "",
        raw,
        flags=re.DOTALL,
    ).rstrip() + "\n"
else:
    with open(path) as f:
        raw = f.read()

backup = path + ".bak." + datetime.now().strftime("%Y%m%d_%H%M%S")
shutil.copy2(path, backup)

new_section = (
    f'\n[mcp_servers."{name}"]\n'
    f'command = "{python}"\n'
    f'args = ["-m", "hestai_context_mcp"]\n'
)

with open(path, "w") as f:
    f.write(raw.rstrip() + "\n" + new_section)

print(f"  ✓ Updated (backup: {backup})")
PYEOF
    fi
fi
echo ""

# ── 4. Goose (~/.config/goose/config.yaml) ───────────────────────────────────

echo "=== 4/5  Goose  (~/.config/goose/config.yaml) ==="
GOOSE_YAML="$HOME/.config/goose/config.yaml"

if [ ! -f "$GOOSE_YAML" ]; then
    echo "  SKIP — $GOOSE_YAML not found"
else
    if $DRY_RUN; then
        echo "  Would add/update '$SERVER_NAME' extension"
    else
        "$VENV_PYTHON" - <<PYEOF
import sys, shutil, yaml
from datetime import datetime

path = "$GOOSE_YAML"
name = "$SERVER_NAME"
python = "$VENV_PYTHON"

with open(path) as f:
    cfg = yaml.safe_load(f) or {}

extensions = cfg.setdefault("extensions", {})

desired = {
    "enabled": True,
    "type": "stdio",
    "name": "HestAI Context",
    "description": "",
    "cmd": python,
    "args": ["-m", "hestai_context_mcp"],
    "envs": {},
    "env_keys": [],
    "timeout": 300,
    "bundled": None,
    "available_tools": [],
}

if extensions.get(name) == desired:
    print("  ✓ Already up to date")
    sys.exit(0)

backup = path + ".bak." + datetime.now().strftime("%Y%m%d_%H%M%S")
shutil.copy2(path, backup)

extensions[name] = desired

with open(path, "w") as f:
    yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

print(f"  ✓ Updated (backup: {backup})")
PYEOF
    fi
fi
echo ""

# ── Summary ───────────────────────────────────────────────────────────────────

if $DRY_RUN; then
    echo "Dry-run complete — no files modified."
else
    echo "Done. Restart each tool (or reload MCP servers) to activate '$SERVER_NAME'."
fi
