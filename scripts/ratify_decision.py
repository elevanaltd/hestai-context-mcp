#!/usr/bin/env python3
"""Governance auto-ratify: flip merged-on-approval AGRs from PROPOSED to RATIFIED.

When a human approves a ``governance/*`` PR, the Governance Auto-Ratify workflow
runs this script over ``.hestai/decisions/``. Any DECISION_RECORD AGR carrying
``STATUS::PROPOSED`` is flipped to ``STATUS::RATIFIED`` and stamped with
``RATIFIED_BY`` + ``RATIFIED_AT`` injected directly after the ``AUTHORED_AT``
line (this repo's META schema order — see existing RATIFIED records). The commit
lands on the PR branch so the file is already ratified by the time the operator
merges.

This is a *mechanical reflection of a human approval event* — the human PR
approval is the ratification act; this records it (PROD::I3 Human Primacy: no
LLM ratifies, no auto-merge). It is the sole automation that mutates
``.hestai/decisions/`` artifacts; extending this mutation pattern requires a new
governance decision.

Design:
- Idempotent: a record already ``RATIFIED`` (or already carrying
  ``RATIFIED_AT``) is left byte-for-byte untouched, so re-runs never churn or
  duplicate fields.
- Whole-line anchored: only the ``  STATUS::PROPOSED`` META field is rewritten,
  never a ``PROPOSED`` substring appearing in prose.
- Stdlib-only (no third-party imports, no package install) so it runs in CI the
  same way scripts/validate_review.py does.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

# Whole-line META field matches (two-space indent, exact value, line-anchored).
_STATUS_PROPOSED_RE = re.compile(r"(?m)^  STATUS::PROPOSED[ \t]*$")
_AUTHORED_AT_LINE_RE = re.compile(r"(?m)^  AUTHORED_AT::.*$")
_RATIFIED_AT_PRESENT_RE = re.compile(r"(?m)^  RATIFIED_AT::")


def ratify_text(text: str, *, reviewer: str, timestamp: str) -> tuple[str, bool]:
    """Return ``(new_text, changed)`` for one AGR document.

    Flips a whole-line ``  STATUS::PROPOSED`` to ``  STATUS::RATIFIED`` and, when
    no ``RATIFIED_AT`` is already present, injects ``RATIFIED_BY`` then
    ``RATIFIED_AT`` immediately after the ``AUTHORED_AT`` line. Returns
    ``changed=False`` (and the text unmodified) when there is no PROPOSED status
    line, making the operation idempotent.

    Args:
        text: The AGR document text.
        reviewer: GitHub login of the approving human (for RATIFIED_BY trace).
        timestamp: ISO-8601 UTC instant to stamp as RATIFIED_AT.
    """
    if not _STATUS_PROPOSED_RE.search(text):
        return text, False

    new_text = _STATUS_PROPOSED_RE.sub("  STATUS::RATIFIED", text, count=1)

    if not _RATIFIED_AT_PRESENT_RE.search(new_text):
        injection = (
            f'\n  RATIFIED_BY::"human:operator<{reviewer}>"' f'\n  RATIFIED_AT::"{timestamp}"'
        )
        match = _AUTHORED_AT_LINE_RE.search(new_text)
        if match is not None:
            insert_at = match.end()
        else:
            # AUTHORED_AT is a required field, so this is a defensive fallback:
            # anchor to the STATUS line we just wrote instead.
            status_match = re.search(r"(?m)^  STATUS::RATIFIED[ \t]*$", new_text)
            insert_at = status_match.end() if status_match else len(new_text)
        new_text = new_text[:insert_at] + injection + new_text[insert_at:]

    return new_text, True


def ratify_directory(decisions_dir: Path, *, reviewer: str, timestamp: str) -> list[Path]:
    """Ratify every PROPOSED AGR under ``decisions_dir``; return changed paths."""
    changed: list[Path] = []
    for path in sorted(decisions_dir.glob("*.oct.md")):
        original = path.read_text(encoding="utf-8")
        updated, was_changed = ratify_text(original, reviewer=reviewer, timestamp=timestamp)
        if was_changed:
            path.write_text(updated, encoding="utf-8")
            changed.append(path)
    return changed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Auto-ratify PROPOSED decision records.")
    parser.add_argument(
        "decisions_dir",
        nargs="?",
        default=".hestai/decisions",
        help="Directory of *.oct.md AGRs (default: .hestai/decisions).",
    )
    parser.add_argument(
        "--reviewer",
        default=os.environ.get("REVIEWER", "unknown"),
        help="Approving GitHub login (default: $REVIEWER).",
    )
    args = parser.parse_args(argv)

    decisions_dir = Path(args.decisions_dir)
    if not decisions_dir.is_dir():
        print(f"No decisions directory at {decisions_dir}; nothing to ratify.")
        print("changed=0")
        return 0

    timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    changed = ratify_directory(decisions_dir, reviewer=args.reviewer, timestamp=timestamp)

    for path in changed:
        print(f"Ratified: {path}")
    print(f"changed={len(changed)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
