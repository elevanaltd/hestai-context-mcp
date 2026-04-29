"""Cubic rework cycle 2 — Finding #6 (P2, identity_resolver.py:54).

RED-first test: ``resolve_identity`` must NOT silently coerce a
non-string identity field (e.g., int, list, dict) via ``str(...)``.
RISK_001 fail-closed default requires returning ``None`` (treat as
"no identity configured") so the caller surfaces a structured
``no_identity_configured`` skip rather than binding to a fabricated
identity. PROD::I2 fail-closed identity safety.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest


def _config(working_dir: Path, payload: dict[str, Any]) -> Path:
    cfg = working_dir / ".hestai" / "state" / "portable" / "identity.json"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(json.dumps(payload))
    return cfg


@pytest.mark.unit
class TestResolveIdentityFailClosedOnNonStringField:
    """Cubic P2 #6: non-string fields must NOT be coerced via str(...)."""

    @pytest.mark.parametrize(
        "field", ["project_id", "workspace_id", "user_id", "carrier_namespace"]
    )
    @pytest.mark.parametrize("value", [123, ["a"], {"k": "v"}])
    def test_non_string_field_returns_none_not_coerced(
        self, tmp_path: Path, field: str, value: Any
    ) -> None:
        from hestai_context_mcp.storage.identity_resolver import resolve_identity

        payload: dict[str, Any] = {
            "project_id": "proj-A",
            "workspace_id": "wt-build",
            "user_id": "alice",
            "state_schema_version": 1,
            "carrier_namespace": "personal",
        }
        payload[field] = value
        _config(tmp_path, payload)

        # Must return None (fail-closed) rather than coerce to e.g. "123".
        result = resolve_identity(tmp_path)
        assert result is None
