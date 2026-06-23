"""Unit tests for scripts/ratify_decision.py — governance auto-ratify logic.

The script flips DECISION_RECORD AGRs carrying ``STATUS::PROPOSED`` to
``STATUS::RATIFIED`` and injects ``RATIFIED_BY`` + ``RATIFIED_AT`` after the
``AUTHORED_AT`` line (this repo's META schema). It is the mechanical reflection
of a human PR-approval event. Stdlib-only, like scripts/validate_review.py.

Binding properties:
- PROPOSED -> RATIFIED with the two metadata fields injected in schema order.
- Idempotent: a second run is a no-op (no duplicate fields, no churn).
- Non-PROPOSED records are never touched.
- Output remains a schema-valid AGR (asserted via the real Gate A validator).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "scripts"))
import ratify_decision  # noqa: E402

_PROPOSED = (
    "===DECISION_RECORD===\n"
    "META:\n"
    "  TYPE::DECISION_RECORD\n"
    '  VERSION::"1.0"\n'
    "  TOKEN::HO-TEST-EXAMPLE-20260622\n"
    "  STATUS::PROPOSED\n"
    "  TIER::STRATEGIC\n"
    '  AUTHORED_AT::"2026-06-22T00:00:00Z"\n'
    '  SCOPE::"hestai-context-mcp"\n'
    '  DECISION::"Test decision."\n'
    '  BECAUSE::"Test rationale."\n'
    "===END===\n"
)


class TestRatifyText:
    def test_proposed_is_flipped_and_fields_injected(self):
        out, changed = ratify_decision.ratify_text(
            _PROPOSED, reviewer="alice", timestamp="2026-06-22T12:00:00Z"
        )
        assert changed is True
        assert "  STATUS::RATIFIED\n" in out
        assert "  STATUS::PROPOSED" not in out
        assert '  RATIFIED_BY::"human:operator<alice>"\n' in out
        assert '  RATIFIED_AT::"2026-06-22T12:00:00Z"\n' in out

    def test_injection_order_authored_then_by_then_at(self):
        out, _ = ratify_decision.ratify_text(
            _PROPOSED, reviewer="alice", timestamp="2026-06-22T12:00:00Z"
        )
        i_auth = out.index("AUTHORED_AT::")
        i_by = out.index("RATIFIED_BY::")
        i_at = out.index("RATIFIED_AT::")
        assert i_auth < i_by < i_at

    def test_idempotent_second_run_is_noop(self):
        once, _ = ratify_decision.ratify_text(
            _PROPOSED, reviewer="alice", timestamp="2026-06-22T12:00:00Z"
        )
        twice, changed = ratify_decision.ratify_text(
            once, reviewer="bob", timestamp="2026-06-23T00:00:00Z"
        )
        assert changed is False
        assert twice == once
        # No duplicate metadata fields.
        assert once.count("RATIFIED_BY::") == 1
        assert once.count("RATIFIED_AT::") == 1

    def test_already_ratified_untouched(self):
        ratified = _PROPOSED.replace("STATUS::PROPOSED", "STATUS::RATIFIED")
        out, changed = ratify_decision.ratify_text(
            ratified, reviewer="alice", timestamp="2026-06-22T12:00:00Z"
        )
        assert changed is False
        assert out == ratified

    def test_other_status_untouched(self):
        voided = _PROPOSED.replace("STATUS::PROPOSED", "STATUS::VOID")
        out, changed = ratify_decision.ratify_text(
            voided, reviewer="alice", timestamp="2026-06-22T12:00:00Z"
        )
        assert changed is False
        assert out == voided

    def test_status_substring_not_corrupted(self):
        # A PROPOSED token inside prose must NOT be rewritten — only the
        # whole-line META field.
        text = _PROPOSED.replace(
            '  DECISION::"Test decision."',
            '  DECISION::"We rejected the PROPOSED alternative."',
        )
        out, _ = ratify_decision.ratify_text(
            text, reviewer="alice", timestamp="2026-06-22T12:00:00Z"
        )
        assert "PROPOSED alternative" in out  # prose preserved
        assert "  STATUS::RATIFIED\n" in out

    def test_output_passes_gate_a(self):
        from hestai_context_mcp.tools.governance.type_checker import validate_octave_content

        out, _ = ratify_decision.ratify_text(
            _PROPOSED, reviewer="alice", timestamp="2026-06-22T12:00:00Z"
        )
        result = validate_octave_content(Path("/tmp"), out)
        assert result.valid, result.errors

    def test_fallback_injects_after_status_when_authored_at_absent(self):
        # Defensive branch: AUTHORED_AT is a required field, but if a malformed
        # record lacks it the injection anchors to the flipped STATUS line
        # instead of silently dropping the metadata.
        no_authored = _PROPOSED.replace('  AUTHORED_AT::"2026-06-22T00:00:00Z"\n', "")
        out, changed = ratify_decision.ratify_text(
            no_authored, reviewer="alice", timestamp="2026-06-22T12:00:00Z"
        )
        assert changed is True
        assert "  STATUS::RATIFIED\n" in out
        assert '  RATIFIED_BY::"human:operator<alice>"\n' in out
        assert '  RATIFIED_AT::"2026-06-22T12:00:00Z"\n' in out
        # The fields land immediately after the STATUS line (the fallback anchor).
        i_status = out.index("  STATUS::RATIFIED")
        i_by = out.index("RATIFIED_BY::")
        assert i_status < i_by


class TestRatifyDirectory:
    def test_ratifies_proposed_files_and_reports(self, tmp_path):
        d = tmp_path / ".hestai" / "decisions"
        d.mkdir(parents=True)
        (d / "a.oct.md").write_text(_PROPOSED, encoding="utf-8")
        (d / "b.oct.md").write_text(
            _PROPOSED.replace("STATUS::PROPOSED", "STATUS::RATIFIED"), encoding="utf-8"
        )

        changed = ratify_decision.ratify_directory(
            d, reviewer="alice", timestamp="2026-06-22T12:00:00Z"
        )

        assert changed == [d / "a.oct.md"]
        assert "STATUS::RATIFIED" in (d / "a.oct.md").read_text()
        # b was already ratified -> not rewritten.
        assert (d / "b.oct.md").read_text().count("RATIFIED_BY::") == 0

    def test_ratifies_multiple_proposed_files_sorted(self, tmp_path):
        d = tmp_path / ".hestai" / "decisions"
        d.mkdir(parents=True)
        # Two PROPOSED records (distinct tokens) + one already RATIFIED.
        (d / "two.oct.md").write_text(
            _PROPOSED.replace("HO-TEST-EXAMPLE-20260622", "HO-TEST-TWO-20260622"),
            encoding="utf-8",
        )
        (d / "one.oct.md").write_text(
            _PROPOSED.replace("HO-TEST-EXAMPLE-20260622", "HO-TEST-ONE-20260622"),
            encoding="utf-8",
        )
        (d / "done.oct.md").write_text(
            _PROPOSED.replace("STATUS::PROPOSED", "STATUS::RATIFIED"), encoding="utf-8"
        )

        changed = ratify_decision.ratify_directory(
            d, reviewer="alice", timestamp="2026-06-22T12:00:00Z"
        )

        # Both PROPOSED files ratified, returned in sorted order; the
        # already-RATIFIED file is untouched.
        assert changed == [d / "one.oct.md", d / "two.oct.md"]
        for name in ("one.oct.md", "two.oct.md"):
            body = (d / name).read_text()
            assert "  STATUS::RATIFIED\n" in body
            assert body.count("RATIFIED_BY::") == 1
