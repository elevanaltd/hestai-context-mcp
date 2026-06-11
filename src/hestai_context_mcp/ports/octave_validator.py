"""OCTAVE validation port (RFC #53 Gate B).

This module defines the :class:`OctaveValidator` Protocol and a small family of
adapters, mirroring the port/adapter/fail-soft pattern established in
:mod:`hestai_context_mcp.ports.ai_client`.

**Why a port** (North Star §4; PROD I6 LEGACY_INDEPENDENCE):
    octave-mcp *owns* the OCTAVE format. This repository never reinvents an
    OCTAVE AST and never depends on octave-mcp at runtime. The real validator is
    reached only through this feature-detected, fail-soft seam, gated by the
    optional ``validation`` extra. The default install stays octave-mcp-free.

**Integration shape** (library-behind-a-port, IN-PROCESS):
    The real adapter imports octave-mcp and calls its public validate API
    *in-process* — never a server over stdio. The flow is:

        doc, warnings = octave_mcp.parse_with_warnings(content, strict_structure=True)
        errors = octave_mcp.Validator().validate(doc, strict=False)

    ``parse_with_warnings`` raises ``LexerError``/``ParserError`` on syntactic /
    structural defects (the class of bug the regex Gate A is blind to);
    ``Validator.validate`` returns a list of ``ValidationError`` dataclasses
    (``code``/``message``/``field_path``/``line``/``severity``).

**Structured result** (PROD I4 STRUCTURED_RETURN_SHAPES):
    Every adapter returns an :class:`OctaveValidationResult` — never a raw
    report blob. ``to_dict`` exposes exactly ``{ok, errors, warnings,
    available}`` so the caller can merge fields programmatically.

**Fail-soft** (never crash, never block):
    When octave-mcp is not importable, :func:`get_octave_validator` returns an
    :class:`UnavailableOctaveValidator`. Its result is ``ok=True`` (so the tool
    is NOT blocked) with ``available=False`` and a structured
    ``REAL_VALIDATION_UNAVAILABLE`` warning (so the degrade is auditable, not
    silent). The regex Gate A continues to run regardless.
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

__all__ = [
    "OctaveValidationResult",
    "OctaveValidator",
    "RealOctaveValidator",
    "UnavailableOctaveValidator",
    "get_octave_validator",
]

# Stable warning code surfaced when the optional ``validation`` extra is absent.
REAL_VALIDATION_UNAVAILABLE = "REAL_VALIDATION_UNAVAILABLE"


@dataclass(frozen=True)
class OctaveValidationResult:
    """Structured outcome of a real-OCTAVE validation pass (PROD I4).

    Fields:
        ok: True when the document passed real validation (no error-severity
            findings). Note the fail-soft adapter also reports ``ok=True`` —
            inspect ``available`` to distinguish "validated clean" from
            "could not validate".
        errors: Error-severity findings, each a structured dict with at least
            ``code`` and ``message`` (plus ``field_path``/``line`` when known).
        warnings: Non-blocking findings (lenient-parse repairs, schema
            warnings, or the degrade signal), same dict shape.
        available: True when the real octave-mcp backend actually ran; False
            when the ``validation`` extra was absent and the pass degraded.
    """

    ok: bool
    errors: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    available: bool = True

    def to_dict(self) -> dict[str, Any]:
        """Return the I4-conformant dict with all fields present."""
        return {
            "ok": self.ok,
            "errors": self.errors,
            "warnings": self.warnings,
            "available": self.available,
        }


@runtime_checkable
class OctaveValidator(Protocol):
    """Validate OCTAVE content against octave-mcp's real grammar.

    Intentionally a single synchronous method. Backend selection, feature
    detection, and the fail-soft degrade all live *below* this port (in the
    adapters and :func:`get_octave_validator`), so callers depend only on the
    structured contract.
    """

    def validate(self, content: str) -> OctaveValidationResult:
        """Return a structured validation result for ``content``.

        Implementations MUST NOT raise on malformed input: a validation failure
        is data (populated ``errors``), not an exception.
        """
        ...


def _octave_mcp_available() -> bool:
    """Feature-detect the optional ``validation`` extra (octave-mcp).

    Uses ``importlib.util.find_spec`` so detection is cheap and does not import
    the package as a side effect. Isolated in a tiny function so tests can
    monkeypatch the probe to simulate the extra's absence in any environment.
    """
    return importlib.util.find_spec("octave_mcp") is not None


class RealOctaveValidator:
    """In-process adapter over octave-mcp's real validate API.

    Imports octave-mcp lazily inside :meth:`validate` so merely importing this
    module never requires the optional extra. Translates octave-mcp's parser /
    lexer exceptions and ``ValidationError`` dataclasses into the structured
    :class:`OctaveValidationResult` (PROD I4).
    """

    def validate(self, content: str) -> OctaveValidationResult:
        # Lazy, in-process import. NEVER a server over stdio; NEVER an in-repo
        # AST. octave-mcp owns the format (North Star §4).
        import octave_mcp

        errors: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []

        try:
            doc, parse_warnings = octave_mcp.parse_with_warnings(content, strict_structure=True)
        except (octave_mcp.LexerError, octave_mcp.ParserError) as exc:
            # Syntactic / structural defect — the regex Gate A cannot see this.
            errors.append(
                {
                    "code": getattr(exc, "code", type(exc).__name__),
                    "message": str(exc),
                    "field_path": "",
                    "line": getattr(exc, "line", 0),
                }
            )
            return OctaveValidationResult(
                ok=False, errors=errors, warnings=warnings, available=True
            )
        except Exception as exc:  # noqa: BLE001 — never propagate; degrade to data.
            errors.append(
                {
                    "code": "OCTAVE_PARSE_ERROR",
                    "message": str(exc),
                    "field_path": "",
                    "line": 0,
                }
            )
            return OctaveValidationResult(
                ok=False, errors=errors, warnings=warnings, available=True
            )

        # Lenient-parse repairs / coalescing notes are warnings, not errors.
        for w in parse_warnings:
            warnings.append(self._normalise_parse_warning(w))

        try:
            validation_errors = octave_mcp.Validator().validate(doc, strict=False)
        except Exception as exc:  # noqa: BLE001 — never propagate; degrade to data.
            errors.append(
                {
                    "code": "OCTAVE_VALIDATE_ERROR",
                    "message": str(exc),
                    "field_path": "",
                    "line": 0,
                }
            )
            return OctaveValidationResult(
                ok=False, errors=errors, warnings=warnings, available=True
            )

        for ve in validation_errors:
            entry = {
                "code": getattr(ve, "code", ""),
                "message": getattr(ve, "message", str(ve)),
                "field_path": getattr(ve, "field_path", ""),
                "line": getattr(ve, "line", 0),
            }
            if getattr(ve, "severity", "error") == "warning":
                warnings.append(entry)
            else:
                errors.append(entry)

        return OctaveValidationResult(
            ok=not errors, errors=errors, warnings=warnings, available=True
        )

    @staticmethod
    def _normalise_parse_warning(raw: Any) -> dict[str, Any]:
        """Coerce an octave-mcp parse-warning dict into the structured shape."""
        if isinstance(raw, dict):
            return {
                "code": str(raw.get("subtype") or raw.get("type") or "PARSE_WARNING"),
                "message": str(raw.get("type", "")),
                "field_path": "",
                "line": int(raw.get("line", 0) or 0),
                "detail": raw,
            }
        return {
            "code": "PARSE_WARNING",
            "message": str(raw),
            "field_path": "",
            "line": 0,
        }


class UnavailableOctaveValidator:
    """Fail-soft adapter used when the ``validation`` extra is absent.

    Returns ``ok=True`` so the tool is never blocked, with ``available=False``
    and a structured ``REAL_VALIDATION_UNAVAILABLE`` warning so the degrade is
    auditable rather than silent. Never imports octave-mcp; never raises.
    """

    def validate(self, content: str) -> OctaveValidationResult:
        return OctaveValidationResult(
            ok=True,
            errors=[],
            warnings=[
                {
                    "code": REAL_VALIDATION_UNAVAILABLE,
                    "message": (
                        "Real OCTAVE validation was skipped: the optional "
                        "'validation' extra (octave-mcp) is not installed. "
                        "Regex Gate A validation still applied. Install with "
                        "'pip install hestai-context-mcp[validation]' to enable "
                        "full in-process AST validation."
                    ),
                    "field_path": "",
                    "line": 0,
                }
            ],
            available=False,
        )


def get_octave_validator() -> OctaveValidator:
    """Return the active OctaveValidator, feature-detecting the extra.

    Real adapter when octave-mcp is importable; the fail-soft
    :class:`UnavailableOctaveValidator` otherwise. The return type is the port
    Protocol, so callers never branch on the concrete adapter.
    """
    if _octave_mcp_available():
        return RealOctaveValidator()
    return UnavailableOctaveValidator()
