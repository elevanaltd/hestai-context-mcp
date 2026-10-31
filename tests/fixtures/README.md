# tests/fixtures

## OPERATIONAL-WORKFLOW.inline.oct.md

Byte-for-byte copy of `.hestai-sys/standards/workflow/OPERATIONAL-WORKFLOW.oct.md` (that
directory is gitignored, so CI cannot read it). `test_pinned_inline_fixture_matches_the_live_bundled_workflow_when_present`
compares it with the live file when one is present.

## OPERATIONAL-WORKFLOW.canonical.oct.md

The same workflow after an `octave_write` pass (wrapped `KEY::[` lists). Test data for
issue #196, not a governance document. It carries no header comment on purpose: the
regeneration test compares the file byte-for-byte with fresh `octave_write` output.

Generated with **octave-mcp 1.15.0** (the `octave-mcp>=1.15` test extra), writing to a
temporary path, never over a repo file:

```bash
.venv/bin/python - <<'PY'
import asyncio
from pathlib import Path
from octave_mcp.mcp.write import WriteTool

src = Path("tests/fixtures/OPERATIONAL-WORKFLOW.inline.oct.md").read_text()
target = Path("/tmp/OPERATIONAL-WORKFLOW.canonical.oct.md")
target.unlink(missing_ok=True)
result = asyncio.run(
    WriteTool().execute(target_path=str(target), content=src, format_style="preserve")
)
assert result["status"] == "success", result
PY
cp /tmp/OPERATIONAL-WORKFLOW.canonical.oct.md tests/fixtures/OPERATIONAL-WORKFLOW.canonical.oct.md
```

`test_canonical_fixture_is_what_octave_mcp_writes_today` runs the same call and asserts the
output equals this file (skipped when octave-mcp is not importable). octave-mcp
reports `W_DUPLICATE_KEY` corrections for the repeated per-phase keys (RACI, SUBPHASES,
...); the written file still contains every phase's lines, but that is not verified
line-by-line here.
