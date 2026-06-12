"""Test-locator shim for the AGR parser.

The authoritative parser suite lives next to its sibling governance tests at
``tests/unit/tools/governance/test_agent_readable_governance_parser.py`` (TMG-
confirmed existing-neighbor convention, ruling (d)). This module re-exports that
suite so a ``core/``-path test-locator (and pytest) discovers it here too; it
adds NO new assertions and duplicates nothing.
"""

from __future__ import annotations

from tests.unit.tools.governance.test_agent_readable_governance_parser import (  # noqa: F401
    TestGracefulDegradation,
    TestPurityAndRegexOnly,
    TestRequiredFieldExtraction,
    TestSupersededRecord,
)
