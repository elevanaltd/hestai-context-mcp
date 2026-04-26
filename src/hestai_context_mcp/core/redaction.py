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
#: older redactor output as safe (PROD::I2 fail-closed). The B1
#: arbitration record locks the value at '1' for the LocalFilesystem
#: adapter ship.
REDACTION_ENGINE_VERSION: str = "1"


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
    - AI API keys (sk-... with 20+ alphanumeric characters)
    - AWS access keys (AKIA..., ASIA... with 16 uppercase alphanumeric)
    - PEM-encoded private keys (BEGIN/END PRIVATE KEY blocks)
    - Bearer authentication tokens
    - Database passwords in connection strings (scheme://user:password@host)

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
    PATTERNS: dict[str, tuple[Pattern[str], str]] = {
        # AI API keys: sk- followed by 20+ alphanumeric chars
        "ai_api_key": (
            re.compile(r"sk-[a-zA-Z0-9]{20,}"),
            "[REDACTED_API_KEY]",
        ),
        # AWS access keys: AKIA or ASIA followed by 16 uppercase alphanumeric
        "aws_key": (
            re.compile(r"(AKIA|ASIA)[0-9A-Z]{16}"),
            "[REDACTED_AWS_KEY]",
        ),
        # PEM private keys: entire BEGIN/END block.
        # Uses [A-Z ]* (zero or more) to handle both qualified keys
        # (e.g., "RSA PRIVATE KEY") and bare "PRIVATE KEY".
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

        Stream-based processing for memory efficiency with large files.
        Processes line-by-line to avoid loading entire file into memory.
        Fail-closed: raises exception if source doesn't exist or redaction fails.
        If redaction fails, destination file is not created (or deleted if
        partially written).

        Args:
            src: Source file path.
            dst: Destination file path.

        Raises:
            FileNotFoundError: If source file doesn't exist.
            Exception: If redaction fails (destination not created).
        """
        if not src.exists():
            raise FileNotFoundError(f"Source file not found: {src}")

        try:
            with (
                open(src, encoding="utf-8") as src_file,
                open(dst, "w", encoding="utf-8") as dst_file,
            ):
                for line in src_file:
                    redacted_line = cls.redact_content(line)
                    dst_file.write(redacted_line)
        except Exception:
            # Fail-closed: remove partial output if redaction failed
            if dst.exists():
                dst.unlink()
            raise
