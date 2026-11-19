"""Re-pin to review-gate-v5 and the status-block approval guidance.

Under the v3 validator a footerless plain-text approval clears nothing; peer
roles clear only through ``mcp__hestai-context__submit_review`` (verdict header
plus a footer bound to the head SHA). The "Review requirements not met" status
comment must say so, and it must not contain a word that the workflow's own
``if:`` trigger matches. GitHub's ``contains()`` is case-insensitive, so the
check below is too. Bot comments are filtered out of the trigger, but the
guidance a human reads is kept trigger-free so a copy-paste cannot re-fire the
gate.

Text-level only (stdlib): the workflow has no JS harness in this repository.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "review-gate.yml"
# review-gate-v2 tooling commit, superseded by review-gate-v3 (record #300).
V2_SHA = "7634feb87298b77c507cade2e6b0f40a6a04d911"
# review-gate-v3 tooling commit, superseded.
V3_SHA = "44a8a1527c3257c5338101e5dac8abf30e652c45"
# review-gate-v4 tooling commit: tagged, superseded by v5 before it was ever pinned.
V4_SHA = "b602d4f3bc30d8d685b2faf93b1fe28c903558cc"
# Peeled commit of annotated tag review-gate-v5 (git ls-remote --tags origin 'review-gate-v5*').
V5_SHA = "3ffcfbeee2abb8cf2707f325d4b7282f0ce913ef"
# The only account that posts the status comment (local and consuming-repo mode).
STATUS_LOGIN = "github-actions[bot]"
# The `if:` trigger substrings, lowercased (GitHub contains() ignores case).
TRIGGERS = ("approve", "reviewed", " go", "**go**")


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def _tooling_ref(text: str) -> str:
    """The ``ref:`` value of the "Checkout review-gate tooling" step."""
    step = text.index("- name: Checkout review-gate tooling")
    match = re.compile(r"^\s+ref:\s*(\S+)\s*$", re.MULTILINE).search(text, step)
    assert match is not None, "tooling step has no ref line"
    return match.group(1)


def _peer_guidance(text: str) -> str:
    """The script lines that build the non-TIER_1_SELF "Required" guidance."""
    start = text.index("if (roles.length > 0) {")
    end = text.index("message += '\\n<details>", start)
    return text[start:end]


def _self_guidance(text: str) -> str:
    start = text.index("if (tier === 'TIER_1_SELF') {")
    end = text.index("} else {\n                if (roles.length > 0)", start)
    return text[start:end]


def _string_literals(js: str) -> str:
    pairs = re.findall(r"'((?:[^'\\]|\\.)*)'|`((?:[^`\\]|\\.)*)`", js)
    return " ".join(a or b for a, b in pairs)


@pytest.mark.unit
def test_pin_comment_names_v5_and_cites_the_record() -> None:
    text = _text()
    assert "review-gate-v5" in text
    assert "never pinned" in text
    assert "review-gate-v3" not in text
    assert "review-gate-v2" not in text
    assert "HO-REVIEW-GATE-AND-HC-MERGE-AUTHORITY-20261119" in text


@pytest.mark.unit
def test_tooling_ref_is_no_longer_a_superseded_commit() -> None:
    assert V2_SHA not in _text()
    assert V3_SHA not in _text()
    assert V4_SHA not in _text()


@pytest.mark.unit
def test_peer_guidance_points_at_submit_review() -> None:
    guidance = _string_literals(_peer_guidance(_text()))
    assert "mcp__hestai-context__submit_review" in guidance
    assert "footer" in guidance
    assert "head SHA" in guidance
    assert "do not count" in guidance


@pytest.mark.unit
def test_peer_guidance_carries_no_gate_trigger_keyword() -> None:
    guidance = _string_literals(_peer_guidance(_text())).lower()
    hits = [t for t in TRIGGERS if t in guidance]
    assert hits == [], f"peer guidance contains gate-trigger text {hits}: {guidance!r}"


@pytest.mark.unit
def test_peer_guidance_no_longer_teaches_plain_text_lines() -> None:
    assert "[assessment]" not in _peer_guidance(_text())


@pytest.mark.unit
def test_self_guidance_says_comment_or_review_never_the_description() -> None:
    guidance = _string_literals(_self_guidance(_text()))
    assert "PR comment" in guidance
    assert "PR Review" in guidance
    assert "description" in guidance


@pytest.mark.unit
def test_tooling_ref_is_exactly_the_v5_commit() -> None:
    assert _tooling_ref(_text()) == V5_SHA


@pytest.mark.unit
def test_mutated_tooling_ref_is_caught() -> None:
    mutated = _text().replace(_tooling_ref(_text()), "1" * 40)
    assert _tooling_ref(mutated) != V5_SHA


@pytest.mark.unit
def test_peer_guidance_names_commit_sha_bound_to_the_head() -> None:
    text = _text()
    guidance = _string_literals(_peer_guidance(text))
    assert "commit_sha" in guidance
    assert "${headSha}" in guidance
    assert (
        "gateData.sha" in text.split("if (tier === 'TIER_1_SELF')")[0].rsplit("const headSha", 1)[1]
    )


def _marker_selectors(text: str) -> list[str]:
    """Each ``.find(...)`` predicate that selects a marker comment."""
    return re.findall(r"\.find\(c =>\s*(.*?c\.body\.includes\(marker\))\s*\)", text, re.DOTALL)


@pytest.mark.unit
def test_cache_and_status_update_selectors_require_the_actions_login() -> None:
    selectors = _marker_selectors(_text())
    # cached-gate-data step and status-comment update step
    assert len(selectors) == 2
    expected = f"c.user.login === '{STATUS_LOGIN}' && c.body.includes(marker)"
    for predicate in selectors:
        # Full predicate: an added `||` clause or any extra condition fails.
        assert predicate == expected


@pytest.mark.unit
def test_marker_selectors_no_longer_trust_any_bot_account() -> None:
    for predicate in _marker_selectors(_text()):
        assert "user.type" not in predicate


@pytest.mark.unit
@pytest.mark.parametrize(
    "widened",
    [
        "c.user.login === 'github-actions[bot]' || c.user.type === 'Bot'",
        "c.user.type === 'Bot' || c.user.login === 'github-actions[bot]'",
        "c.user.login === 'github-actions[bot]' && c.body.includes(marker) || true",
    ],
)
def test_widened_selector_predicate_is_caught(widened: str) -> None:
    text = _text()
    original = f"c.user.login === '{STATUS_LOGIN}' && c.body.includes(marker)"
    mutated = text.replace(original, widened, 1)
    assert mutated != text
    expected = original
    selectors = _marker_selectors(mutated)
    assert len(selectors) != 2 or any(p != expected for p in selectors)
