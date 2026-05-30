"""Redaction engine: Detects and redacts sensitive credentials from session transcripts.

Security-critical module that prevents API keys, tokens, passwords, and other
credentials from being persisted in session archives. Used by clock_out to
ensure credential safety before archival.

Fail-closed design: If redaction fails, archival is blocked.

Harvested from legacy hestai-mcp RedactionEngine with clean interface adaptation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from re import Pattern

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
REDACTION_ENGINE_VERSION: str = "2"


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
    - PEM-encoded private keys (BEGIN/END PRIVATE KEY blocks)
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
    PATTERNS: dict[str, tuple[Pattern[str], str]] = {
        # AI API keys: sk- followed by 20+ alphanumeric, hyphen, or underscore chars.
        # G7 fix: widened from [a-zA-Z0-9] to [a-zA-Z0-9\-_] to capture full tokens
        # for Anthropic (sk-ant-api03-...) and OpenAI (sk-proj-..., sk-svcacct-...).
        # Without hyphens/underscores in the character class the regex terminates at
        # the first hyphen, leaving the entropy tail in cleartext.
        "ai_api_key": (
            re.compile(r"sk-[a-zA-Z0-9\-_]{20,}"),
            "[REDACTED_API_KEY]",
        ),
        # AWS access keys: AKIA or ASIA followed by 16 uppercase alphanumeric
        "aws_key": (
            re.compile(r"(AKIA|ASIA)[0-9A-Z]{16}"),
            "[REDACTED_AWS_KEY]",
        ),
        # PEM private keys: entire BEGIN/END block.
        # Uses [A-Z ]* (zero or more) to handle both qualified keys
        # (e.g., "RSA PRIVATE KEY") and bare "PRIVATE KEY").
        # NOTE: DOTALL is required; this pattern only works on a full-buffer string.
        # copy_and_redact uses full-buffer mode (G1 fix) to guarantee this pattern fires.
        "private_key": (
            re.compile(
                r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
                re.DOTALL,
            ),
            "[REDACTED_PRIVATE_KEY]",
        ),
        # Bearer tokens: Bearer followed by base64-like characters
        "bearer_token": (
            re.compile(r"Bearer [a-zA-Z0-9\-\._~\+\/]+=*"),
            "Bearer [REDACTED_BEARER]",
        ),
        # Database passwords in connection strings.
        # Matches: scheme://user:password@host:port/db
        # Uses negative lookahead to find the LAST @ before host/port/path.
        # Pattern breakdown:
        #   (\w+://[^:]+:) - Capture scheme://user:
        #   (.+)           - Capture password (greedy, everything)
        #   (@)            - Capture the @ separator
        #   (?=[^@]*$)     - Lookahead: ensure no more @ after this one (= last @)
        #   This ensures password can contain @ symbols but we match to the final @
        "db_password": (
            re.compile(r"(\w+://[^:]+:)(.+)(@)(?=[^@]*$)"),
            r"\1[REDACTED_PASSWORD]\3",
        ),
        # GitHub Personal Access Tokens (G2).
        # Classic PATs (40-char alphanumeric tail, introduced 2021):
        #   ghp_ (personal), gho_ (OAuth app), ghu_ (user-to-server),
        #   ghs_ (server-to-server), ghr_ (refresh token)
        # Fine-grained PATs (82-char alphanumeric+underscore tail):
        #   github_pat_
        # GitHub recommends these prefixes for secret scanning since 2021.
        "github_token": (
            re.compile(r"gh[pousr]_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{82}"),
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
        result = text
        total_count = 0
        found_types: list[str] = []

        for pattern_name, (pattern, replacement) in self.PATTERNS.items():
            matches = pattern.findall(result)
            match_count = len(matches)
            if match_count > 0:
                result = pattern.sub(replacement, result)
                total_count += match_count
                if pattern_name not in found_types:
                    found_types.append(pattern_name)

        return RedactionResult(
            redacted_text=result,
            redaction_count=total_count,
            redacted_types=found_types,
        )

    @classmethod
    def redact_content(cls, text: str) -> str:
        """Redact sensitive data from text content (backward-compatible classmethod).

        Args:
            text: Input text that may contain secrets.

        Returns:
            Text with secrets replaced by redaction markers.
        """
        result = text
        for _pattern_name, (pattern, replacement) in cls.PATTERNS.items():
            result = pattern.sub(replacement, result)
        return result

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
