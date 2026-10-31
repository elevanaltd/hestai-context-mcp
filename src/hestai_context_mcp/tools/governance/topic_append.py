"""append_ruling for quoted-YAML topic records (issue #203 S2).

Pure functions only: no git, no filesystem, no LLM, no compiler. The caller
(``submit_governance``'s append_ruling mode) reads the record's bytes at the
``origin/main`` OID and hands them here; this module returns the new record text.

There is no codec, emitter or escaping here. The record is read with main's
parser and re-emitted ONLY through ``emit_yaml_record`` (ADR-RFC-ARCH-004 §1.1,
§1.7), so an appended record has exactly the bytes, and therefore the hash, that
the content-mode write path (EPIC4 PR-5) would give it. The operator's VERBATIM
words never pass through a model (#195): they go straight to the scalar encoder.

Rendering contract:

* new ids are ``R<n>``, n = the highest id in the record (``rulings`` entries,
  ``current`` lines, ``replaces`` references) + 1, in call order;
* ``replaces`` removes the replaced entries; git keeps the old text;
* ``current`` is rebuilt from the live ``rule`` lines, in id order;
* a dated plain-words entry is prepended to ``revision`` (one line per
  amendment, newest first); ``version`` is never changed;
* every other field is untouched and the markdown body is kept byte for byte.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from hestai_context_mcp.core.agent_readable_governance_parser import (
    TOKEN_FORMAT_PATTERN,
    DecisionRecord,
    RulingEntry,
    TopicBlocks,
    YamlSyntaxError,
    canonicalize_yaml_record,
    classify_record_text,
    collect_topic_blocks,
    emit_yaml_record,
    parse_decision_record,
)
from hestai_context_mcp.tools.governance.type_checker import MAX_REASONING_WORDS

__all__ = [
    "AppendRequest",
    "RenderOutcome",
    "RulingInput",
    "parse_append_request",
    "record_hash",
    "render_append",
]

# Structured error codes (PROD I4); submit_governance surfaces them.
APPEND_INPUT_INVALID = "APPEND_INPUT_INVALID"
NOT_YAML_TOPIC_RECORD = "NOT_YAML_TOPIC_RECORD"
NOT_A_TOPIC_RECORD = "NOT_A_TOPIC_RECORD"
RECORD_UNREADABLE = "RECORD_UNREADABLE"
TOPIC_BLOCKS_MALFORMED = "TOPIC_BLOCKS_MALFORMED"
REPLACES_UNKNOWN_ID = "REPLACES_UNKNOWN_ID"
RENDER_REJECTED = "RENDER_REJECTED"
# Refusals about WHAT the record is (reported before CAS and the in-flight check).
RECORD_KIND_CODES = frozenset({NOT_YAML_TOPIC_RECORD, NOT_A_TOPIC_RECORD, RECORD_UNREADABLE})

_REQUEST_KEYS = frozenset({"topic_token", "rulings", "expected_record_hash"})
_RULING_KEYS = frozenset({"rule", "verbatim", "ruled", "replaces"})
_RULING_ID_RE = re.compile(r"^R(\d+)$")
_ID_REF_RE = re.compile(r"\bR(\d+)\b")
_HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_TOKEN_RE = re.compile(TOKEN_FORMAT_PATTERN)
# Operator ruling 2026-10-31 (HO-AGR-PLAIN-WORDS-REASONING-20261031): relations in
# plain words, never arrows or symbols. Applied to RULE as to DECISION and BECAUSE.
_GLYPHS = ("→", "⇌", "∴", "⊕", "∧", "∨")


@dataclass(frozen=True)
class RulingInput:
    """One ruling to append: the agent-written RULE plus the operator's words."""

    rule: str
    verbatim: str
    ruled: str
    replaces: tuple[str, ...] = ()


@dataclass(frozen=True)
class AppendRequest:
    """A validated ``append_ruling`` argument."""

    topic_token: str
    rulings: tuple[RulingInput, ...]
    expected_record_hash: str | None


@dataclass
class RenderOutcome:
    """Result of :func:`render_append` (structured; never raised)."""

    ok: bool
    text: str | None = None
    appended_ids: list[str] = field(default_factory=list)
    replaced_ids: list[str] = field(default_factory=list)
    revision_entry: str | None = None
    pairs: list[dict[str, str]] = field(default_factory=list)
    error_code: str | None = None
    errors: list[str] = field(default_factory=list)


def record_hash(data: bytes) -> str:
    """The ADR-RFC-ARCH-004 §1.1/§3.5 CAS primitive: ``sha256:<hex>`` of the file bytes."""
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _breaks_line(value: str) -> bool:
    """True if ``value`` holds any character ``str.splitlines()`` splits on."""
    return bool(value) and value.splitlines() != [value]


# ---------------------------------------------------------------------------
# Input contract
# ---------------------------------------------------------------------------


def _check_rule(where: str, rule: Any, errors: list[str]) -> None:
    if not isinstance(rule, str) or not rule.strip():
        errors.append(f"{where}.rule must be a non-empty string.")
    elif _breaks_line(rule):
        errors.append(f"{where}.rule must be one line (no newline).")
    elif len(rule.split()) > MAX_REASONING_WORDS:
        errors.append(
            f"{where}.rule is {len(rule.split())} words (max {MAX_REASONING_WORDS}); "
            "a RULE is one line, like DECISION."
        )
    else:
        glyphs = [g for g in _GLYPHS if g in rule]
        if glyphs:
            errors.append(
                f"{where}.rule must be plain words, never arrows or symbols "
                f"(found {' '.join(glyphs)})."
            )


def _parse_replaces(where: str, raw: Any, errors: list[str]) -> list[str]:
    replaces: list[str] = []
    if raw is None:
        return replaces
    if not isinstance(raw, list):
        errors.append(f"{where}.replaces must be null or a list of ruling ids.")
        return replaces
    for rid in raw:
        if not isinstance(rid, str) or not _RULING_ID_RE.match(rid):
            errors.append(f"{where}.replaces id {rid!r} is not of the form R<n>.")
        elif rid in replaces:
            errors.append(f"{where}.replaces lists {rid} more than once.")
        else:
            replaces.append(rid)
    return replaces


def _parse_ruling(index: int, raw: Any, errors: list[str]) -> RulingInput | None:
    where = f"append_ruling.rulings[{index}]"
    if not isinstance(raw, dict):
        errors.append(f"{where} must be a dict with keys rule, verbatim, ruled, replaces.")
        return None
    start = len(errors)
    unknown = sorted(set(raw) - _RULING_KEYS)
    if unknown:
        errors.append(f"{where} has unknown key(s): {', '.join(unknown)}.")

    rule = raw.get("rule")
    _check_rule(where, rule, errors)

    verbatim = raw.get("verbatim")
    if not isinstance(verbatim, str) or not verbatim.strip():
        errors.append(f"{where}.verbatim must be a non-empty string (the operator's exact words).")

    ruled = raw.get("ruled")
    if not isinstance(ruled, str) or not ruled.strip():
        errors.append(f"{where}.ruled must be a non-empty provenance string.")
    elif _breaks_line(ruled):
        errors.append(f"{where}.ruled must be one line (no newline).")

    replaces = _parse_replaces(where, raw.get("replaces"), errors)

    if len(errors) > start:
        return None
    assert isinstance(rule, str) and isinstance(verbatim, str) and isinstance(ruled, str)
    return RulingInput(rule=rule, verbatim=verbatim, ruled=ruled, replaces=tuple(replaces))


def parse_append_request(raw: Any) -> tuple[AppendRequest | None, list[str]]:
    """Validate the ``append_ruling`` argument; return ``(request, errors)``.

    ``request`` is None whenever ``errors`` is non-empty. VERBATIM is kept
    exactly as given (never stripped or normalised).
    """
    if not isinstance(raw, dict):
        return None, [
            "append_ruling must be a dict with keys topic_token, rulings, expected_record_hash."
        ]
    errors: list[str] = []
    unknown = sorted(set(raw) - _REQUEST_KEYS)
    if unknown:
        errors.append(
            f"append_ruling has unknown key(s): {', '.join(unknown)} "
            f"(allowed: {', '.join(sorted(_REQUEST_KEYS))})."
        )

    token = raw.get("topic_token")
    if not isinstance(token, str) or not _TOKEN_RE.match(token):
        errors.append(
            "append_ruling.topic_token must be the TOKEN of a merged topic record "
            "(ADR-RFC-ARCH-004 §1.3 format)."
        )

    rulings_raw = raw.get("rulings")
    rulings: list[RulingInput] = []
    if not isinstance(rulings_raw, list) or not rulings_raw:
        errors.append("append_ruling.rulings must be a non-empty list.")
    else:
        for index, item in enumerate(rulings_raw):
            ruling = _parse_ruling(index, item, errors)
            if ruling is not None:
                rulings.append(ruling)
        seen: set[str] = set()
        for ruling in rulings:
            for rid in ruling.replaces:
                if rid in seen:
                    errors.append(
                        f"ruling id {rid} is replaced by more than one ruling in this call."
                    )
                seen.add(rid)

    expected = raw.get("expected_record_hash")
    if expected is not None and (not isinstance(expected, str) or not _HASH_RE.match(expected)):
        errors.append(
            "append_ruling.expected_record_hash must be null or 'sha256:<64 lowercase hex>'."
        )

    if errors:
        return None, errors
    assert isinstance(token, str)
    return (
        AppendRequest(topic_token=token, rulings=tuple(rulings), expected_record_hash=expected),
        [],
    )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _fail(code: str, *errors: str) -> RenderOutcome:
    return RenderOutcome(ok=False, error_code=code, errors=list(errors))


def _record_fields(parsed: DecisionRecord) -> dict[str, str]:
    """Every decoded front-matter field by uppercase name, core and extra alike."""
    flat = {k.upper(): v for k, v in parsed.items() if k != "fields" and isinstance(v, str)}
    flat.update(parsed["fields"])
    return flat


def _id_number(rid: str) -> int:
    return int(rid[1:])


def _read_topic_record(
    base: bytes,
) -> tuple[dict[str, str], TopicBlocks, str] | RenderOutcome:
    """``(fields, blocks, body)`` of a YAML topic record, or the refusal."""
    record = classify_record_text(base)
    if record.syntax != "yaml":
        return _fail(
            NOT_YAML_TOPIC_RECORD,
            "append_ruling writes YAML topic records only; this record is OCTAVE "
            "(rewrite it as a quoted-YAML topic record first).",
        )
    if record.diagnostic is not None:
        return _fail(
            RECORD_UNREADABLE,
            f"The record at main is rejected by the reader at line "
            f"{record.diagnostic['line']}: {record.diagnostic['construct']}.",
        )
    parsed = parse_decision_record(record.text)
    fields = _record_fields(parsed)
    if not fields.get("TOPIC"):
        return _fail(
            NOT_A_TOPIC_RECORD,
            "append_ruling amends topic records only; this record has no topic field.",
        )
    blocks = collect_topic_blocks(record.text)
    try:
        # The body is whatever follows the canonical front matter: canonicalisation
        # copies it VERBATIM from the raw bytes (the reader's own body rule).
        canonical = canonicalize_yaml_record(base)
        front = emit_yaml_record(fields, blocks)
    except YamlSyntaxError as exc:
        return _fail(RECORD_UNREADABLE, f"The record at main cannot be canonicalised: {exc}.")
    if not canonical.startswith(front):  # pragma: no cover - emitter invariant
        return _fail(RECORD_UNREADABLE, "The record's front matter does not re-emit canonically.")
    return fields, blocks, canonical[len(front) :]


def _live_rulings(blocks: TopicBlocks) -> dict[str, RulingEntry] | RenderOutcome:
    """The existing ``rulings`` entries by id, after the integrity checks."""
    existing: dict[str, RulingEntry] = {}
    for entry in blocks["rulings"]:
        if entry["rule"] is None:
            return _fail(
                TOPIC_BLOCKS_MALFORMED,
                f"rulings entry {entry['id']} has no rule line; current cannot be rebuilt.",
            )
        existing[entry["id"]] = entry
    orphans = [c["id"] for c in blocks["current"] if c["id"] not in existing]
    if orphans:
        return _fail(
            TOPIC_BLOCKS_MALFORMED,
            f"current lists {', '.join(orphans)} with no rulings entry; rebuilding current "
            "would drop it. Fix the record by hand first.",
        )
    return existing


def _next_number(blocks: TopicBlocks) -> int:
    numbers = [_id_number(e["id"]) for e in blocks["rulings"]]
    numbers += [_id_number(c["id"]) for c in blocks["current"]]
    for entry in blocks["rulings"]:
        numbers += [int(n) for n in _ID_REF_RE.findall(entry["replaces"] or "")]
    return max(numbers, default=0) + 1


def _revision_entry(today: date, new_ids: list[str], rulings: Sequence[RulingInput]) -> str:
    entry = f"{today.isoformat()}: {', '.join(new_ids)} added"
    for rid, ruling in zip(new_ids, rulings, strict=True):
        if ruling.replaces:
            entry += f"; {rid} replaces {', '.join(ruling.replaces)}"
    return entry


def render_append(base: bytes, rulings: Sequence[RulingInput], today: date) -> RenderOutcome:
    """Append ``rulings`` to the YAML topic record ``base`` (pure, deterministic)."""
    read = _read_topic_record(base)
    if isinstance(read, RenderOutcome):
        return read
    fields, blocks, body = read

    existing = _live_rulings(blocks)
    if isinstance(existing, RenderOutcome):
        return existing

    unknown = [rid for r in rulings for rid in r.replaces if rid not in existing]
    if unknown:
        return _fail(
            REPLACES_UNKNOWN_ID,
            f"replaces names {', '.join(unknown)}, which "
            f"{'is' if len(unknown) == 1 else 'are'} not an entry in rulings at main.",
        )

    first = _next_number(blocks)
    new_ids = [f"R{first + i}" for i in range(len(rulings))]
    replaced = [rid for r in rulings for rid in r.replaces]

    entries: list[RulingEntry] = [e for rid, e in existing.items() if rid not in replaced]
    for rid, ruling in zip(new_ids, rulings, strict=True):
        entries.append(
            {
                "id": rid,
                "rule": ruling.rule,
                "verbatim": ruling.verbatim,
                "ruled": ruling.ruled,
                "replaces": ", ".join(ruling.replaces) or None,
            }
        )
    live = sorted(entries, key=lambda e: _id_number(e["id"]))
    new_blocks: TopicBlocks = {
        "current": [{"id": e["id"], "rule": e["rule"] or ""} for e in live],
        "rulings": entries,
    }

    revision_entry = _revision_entry(today, new_ids, rulings)
    old_revision = fields.get("REVISION")
    fields["REVISION"] = f"{revision_entry}\n{old_revision}" if old_revision else revision_entry

    try:
        text = emit_yaml_record(fields, new_blocks, body=body)
    except YamlSyntaxError as exc:
        return _fail(RENDER_REJECTED, f"The appended record cannot be emitted: {exc}.")

    return RenderOutcome(
        ok=True,
        text=text,
        appended_ids=new_ids,
        replaced_ids=replaced,
        revision_entry=revision_entry,
        pairs=[
            {"id": rid, "rule": r.rule, "verbatim": r.verbatim}
            for rid, r in zip(new_ids, rulings, strict=True)
        ],
    )
