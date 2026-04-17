"""Tests for transcript module public API exports."""

from hestai_context_mcp.core.transcript import (
    ClaudeTranscriptParser,
    TranscriptMessage,
    TranscriptParser,
    detect_parser,
    register_parser,
)


def test_module_exports_transcript_message():
    """TranscriptMessage is exported from the transcript module."""
    assert TranscriptMessage is not None


def test_module_exports_transcript_parser():
    """TranscriptParser is exported from the transcript module."""
    assert TranscriptParser is not None


def test_module_exports_claude_parser():
    """ClaudeTranscriptParser is exported from the transcript module."""
    assert ClaudeTranscriptParser is not None


def test_module_exports_detect_parser():
    """detect_parser is exported from the transcript module."""
    assert detect_parser is not None


def test_module_exports_register_parser():
    """register_parser is exported from the transcript module."""
    assert register_parser is not None
