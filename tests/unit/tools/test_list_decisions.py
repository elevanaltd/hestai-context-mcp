"""Test-locator shim for ``list_decisions``.

The authoritative suite lives at
``tests/unit/tools/governance/test_list_decisions.py`` (TMG-confirmed
existing-neighbor convention, ruling (d)). A ``tools/``-path test-locator/gate
derives the expected test path from the source module
(``src/hestai_context_mcp/tools/list_decisions.py`` →
``tests/unit/tools/test_list_decisions.py``); this file satisfies that path.

It uses a MODULE-ALIAS import (not ``from … import Test*``) so the authoritative
``Test*`` classes are NOT re-bound into this module's namespace — pytest
therefore collects them EXACTLY once (in their home module), with no duplicate
collection and no risk of silently dropping a class (the previous explicit
import list omitted ``TestCoLocatedNonAgrFiles``; an alias import cannot drop
anything).
"""

from __future__ import annotations

import tests.unit.tools.governance.test_list_decisions as _list_decisions_tests  # noqa: F401
