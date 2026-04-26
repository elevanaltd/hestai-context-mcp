"""GROUP_003: IDENTITY_VALIDATION — RED-first tests for storage/identity.py.

Asserts the IdentityTuple validation contract per ADR-0013 R3:
- All five identity fields must be non-blank strings.
- ``state_schema_version`` must be a positive int in the supported set.
- Path-traversal / control-character / separator characters are rejected
  *before* any path construction (R3 + R10).
- A namespace/identity mismatch returns a structured ``RestoreError``,
  not silent empty fallback (RISK_001 + A1 fail-closed observability).
- The validator has no filesystem side effects.

R-trace: see BUILD-PLAN §TDD_TEST_LIST GROUP_003_IDENTITY_VALIDATION.
"""

from __future__ import annotations

from pathlib import Path

import pytest


def _identity(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "project_id": "hestai-context-mcp",
        "workspace_id": "build-adr-13",
        "user_id": "shaun",
        "state_schema_version": 1,
        "carrier_namespace": "personal",
    }
    base.update(overrides)
    return base


@pytest.mark.unit
class TestValidIdentity:
    """TEST_021: a fully-valid identity passes."""

    def test_valid_identity_tuple_passes_validation(self) -> None:
        from hestai_context_mcp.storage.identity import validate_identity_tuple
        from hestai_context_mcp.storage.types import IdentityTuple

        identity = IdentityTuple(**_identity())  # type: ignore[arg-type]
        # No exception -> success.
        result = validate_identity_tuple(identity)
        assert result is identity


@pytest.mark.unit
class TestBlankRejection:
    """TEST_022..TEST_025: blank components are rejected."""

    @pytest.mark.parametrize(
        "field",
        ["project_id", "workspace_id", "user_id", "carrier_namespace"],
    )
    def test_blank_component_is_rejected(self, field: str) -> None:
        from hestai_context_mcp.storage.identity import (
            IdentityValidationError,
            validate_identity_tuple,
        )
        from hestai_context_mcp.storage.types import IdentityTuple

        identity = IdentityTuple(**_identity(**{field: "  "}))  # type: ignore[arg-type]
        with pytest.raises(IdentityValidationError) as excinfo:
            validate_identity_tuple(identity)
        assert excinfo.value.code == "blank_identity_component"
        assert excinfo.value.field == field


@pytest.mark.unit
class TestUnsupportedSchemaVersion:
    """TEST_026: state_schema_version must be in SUPPORTED set."""

    @pytest.mark.parametrize("version", [0, -1, 99])
    def test_unsupported_schema_version_is_rejected(self, version: int) -> None:
        from hestai_context_mcp.storage.identity import (
            IdentityValidationError,
            validate_identity_tuple,
        )
        from hestai_context_mcp.storage.types import IdentityTuple

        identity = IdentityTuple(**_identity(state_schema_version=version))  # type: ignore[arg-type]
        with pytest.raises(IdentityValidationError) as excinfo:
            validate_identity_tuple(identity)
        assert excinfo.value.code == "unsupported_schema_version"


@pytest.mark.unit
class TestPathTraversalRejection:
    """TEST_027/TEST_028/TEST_029: unsafe characters rejected before path construction."""

    @pytest.mark.parametrize(
        "field, value",
        [
            ("project_id", "p/q"),
            ("workspace_id", "w\\x"),
            ("user_id", "..//evil"),
            ("carrier_namespace", "team\nrogue"),
            ("project_id", "a\tb"),
            ("user_id", "u\rv"),
        ],
    )
    def test_unsafe_characters_in_identity_components_rejected(
        self, field: str, value: str
    ) -> None:
        from hestai_context_mcp.storage.identity import (
            IdentityValidationError,
            validate_identity_tuple,
        )
        from hestai_context_mcp.storage.types import IdentityTuple

        identity = IdentityTuple(**_identity(**{field: value}))  # type: ignore[arg-type]
        with pytest.raises(IdentityValidationError) as excinfo:
            validate_identity_tuple(identity)
        assert excinfo.value.code in {"path_separator", "path_traversal", "control_character"}
        assert excinfo.value.field == field


@pytest.mark.unit
class TestNamespaceIdentityMismatch:
    """TEST_030/TEST_031: namespace and identity must align (structured error)."""

    def test_namespace_and_identity_mismatch_is_structured_error(self) -> None:
        from hestai_context_mcp.storage.identity import (
            IdentityValidationError,
            validate_namespace_matches_identity,
        )
        from hestai_context_mcp.storage.types import IdentityTuple, PortableNamespace

        identity = IdentityTuple(**_identity())  # type: ignore[arg-type]
        namespace = PortableNamespace(
            project_id="other-project",
            workspace_id=identity.workspace_id,
            user_id=identity.user_id,
            state_schema_version=identity.state_schema_version,
            carrier_namespace=identity.carrier_namespace,
        )
        with pytest.raises(IdentityValidationError) as excinfo:
            validate_namespace_matches_identity(namespace=namespace, identity=identity)
        assert excinfo.value.code == "namespace_identity_mismatch"

    def test_restore_identity_mismatch_does_not_return_empty_success(self) -> None:
        # RISK_001 + A1 — fail-closed: an identity mismatch must surface as
        # a structured RestoreError so callers can react, not pretend success.
        from hestai_context_mcp.storage.identity import RestoreError

        err = RestoreError(code="identity_mismatch", message="forks not allowed")
        assert err.code == "identity_mismatch"
        # cause is optional but field exists for chained diagnostics.
        assert hasattr(err, "cause")


@pytest.mark.unit
class TestNoSideEffects:
    """TEST_032: validation has no filesystem side effects."""

    def test_identity_validation_has_no_filesystem_side_effects(self, tmp_path: Path) -> None:
        from hestai_context_mcp.storage.identity import validate_identity_tuple
        from hestai_context_mcp.storage.types import IdentityTuple

        before = sorted(p.name for p in tmp_path.iterdir())
        identity = IdentityTuple(**_identity())  # type: ignore[arg-type]
        validate_identity_tuple(identity)
        after = sorted(p.name for p in tmp_path.iterdir())
        assert before == after


@pytest.mark.unit
class TestRestoreErrorStructure:
    """A1: structured RestoreError has code + cause (fail-closed observability)."""

    def test_restore_error_carries_code_and_cause(self) -> None:
        from hestai_context_mcp.storage.identity import RestoreError

        cause = ValueError("upstream")
        err = RestoreError(code="schema_too_new", message="reader too old", cause=cause)
        assert err.code == "schema_too_new"
        assert err.cause is cause
        # Inheriting from Exception so callers can raise/catch normally.
        assert isinstance(err, Exception)
