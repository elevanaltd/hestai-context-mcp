"""Test-locator shim for the AGR parser.

The authoritative parser suite lives next to its sibling governance tests at
``tests/unit/tools/governance/test_agent_readable_governance_parser.py`` (TMG-
confirmed existing-neighbor convention, ruling (d)). A ``core/``-path
test-locator/gate derives the expected test path from the source module
(``src/hestai_context_mcp/core/agent_readable_governance_parser.py`` →
``tests/unit/core/test_agent_readable_governance_parser.py``); this file
satisfies that path.

It uses a MODULE-ALIAS import (not ``from … import Test*``) so the authoritative
``Test*`` classes are NOT re-bound into this module's namespace — pytest
therefore collects them EXACTLY once (in their home module), with no duplicate
collection.
"""

from __future__ import annotations

import tests.unit.tools.governance.test_agent_readable_governance_parser as _agr_parser_tests  # noqa: E501, F401
