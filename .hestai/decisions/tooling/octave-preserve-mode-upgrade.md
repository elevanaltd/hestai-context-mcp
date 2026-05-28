---
topic: octave-mcp upgrade
octave_version: "1.13.1"
date: "2026-05-28"
branch: update-octave-1-13-1
status: active
---

# octave-mcp Upgrade: preserve Mode

octave-mcp upgraded to v1.13.0, then to v1.13.1. Key change: `format_style='preserve'` (Strategy A, GH#377) is now the recommended write mode. The default will flip from full canonical re-emit to `preserve` in v1.14.0.

## v1.13.1 (no behaviour change)

v1.13.1 (2026-05-28) is a pure internal refactor: the `write.py` god-object (4887 LOC) was decomposed into five peer modules (`write_detection`, `write_metrics`, `write_format`, `write_mutation`), down to 3197 LOC. **Zero behaviour change, byte-identical output, unchanged `octave_write` API** — all 3614 tests preserved byte-identically. The only addition is octave-mcp's own skill docs (`TELEGRAPHIC_PHRASE`), which do not affect this project. Everything below (the v1.13.0 changes) remains current.

## Changes in v1.13.0

### `format_style` parameter (octave_write)

| Value | Behaviour |
|---|---|
| `'preserve'` | Span-aware mode. Clean nodes slice verbatim from baseline bytes; dirty/repaired nodes re-emit canonically. Diff footprint ≤0.5% on single-key edits. **New recommended default.** |
| `'expanded'` | Full canonical re-emit (former default behaviour). Use if you need deterministic full-normalisation. |
| `'compact'` | Collapses atom-only Blocks to inline-map form. Comment-bearing subtrees vetoed with `W_COMPACT_REFUSED`. |
| `null` (explicit) | DeprecationWarning in v1.13.0. Will be removed or changed in v1.14.0. |
| omitted | Silently accepts the v1.14.0 default (`preserve`). Safe, but not explicit. |

**Guidance for this project**: Always pass `format_style='preserve'` explicitly in new octave_write calls.

### Deprecation path

- **v1.13.0**: `format_style=null` (explicit) emits `DeprecationWarning`.
- **v1.14.0**: Default flips to `preserve`. To keep old behaviour past v1.14.0, pass `format_style='expanded'`.

## Impact on RD18 — Multi-envelope workaround

**Token**: `HO-OCTAVE-WRITE-MULTI-ENVELOPE-WORKAROUND-20260513`

The RD18 workaround (direct `Write` tool for FRAME_CARD / CONCEPT_CARD authoring) was needed because `octave_write` collapsed multi-envelope content to META-only via `TN_RECONCILE_CANONICAL`. The `preserve` mode's span-aware approach is the most likely fix for this pattern.

**Current status**: Needs testing. The workaround remains active until `preserve` mode is empirically confirmed to resolve the multi-envelope collapse. Test procedure:

1. Author a FRAME_CARD or CONCEPT_CARD with multiple envelopes using `octave_write(format_style='preserve')`.
2. Verify all envelopes survive (not collapsed to META-only).
3. If confirmed fixed: `VOID` the RD18 token and remove the direct-write exception from CLAUDE.md.

**References**: octave-mcp #420, `.hestai/decisions/handoff/2026-05-16-rfc-40-mac-b1-carry-forward.md` (RD18 candidate).
