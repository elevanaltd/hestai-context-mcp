"""Redaction engine: Detects and redacts sensitive credentials from session transcripts.

Security-critical module that prevents API keys, tokens, passwords, and other
credentials from being persisted in session archives. Used by clock_out to
ensure credential safety before archival.

Fail-closed design: If redaction fails, archival is blocked.

Harvested from legacy hestai-mcp RedactionEngine with clean interface adaptation.
"""

from __future__ import annotations

import functools
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from re import Match, Pattern

#: Canonical engine identifier for provenance metadata (RISK_004 / G6).
#: Used by storage.provenance.build_provenance to populate
#: RedactionProvenance.engine_name on every published Portable Memory
#: Artifact (ADR-0013 R6). Must remain stable across refactors so older
#: artifacts can identify the engine that produced them.
REDACTION_ENGINE_NAME: str = "hestai-context-mcp.redaction"

#: Engine version embedded in artifact metadata (RISK_004 + G6 + A4).
#: Bump this constant whenever PATTERNS or redaction semantics change so
#: downstream readers can detect stale provenance and refuse to treat
#: older redactor output as safe (PROD::I2 fail-closed).
#:
#: BUMP POLICY: Increment by 1 on every pattern addition or semantic change.
#: Version history:
#:   '1' — B1 LocalFilesystem adapter ship (ADR-0013): ai_api_key, aws_key,
#:          private_key, bearer_token, db_password.
#:   '2' — Phase 1 hardening (issue #43): G1 stream-mode PEM fix (full-buffer
#:          copy_and_redact), G2 GitHub PAT patterns (classic + fine-grained),
#:          G7 sk- character class widened to include hyphens/underscores.
#:   '3' — issue #256 / PR #261: db_password line-bounded at every
#:          str.splitlines() boundary (v2 could keep a password on multi-line
#:          input when a later line held '@'); private_key redacts a BEGIN with
#:          no END to the end of the input (fail safe), and its header matches
#:          case-insensitively, incl. PGP "PRIVATE KEY BLOCK" and SSH2 armour.
#:   '4' — issue #264 / PR #265: S2 span-union redaction (single-line
#:          patterns all match the same text; the union of overlapping secret
#:          spans is replaced), so no pattern can consume another's anchor
#:          (v3 leaked on B1-B3, A1-A4); bearer chain; possessive db scheme.
#:   '5' — issue #269: db_password allows an empty user part ("redis://:pw@");
#:          bearer keyword case-insensitive (incl. the chain); over-width token
#:          runs redacted whole (aws {16,}, github {36,}/{82,}); github_token
#:          split (classic overlapping, github_pat non-overlapping).
REDACTION_ENGINE_VERSION: str = "5"

#: Every line boundary ``str.splitlines()`` honours, as a regex character-class
#: body: LF, CR, VT, FF, FS, GS, RS, NEL, LINE SEPARATOR, PARAGRAPH SEPARATOR
#: (CRLF is CR then LF). Single-line patterns must not cross any of them (#261).
_LINE_SEPARATORS: str = r"\n\r\x0b\x0c\x1c\x1d\x1e\x85\u2028\u2029"

#: One line: a maximal run of characters that are not _LINE_SEPARATORS.
_LINE: Pattern[str] = re.compile(rf"[^{_LINE_SEPARATORS}]+")

#: Name of the group that wraps an overlapping matcher's whole match.
_OVERLAP_GROUP: str = "_overlap"


def _last_at_bounded(pattern: Pattern[str], text: str) -> Iterator[Match[str]]:
    """``pattern.finditer(text)`` for a pattern whose every match ends at the
    LAST '@' of its line, in linear time (#266).

    Plain ``finditer`` was quadratic on one long line: every ``scheme://``
    candidate scanned its password to the end of the line before failing (400k
    chars: about 70s). Here a line with no '@' is skipped, since no match is
    possible on it, and on any other line ONE search runs, in a window that
    ends just after the line's last '@': the text after it is never scanned.

    Same matches as ``finditer``, group for group, because: each match lies
    inside one line and its lookahead passes only at the line's last '@' A, so
    a line has at most one match and it ends at A+1. In the window
    [line start, A+1) the lookahead also passes only at A (``\\Z`` matches at
    ``endpos``); ``\\b`` at ``pos`` reads the real preceding character, a
    separator, which is never ``\\w``. The greedy password stops at A either
    way. Pinned by test_redaction_last_at_bounded.py (differential + guard).
    """
    for line in _LINE.finditer(text):
        start, end = line.span()
        last_at = text.rfind("@", start, end)
        if last_at < 0:
            continue
        match = pattern.search(text, start, last_at + 1)
        if match is not None:
            yield match


@functools.cache
def _overlapping(pattern: Pattern[str]) -> Pattern[str]:
    """``pattern`` inside a lookahead, so ``finditer`` tries EVERY start position.

    A plain ``finditer`` never starts a match inside the previous one, so a
    bounded-width match that ends partway into the next token's anchor hides
    that token (#265 C1). Zero-width lookahead matches advance one character
    at a time; the span comes from the wrapping group (or ``secret``).
    """
    return re.compile(rf"(?=(?P<{_OVERLAP_GROUP}>{pattern.pattern}))", pattern.flags)


#: One bearer-token value: base64-like characters plus optional '=' padding.
_BEARER_VALUE: str = r"[a-zA-Z0-9\-\._~\+\/]+=*"


@dataclass(frozen=True)
class RedactionResult:
    """Result of a redaction operation.

    Attributes:
        redacted_text: The input text with all detected credentials replaced
            by redaction markers.
        redaction_count: Total number of individual credential instances redacted.
        redacted_types: Deduplicated list of credential type names that were
            detected (e.g., ["ai_api_key", "aws_key"]).
    """

    redacted_text: str
    redaction_count: int = 0
    redacted_types: list[str] = field(default_factory=list)


class RedactionEngine:
    """Engine for detecting and redacting sensitive credentials from text.

    Detects the following credential patterns (high-confidence, low false-positive):
    - AI API keys (sk-... including Anthropic sk-ant-* and OpenAI sk-proj-*/sk-svcacct-*)
    - AWS access keys (AKIA..., ASIA... with 16 uppercase alphanumeric)
    - PEM-encoded private keys (BEGIN/END PRIVATE KEY blocks; a BEGIN with no
      END is redacted to the end of the input, fail safe)
    - Bearer authentication tokens
    - Database passwords in connection strings (scheme://user:password@host)
    - GitHub Personal Access Tokens (classic ghp_/gho_/ghu_/ghs_/ghr_,
      fine-grained github_pat_)

    Usage:
        engine = RedactionEngine()
        result = engine.redact(text)
        print(result.redacted_text)    # Text with credentials replaced
        print(result.redaction_count)   # Number of credentials found
        print(result.redacted_types)    # Types of credentials found

    Backward-compatible classmethod interface also available:
        clean = RedactionEngine.redact_content(text)  # Returns str directly
    """

    # Pre-compiled regex patterns for performance.
    # Each entry: pattern_name -> (compiled_regex, replacement_string)
    #
    # BUMP POLICY: When adding or changing any pattern here, also increment
    # REDACTION_ENGINE_VERSION above. This ensures artifact provenance records
    # accurately reflect which pattern set was active at archive time.
    #
    # LINE-BOUNDING RULE (#256, #261): callers pass multi-line text
    # (copy_and_redact passes a whole file). Every pattern except private_key
    # must be line-bounded: no character class may match any of
    # _LINE_SEPARATORS, and an end-of-line test must be a lookahead for one
    # of them (or \Z). Do not use '$' with re.MULTILINE: it knows only '\n'.
    #
    # REDACTION MODEL (S2, #264/#265 HC ruling). Each entry is (regex, label):
    # 1. Stage 1: private_key alone, ``subn`` over the whole input. It runs first
    #    (by name, not by dict position) so no single-line match can consume a
    #    key's armour line (#261). It stays the first entry for readability and
    #    is pinned by test_private_key_is_the_first_pattern.
    # 2. Stage 2: every other pattern runs ``finditer`` on the SAME stage-1 text,
    #    so no pattern ever sees another's replacement (the old sequential model
    #    let one pattern consume another's anchor: #264 A1-A4, B1). Each match
    #    contributes the span of its named group ``secret``, or the whole match.
    #    The UNION of overlapping spans is replaced, so no byte of any matched
    #    secret survives, even on partial overlap. Text outside every secret
    #    span (e.g. "Bearer ", "scheme://user:") is kept, so a kept prefix can
    #    never extend into another pattern's secret. Label of a merged span:
    #    the longest contributing span's label, ties broken by PATTERNS order.
    # 3. OVERLAPPING (#265 C1, #269): a token match that can END partway into
    #    the anchor of a second token of the SAME pattern hides that token from
    #    plain finditer. A whole-match token pattern is safe without overlap only
    #    if it ABSORBS its own anchors: an unbounded run whose class contains
    #    every anchor char (aws_key: AKIA/ASIA in [0-9A-Z]; github_pat: in
    #    [A-Za-z0-9_]; ai_api_key: "sk-" in its class). Otherwise it must run as
    #    an overlapping matcher: classic github_token ("_" is in its anchor but
    #    not its class, so "ghp_<33>ghp" + "_<36>" stops at the "_"). Overlap is
    #    never combined with an absorbing run: every start would rescan the run
    #    (quadratic on repeated anchors, e.g. "AKIA" x 50,000).
    #    test_token_patterns_absorb_own_anchors_or_are_overlapping derives this
    #    from PATTERNS and fails if a pattern is on the wrong side.
    # 4. LAST_AT_BOUNDED (#266 HC ruling): a pattern whose every match ends at
    #    the LAST '@' of its line (db_password) runs through _last_at_bounded,
    #    not finditer: same matches, linear time on long lines. Only a pattern
    #    with that property may be listed: the differential in
    #    test_redaction_last_at_bounded.py checks every entry against finditer.
    # compute_ruleset_hash sorts PATTERNS by NAME and hashes only the strings,
    # so it cannot see dict order or this model (tracked in #263).
    #
    # Critical-Engineer: consulted for Redaction security and archive integrity
    # (#261 round 1 BLOCKED at 46f6108; separators, key headers, two URIs).
    OVERLAPPING: frozenset[str] = frozenset({"github_token"})
    LAST_AT_BOUNDED: frozenset[str] = frozenset({"db_password"})

    PATTERNS: dict[str, tuple[Pattern[str], str]] = {
        # PEM private keys: entire BEGIN/END block.
        # Header rule (#261, fail-safe bias): case-insensitive; 4 or 5 dashes with an
        # optional space (SSH2 "---- BEGIN ... ----"); any kind words before
        # "PRIVATE KEY" ([A-Z0-9 ]*: RSA, EC, DSA, OPENSSH, ENCRYPTED, SSH2, bare)
        # and any after it (PGP "PRIVATE KEY BLOCK"). Public keys, PGP public
        # blocks and certificates never say "PRIVATE KEY", so they do not match.
        # NOTE: DOTALL is required; this pattern only works on a full-buffer string.
        # copy_and_redact uses full-buffer mode (G1 fix) to guarantee this pattern fires,
        # including a block whose BEGIN and END sit in different JSONL records.
        # Fail safe (#256, PROD::I2): a BEGIN with no END anywhere after it
        # (truncated output) is redacted to the END OF THE INPUT. The lazy first
        # alternative is always tried first, so a terminated block is still
        # replaced in place; only an unterminated BEGIN falls through to ``.*``.
        # Accepted cost: everything after an unterminated BEGIN is lost from
        # that input (data loss over data exposure). Whatever input a caller
        # passes defines that span: a whole file for copy_and_redact, one line
        # or record for a per-line caller. On a JSONL archive that means every
        # later record is dropped and the cut record is no longer valid JSON.
        # A bare BEGIN marker with no key material (prose, grep output) also
        # triggers it. Bounding the span to one record was rejected: a
        # truncated key streamed across several records would then leak.
        "private_key": (
            re.compile(
                r"-{4,5} ?BEGIN [A-Z0-9 ]*PRIVATE KEY[A-Z ]* ?-{4,5}"
                r"(?:.*?-{4,5} ?END [A-Z0-9 ]*PRIVATE KEY[A-Z ]* ?-{4,5}|.*)",
                re.DOTALL | re.IGNORECASE,
            ),
            "[REDACTED_PRIVATE_KEY]",
        ),
        # AI API keys: sk- followed by 20+ alphanumeric, hyphen, or underscore chars.
        # G7 fix: widened from [a-zA-Z0-9] to [a-zA-Z0-9\-_] to capture full tokens
        # for Anthropic (sk-ant-api03-...) and OpenAI (sk-proj-..., sk-svcacct-...).
        # Without hyphens/underscores in the character class the regex terminates at
        # the first hyphen, leaving the entropy tail in cleartext.
        "ai_api_key": (
            re.compile(r"sk-[a-zA-Z0-9\-_]{20,}"),
            "[REDACTED_API_KEY]",
        ),
        # AWS access keys: AKIA or ASIA followed by 16 or MORE uppercase
        # alphanumerics. Over-width run (#269 U3, HC ruling (a)): the whole run is
        # redacted, fail safe. The run's class covers AKIA/ASIA, so it absorbs a
        # following anchor: NOT an overlapping matcher.
        "aws_key": (
            re.compile(r"(AKIA|ASIA)[0-9A-Z]{16,}"),
            "[REDACTED_AWS_KEY]",
        ),
        # Bearer tokens: "Bearer " then base64-like characters; the value is the
        # secret. Chain (#264 B2/B3): the value class has no space, so a value
        # that ends in the word "Bearer" ("Bearer Bearer X", "Bearer V1Bearer V2")
        # continues through the following spaces and value instead of leaving
        # it unredacted. Linear: the value class, '=' and ' ' are disjoint and
        # the lookbehind is fixed-width.
        # KEYWORD case-insensitive (#269 U2, HC ruling S-a), in the chain
        # lookbehind too ("bearer bearer X"); the value class is unchanged and
        # the keyword's own casing is kept. Accepted prose cost: ordinary
        # English "bearer <word>" redacts <word> (6 files / 9 lines in the repo).
        "bearer_token": (
            re.compile(
                rf"(?i:Bearer) (?P<secret>{_BEARER_VALUE}(?:(?<=(?i:Bearer)) +{_BEARER_VALUE})*)"
            ),
            "[REDACTED_BEARER]",
        ),
        # Database passwords in connection strings.
        # Matches: scheme://user:password@host:port/db
        # Uses a lookahead to find the LAST @ ON THE LINE before host/port/path.
        # Pattern breakdown (S = _LINE_SEPARATORS, every str.splitlines() boundary):
        #   (\b\w++://[^:S]*:)   - Keep scheme://user: (user part may be EMPTY: #269 U1)
        #   (?P<secret>[^S]+)    - The password, the only redacted part (greedy, one line)
        #   (@)                  - Capture the @ separator
        #   (?=[^@S]*(?:[S]|\Z)) - Lookahead: no more @ before the END OF THIS LINE
        #   This ensures password can contain @ symbols but we match to the line's final @
        # LINE-BOUNDED (#256, PROD::I2): without it, on multi-line input (the
        # whole-file copy_and_redact archive) an '@' on a LATER line failed the
        # lookahead and the password survived, and the user part joined a URL line
        # to a later '@' line, over-redacting unrelated text. '\n' alone was not
        # enough (#261): a lone '\r' or U+2028 inside a record ran the match on.
        # Two URIs on ONE line collapse into one match to the line's last '@';
        # that only over-redacts the text between them (both passwords are
        # inside the redacted group). It is kept on purpose: a password ending at
        # whitespace would leak an unencoded password that contains a space.
        # ReDoS (#265): the scheme is ``\b\w++`` (word-boundary start, possessive),
        # so one long word is scanned once; plain ``\w+://`` retried every start
        # inside the word and was quadratic (40k chars: about 1s). The redacted
        # password span is unchanged; only the kept prefix can start earlier.
        # Long lines (#266): finditer was still quadratic (every candidate's
        # password ran to the end of the line), so this pattern is matched by
        # _last_at_bounded (LAST_AT_BOUNDED). Same matches as finditer: the
        # strategy alone never changes output (the U1 change above is #269's).
        "db_password": (
            re.compile(
                rf"(\b\w++://[^:{_LINE_SEPARATORS}]*:)(?P<secret>[^{_LINE_SEPARATORS}]+)(@)"
                rf"(?=[^@{_LINE_SEPARATORS}]*(?:[{_LINE_SEPARATORS}]|\Z))"
            ),
            "[REDACTED_PASSWORD]",
        ),
        # GitHub Personal Access Tokens (G2), split in two (#269).
        # Classic PATs: ghp_ (personal), gho_ (OAuth app), ghu_ (user-to-server),
        # ghs_ (server-to-server), ghr_ (refresh token), then 36 or MORE
        # alphanumerics. Over-width run (#269 U3, HC ruling (a)): whole run
        # redacted. "_" is in the anchor but not the class, so this one stays an
        # OVERLAPPING matcher (C1); its runs end at the next "_", so it is linear.
        "github_token": (
            re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}"),
            "[REDACTED_GITHUB_TOKEN]",
        ),
        # Fine-grained PATs: github_pat_ then 82 or MORE [A-Za-z0-9_]. The class
        # covers the whole anchor, so the run absorbs a following github_pat_:
        # NOT an overlapping matcher. Same label as classic tokens.
        "github_pat": (
            re.compile(r"github_pat_[A-Za-z0-9_]{82,}"),
            "[REDACTED_GITHUB_TOKEN]",
        ),
    }

    def redact(self, text: str) -> RedactionResult:
        """Redact sensitive credentials from text content.

        Args:
            text: Input text that may contain secrets.

        Returns:
            RedactionResult with redacted text, count, and type metadata.
        """
        return self._redact(text)

    @classmethod
    def redact_content(cls, text: str) -> str:
        """Redact sensitive data from text content (backward-compatible classmethod).

        Args:
            text: Input text that may contain secrets.

        Returns:
            Text with secrets replaced by redaction markers.
        """
        return cls._redact(text).redacted_text

    @classmethod
    def _redact(cls, text: str) -> RedactionResult:
        """Apply the S2 redaction model described above PATTERNS."""
        counts: dict[str, int] = {}

        # Stage 1: private keys over the whole input, before anything else.
        key_pattern, key_label = cls.PATTERNS["private_key"]
        text, counts["private_key"] = key_pattern.subn(key_label, text)

        # Stage 2: every single-line pattern on the same stage-1 text.
        # (start, end, length, PATTERNS rank, label) for each secret span.
        spans: list[tuple[int, int, int, int, str]] = []
        for rank, (name, (pattern, label)) in enumerate(cls.PATTERNS.items()):
            if name == "private_key":
                continue
            overlapping = name in cls.OVERLAPPING
            matcher = _overlapping(pattern) if overlapping else pattern
            group: int | str = "secret" if "secret" in pattern.groupindex else 0
            if group == 0 and overlapping:
                group = _OVERLAP_GROUP
            if name in cls.LAST_AT_BOUNDED:
                matches = _last_at_bounded(pattern, text)
            else:
                matches = matcher.finditer(text)
            for match in matches:
                start, end = match.span(group)
                spans.append((start, end, end - start, rank, label))
                counts[name] = counts.get(name, 0) + 1
        spans.sort(key=lambda span: span[0])

        # Replace the union of overlapping spans with one label: the longest
        # member's, ties broken by PATTERNS order (lower rank wins).
        pieces: list[str] = []
        cursor = 0
        i = 0
        while i < len(spans):
            start, end, _length, _rank, _label = spans[i]
            members = [spans[i]]
            i += 1
            while i < len(spans) and spans[i][0] < end:
                end = max(end, spans[i][1])
                members.append(spans[i])
                i += 1
            label = min(members, key=lambda m: (-m[2], m[3]))[4]
            pieces += [text[cursor:start], label]
            cursor = end
        pieces.append(text[cursor:])

        return RedactionResult(
            redacted_text="".join(pieces),
            redaction_count=sum(counts.values()),
            redacted_types=[name for name in cls.PATTERNS if counts.get(name)],
        )

    @classmethod
    def copy_and_redact(cls, src: Path, dst: Path) -> None:
        """Copy file from src to dst with redaction applied.

        G1 fix: Reads the entire source file into memory before redacting.
        The previous line-by-line streaming approach silently missed multi-line
        PEM blocks because the private_key DOTALL pattern requires seeing the
        full BEGIN...END span, which never occurs within a single line.

        For this use-case (transcript JSONL archives on a single-developer
        laptop), files are bounded in size and full-buffer processing is safe.
        The memory cost is acceptable; the correctness gain is mandatory
        (PROD::I2: zero credentials persist in archives).

        ADR-tier decision (issue #43 Phase 1): Option (c) — full-buffer read.
        Options (a) look-back buffer and (b) BEGIN-marker accumulator were
        considered but rejected: both require stateful line-iteration logic
        that adds accumulative complexity without proportional benefit at this
        scale. Option (c) eliminates the entire class of stream-fragmentation
        bugs with minimal code change.

        Fail-closed: raises exception if source doesn't exist or redaction fails.
        Only the temp file written by this attempt is removed on failure; a
        pre-existing destination is preserved.

        Args:
            src: Source file path.
            dst: Destination file path.

        Raises:
            FileNotFoundError: If source file doesn't exist.
            Exception: If redaction fails (destination not created).
        """
        if not src.exists():
            raise FileNotFoundError(f"Source file not found: {src}")

        tmp = dst.with_suffix(dst.suffix + ".tmp")
        try:
            content = src.read_text(encoding="utf-8")
            redacted = cls.redact_content(content)
            tmp.write_text(redacted, encoding="utf-8")
            tmp.replace(dst)
        except Exception:
            if tmp.exists():
                tmp.unlink()
            raise
