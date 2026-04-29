"""Cubic rework cycle 2 — Finding #2 (P1, identity.py:74).

RED-first test: non-string truthy values (int, list, dict, float, tuple)
for the four string fields must NOT reach ``.strip()``; they must raise
``IdentityValidationError`` with code ``invalid_identity_component_type``
(PROD::I2 fail-closed identity validation, RISK_001).
"""

from __future__ import annotations

from typing import Any

import pytest


def _base() -> dict[str, Any]:
    return {
        "project_id": "proj-A",
        "workspace_id": "wt-build",
        "user_id": "alice",
        "state_schema_version": 1,
        "carrier_namespace": "personal",
    }


@pytest.mark.unit
class TestNonStringIdentityComponentTypeRejection:
    """Cubic P1 #2: non-string truthy values must fail-closed structured."""

    @pytest.mark.parametrize(
        "field",
        ["project_id", "workspace_id", "user_id", "carrier_namespace"],
    )
    @pytest.mark.parametrize(
        "value",
        [123, ["a", "b"], {"k": "v"}, 1.5, ("a",)],
    )
    def test_non_string_component_raises_structured_error(self, field: str, value: Any) -> None:
        from hestai_context_mcp.storage.identity import (
            IdentityValidationError,
            validate_identity_tuple,
        )
        from hestai_context_mcp.storage.types import IdentityTuple

        kwargs = _base()
        kwargs[field] = value
        identity = IdentityTuple(**kwargs)  # type: ignore[arg-type]

        with pytest.raises(IdentityValidationError) as excinfo:
            validate_identity_tuple(identity)

        assert excinfo.value.code == "invalid_identity_component_type"
        assert excinfo.value.field == field
