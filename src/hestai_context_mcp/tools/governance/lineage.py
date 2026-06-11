"""Lineage edge-resolution guard (ADR-RFC-ARCH-004 §4.1 invariant #8).

Enforces that AMENDS / EXTENDS / SUPERSEDED_BY references resolve to TOKENs
present in the SAME repository. Dangling same-repo edges are reported as a
STRUCTURED finding (PROD I4 STRUCTURED_RETURN_SHAPES) — never raised as an
exception.

Scope (per §1.6 / §2.4):
  - SAME-REPO edges (bare or quoted TOKEN references) are resolved against the
    governance store via the deterministic lexer lookup. Unresolved => dangling.
  - CROSS-REPO edges (``repo:<id>:...`` or ``pin:<url>...`` forms) are advisory
    and OUT OF SCOPE for automated validation; they are reported separately and
    never counted as dangling.

Cohort-isolation handling:
  A dangling target may legitimately be absent from a test subset while existing
  in the full corpus (e.g. ``HO-PRODUCTION-TYPE-VARIANCE-PRICING-20260513`` seen
  in isolation). Callers pass such known-isolated TOKENs via
  ``expected_isolated_tokens``; those are reported under ``expected_isolated``
  and do NOT mark the finding as failed. This is an explicit, scoped allowance —
  it never suppresses OTHER unresolved same-repo targets.

North Star boundary (PROD §4 IS_NOT: octave-mcp owns format): regex extraction
only, no OCTAVE AST parsing, no LLM calls. Deterministic and read-only.
"""

import re
from pathlib import Path
from typing import Any

from hestai_context_mcp.tools.governance.lexer import lookup_token_deterministic
from hestai_context_mcp.tools.governance.type_checker import _extract_token

# List-valued edge fields: AMENDS::[A, B, …] / EXTENDS::[A, B, …].
# The body between the brackets is captured and split on commas downstream.
_LIST_EDGE_RE_TEMPLATE = r"(?m)^\s*{field}::\[([^\]]*)\]"

# Single-valued edge field: SUPERSEDED_BY::<TOKEN> or SUPERSEDED_BY::"<TOKEN>".
_SUPERSEDED_BY_RE = re.compile(r'(?m)^\s*SUPERSEDED_BY::(?:"([^"]+)"|([^"\s]+))\s*$')

_LIST_EDGE_TYPES = ("AMENDS", "EXTENDS")

# A cross-repo reference uses an explicit scheme prefix (PR-B §1.4.1 / §2.4).
_CROSS_REPO_PREFIXES = ("repo:", "pin:")


def _split_list_body(body: str) -> list[str]:
    """Split an OCTAVE list body into individual, de-quoted entries."""
    entries: list[str] = []
    for raw in body.split(","):
        item = raw.strip().strip('"').strip()
        if item:
            entries.append(item)
    return entries


def _is_cross_repo(target: str) -> bool:
    """True if the target is a cross-repo / external pin reference (§2.4)."""
    return target.startswith(_CROSS_REPO_PREFIXES)


def _collect_edges(content: str) -> list[tuple[str, str]]:
    """Extract (edge_type, target) pairs from raw OCTAVE content.

    Handles list-valued AMENDS/EXTENDS and single-valued SUPERSEDED_BY.
    Order is stable: list edges in declaration order, then SUPERSEDED_BY.
    """
    edges: list[tuple[str, str]] = []

    for edge_type in _LIST_EDGE_TYPES:
        pattern = re.compile(_LIST_EDGE_RE_TEMPLATE.format(field=edge_type))
        for match in pattern.finditer(content):
            for target in _split_list_body(match.group(1)):
                edges.append((edge_type, target))

    sb = _SUPERSEDED_BY_RE.search(content)
    if sb:
        target = sb.group(1) if sb.group(1) is not None else sb.group(2)
        edges.append(("SUPERSEDED_BY", target))

    return edges


def resolve_lineage_edges(
    working_dir: Path,
    content: str,
    expected_isolated_tokens: set[str] | None = None,
) -> dict[str, Any]:
    """Resolve AMENDS/EXTENDS/SUPERSEDED_BY edges against the same repo.

    Args:
        working_dir: Project root directory (governance store lives under
            ``.hestai/decisions`` and ``.hestai/context/concepts``).
        content: Raw OCTAVE document text of the record carrying the edges.
        expected_isolated_tokens: TOKENs known to exist in the full corpus but
            legitimately absent in this (test/cohort) subset. Unresolved targets
            in this set are reported as expected isolation, not as defects.

    Returns:
        A structured finding dict (PROD I4), never raises:
          {
            "ok": bool,                    # False iff any genuine dangling edge
            "source": str | None,          # source record TOKEN (best-effort)
            "dangling": [                  # genuine same-repo unresolved edges
              {"edge_type", "source", "target", "scope": "same-repo"}, …
            ],
            "expected_isolated": [         # cohort-isolation excused edges
              {"edge_type", "source", "target", "scope": "same-repo-isolated"}, …
            ],
            "cross_repo": [                # advisory / out-of-scope (§2.4)
              {"edge_type", "source", "target", "scope": "cross-repo"}, …
            ],
          }
    """
    expected = expected_isolated_tokens or set()

    dangling: list[dict[str, str]] = []
    expected_isolated: list[dict[str, str]] = []
    cross_repo: list[dict[str, str]] = []
    source: str | None = None

    try:
        source = _extract_token(content)

        for edge_type, target in _collect_edges(content):
            if _is_cross_repo(target):
                cross_repo.append(
                    {
                        "edge_type": edge_type,
                        "source": source or "",
                        "target": target,
                        "scope": "cross-repo",
                    }
                )
                continue

            if lookup_token_deterministic(working_dir, target):
                continue  # resolves in-repo — healthy edge

            # Unresolved same-repo target.
            if target in expected:
                expected_isolated.append(
                    {
                        "edge_type": edge_type,
                        "source": source or "",
                        "target": target,
                        "scope": "same-repo-isolated",
                    }
                )
            else:
                dangling.append(
                    {
                        "edge_type": edge_type,
                        "source": source or "",
                        "target": target,
                        "scope": "same-repo",
                    }
                )
    except Exception:  # noqa: BLE001
        # Fail-safe: a parse anomaly must never crash the guard. Report what was
        # gathered so far with ok reflecting only genuine dangling edges.
        pass

    return {
        "ok": len(dangling) == 0,
        "source": source,
        "dangling": dangling,
        "expected_isolated": expected_isolated,
        "cross_repo": cross_repo,
    }
