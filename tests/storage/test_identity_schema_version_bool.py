"""Cubic rework cycle 2 — Finding #5 (P1, identity.py:120).

RED-first test: ``isinstance(value, int)`` accepts ``bool`` because
``bool`` subclasses ``int``. ``state_schema_version=True`` would
silently coerce to 1 and pass validation. Per PROD::I2 fail-closed
identity validation it must raise ``IdentityValidationError`` with
code ``unsupported_schema_version`` regardless of the truthy/falsy
bool value.
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
class TestSchemaVersionBoolRejection:
    """Cubic P1 #5: bool must be rejected even though it subclasses int."""

    @pytest.mark.parametrize("value", [True, False])
    def test_bool_state_schema_version_is_rejected(self, value: bool) -> None:
        from hestai_context_mcp.storage.identity import (
            IdentityValidationError,
            validate_identity_tuple,
        )
        from hestai_context_mcp.storage.types import IdentityTuple

        kwargs = _base()
        kwargs["state_schema_version"] = value
        identity = IdentityTuple(**kwargs)  # type: ignore[arg-type]

        with pytest.raises(IdentityValidationError) as excinfo:
            validate_identity_tuple(identity)

        # Bool is structurally invalid as a schema version even though
        # ``isinstance(bool, int)`` is True.
        assert excinfo.value.code == "unsupported_schema_version"
        assert excinfo.value.field == "state_schema_version"
