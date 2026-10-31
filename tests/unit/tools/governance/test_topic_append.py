"""RED suite: append_ruling renderer and input contract for YAML topic records (#203 S2).

The renderer is pure (no git, no LLM, no compiler). It takes the bytes of a quoted-YAML
topic record as read at the origin/main OID plus the caller's rulings and returns the
new record. It writes nothing of its own: the record is parsed with main's reader and
re-emitted ONLY through ``emit_yaml_record`` (ADR-RFC-ARCH-004 §1.1, §1.7), so an
appended record has exactly the bytes and hash the PR-5 write path would give it.

Contract:

* new ids are ``R<n>``, n = the highest id in the record + 1, in call order;
* ``replaces`` removes the replaced entries; git keeps the old text;
* ``current`` is regenerated from the live ``rule`` lines, in id order;
* a dated plain-words entry is prepended to ``revision``; ``version`` never changes;
* every other field is untouched and the markdown body is kept byte for byte;
* C1: every VERBATIM reads back byte-exact.
"""

from __future__ import annotations

import hashlib
from datetime import date

import pytest

from hestai_context_mcp.core.agent_readable_governance_parser import (
    canonicalize_yaml_record,
    collect_topic_blocks,
    emit_yaml_record,
    parse_decision_record,
)
from hestai_context_mcp.tools.governance.topic_append import (
    NOT_A_TOPIC_RECORD,
    NOT_YAML_TOPIC_RECORD,
    RECORD_UNREADABLE,
    RENDER_REJECTED,
    REPLACES_UNKNOWN_ID,
    TOPIC_BLOCKS_MALFORMED,
    AppendRequest,
    RulingInput,
    parse_append_request,
    record_hash,
    render_append,
)

_TODAY = date(2026, 10, 31)
_TOKEN = "TOPIC-CLIENT-ACCESS-20261015"

_BODY = (
    "\n# Client access topic\n\n"
    'Body prose keeps "quotes", a backslash \\ and a current: line verbatim.\r\n'
    "rulings:\n"
    '  R99: "not a block: the body is never read as record content"\n'
)

# Canonical front matter (fixed key order, canonical indentation) plus a body.
_FRONT = (
    "---\n"
    'type: "DECISION_RECORD"\n'
    'version: "1.5"\n'
    f'token: "{_TOKEN}"\n'
    'status: "RATIFIED"\n'
    'tier: "TACTICAL"\n'
    'authored_at: "2026-10-15T00:00:00Z"\n'
    'decision: "Access follows the rules listed under current for this topic."\n'
    'because: "One long-running record per topic keeps the rules in force in one place."\n'
    'revision: "2026-10-16: R2 added; R2 replaces R1"\n'
    'topic: "client-access"\n'
    'ratified_by: "human:operator"\n'
    "current:\n"
    '  R2: "Contractors get read-only access."\n'
    '  R3: "Staff get full access."\n'
    "rulings:\n"
    "  R2:\n"
    '    rule: "Contractors get read-only access."\n'
    '    verbatim: "contractors read only"\n'
    '    ruled: "operator, 2026-10-16"\n'
    '    replaces: "R1"\n'
    "  R3:\n"
    '    rule: "Staff get full access."\n'
    '    verbatim: "staff full access"\n'
    '    ruled: "operator, 2026-10-16"\n'
    "---\n"
)
_BASE = _FRONT + _BODY


def _ruling(rule: str = "Auditors get read-only access.", **kw: object) -> RulingInput:
    return RulingInput(
        rule=rule,
        verbatim=str(kw.get("verbatim", "auditors can look but not touch")),
        ruled=str(kw.get("ruled", "operator, 2026-10-31, HC control room")),
        replaces=tuple(kw.get("replaces", ())),  # type: ignore[arg-type]
    )


def _render(base: str | bytes = _BASE, *rulings: RulingInput):
    outcome = render_append(
        base.encode("utf-8") if isinstance(base, str) else base,
        list(rulings) or [_ruling()],
        _TODAY,
    )
    assert outcome.ok, (outcome.error_code, outcome.errors)
    assert outcome.text is not None
    return outcome


def _fields(text: str) -> dict[str, str]:
    parsed = parse_decision_record(text)
    flat = {k: v for k, v in parsed.items() if k != "fields" and isinstance(v, str)}
    flat.update({k.lower(): v for k, v in parsed["fields"].items()})
    return flat


def test_base_fixture_is_canonical() -> None:
    """Guard: the fixture is already canonical, so byte comparisons below are exact."""
    assert canonicalize_yaml_record(_BASE.encode("utf-8")) == _BASE


class TestRecordHash:
    def test_sha256_prefix_and_hex_of_the_bytes(self) -> None:
        assert record_hash(b"abc") == "sha256:" + hashlib.sha256(b"abc").hexdigest()


class TestSingleAppend:
    def test_new_id_is_max_plus_one(self) -> None:
        assert _render().appended_ids == ["R4"]

    def test_entry_is_appended_to_rulings(self) -> None:
        text = _render().text
        blocks = collect_topic_blocks(text)
        assert [e["id"] for e in blocks["rulings"]] == ["R2", "R3", "R4"]
        assert blocks["rulings"][-1] == {
            "id": "R4",
            "rule": "Auditors get read-only access.",
            "verbatim": "auditors can look but not touch",
            "ruled": "operator, 2026-10-31, HC control room",
            "replaces": None,
        }

    def test_current_is_regenerated_in_id_order(self) -> None:
        blocks = collect_topic_blocks(_render().text)
        assert blocks["current"] == [
            {"id": "R2", "rule": "Contractors get read-only access."},
            {"id": "R3", "rule": "Staff get full access."},
            {"id": "R4", "rule": "Auditors get read-only access."},
        ]

    def test_current_is_rebuilt_from_rule_lines_not_appended_to(self) -> None:
        # The base's CURRENT is out of order and carries stale text for R2: a renderer
        # that appended to the old CURRENT would keep both defects.
        drifted = _BASE.replace(
            '  R2: "Contractors get read-only access."\n  R3: "Staff get full access."\n',
            '  R3: "Staff get full access."\n  R2: "Stale wording of R2."\n',
        )
        blocks = collect_topic_blocks(_render(drifted).text)
        assert blocks["current"] == [
            {"id": "R2", "rule": "Contractors get read-only access."},
            {"id": "R3", "rule": "Staff get full access."},
            {"id": "R4", "rule": "Auditors get read-only access."},
        ]

    def test_revision_entry_is_prepended_on_its_own_line(self) -> None:
        outcome = _render()
        assert outcome.revision_entry == "2026-10-31: R4 added"
        assert _fields(outcome.text)["revision"] == (
            "2026-10-31: R4 added\n2026-10-16: R2 added; R2 replaces R1"
        )

    def test_version_is_never_bumped(self) -> None:
        assert _fields(_render().text)["version"] == "1.5"

    def test_fields_untouched_apart_from_revision_and_blocks(self) -> None:
        before = _fields(_BASE)
        after = _fields(_render().text)
        assert set(after) == set(before)
        for key in before:
            if key != "revision":
                assert after[key] == before[key], key

    def test_body_is_preserved_byte_exact(self) -> None:
        text = _render().text
        assert text.endswith("---\n" + _BODY)
        assert text.split("---\n", 2)[2] == _BODY

    def test_pairs_carry_only_the_new_rule_and_verbatim(self) -> None:
        assert _render().pairs == [
            {
                "id": "R4",
                "rule": "Auditors get read-only access.",
                "verbatim": "auditors can look but not touch",
            }
        ]

    def test_rendering_is_deterministic(self) -> None:
        assert _render().text == _render().text


class TestReplaces:
    def test_replaced_entry_is_removed_and_current_drops_it(self) -> None:
        outcome = _render(_BASE, _ruling("Staff get read-only access.", replaces=["R3"]))
        blocks = collect_topic_blocks(outcome.text)
        assert [e["id"] for e in blocks["rulings"]] == ["R2", "R4"]
        assert blocks["rulings"][-1]["replaces"] == "R3"
        assert [c["id"] for c in blocks["current"]] == ["R2", "R4"]
        assert outcome.replaced_ids == ["R3"]
        assert "staff full access" not in outcome.text

    def test_revision_names_the_replacement_in_plain_words(self) -> None:
        outcome = _render(_BASE, _ruling(replaces=["R2"]))
        assert outcome.revision_entry == "2026-10-31: R4 added; R4 replaces R2"

    def test_one_ruling_replacing_two_ids(self) -> None:
        outcome = _render(_BASE, _ruling(replaces=["R2", "R3"]))
        blocks = collect_topic_blocks(outcome.text)
        assert [e["id"] for e in blocks["rulings"]] == ["R4"]
        assert blocks["rulings"][0]["replaces"] == "R2, R3"
        assert outcome.revision_entry == "2026-10-31: R4 added; R4 replaces R2, R3"

    def test_unknown_replaces_id_is_refused(self) -> None:
        outcome = render_append(_BASE.encode(), [_ruling(replaces=["R7"])], _TODAY)
        assert not outcome.ok
        assert outcome.error_code == REPLACES_UNKNOWN_ID
        assert any("R7" in e for e in outcome.errors)

    def test_replacing_an_id_that_was_already_replaced_is_refused(self) -> None:
        outcome = render_append(_BASE.encode(), [_ruling(replaces=["R1"])], _TODAY)
        assert not outcome.ok and outcome.error_code == REPLACES_UNKNOWN_ID


class TestSeveralRulingsOneCall:
    def test_ids_follow_call_order_and_revision_lists_all(self) -> None:
        outcome = _render(
            _BASE,
            _ruling("First new rule."),
            _ruling("Second new rule.", replaces=["R2"]),
        )
        assert outcome.appended_ids == ["R4", "R5"]
        assert outcome.replaced_ids == ["R2"]
        assert outcome.revision_entry == "2026-10-31: R4, R5 added; R5 replaces R2"
        blocks = collect_topic_blocks(outcome.text)
        assert [c["id"] for c in blocks["current"]] == ["R3", "R4", "R5"]
        assert [p["id"] for p in outcome.pairs] == ["R4", "R5"]


class TestIdAllocation:
    def test_max_id_counts_replaces_references(self) -> None:
        base = _BASE.replace('replaces: "R1"', 'replaces: "R8"')
        assert _render(base).appended_ids == ["R9"]

    def test_ids_compare_numerically(self) -> None:
        base = _BASE.replace("R3", "R10")
        assert _render(base).appended_ids == ["R11"]

    def test_first_ruling_of_a_topic_without_blocks_is_r1(self) -> None:
        start = _FRONT.index("current:\n")
        end = _FRONT.index("---\n", 4)
        base = _FRONT[:start] + _FRONT[end:] + _BODY
        outcome = _render(base)
        assert outcome.appended_ids == ["R1"]
        assert collect_topic_blocks(outcome.text)["current"] == [
            {"id": "R1", "rule": "Auditors get read-only access."}
        ]


class TestCanonicalisation:
    def test_a_non_canonical_base_is_rewritten_canonically(self) -> None:
        # Keys out of order: still a valid record; the append re-emits it canonically.
        swapped = _BASE.replace('topic: "client-access"\n', "").replace(
            'type: "DECISION_RECORD"\n', 'type: "DECISION_RECORD"\ntopic: "client-access"\n'
        )
        assert canonicalize_yaml_record(swapped) != swapped
        text = _render(swapped).text
        assert canonicalize_yaml_record(text) == text

    def test_crlf_base_keeps_its_body_bytes(self) -> None:
        crlf = _FRONT.replace("\n", "\r\n") + _BODY
        text = _render(crlf.encode("utf-8")).text
        assert text.endswith(_BODY)


class TestContractInvariants:
    def test_idempotent_emit_of_parse(self) -> None:
        text = _render(_BASE, _ruling(replaces=["R2"]), _ruling("Another rule.")).text
        assert canonicalize_yaml_record(text.encode("utf-8")) == text
        parsed = parse_decision_record(text)
        fields = {k: v for k, v in parsed.items() if k != "fields" and isinstance(v, str)}
        fields.update(parsed["fields"])
        front = emit_yaml_record(fields, collect_topic_blocks(text))
        assert front + _BODY == text

    def test_hash_of_rendered_bytes(self) -> None:
        outcome = _render()
        assert outcome.text is not None
        assert record_hash(outcome.text.encode("utf-8")) == (
            "sha256:" + hashlib.sha256(outcome.text.encode("utf-8")).hexdigest()
        )


# C1: VERBATIM byte-exact through append. Every ruled escape, control characters
# (written as \uXXXX), unicode, quotes and the operator's typos read back unchanged.
_C1_VERBATIMS = [
    "a backslash \\ and two \\\\ in a row",
    'double "quotes" inside',
    "line one\nline two",
    "carriage\rreturn and CRLF\r\n",
    "tab\tseparated",
    "nul \x00 bel \x07 esc \x1b del \x7f us \x1f",
    "unicode: caf\u00e9 \u6f22\u5b57 \U0001f389 nbsp\u00a0 ls\u2028 ps\u2029",
    "  leading and trailing spaces  ",
    "I'd like to be able to ppend to decisions easily and update somethig. TYou're right",
    'already-escaped looking text: \\" \\n \\u0041 stays literal',
    "---\nnot a fence inside a value",
]


class TestVerbatimByteExact:
    @pytest.mark.parametrize("verbatim", _C1_VERBATIMS)
    def test_verbatim_round_trips_byte_exact(self, verbatim: str) -> None:
        text = _render(_BASE, _ruling(verbatim=verbatim)).text
        entry = collect_topic_blocks(text)["rulings"][-1]
        assert entry["verbatim"] == verbatim
        assert canonicalize_yaml_record(text.encode("utf-8")) == text

    def test_rule_and_ruled_with_quotes_and_backslashes_round_trip(self) -> None:
        rule = 'Rule with "quotes" and a \\ backslash.'
        ruled = 'operator "first-party", C:\\path'
        text = _render(_BASE, _ruling(rule, ruled=ruled)).text
        blocks = collect_topic_blocks(text)
        assert blocks["rulings"][-1]["rule"] == rule
        assert blocks["rulings"][-1]["ruled"] == ruled
        assert blocks["current"][-1]["rule"] == rule

    def test_all_verbatims_in_one_call_round_trip(self) -> None:
        rulings = [_ruling(f"Rule {i}.", verbatim=v) for i, v in enumerate(_C1_VERBATIMS)]
        text = _render(_BASE, *rulings).text
        got = [e["verbatim"] for e in collect_topic_blocks(text)["rulings"][2:]]
        assert got == _C1_VERBATIMS

    def test_lone_surrogate_is_a_structured_refusal_not_an_exception(self) -> None:
        outcome = render_append(_BASE.encode(), [_ruling(verbatim="bad \ud800 text")], _TODAY)
        assert not outcome.ok
        assert outcome.error_code == RENDER_REJECTED


_OCTAVE_TOPIC = """===DECISION_RECORD===
META:
  TYPE::DECISION_RECORD
  VERSION::"1.3"
  TOKEN::TOPIC-CLIENT-ACCESS-20261015
  STATUS::RATIFIED
  TIER::TACTICAL
  AUTHORED_AT::"2026-10-15T00:00:00Z"
  DECISION::"Access follows the rules in force."
  BECAUSE::"One record per topic."
  TOPIC::client-access
CURRENT:
  R1::"Contractors get read-only access."
RULINGS:
  R1:
    RULE::"Contractors get read-only access."
    VERBATIM::"contractors read only"
    RULED::"operator"
===END===
"""


class TestRefusals:
    def test_octave_topic_record_is_refused(self) -> None:
        outcome = render_append(_OCTAVE_TOPIC.encode(), [_ruling()], _TODAY)
        assert not outcome.ok
        assert outcome.error_code == NOT_YAML_TOPIC_RECORD
        assert any("append_ruling writes YAML topic records only" in e for e in outcome.errors)

    def test_yaml_record_without_topic_is_refused(self) -> None:
        base = _FRONT.replace('topic: "client-access"\n', "")
        start, end = base.index("current:\n"), base.rindex("---\n")
        outcome = render_append((base[:start] + base[end:]).encode(), [_ruling()], _TODAY)
        assert not outcome.ok
        assert outcome.error_code == NOT_A_TOPIC_RECORD

    def test_unparseable_yaml_record_is_refused(self) -> None:
        bad = _BASE.replace('tier: "TACTICAL"', "tier: TACTICAL")
        outcome = render_append(bad.encode(), [_ruling()], _TODAY)
        assert not outcome.ok
        assert outcome.error_code == RECORD_UNREADABLE
        assert any("unquoted_value" in e for e in outcome.errors)

    def test_ruling_entry_without_rule_is_refused(self) -> None:
        bad = _BASE.replace('    rule: "Staff get full access."\n', "")
        outcome = render_append(bad.encode(), [_ruling()], _TODAY)
        assert not outcome.ok
        assert outcome.error_code == TOPIC_BLOCKS_MALFORMED

    def test_current_id_without_a_rulings_entry_is_refused(self) -> None:
        # Regenerating CURRENT would silently drop R5: refuse instead.
        bad = _BASE.replace(
            '  R3: "Staff get full access."\n',
            '  R3: "Staff get full access."\n  R5: "An orphan rule."\n',
        )
        outcome = render_append(bad.encode(), [_ruling()], _TODAY)
        assert not outcome.ok
        assert outcome.error_code == TOPIC_BLOCKS_MALFORMED
        assert any("R5" in e for e in outcome.errors)


def _valid_raw() -> dict:
    return {
        "topic_token": _TOKEN,
        "rulings": [
            {
                "rule": "Contractors get read-only access.",
                "verbatim": "contractors, read only, always",
                "ruled": "operator, 2026-10-31",
                "replaces": None,
            }
        ],
        "expected_record_hash": None,
    }


class TestParseAppendRequest:
    def test_valid_request(self) -> None:
        req, errors = parse_append_request(_valid_raw())
        assert errors == []
        assert req == AppendRequest(
            topic_token=_TOKEN,
            rulings=(
                RulingInput(
                    rule="Contractors get read-only access.",
                    verbatim="contractors, read only, always",
                    ruled="operator, 2026-10-31",
                    replaces=(),
                ),
            ),
            expected_record_hash=None,
        )

    def test_verbatim_is_kept_exactly_not_stripped(self) -> None:
        raw = _valid_raw()
        raw["rulings"][0]["verbatim"] = "  spaced \n"
        req, errors = parse_append_request(raw)
        assert errors == [] and req is not None
        assert req.rulings[0].verbatim == "  spaced \n"

    @pytest.mark.parametrize(
        ("mutate", "needle"),
        [
            (lambda r: r.update(extra=1), "extra"),
            (lambda r: r.pop("topic_token"), "topic_token"),
            (lambda r: r.update(topic_token="not-a-token"), "topic_token"),
            (lambda r: r.update(rulings=[]), "rulings"),
            (lambda r: r.update(rulings="x"), "rulings"),
            (lambda r: r["rulings"].append("x"), "rulings[1]"),
            (lambda r: r["rulings"][0].update(colour="red"), "colour"),
            (lambda r: r["rulings"][0].update(rule=""), "rule"),
            (lambda r: r["rulings"][0].update(rule="one\ntwo"), "newline"),
            (lambda r: r["rulings"][0].update(rule="a\u2028b"), "newline"),
            (lambda r: r["rulings"][0].update(rule=" ".join(["w"] * 41)), "41 words"),
            (lambda r: r["rulings"][0].update(verbatim="   "), "verbatim"),
            (lambda r: r["rulings"][0].update(verbatim=3), "verbatim"),
            (lambda r: r["rulings"][0].update(ruled=""), "ruled"),
            (lambda r: r["rulings"][0].update(ruled="a\nb"), "ruled"),
            (lambda r: r["rulings"][0].update(replaces="R1"), "replaces"),
            (lambda r: r["rulings"][0].update(replaces=["X1"]), "X1"),
            (lambda r: r["rulings"][0].update(replaces=["R1", "R1"]), "R1"),
            (lambda r: r.update(expected_record_hash="abc"), "expected_record_hash"),
            (lambda r: r.update(expected_record_hash="sha256:" + "A" * 64), "expected_record_hash"),
        ],
    )
    def test_invalid_requests_are_refused(self, mutate, needle: str) -> None:
        raw = _valid_raw()
        mutate(raw)
        req, errors = parse_append_request(raw)
        assert req is None
        assert any(needle in e for e in errors), errors

    @pytest.mark.parametrize("glyph", ["\u2192", "\u21cc", "\u2234", "\u2295", "\u2227", "\u2228"])
    def test_rule_must_be_plain_words(self, glyph: str) -> None:
        raw = _valid_raw()
        raw["rulings"][0]["rule"] = f"Contractors {glyph} read-only access."
        req, errors = parse_append_request(raw)
        assert req is None
        assert any("plain words" in e and glyph in e for e in errors), errors

    def test_glyphs_in_verbatim_are_the_operators_words_and_allowed(self) -> None:
        raw = _valid_raw()
        raw["rulings"][0]["verbatim"] = "A \u2192 B \u2227 C"
        req, errors = parse_append_request(raw)
        assert errors == [] and req is not None

    def test_same_id_replaced_by_two_rulings_is_refused(self) -> None:
        raw = _valid_raw()
        second = dict(raw["rulings"][0], replaces=["R2"])
        raw["rulings"][0]["replaces"] = ["R2"]
        raw["rulings"].append(second)
        req, errors = parse_append_request(raw)
        assert req is None
        assert any("R2" in e for e in errors)

    def test_forty_words_is_allowed(self) -> None:
        raw = _valid_raw()
        raw["rulings"][0]["rule"] = " ".join(["w"] * 40)
        req, errors = parse_append_request(raw)
        assert errors == [] and req is not None

    def test_non_dict_is_refused(self) -> None:
        req, errors = parse_append_request(["not", "a", "dict"])
        assert req is None and errors

    def test_valid_hash_is_kept(self) -> None:
        raw = _valid_raw()
        raw["expected_record_hash"] = "sha256:" + "a" * 64
        req, _ = parse_append_request(raw)
        assert req is not None and req.expected_record_hash == "sha256:" + "a" * 64
