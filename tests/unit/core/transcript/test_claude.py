"""Tests for Claude transcript parser.

RED phase: These tests define the expected behavior of ClaudeTranscriptParser
for handling current Claude JSONL format, including graceful handling of
unknown record types.
"""

import json
from pathlib import Path

import pytest

from hestai_context_mcp.core.transcript.base import TranscriptMessage
from hestai_context_mcp.core.transcript.claude import ClaudeTranscriptParser


def _write_jsonl(path: Path, records: list[dict]) -> None:
    """Helper to write JSONL records to a file."""
    with open(path, "w") as f:
        for record in records:
            f.write(json.dumps(record) + "\n")


@pytest.fixture
def parser():
    """Create a ClaudeTranscriptParser instance."""
    return ClaudeTranscriptParser()


@pytest.fixture
def sample_claude_jsonl(tmp_path: Path) -> Path:
    """Create a sample Claude JSONL file with human and assistant messages."""
    records = [
        {
            "type": "human",
            "message": {
                "role": "user",
                "content": "What is 2+2?",
            },
            "timestamp": "2026-04-17T10:00:00Z",
        },
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "The answer is 4."},
                ],
            },
            "timestamp": "2026-04-17T10:00:01Z",
        },
    ]
    path = tmp_path / "transcript.jsonl"
    _write_jsonl(path, records)
    return path


@pytest.fixture
def claude_jsonl_with_unknown_types(tmp_path: Path) -> Path:
    """Create a Claude JSONL file with unknown record types mixed in."""
    records = [
        {"type": "queue-operation", "data": {"queue_id": "abc123"}},
        {
            "type": "human",
            "message": {
                "role": "user",
                "content": "Hello",
            },
            "timestamp": "2026-04-17T10:00:00Z",
        },
        {"type": "progress", "data": {"percent": 50}},
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "Hi there!"}],
            },
            "timestamp": "2026-04-17T10:00:01Z",
        },
        {"type": "pr-link", "data": {"url": "https://github.com/test/pr/1"}},
    ]
    path = tmp_path / "transcript_mixed.jsonl"
    _write_jsonl(path, records)
    return path


class TestClaudeTranscriptParserCanParse:
    """Tests for can_parse detection."""

    def test_can_parse_valid_claude_jsonl(self, parser, sample_claude_jsonl):
        """Parser detects valid Claude JSONL files."""
        assert parser.can_parse(sample_claude_jsonl) is True

    def test_cannot_parse_non_jsonl(self, parser, tmp_path):
        """Parser rejects non-JSONL files."""
        txt_file = tmp_path / "transcript.txt"
        txt_file.write_text("Not a JSONL file")
        assert parser.can_parse(txt_file) is False

    def test_cannot_parse_missing_file(self, parser, tmp_path):
        """Parser returns False for non-existent files."""
        missing = tmp_path / "nonexistent.jsonl"
        assert parser.can_parse(missing) is False

    def test_cannot_parse_empty_file(self, parser, tmp_path):
        """Parser returns False for empty JSONL files."""
        empty = tmp_path / "empty.jsonl"
        empty.write_text("")
        assert parser.can_parse(empty) is False

    def test_cannot_parse_non_claude_jsonl(self, parser, tmp_path):
        """Parser rejects JSONL without Claude-specific structure."""
        path = tmp_path / "other.jsonl"
        records = [{"event": "log", "message": "something"}]
        _write_jsonl(path, records)
        assert parser.can_parse(path) is False


class TestClaudeTranscriptParserParse:
    """Tests for parse functionality."""

    def test_parse_human_and_assistant_messages(self, parser, sample_claude_jsonl):
        """Parser extracts human and assistant messages correctly."""
        messages = parser.parse(sample_claude_jsonl)
        assert len(messages) == 2

        assert messages[0].role == "human"
        assert messages[0].content == "What is 2+2?"

        assert messages[1].role == "assistant"
        assert messages[1].content == "The answer is 4."

    def test_parse_preserves_timestamps(self, parser, sample_claude_jsonl):
        """Parser preserves message timestamps."""
        messages = parser.parse(sample_claude_jsonl)
        assert messages[0].timestamp == "2026-04-17T10:00:00Z"
        assert messages[1].timestamp == "2026-04-17T10:00:01Z"

    def test_parse_returns_transcript_message_instances(self, parser, sample_claude_jsonl):
        """Parser returns TranscriptMessage instances."""
        messages = parser.parse(sample_claude_jsonl)
        for msg in messages:
            assert isinstance(msg, TranscriptMessage)

    def test_skip_unknown_record_types_gracefully(self, parser, claude_jsonl_with_unknown_types):
        """Parser skips queue-operation, progress, pr-link without crashing."""
        messages = parser.parse(claude_jsonl_with_unknown_types)
        # Only human and assistant messages should be extracted
        assert len(messages) == 2
        assert messages[0].role == "human"
        assert messages[0].content == "Hello"
        assert messages[1].role == "assistant"
        assert messages[1].content == "Hi there!"

    def test_parse_empty_file_returns_empty_list(self, parser, tmp_path):
        """Parser returns empty list for empty JSONL file."""
        empty = tmp_path / "empty.jsonl"
        empty.write_text("")
        messages = parser.parse(empty)
        assert messages == []

    def test_parse_handles_string_content_in_assistant(self, parser, tmp_path):
        """Parser handles assistant messages with plain string content."""
        records = [
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": "Plain string response",
                },
                "timestamp": "2026-04-17T10:00:00Z",
            },
        ]
        path = tmp_path / "string_content.jsonl"
        _write_jsonl(path, records)
        messages = parser.parse(path)
        assert len(messages) == 1
        assert messages[0].content == "Plain string response"

    def test_parse_handles_multi_block_assistant_content(self, parser, tmp_path):
        """Parser concatenates multiple text blocks in assistant messages."""
        records = [
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "First part. "},
                        {"type": "text", "text": "Second part."},
                    ],
                },
                "timestamp": "2026-04-17T10:00:00Z",
            },
        ]
        path = tmp_path / "multi_block.jsonl"
        _write_jsonl(path, records)
        messages = parser.parse(path)
        assert len(messages) == 1
        assert messages[0].content == "First part. Second part."

    def test_parse_skips_tool_use_blocks(self, parser, tmp_path):
        """Parser extracts text only, skipping tool_use blocks in content."""
        records = [
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "Let me check."},
                        {"type": "tool_use", "id": "tu_1", "name": "read", "input": {}},
                    ],
                },
                "timestamp": "2026-04-17T10:00:00Z",
            },
        ]
        path = tmp_path / "tool_use.jsonl"
        _write_jsonl(path, records)
        messages = parser.parse(path)
        assert len(messages) == 1
        assert messages[0].content == "Let me check."

    def test_parse_handles_human_string_content(self, parser, tmp_path):
        """Parser handles human messages with plain string content."""
        records = [
            {
                "type": "human",
                "message": {
                    "role": "user",
                    "content": "Simple question",
                },
            },
        ]
        path = tmp_path / "human_string.jsonl"
        _write_jsonl(path, records)
        messages = parser.parse(path)
        assert len(messages) == 1
        assert messages[0].role == "human"
        assert messages[0].content == "Simple question"

    def test_parse_handles_human_list_content(self, parser, tmp_path):
        """Parser handles human messages with list content blocks."""
        records = [
            {
                "type": "human",
                "message": {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Question with context"},
                    ],
                },
            },
        ]
        path = tmp_path / "human_list.jsonl"
        _write_jsonl(path, records)
        messages = parser.parse(path)
        assert len(messages) == 1
        assert messages[0].content == "Question with context"

    def test_parse_skips_malformed_json_lines(self, parser, tmp_path):
        """Parser skips lines that are not valid JSON."""
        path = tmp_path / "malformed.jsonl"
        with open(path, "w") as f:
            f.write('{"type": "human", "message": {"role": "user", "content": "Good"}}\n')
            f.write("this is not valid json\n")
            f.write(
                '{"type": "assistant", "message": {"role": "assistant",'
                ' "content": "Also good"}}\n'
            )
        messages = parser.parse(path)
        assert len(messages) == 2

    def test_parse_nonexistent_file_returns_empty(self, parser, tmp_path):
        """Parser returns empty list for non-existent file."""
        missing = tmp_path / "nonexistent.jsonl"
        messages = parser.parse(missing)
        assert messages == []

    def test_parse_system_messages(self, parser, tmp_path):
        """Parser handles system-type records if present."""
        records = [
            {
                "type": "system",
                "message": {
                    "role": "system",
                    "content": "System prompt text",
                },
            },
        ]
        path = tmp_path / "system.jsonl"
        _write_jsonl(path, records)
        messages = parser.parse(path)
        assert len(messages) == 1
        assert messages[0].role == "system"
        assert messages[0].content == "System prompt text"
