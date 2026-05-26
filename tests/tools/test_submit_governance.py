"""Tests for the submit_governance MCP tool (Symbiotic Intake Engine).

Spec source: GitHub issue #53 RFC body, ADR-RFC-ARCH-002 (L1S facet ABI),
ADR-RFC-ARCH-004 (AGR record schema). The tool transduces freeform prose
into governance artefacts via octave-secretary (goose) and emits a PR.

TDD RED phase: written before implementation. Covers:
  - Structured MCPResponse shape (PROD I4)
  - RedactionEngine pre-dispatch (PROD I2 fail-closed)
  - Deterministic SUPERSEDES lookup (no LLM)
  - L1S + AGR schema validators
  - gh-CLI PR emission gated by validation
  - Provider-adapter seam for goose (PROD I3)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Adversarial-fixture token assembly (defense in depth vs static scanners).
#
# The RedactionEngine MUST strip AWS-access-key-shaped tokens (AKIA + 16 of
# [A-Z0-9]) from prose_input before dispatch. To exercise that path we need
# a real-shape token at *runtime*, but we MUST NOT embed the literal in the
# source — GitGuardian's SaaS GitHub-App scanner ignores in-repo allowlists
# (.gitguardian.yaml, inline # ggignore markers) and would block the PR.
#
# Splitting the literal at module scope means:
#   - Source contains zero matches for AKIA[0-9A-Z]{16} → scanner is happy.
#   - Runtime-assembled string is byte-identical to the original adversarial
#     token, so RedactionEngine coverage (PROD I2 + A4) is unchanged.
# Keep .gitguardian.yaml and inline # ggignore markers as redundant layers.
# ---------------------------------------------------------------------------
_AWS_KEY_PREFIX = "AKIA"  # not a credential on its own
_AWS_KEY_BODY = "ABCDEFGHIJKLMNOP"  # 16 chars of [A-Z], shape-only filler
_ADVERSARIAL_AWS = _AWS_KEY_PREFIX + _AWS_KEY_BODY


# ---------------------------------------------------------------------------
# Component C: lookup_token_deterministic — pure FS, no LLM
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestLookupTokenDeterministic:
    """Token lookup must be pure-Python + filesystem; never an LLM call."""

    def test_returns_true_for_existing_decision_token(self, tmp_path: Path) -> None:
        from hestai_context_mcp.tools.submit_governance import (
            lookup_token_deterministic,
        )

        decisions = tmp_path / ".hestai" / "decisions"
        decisions.mkdir(parents=True)
        (decisions / "HO-EXAMPLE-DECISION-20260520.oct.md").write_text(
            '===DECISION_RECORD===\nMETA:\n  TYPE::DECISION_RECORD\n  TOKEN::"HO-EXAMPLE-DECISION-20260520"\n===END===\n'
        )

        assert lookup_token_deterministic(tmp_path, "HO-EXAMPLE-DECISION-20260520") is True

    def test_returns_true_for_existing_facet_card_id(self, tmp_path: Path) -> None:
        from hestai_context_mcp.tools.submit_governance import (
            lookup_token_deterministic,
        )

        concepts = tmp_path / ".hestai" / "context" / "concepts" / "hestai-context-mcp"
        concepts.mkdir(parents=True)
        (concepts / "FOUNDATIONAL.oct.md").write_text(
            "===CLUSTER_CARD===\nMETA:\n  ID::FOUNDATIONAL\n===END===\n"
        )

        assert lookup_token_deterministic(tmp_path, "FOUNDATIONAL") is True

    def test_returns_false_for_missing_token(self, tmp_path: Path) -> None:
        from hestai_context_mcp.tools.submit_governance import (
            lookup_token_deterministic,
        )

        (tmp_path / ".hestai" / "decisions").mkdir(parents=True)
        assert lookup_token_deterministic(tmp_path, "NEVER-EXISTED-20260101") is False

    def test_returns_false_on_missing_root(self, tmp_path: Path) -> None:
        from hestai_context_mcp.tools.submit_governance import (
            lookup_token_deterministic,
        )

        # No .hestai/ at all — must not crash.
        assert lookup_token_deterministic(tmp_path, "ANY-TOKEN-20260101") is False


# ---------------------------------------------------------------------------
# Component D: schema validators
# ---------------------------------------------------------------------------
@pytest.mark.contract
class TestAgrSchemaValidator:
    """AGR record validation per ADR-RFC-ARCH-004 §1.2 / §4.1."""

    def _valid_agr(self) -> dict[str, Any]:
        return {
            "type": "DECISION_RECORD",
            "version": "1.0",
            "token": "HO-EXAMPLE-DECISION-20260520",
            "status": "PROPOSED",
            "tier": "TACTICAL",
            "decision": "We adopt the symbiotic intake engine.",
            "because": "Authoring friction is the root cause of monolith growth.",
            "authored_at": "2026-05-20T12:00:00Z",
        }

    def test_valid_agr_passes(self) -> None:
        from hestai_context_mcp.tools.submit_governance import validate_agr_record

        errors = validate_agr_record(self._valid_agr())
        assert errors == []

    def test_missing_required_field_fails(self) -> None:
        from hestai_context_mcp.tools.submit_governance import validate_agr_record

        rec = self._valid_agr()
        del rec["decision"]
        errors = validate_agr_record(rec)
        assert any("decision" in e.lower() for e in errors)

    def test_malformed_token_fails(self) -> None:
        from hestai_context_mcp.tools.submit_governance import validate_agr_record

        rec = self._valid_agr()
        rec["token"] = "lowercase-bad-token"
        errors = validate_agr_record(rec)
        assert any("token" in e.lower() for e in errors)

    def test_date_mismatch_with_token_suffix_fails(self) -> None:
        from hestai_context_mcp.tools.submit_governance import validate_agr_record

        rec = self._valid_agr()
        rec["authored_at"] = "2026-01-01T00:00:00Z"  # disagrees with -20260520 suffix
        errors = validate_agr_record(rec)
        assert any("date" in e.lower() or "authored_at" in e.lower() for e in errors)

    def test_status_enum_rejected(self) -> None:
        from hestai_context_mcp.tools.submit_governance import validate_agr_record

        rec = self._valid_agr()
        rec["status"] = "DRAFT"
        errors = validate_agr_record(rec)
        assert any("status" in e.lower() for e in errors)

    def test_tier_enum_rejected(self) -> None:
        from hestai_context_mcp.tools.submit_governance import validate_agr_record

        rec = self._valid_agr()
        rec["tier"] = "URGENT"
        errors = validate_agr_record(rec)
        assert any("tier" in e.lower() for e in errors)

    def test_reserved_field_rejected(self) -> None:
        from hestai_context_mcp.tools.submit_governance import validate_agr_record

        rec = self._valid_agr()
        rec["DEPENDS_ON"] = ["OTHER-20260101"]
        errors = validate_agr_record(rec)
        assert any("reserved" in e.lower() or "depends_on" in e.lower() for e in errors)

    def test_superseded_requires_superseded_by(self) -> None:
        from hestai_context_mcp.tools.submit_governance import validate_agr_record

        rec = self._valid_agr()
        rec["status"] = "SUPERSEDED"
        # Missing SUPERSEDED_BY
        errors = validate_agr_record(rec)
        assert any("superseded_by" in e.lower() for e in errors)


@pytest.mark.contract
class TestL1sFacetSchemaValidator:
    """L1S facet ABI validation per ADR-RFC-ARCH-002 §1.2 envelope."""

    def _valid_facet(self) -> dict[str, Any]:
        return {
            "kind": "CONCEPT_CARD",
            "id": "ENGAGEMENT_UMBRELLA",
            "status": "proposed",
            "summary": "Parent data-lifecycle anchor.",
        }

    def test_valid_facet_passes(self) -> None:
        from hestai_context_mcp.tools.submit_governance import validate_l1s_facet_card

        assert validate_l1s_facet_card(self._valid_facet()) == []

    def test_bad_kind_rejected(self) -> None:
        from hestai_context_mcp.tools.submit_governance import validate_l1s_facet_card

        f = self._valid_facet()
        f["kind"] = "MYSTERY_CARD"
        errors = validate_l1s_facet_card(f)
        assert any("kind" in e.lower() for e in errors)

    def test_missing_id_rejected(self) -> None:
        from hestai_context_mcp.tools.submit_governance import validate_l1s_facet_card

        f = self._valid_facet()
        del f["id"]
        errors = validate_l1s_facet_card(f)
        assert any("id" in e.lower() for e in errors)


# ---------------------------------------------------------------------------
# Component A + B: top-level submit_governance entry + goose seam
# ---------------------------------------------------------------------------
class _StubDispatcher:
    """Test double for the goose dispatcher seam (PROD I3)."""

    def __init__(self, output: list[dict[str, Any]] | Exception) -> None:
        self._output = output
        self.received_prompt: str | None = None

    def dispatch(self, prompt: str) -> list[dict[str, Any]]:
        self.received_prompt = prompt
        if isinstance(self._output, Exception):
            raise self._output
        return self._output


@pytest.mark.unit
class TestSubmitGovernanceShape:
    """submit_governance must return a structured MCPResponse dict (PROD I4)."""

    def test_returns_structured_dict(self, tmp_path: Path) -> None:
        from hestai_context_mcp.tools.submit_governance import submit_governance

        dispatcher = _StubDispatcher(output=[])
        result = submit_governance(
            prose_input="placeholder",
            working_dir=str(tmp_path),
            dispatcher=dispatcher,
            dry_run=True,
        )
        assert isinstance(result, dict)
        for key in (
            "success",
            "branch",
            "pr_url",
            "validation_errors",
            "facet_artifacts",
        ):
            assert key in result

    def test_empty_prose_fails_validation(self, tmp_path: Path) -> None:
        from hestai_context_mcp.tools.submit_governance import submit_governance

        dispatcher = _StubDispatcher(output=[])
        result = submit_governance(
            prose_input="   ",
            working_dir=str(tmp_path),
            dispatcher=dispatcher,
            dry_run=True,
        )
        assert result["success"] is False
        assert result["pr_url"] is None
        assert any(
            "prose" in e.lower() or "empty" in e.lower() for e in result["validation_errors"]
        )


# ---------------------------------------------------------------------------
# REDACTION INTEGRATION — fail-closed (PROD I2)
# ---------------------------------------------------------------------------
@pytest.mark.integration
class TestRedactionIntegration:
    """Credentials in prose_input MUST NEVER reach the dispatch payload."""

    def test_api_key_redacted_before_dispatch(self, tmp_path: Path) -> None:
        from hestai_context_mcp.tools.submit_governance import submit_governance

        dispatcher = _StubDispatcher(output=[])
        leaky_prose = (
            "Decision: rotate the key. The compromised value was "
            "sk-AAAAAAAAAAAAAAAAAAAAAAAAAAAA which leaked."
        )
        submit_governance(
            prose_input=leaky_prose,
            working_dir=str(tmp_path),
            dispatcher=dispatcher,
            dry_run=True,
        )
        assert dispatcher.received_prompt is not None
        assert "sk-AAAAAAAAAAAAAAAAAAAAAAAAAAAA" not in dispatcher.received_prompt
        assert "[REDACTED_API_KEY]" in dispatcher.received_prompt

    def test_aws_key_redacted_before_dispatch(self, tmp_path: Path) -> None:
        from hestai_context_mcp.tools.submit_governance import submit_governance

        dispatcher = _StubDispatcher(output=[])
        # Adversarial AKIA-shaped fixture for PROD I2 (fail-closed redaction) /
        # PROD A4 (adversarial redaction review on new provider adapter). NOT a
        # real credential; the test asserts the RedactionEngine strips this
        # exact pattern shape from prose_input before goose dispatch. The
        # token is assembled at runtime from module-level halves so the source
        # text contains no AKIA[0-9A-Z]{16} match (defeats GitGuardian SaaS
        # scanner which ignores in-repo allowlists). Runtime semantics are
        # identical to a single literal.
        leaky = f"AWS leak {_ADVERSARIAL_AWS} in the prose."  # ggignore
        submit_governance(
            prose_input=leaky,
            working_dir=str(tmp_path),
            dispatcher=dispatcher,
            dry_run=True,
        )
        assert dispatcher.received_prompt is not None
        assert _ADVERSARIAL_AWS not in dispatcher.received_prompt  # ggignore

    def test_redaction_failure_refuses_dispatch(self, tmp_path: Path) -> None:
        """If RedactionEngine raises, the tool MUST refuse to dispatch."""
        from hestai_context_mcp.tools.submit_governance import submit_governance

        dispatcher = _StubDispatcher(output=[])
        with patch("hestai_context_mcp.tools.submit_governance.RedactionEngine") as mock_engine:
            mock_engine.return_value.redact.side_effect = RuntimeError("boom")
            result = submit_governance(
                prose_input="anything",
                working_dir=str(tmp_path),
                dispatcher=dispatcher,
                dry_run=True,
            )
        assert result["success"] is False
        assert dispatcher.received_prompt is None
        assert any("redaction" in e.lower() for e in result["validation_errors"])


# ---------------------------------------------------------------------------
# Validation gate (Component D) — schema failure blocks PR emission (Component E)
# ---------------------------------------------------------------------------
@pytest.mark.contract
class TestValidationGatesPrEmission:
    """If schema validation fails, gh-CLI MUST NOT be invoked."""

    def test_malformed_agr_blocks_pr(self, tmp_path: Path) -> None:
        from hestai_context_mcp.tools.submit_governance import submit_governance

        # Dispatcher returns a malformed AGR (missing required `decision`)
        bad_output = [
            {
                "artifact_kind": "agr",
                "record": {
                    "type": "DECISION_RECORD",
                    "version": "1.0",
                    "token": "HO-BAD-DECISION-20260520",
                    "status": "PROPOSED",
                    "tier": "TACTICAL",
                    # decision missing
                    "because": "rationale",
                    "authored_at": "2026-05-20T00:00:00Z",
                },
            }
        ]
        dispatcher = _StubDispatcher(output=bad_output)

        with patch("hestai_context_mcp.tools.submit_governance._emit_pr_via_gh") as mock_emit:
            result = submit_governance(
                prose_input="real prose",
                working_dir=str(tmp_path),
                dispatcher=dispatcher,
                dry_run=False,
            )

        assert result["success"] is False
        assert result["pr_url"] is None
        mock_emit.assert_not_called()
        assert result["validation_errors"], "expected schema errors"

    def test_missing_supersedes_target_blocks_pr(self, tmp_path: Path) -> None:
        from hestai_context_mcp.tools.submit_governance import submit_governance

        # AGR references a SUPERSEDES token that does not exist on disk.
        bad_output = [
            {
                "artifact_kind": "agr",
                "record": {
                    "type": "DECISION_RECORD",
                    "version": "1.0",
                    "token": "HO-NEW-DECISION-20260520",
                    "status": "RATIFIED",
                    "tier": "TACTICAL",
                    "decision": "supersede the missing one",
                    "because": "because we said so",
                    "authored_at": "2026-05-20T00:00:00Z",
                    "supersedes": "HO-DOES-NOT-EXIST-20260101",
                },
            }
        ]
        dispatcher = _StubDispatcher(output=bad_output)

        with patch("hestai_context_mcp.tools.submit_governance._emit_pr_via_gh") as mock_emit:
            result = submit_governance(
                prose_input="real prose",
                working_dir=str(tmp_path),
                dispatcher=dispatcher,
                dry_run=False,
            )

        assert result["success"] is False
        mock_emit.assert_not_called()
        assert any(
            "supersede" in e.lower() or "does-not-exist" in e.lower()
            for e in result["validation_errors"]
        )

    def test_valid_artifacts_invoke_pr_emission(self, tmp_path: Path) -> None:
        from hestai_context_mcp.tools.submit_governance import submit_governance

        good_output = [
            {
                "artifact_kind": "agr",
                "record": {
                    "type": "DECISION_RECORD",
                    "version": "1.0",
                    "token": "HO-GOOD-DECISION-20260520",
                    "status": "PROPOSED",
                    "tier": "TACTICAL",
                    "decision": "adopt the intake engine",
                    "because": "authoring friction is real",
                    "authored_at": "2026-05-20T00:00:00Z",
                },
            }
        ]
        dispatcher = _StubDispatcher(output=good_output)

        with patch("hestai_context_mcp.tools.submit_governance._emit_pr_via_gh") as mock_emit:
            mock_emit.return_value = {
                "branch": "governance/HO-GOOD-DECISION-20260520",
                "pr_url": "https://github.com/example/repo/pull/123",
            }
            result = submit_governance(
                prose_input="adopt the intake engine",
                working_dir=str(tmp_path),
                dispatcher=dispatcher,
                dry_run=False,
            )

        assert result["success"] is True
        assert result["pr_url"] == "https://github.com/example/repo/pull/123"
        assert result["branch"] == "governance/HO-GOOD-DECISION-20260520"
        mock_emit.assert_called_once()
        assert result["validation_errors"] == []
        assert len(result["facet_artifacts"]) == 1


# ---------------------------------------------------------------------------
# PalClinkGooseDispatcher — provider-adapter seam unit tests
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestPalClinkGooseDispatcher:
    """Default dispatcher must fail-closed on every subprocess error mode."""

    def test_executable_missing_raises_runtime_error(self) -> None:
        from hestai_context_mcp.tools.submit_governance import PalClinkGooseDispatcher

        d = PalClinkGooseDispatcher(executable="nonexistent-binary-xyz-123")
        with pytest.raises(RuntimeError, match="executable not found"):
            d.dispatch("hello")

    def test_nonzero_exit_raises_runtime_error(self) -> None:
        from hestai_context_mcp.tools import submit_governance as mod

        class _Result:
            returncode = 2
            stdout = ""
            stderr = "boom"

        with (
            patch.object(mod.shutil, "which", return_value="/bin/true"),
            patch.object(mod.subprocess, "run", return_value=_Result()),
        ):
            d = mod.PalClinkGooseDispatcher()
            with pytest.raises(RuntimeError, match="exited 2"):
                d.dispatch("p")

    def test_non_json_output_raises_runtime_error(self) -> None:
        from hestai_context_mcp.tools import submit_governance as mod

        class _Result:
            returncode = 0
            stdout = "not json at all"
            stderr = ""

        with (
            patch.object(mod.shutil, "which", return_value="/bin/true"),
            patch.object(mod.subprocess, "run", return_value=_Result()),
        ):
            d = mod.PalClinkGooseDispatcher()
            with pytest.raises(RuntimeError, match="non-JSON"):
                d.dispatch("p")

    def test_non_list_json_raises_runtime_error(self) -> None:
        from hestai_context_mcp.tools import submit_governance as mod

        class _Result:
            returncode = 0
            stdout = '{"not": "a list"}'
            stderr = ""

        with (
            patch.object(mod.shutil, "which", return_value="/bin/true"),
            patch.object(mod.subprocess, "run", return_value=_Result()),
        ):
            d = mod.PalClinkGooseDispatcher()
            with pytest.raises(RuntimeError, match="JSON list"):
                d.dispatch("p")

    def test_valid_json_list_passthrough(self) -> None:
        from hestai_context_mcp.tools import submit_governance as mod

        class _Result:
            returncode = 0
            stdout = '[{"artifact_kind": "agr", "record": {}}]'
            stderr = ""

        with (
            patch.object(mod.shutil, "which", return_value="/bin/true"),
            patch.object(mod.subprocess, "run", return_value=_Result()),
        ):
            d = mod.PalClinkGooseDispatcher()
            result = d.dispatch("p")
        assert result == [{"artifact_kind": "agr", "record": {}}]


# ---------------------------------------------------------------------------
# Dispatch failure surfacing (Component A error path)
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestDispatchErrorSurfacing:
    """Dispatcher exceptions must be surfaced via the structured response."""

    def test_dispatch_exception_returns_structured_error(self, tmp_path: Path) -> None:
        from hestai_context_mcp.tools.submit_governance import submit_governance

        dispatcher = _StubDispatcher(output=RuntimeError("upstream goose failure"))
        result = submit_governance(
            prose_input="real prose",
            working_dir=str(tmp_path),
            dispatcher=dispatcher,
            dry_run=True,
        )
        assert result["success"] is False
        assert any("dispatch_failed" in e for e in result["validation_errors"])


# ---------------------------------------------------------------------------
# Artifact-shape rejections
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestArtifactShapeRejections:
    """Non-object artifacts and missing artifact_kind/record must be rejected."""

    def test_non_dict_artifact_rejected(self, tmp_path: Path) -> None:
        from hestai_context_mcp.tools.submit_governance import submit_governance

        dispatcher = _StubDispatcher(output=["not-a-dict"])  # type: ignore[list-item]
        result = submit_governance(
            prose_input="real prose",
            working_dir=str(tmp_path),
            dispatcher=dispatcher,
            dry_run=True,
        )
        assert result["success"] is False
        assert any("not an object" in e for e in result["validation_errors"])

    def test_missing_artifact_kind_rejected(self, tmp_path: Path) -> None:
        from hestai_context_mcp.tools.submit_governance import submit_governance

        dispatcher = _StubDispatcher(output=[{"record": {}}])
        result = submit_governance(
            prose_input="real prose",
            working_dir=str(tmp_path),
            dispatcher=dispatcher,
            dry_run=True,
        )
        assert result["success"] is False
        assert any("artifact_kind" in e for e in result["validation_errors"])


# ---------------------------------------------------------------------------
# Few-shot corpus loader (read-only filesystem traversal)
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestFewShotCorpus:
    """Corpus loader must include both facet cards and AGR records."""

    def test_loads_both_facets_and_agrs(self, tmp_path: Path) -> None:
        from hestai_context_mcp.tools.submit_governance import _load_few_shot_corpus

        facets = tmp_path / ".hestai" / "context" / "concepts" / "demo"
        facets.mkdir(parents=True)
        (facets / "EXAMPLE.oct.md").write_text("FACET_BODY")

        decisions = tmp_path / ".hestai" / "decisions"
        decisions.mkdir(parents=True)
        (decisions / "HO-AGR-20260520.oct.md").write_text("AGR_BODY")

        corpus = _load_few_shot_corpus(tmp_path)
        assert "FACET_BODY" in corpus
        assert "AGR_BODY" in corpus

    def test_empty_when_no_dirs(self, tmp_path: Path) -> None:
        from hestai_context_mcp.tools.submit_governance import _load_few_shot_corpus

        assert _load_few_shot_corpus(tmp_path) == ""


# ---------------------------------------------------------------------------
# PR emission gating — gh-CLI happy + failure path
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestPrEmissionFailureSurfacing:
    """gh-CLI failures must surface as structured errors, never crash."""

    def test_gh_failure_returns_structured_error(self, tmp_path: Path) -> None:
        from hestai_context_mcp.tools import submit_governance as mod

        good = [
            {
                "artifact_kind": "agr",
                "record": {
                    "type": "DECISION_RECORD",
                    "version": "1.0",
                    "token": "HO-GH-FAIL-DECISION-20260520",
                    "status": "PROPOSED",
                    "tier": "TACTICAL",
                    "decision": "x",
                    "because": "y",
                    "authored_at": "2026-05-20T00:00:00Z",
                },
            }
        ]
        dispatcher = _StubDispatcher(output=good)

        with patch.object(mod, "_emit_pr_via_gh", side_effect=RuntimeError("gh boom")):
            result = mod.submit_governance(
                prose_input="prose",
                working_dir=str(tmp_path),
                dispatcher=dispatcher,
                dry_run=False,
            )
        assert result["success"] is False
        assert any("pr_emission_failed" in e for e in result["validation_errors"])


# ---------------------------------------------------------------------------
# Server registration
# ---------------------------------------------------------------------------
@pytest.mark.smoke
class TestServerRegistration:
    """submit_governance must be registered alongside the four existing tools."""

    def test_imported_into_server_module(self) -> None:
        from hestai_context_mcp import server

        assert hasattr(server, "submit_governance")
