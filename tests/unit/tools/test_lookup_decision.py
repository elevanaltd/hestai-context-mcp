"""Test-locator shim for ``lookup_decision``.

The authoritative suite lives at
``tests/unit/tools/governance/test_lookup_decision.py`` (TMG-confirmed
existing-neighbor convention, ruling (d)). A ``tools/``-path test-locator/gate
derives the expected test path from the source module
(``src/hestai_context_mcp/tools/lookup_decision.py`` →
``tests/unit/tools/test_lookup_decision.py``); this file satisfies that path.

It uses a MODULE-ALIAS import (not ``from … import Test*``) so the authoritative
``Test*`` classes are NOT re-bound into this module's namespace — pytest
therefore collects them EXACTLY once (in their home module), with no duplicate
collection and no risk of silently dropping a class from an explicit import list.
"""

from __future__ import annotations

import tests.unit.tools.governance.test_lookup_decision as _lookup_decision_tests  # noqa: F401
