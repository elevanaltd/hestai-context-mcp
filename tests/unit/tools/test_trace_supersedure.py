"""Test-locator shim for ``trace_supersedure``.

The authoritative suite lives at
``tests/unit/tools/governance/test_trace_supersedure.py`` (TMG-confirmed
existing-neighbor convention, ruling (d)). A ``tools/``-path test-locator/gate
derives the expected test path from the source module
(``src/hestai_context_mcp/tools/trace_supersedure.py`` →
``tests/unit/tools/test_trace_supersedure.py``); this file satisfies that path.

It uses a MODULE-ALIAS import (not ``from … import Test*``) so the authoritative
``Test*`` classes are NOT re-bound into this module's namespace — pytest
therefore collects them EXACTLY once (in their home module), with no duplicate
collection.
"""

from __future__ import annotations

import tests.unit.tools.governance.test_trace_supersedure as _trace_supersedure_tests  # noqa: F401
