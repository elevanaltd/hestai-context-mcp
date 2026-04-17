"""Transcript parsing module with provider adapter pattern.

Provides an abstract TranscriptParser interface with concrete implementations
for different AI provider transcript formats. Currently supports Claude JSONL.

Key components:
- TranscriptMessage: Common message format across all providers
- TranscriptParser: Abstract base for provider-specific parsers
- ClaudeTranscriptParser: Parser for Claude's JSONL transcript format
- detect_parser: Auto-detect transcript format and return appropriate parser
"""

from hestai_context_mcp.core.transcript.base import TranscriptMessage, TranscriptParser
from hestai_context_mcp.core.transcript.claude import ClaudeTranscriptParser
from hestai_context_mcp.core.transcript.registry import detect_parser, register_parser

__all__ = [
    "ClaudeTranscriptParser",
    "TranscriptMessage",
    "TranscriptParser",
    "detect_parser",
    "register_parser",
]
