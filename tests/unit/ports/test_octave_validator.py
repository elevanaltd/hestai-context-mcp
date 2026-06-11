"""Port contract tests for ``hestai_context_mcp.ports.octave_validator``.

RFC #53 Gate B. Locks the OctaveValidator port shape (mirroring ai_client.py):

* A runtime-checkable :class:`typing.Protocol` (``OctaveValidator``) with a
  single ``validate`` method returning a STRUCTURED result (PROD I4), never a
  blob.
* A frozen ``OctaveValidationResult`` dataclass: ``ok: bool``,
  ``errors: list[...]``, ``warnings: list[...]``, plus an ``available`` flag.
* A real adapter that wraps octave-mcp's IN-PROCESS validate API
  (``parse_with_warnings`` + ``Validator().validate``) — never over stdio,
  never an in-repo AST.
* A fail-soft path: when the ``validation`` extra (octave-mcp) is not
  importable, ``get_octave_validator()`` returns a degraded validator whose
  result is ``ok=True, available=False`` with a structured
  "real-validation unavailable" warning. It NEVER crashes and NEVER blocks.

The real-adapter tests are skipped when octave-mcp is absent; the fail-soft
tests simulate absence by monkeypatching the import probe, so they run in BOTH
environments.
"""

from __future__ import annotations

import importlib.util

import pytest

OCTAVE_MCP_INSTALLED = importlib.util.find_spec("octave_mcp") is not None

requires_octave_mcp = pytest.mark.skipif(
    not OCTAVE_MCP_INSTALLED,
    reason="octave-mcp not installed (the 'validation' extra is absent)",
)

VALID_DECISION = (
    "===DECISION_RECORD===\n" "META:\n" "  TYPE::DECISION_RECORD\n" "  TOKEN::FOO-BAR-20260101\n"
)

# Unbalanced bracket — octave-mcp's strict lexer raises (LexerError) where the
# regex Gate A is blind. This is exactly the class of defect Gate B hardens.
BROKEN_AST = "===DECISION_RECORD===\nMETA:\n  X::[a, b\n"


class TestPortModuleShape:
    """Module exposes the expected public symbols."""

    def test_module_importable(self):
        import hestai_context_mcp.ports.octave_validator  # noqa: F401

    def test_exports_protocol_class(self):
        from hestai_context_mcp.ports.octave_validator import OctaveValidator

        assert getattr(OctaveValidator, "_is_protocol", False)

    def test_protocol_is_runtime_checkable(self):
        from hestai_context_mcp.ports.octave_validator import OctaveValidator

        # runtime_checkable protocols support isinstance against duck types.
        class _Dummy:
            def validate(self, content: str) -> object:  # pragma: no cover
                return None

        assert isinstance(_Dummy(), OctaveValidator)

    def test_exports_result_dataclass(self):
        from hestai_context_mcp.ports.octave_validator import OctaveValidationResult

        result = OctaveValidationResult(ok=True, errors=[], warnings=[], available=True)
        assert result.ok is True
        assert result.errors == []
        assert result.warnings == []
        assert result.available is True

    def test_result_is_frozen(self):
        from dataclasses import FrozenInstanceError

        from hestai_context_mcp.ports.octave_validator import OctaveValidationResult

        result = OctaveValidationResult(ok=True, errors=[], warnings=[], available=True)
        with pytest.raises(FrozenInstanceError):
            result.ok = False  # type: ignore[misc]

    def test_exports_factory(self):
        from hestai_context_mcp.ports.octave_validator import get_octave_validator

        validator = get_octave_validator()
        # Whatever it returns, it must satisfy the port.
        from hestai_context_mcp.ports.octave_validator import OctaveValidator

        assert isinstance(validator, OctaveValidator)


class TestResultStructure:
    """PROD I4: the result is a structured dict-able shape, never a blob."""

    def test_to_dict_has_defined_fields(self):
        from hestai_context_mcp.ports.octave_validator import OctaveValidationResult

        result = OctaveValidationResult(
            ok=False,
            errors=[{"code": "E007", "message": "bad", "line": 3}],
            warnings=[{"code": "W001", "message": "warn", "line": 0}],
            available=True,
        )
        payload = result.to_dict()
        assert set(payload) == {"ok", "errors", "warnings", "available"}
        assert payload["ok"] is False
        assert payload["errors"][0]["code"] == "E007"
        assert payload["warnings"][0]["code"] == "W001"
        assert payload["available"] is True


@requires_octave_mcp
class TestRealAdapter:
    """The real adapter binds to octave-mcp's IN-PROCESS validate API."""

    def _make(self):
        from hestai_context_mcp.ports.octave_validator import RealOctaveValidator

        return RealOctaveValidator()

    def test_valid_document_passes(self):
        result = self._make().validate(VALID_DECISION)
        assert result.available is True
        assert result.ok is True
        assert result.errors == []

    def test_unbalanced_bracket_fails_with_structured_error(self):
        result = self._make().validate(BROKEN_AST)
        assert result.available is True
        assert result.ok is False
        assert result.errors, "expected at least one structured error"
        first = result.errors[0]
        # Structured, not a blob: every error carries a code + message.
        assert "code" in first
        assert "message" in first
        assert isinstance(first["message"], str)

    def test_never_raises_on_garbage(self):
        # Even total garbage must produce a structured result, never an exception.
        result = self._make().validate("\x00 not octave at all { ] [")
        assert result.available is True
        assert result.ok is False
        assert isinstance(result.errors, list)

    def test_factory_returns_real_adapter_when_extra_present(self):
        from hestai_context_mcp.ports.octave_validator import (
            RealOctaveValidator,
            get_octave_validator,
        )

        assert isinstance(get_octave_validator(), RealOctaveValidator)


class TestFailSoftWhenExtraAbsent:
    """Fail-soft: octave-mcp absent -> degrade, never crash, never block."""

    def test_unavailable_validator_is_ok_but_flags_unavailable(self):
        from hestai_context_mcp.ports.octave_validator import UnavailableOctaveValidator

        result = UnavailableOctaveValidator().validate(VALID_DECISION)
        # ok=True so it does NOT block the tool; available=False signals degrade.
        assert result.ok is True
        assert result.available is False
        assert result.errors == []
        # A structured warning surfaces the degraded state (not a silent pass).
        assert result.warnings, "expected a real-validation-unavailable warning"
        codes = {w.get("code") for w in result.warnings}
        assert "REAL_VALIDATION_UNAVAILABLE" in codes

    def test_unavailable_validator_never_raises(self):
        from hestai_context_mcp.ports.octave_validator import UnavailableOctaveValidator

        # Garbage in, structured degraded result out — no exception.
        result = UnavailableOctaveValidator().validate("\x00 { ] [ garbage")
        assert result.available is False
        assert result.ok is True

    def test_factory_degrades_when_import_probe_reports_absent(self, monkeypatch):
        import hestai_context_mcp.ports.octave_validator as mod

        # Simulate the 'validation' extra being absent regardless of the real
        # environment by forcing the feature-detection probe to report False.
        monkeypatch.setattr(mod, "_octave_mcp_available", lambda: False)

        validator = mod.get_octave_validator()
        assert isinstance(validator, mod.UnavailableOctaveValidator)

        result = validator.validate(VALID_DECISION)
        assert result.available is False
        assert result.ok is True
