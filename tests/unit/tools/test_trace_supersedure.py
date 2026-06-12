"""Test-locator shim for ``trace_supersedure``.

The authoritative suite lives at
``tests/unit/tools/governance/test_trace_supersedure.py`` (TMG-confirmed
existing-neighbor convention, ruling (d)). This module re-exports it so a
``tools/``-path test-locator (and pytest) discovers it here too; it adds NO new
assertions and duplicates nothing.
"""

from __future__ import annotations

from tests.unit.tools.governance.test_trace_supersedure import (  # noqa: F401
    TestErrorEnvelope,
    TestHappyPath,
    TestPurity,
)
