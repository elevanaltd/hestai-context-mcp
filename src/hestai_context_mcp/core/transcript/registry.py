"""Transcript parser registry.

Auto-detects transcript format by trying each registered parser's
can_parse() method. Claude parser is registered by default.
"""

from __future__ import annotations

from pathlib import Path

from hestai_context_mcp.core.transcript.base import TranscriptParser
from hestai_context_mcp.core.transcript.claude import ClaudeTranscriptParser

# Global registry of parsers, ordered by priority (first match wins)
_parsers: list[TranscriptParser] = []

# Register Claude parser by default
_parsers.append(ClaudeTranscriptParser())


def detect_parser(path: Path) -> TranscriptParser | None:
    """Auto-detect transcript format and return the appropriate parser.

    Tries each registered parser's can_parse() method in order.
    Returns the first parser that claims to handle the file.

    Args:
        path: Path to the transcript file.

    Returns:
        A TranscriptParser instance that can handle the file,
        or None if no parser matches.
    """
    for parser in _parsers:
        if parser.can_parse(path):
            return parser
    return None


def register_parser(parser: TranscriptParser) -> None:
    """Register a custom transcript parser.

    The new parser is added to the end of the registry.
    Parsers are tried in order during detection.

    Args:
        parser: A TranscriptParser instance to register.
    """
    _parsers.append(parser)
