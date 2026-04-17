"""Tests for transcript parser registry.

RED phase: These tests define the expected behavior of the parser registry
for auto-detecting transcript format and returning the appropriate parser.
"""

import json
from pathlib import Path

from hestai_context_mcp.core.transcript.claude import ClaudeTranscriptParser
from hestai_context_mcp.core.transcript.registry import detect_parser, register_parser


def _write_jsonl(path: Path, records: list[dict]) -> None:
    """Helper to write JSONL records to a file."""
    with open(path, "w") as f:
        for record in records:
            f.write(json.dumps(record) + "\n")


class TestDetectParser:
    """Tests for detect_parser auto-detection."""

    def test_detect_claude_parser_from_jsonl(self, tmp_path):
        """Registry detects Claude parser for Claude JSONL files."""
        records = [
            {
                "type": "human",
                "message": {"role": "user", "content": "test"},
            },
        ]
        path = tmp_path / "transcript.jsonl"
        _write_jsonl(path, records)

        parser = detect_parser(path)
        assert isinstance(parser, ClaudeTranscriptParser)

    def test_detect_returns_none_for_unknown_format(self, tmp_path):
        """Registry returns None when no parser matches."""
        path = tmp_path / "unknown.jsonl"
        records = [{"event": "log", "data": "something"}]
        _write_jsonl(path, records)

        parser = detect_parser(path)
        assert parser is None

    def test_detect_returns_none_for_missing_file(self, tmp_path):
        """Registry returns None for non-existent files."""
        path = tmp_path / "nonexistent.jsonl"
        parser = detect_parser(path)
        assert parser is None

    def test_detect_returns_none_for_empty_file(self, tmp_path):
        """Registry returns None for empty files."""
        path = tmp_path / "empty.jsonl"
        path.write_text("")
        parser = detect_parser(path)
        assert parser is None


class TestRegisterParser:
    """Tests for custom parser registration."""

    def test_register_and_detect_custom_parser(self, tmp_path):
        """Custom parsers can be registered and detected."""
        from hestai_context_mcp.core.transcript.base import TranscriptParser

        class CustomParser(TranscriptParser):
            def can_parse(self, path: Path) -> bool:
                return path.suffix == ".custom"

            def parse(self, path: Path) -> list:
                return []

        register_parser(CustomParser())

        custom_file = tmp_path / "transcript.custom"
        custom_file.write_text("custom format")

        parser = detect_parser(custom_file)
        assert isinstance(parser, CustomParser)
