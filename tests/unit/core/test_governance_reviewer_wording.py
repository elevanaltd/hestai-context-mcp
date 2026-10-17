"""RED tests: fourth Stage-5 reviewer outcome WORDING (wording-only findings)."""

from __future__ import annotations

from hestai_context_mcp.core import governance_reviewer as gr


def _parse(raw: str):
    return gr._parse_review(raw, "m", 1, 0.0, cost_is_estimate=True)


def test_wording_verdict_with_fixes_parsed():
    r = _parse(
        "VERDICT::WORDING\nASSESSMENT::Sound.\n"
        "WORDING_FIXES::[Soften 'always'; Move citation to CONSTRAINTS]\nCONCERNS::[]"
    )
    assert r["verdict"] == "WORDING"
    assert r["wording_fixes"] == ["Soften 'always'", "Move citation to CONSTRAINTS"]
    assert r["concerns"] == []
    assert r["reviewer_available"] is True


def test_wording_without_fixes_degrades_to_concerns():
    r = _parse("VERDICT::WORDING\nASSESSMENT::x\nWORDING_FIXES::[]\nCONCERNS::[]")
    assert r["verdict"] == "CONCERNS"


def test_wording_with_concerns_degrades_to_concerns():
    r = _parse("VERDICT::WORDING\nASSESSMENT::x\nWORDING_FIXES::[fix a]\nCONCERNS::[contradiction]")
    assert r["verdict"] == "CONCERNS"
    assert "contradiction" in r["concerns"]


def test_wording_missing_fixes_line_degrades_to_concerns():
    assert _parse("VERDICT::WORDING\nASSESSMENT::x")["verdict"] == "CONCERNS"


def test_wording_missing_concerns_line_degrades_to_concerns():
    r = _parse("VERDICT::WORDING\nASSESSMENT::x\nWORDING_FIXES::[fix a]")
    assert r["verdict"] == "CONCERNS"
    assert "wording_fixes" not in r


def test_wording_missing_concerns_and_assessment_degrades_to_concerns():
    r = _parse("VERDICT::WORDING\nWORDING_FIXES::[fix a]")
    assert r["verdict"] == "CONCERNS"
    assert r["reviewer_available"] is True


def test_wording_non_empty_concerns_never_wording():
    r = _parse("VERDICT::WORDING\nASSESSMENT::x\nWORDING_FIXES::[fix a]\nCONCERNS::[scope drift]")
    assert r["verdict"] == "CONCERNS"
    assert r["concerns"] == ["scope drift"]
    assert "wording_fixes" not in r


def test_approved_without_concerns_line_unchanged():
    assert _parse("VERDICT::APPROVED\nASSESSMENT::x")["verdict"] == "APPROVED"


def test_unparseable_still_concerns_never_approved():
    assert _parse("garbage")["verdict"] == "CONCERNS"
    assert _parse("VERDICT::WORDINGS\nASSESSMENT::x")["verdict"] == "CONCERNS"


def test_existing_verdicts_unchanged():
    for v in ("APPROVED", "CONCERNS", "BLOCKED"):
        assert _parse(f"VERDICT::{v}\nASSESSMENT::x\nCONCERNS::[]")["verdict"] == v


def test_prompt_defines_wording_outcome_and_keeps_substantive_scope():
    p = gr._REVIEW_SYSTEM_PROMPT
    assert "WORDING" in p and "WORDING_FIXES::" in p
    flat = " ".join(p.lower().split())
    # The substantive axes must be mapped to CONCERNS/BLOCKED, never WORDING.
    assert (
        "anything touching precedence, contradiction, scope or concept-validity "
        "is never wording: it stays concerns or blocked"
    ) in flat
    # WORDING is restricted to purely-wording findings with CONCERNS left empty.
    assert "use wording only when every finding is purely wording" in flat
    assert "leave concerns empty" in flat
    assert "never schema" in p.lower() or "NEVER comment on schema" in p
