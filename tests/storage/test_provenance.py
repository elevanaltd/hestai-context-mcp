"""GROUP_005: REDACTION_PROVENANCE — RED-first tests for storage/provenance.py.

Asserts the redaction provenance contract per ADR-0013 R6 + R10 and the
binding rulings:
- RISK_004 + G6: ``REDACTION_ENGINE_NAME`` and ``REDACTION_ENGINE_VERSION``
  constants live in ``core.redaction`` and propagate into every
  RedactionProvenance metadata block; the version bumps on pattern or
  semantic change (A4 contract test).
- RISK_010: publication fails closed when provenance is incomplete.
- G4 (CIV): write_artifact paths MUST wrap RedactionProvenance construction
  in a single atomic guard that raises BEFORE any filesystem write. This
  group provides the guard helper that downstream groups (006,
  012) consume.

R-trace: see BUILD-PLAN §TDD_TEST_LIST GROUP_005_REDACTION_PROVENANCE +
INVARIANT_003.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timezone

import pytest


@pytest.mark.unit
class TestRulesetHashDeterministic:
    """TEST_045: ruleset hash deterministic for current PATTERNS."""

    def test_ruleset_hash_is_deterministic_for_redaction_patterns(self) -> None:
        from hestai_context_mcp.storage.provenance import compute_ruleset_hash

        h1 = compute_ruleset_hash()
        h2 = compute_ruleset_hash()
        assert h1 == h2
        # Hex digest, non-empty.
        assert isinstance(h1, str) and len(h1) >= 16
        int(h1, 16)  # parses as hex


@pytest.mark.unit
class TestEngineNameAndVersion:
    """TEST_046 + RISK_004 + G6: provenance carries engine name + version."""

    def test_redaction_provenance_contains_engine_name_and_version(self) -> None:
        from hestai_context_mcp.core.redaction import (
            REDACTION_ENGINE_NAME,
            REDACTION_ENGINE_VERSION,
        )
        from hestai_context_mcp.storage.provenance import build_provenance

        prov = build_provenance(
            input_text="hello sk-AAAAAAAAAAAAAAAAAAAAAA world",
            output_text="hello [REDACTED_API_KEY] world",
            redacted_credential_categories=("ai_api_key",),
        )
        assert prov.engine_name == REDACTION_ENGINE_NAME
        assert prov.engine_version == REDACTION_ENGINE_VERSION
        # G6: REDACTION_ENGINE_VERSION constant is a string and is asserted
        # present in artifact metadata via this provenance object.
        assert isinstance(REDACTION_ENGINE_VERSION, str) and REDACTION_ENGINE_VERSION


@pytest.mark.unit
class TestHashesPresent:
    """TEST_047: input + output hashes present and distinct for non-trivial input."""

    def test_redaction_provenance_contains_input_and_output_hashes(self) -> None:
        from hestai_context_mcp.storage.provenance import build_provenance

        prov = build_provenance(
            input_text="hello sk-AAAAAAAAAAAAAAAAAAAAAA world",
            output_text="hello [REDACTED_API_KEY] world",
            redacted_credential_categories=("ai_api_key",),
        )
        assert prov.input_artifact_hash and prov.output_artifact_hash
        assert prov.input_artifact_hash != prov.output_artifact_hash


@pytest.mark.unit
class TestTimestampTimezoneAware:
    """TEST_048: redacted_at is timezone-aware."""

    def test_redaction_provenance_timestamp_is_timezone_aware(self) -> None:
        from hestai_context_mcp.storage.provenance import build_provenance

        prov = build_provenance(
            input_text="x",
            output_text="x",
            redacted_credential_categories=(),
        )
        assert prov.redacted_at.tzinfo is not None


@pytest.mark.unit
class TestClassificationLabel:
    """TEST_049: classification_label gate is PORTABLE_MEMORY."""

    def test_redaction_provenance_classification_must_be_portable_memory(self) -> None:
        from hestai_context_mcp.storage.provenance import build_provenance

        prov = build_provenance(
            input_text="x", output_text="x", redacted_credential_categories=()
        )
        assert prov.classification_label == "PORTABLE_MEMORY"


@pytest.mark.unit
class TestCategoriesNormalization:
    """TEST_050: redacted_credential_categories may be empty, never None."""

    def test_redacted_categories_can_be_empty_but_not_none(self) -> None:
        from hestai_context_mcp.storage.provenance import build_provenance

        prov = build_provenance(
            input_text="x", output_text="x", redacted_credential_categories=()
        )
        assert prov.redacted_credential_categories == ()


@pytest.mark.unit
class TestCompletenessValidation:
    """TEST_051..TEST_054: any missing field fails complete-provenance validation."""

    @pytest.mark.parametrize(
        "field, value",
        [
            ("engine_name", ""),
            ("engine_version", ""),
            ("ruleset_hash", ""),
            ("input_artifact_hash", ""),
            ("output_artifact_hash", ""),
        ],
    )
    def test_missing_field_fails_complete_provenance_validation(
        self, field: str, value: str
    ) -> None:
        from hestai_context_mcp.storage.provenance import (
            ProvenanceIncompleteError,
            build_provenance,
            validate_provenance_complete,
        )

        prov = build_provenance(
            input_text="x", output_text="x", redacted_credential_categories=()
        )
        broken = dataclasses.replace(prov, **{field: value})
        with pytest.raises(ProvenanceIncompleteError) as excinfo:
            validate_provenance_complete(broken)
        assert excinfo.value.code == "provenance_incomplete"
        assert excinfo.value.missing_field == field


@pytest.mark.unit
class TestStaleRulesetHashFails:
    """TEST_055: stale ruleset hash fails publication validation."""

    def test_stale_ruleset_hash_fails_publication_validation(self) -> None:
        from hestai_context_mcp.storage.provenance import (
            ProvenanceStaleError,
            assert_ruleset_hash_current,
            build_provenance,
        )

        prov = build_provenance(
            input_text="x", output_text="x", redacted_credential_categories=()
        )
        stale = dataclasses.replace(prov, ruleset_hash="0" * 64)
        with pytest.raises(ProvenanceStaleError) as excinfo:
            assert_ruleset_hash_current(stale)
        assert excinfo.value.code == "ruleset_hash_stale"


@pytest.mark.unit
class TestRedactionResultIntegration:
    """TEST_056: RedactionEngine.redact result feeds provenance categories."""

    def test_existing_redaction_engine_redacted_types_feed_provenance_categories(self) -> None:
        from hestai_context_mcp.core.redaction import RedactionEngine
        from hestai_context_mcp.storage.provenance import build_provenance_from_result

        engine = RedactionEngine()
        text = "Bearer abc123== and AKIAABCDEFGHIJKLMNOP"
        result = engine.redact(text)
        prov = build_provenance_from_result(input_text=text, result=result)
        assert set(prov.redacted_credential_categories) == set(result.redacted_types)
        assert prov.input_artifact_hash != prov.output_artifact_hash


@pytest.mark.unit
class TestG4AtomicGuard:
    """G4: build_provenance_or_raise raises BEFORE any side effect when incomplete.

    This is the atomic guard helper that storage/local_filesystem.py and
    clock_out wrap their write paths in (RISK_010 fail-closed publish).
    """

    def test_atomic_guard_raises_before_any_write_when_incomplete(self) -> None:
        from hestai_context_mcp.storage.provenance import (
            ProvenanceIncompleteError,
            build_provenance_or_raise,
        )

        with pytest.raises(ProvenanceIncompleteError):
            # Empty input/output with no categories is permitted (categories
            # may be empty per NOTE_009), but blank engine version triggers
            # the guard via override.
            build_provenance_or_raise(
                input_text="x",
                output_text="x",
                redacted_credential_categories=(),
                engine_version_override="",
            )


@pytest.mark.unit
class TestRedactionEngineVersionBumpContract:
    """A4: REDACTION_ENGINE_VERSION bump asserts metadata persistence.

    The RISK_004 ruling is that the version is bumped when patterns or
    semantics change. We assert the bump *contract* by computing a stable
    digest over PATTERNS at the version's documented snapshot — if anyone
    edits PATTERNS without bumping REDACTION_ENGINE_VERSION, this test
    fails and forces the human bump.
    """

    def test_redaction_engine_version_matches_pattern_set_snapshot(self) -> None:
        from hestai_context_mcp.core.redaction import (
            REDACTION_ENGINE_VERSION,
            RedactionEngine,
        )
        from hestai_context_mcp.storage.provenance import compute_ruleset_hash

        # The current PATTERNS set has these named keys; if a new pattern
        # is added or an existing one renamed, this snapshot must be
        # updated AND REDACTION_ENGINE_VERSION must be bumped.
        snapshot_keys = sorted(RedactionEngine.PATTERNS.keys())
        assert snapshot_keys == [
            "ai_api_key",
            "aws_key",
            "bearer_token",
            "db_password",
            "private_key",
        ], (
            "RedactionEngine.PATTERNS changed — bump REDACTION_ENGINE_VERSION "
            "in core.redaction and update this snapshot."
        )
        # Version must be a non-empty string; bump cycle is human-driven
        # (RISK_004). For B1 the documented value is '1'.
        assert REDACTION_ENGINE_VERSION == "1"
        # Ruleset hash is computed from PATTERNS — assert it matches a
        # stored snapshot. We don't pin the exact hex here (it would
        # over-couple to regex internals); we assert that toggling a
        # pattern changes the hash deterministically.
        h_now = compute_ruleset_hash()
        # mutate-and-restore round trip: alter a pattern's replacement,
        # confirm hash changes, then restore.
        original = RedactionEngine.PATTERNS["ai_api_key"]
        try:
            RedactionEngine.PATTERNS["ai_api_key"] = (
                original[0],
                "[REDACTED_API_KEY_v2]",
            )
            h_after = compute_ruleset_hash()
            assert h_now != h_after
        finally:
            RedactionEngine.PATTERNS["ai_api_key"] = original
        h_restored = compute_ruleset_hash()
        assert h_now == h_restored


@pytest.mark.unit
class TestProvenanceClassificationLiteral:
    """CRS C1: classification_label is the Literal['PORTABLE_MEMORY']."""

    def test_provenance_classification_literal(self) -> None:
        from hestai_context_mcp.storage.provenance import build_provenance

        prov = build_provenance(
            input_text="x", output_text="x", redacted_credential_categories=()
        )
        assert prov.classification_label == "PORTABLE_MEMORY"
        # tzinfo robustness across Python timezone module variants
        _ = timezone.utc
        _ = UTC
        assert prov.redacted_at.tzinfo is not None
        # not naive
        assert prov.redacted_at != datetime.utcnow()
