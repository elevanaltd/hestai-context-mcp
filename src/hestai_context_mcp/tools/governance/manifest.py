"""MANIFEST generator for governance artifacts.

Builds a flat TOKEN/ID -> file_path index from:
  - .hestai/decisions/**/*.oct.md  (DECISION_RECORD, TOKEN field)
  - .hestai/context/concepts/**/*.oct.md  (facet cards, ID field)

The MANIFEST is written to .hestai/MANIFEST.md after each successful
Linker commit to keep the index fresh for lookup_token_deterministic.

North Star boundary: no OCTAVE AST parsing — regex extraction only.
"""

import os
import re
import tempfile
from pathlib import Path

# Regex to extract TOKEN from DECISION_RECORD
_TOKEN_RE = re.compile(r'TOKEN::"([^"]+)"')

# Regex to extract ID from facet cards
_ID_RE = re.compile(r'(?m)^  ID::"([^"]+)"')

# Alternative: bare ID:: without quotes (e.g. ID::SOME_CONSTANT)
_ID_BARE_RE = re.compile(r"(?m)^  ID::([A-Z][A-Z0-9_]{2,127})\s*$")


def _extract_token_or_id(content: str) -> str | None:
    """Extract TOKEN or ID from raw oct.md content using regex.

    Tries TOKEN field first (DECISION_RECORD), then ID field (facet cards).
    Returns the extracted value or None if neither found.
    """
    m = _TOKEN_RE.search(content)
    if m:
        return m.group(1)

    m = _ID_RE.search(content)
    if m:
        return m.group(1)

    m = _ID_BARE_RE.search(content)
    if m:
        return m.group(1)

    return None


def build_manifest(working_dir: Path) -> str:
    """Build a markdown MANIFEST table from all governance oct.md files.

    Searches:
      - .hestai/decisions/**/*.oct.md
      - .hestai/context/concepts/**/*.oct.md

    Returns a markdown table string with columns | TOKEN/ID | path |.
    Returns an empty table header if no files found.
    """
    hestai = working_dir / ".hestai"
    decisions_root = hestai / "decisions"
    concepts_root = hestai / "context" / "concepts"

    rows: list[tuple[str, str]] = []

    for root in (decisions_root, concepts_root):
        if not root.exists():
            continue
        for oct_file in sorted(root.rglob("*.oct.md")):
            try:
                content = oct_file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            key = _extract_token_or_id(content)
            if key:
                rel = oct_file.relative_to(working_dir)
                rows.append((key, str(rel)))

    lines = ["| TOKEN/ID | path |", "| --- | --- |"]
    for key, path in rows:
        lines.append(f"| {key} | {path} |")

    return "\n".join(lines) + "\n"


def get_manifest_path(working_dir: Path) -> Path:
    """Return the canonical path to MANIFEST.md.

    Args:
        working_dir: Project root directory.

    Returns:
        Path to .hestai/MANIFEST.md.
    """
    return working_dir / ".hestai" / "MANIFEST.md"


def write_manifest(working_dir: Path) -> None:
    """Write the MANIFEST to the canonical path using an atomic temp-file rename.

    Builds the manifest from the current filesystem state and writes it
    atomically to .hestai/MANIFEST.md via a temporary file + os.replace()
    so a concurrent reader never sees a partial write.

    Args:
        working_dir: Project root directory.
    """
    manifest_path = get_manifest_path(working_dir)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    new_content = build_manifest(working_dir)

    # Atomic write: temp file in same directory + os.replace (Bug 6 fix)
    with tempfile.NamedTemporaryFile(
        "w",
        dir=manifest_path.parent,
        delete=False,
        suffix=".tmp",
        encoding="utf-8",
    ) as tmp_f:
        tmp_f.write(new_content)
        tmp_name = tmp_f.name

    os.replace(tmp_name, manifest_path)
