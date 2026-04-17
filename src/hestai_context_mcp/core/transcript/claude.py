"""Claude transcript parser.

Handles current Claude JSONL transcript format, robustly skipping
unknown record types (queue-operation, progress, pr-link, etc.)
that caused the legacy ClaudeJsonlLens to crash.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from hestai_context_mcp.core.transcript.base import TranscriptMessage, TranscriptParser

logger = logging.getLogger(__name__)

# Claude JSONL record types that contain messages we want to extract
_MESSAGE_TYPES = frozenset({"human", "assistant", "system"})


class ClaudeTranscriptParser(TranscriptParser):
    """Parser for Claude's JSONL transcript format.

    Handles the current Claude JSONL structure where each line is a JSON
    object with a "type" field. Message records have a nested "message"
    object containing role and content.

    Gracefully skips unknown record types (queue-operation, progress,
    pr-link, etc.) without crashing -- the key fix over legacy ClaudeJsonlLens.
    """

    def can_parse(self, path: Path) -> bool:
        """Detect whether the file is a Claude JSONL transcript.

        Checks that the file exists, has content, and the first valid JSON
        line contains Claude-specific structure (type + message fields).

        Args:
            path: Path to the transcript file.

        Returns:
            True if the file appears to be Claude JSONL format.
        """
        if not path.exists() or not path.is_file():
            return False

        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        return False

                    # Claude JSONL has "type" field; message records have "message" sub-object
                    if not isinstance(record, dict) or "type" not in record:
                        return False

                    # Check if any record type matches Claude's known types
                    # (including non-message types like queue-operation, progress)
                    record_type = record.get("type", "")
                    if record_type in _MESSAGE_TYPES:
                        return "message" in record
                    # Known non-message Claude types also confirm Claude format
                    if record_type in {
                        "queue-operation",
                        "progress",
                        "pr-link",
                        "tool_result",
                        "tool_use",
                    }:
                        return True
                    # Has type field but unknown -- still looks like Claude format
                    # if it has proper JSON structure
                    return True

        except OSError:
            return False

        # Empty file
        return False

    def parse(self, path: Path) -> list[TranscriptMessage]:
        """Parse a Claude JSONL transcript into TranscriptMessage list.

        Extracts human, assistant, and system messages. Skips unknown
        record types gracefully. Handles both string and list content
        formats in messages.

        Args:
            path: Path to the Claude JSONL transcript file.

        Returns:
            List of TranscriptMessage instances. Empty list if file
            is missing, empty, or unparseable.
        """
        if not path.exists() or not path.is_file():
            return []

        messages: list[TranscriptMessage] = []

        try:
            with open(path, encoding="utf-8") as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue

                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        logger.debug("Skipping malformed JSON at line %d", line_num)
                        continue

                    if not isinstance(record, dict):
                        continue

                    record_type = record.get("type")
                    if record_type not in _MESSAGE_TYPES:
                        # Skip unknown record types gracefully
                        continue

                    message_data = record.get("message")
                    if not isinstance(message_data, dict):
                        continue

                    content = self._extract_content(message_data.get("content"))
                    if content is None:
                        continue

                    # Map Claude role to our role convention
                    role = self._map_role(record_type, message_data.get("role", ""))

                    messages.append(
                        TranscriptMessage(
                            role=role,
                            content=content,
                            timestamp=record.get("timestamp"),
                            metadata={"provider": "claude", "record_type": record_type},
                        )
                    )

        except OSError as e:
            logger.warning("Could not read transcript file %s: %s", path, e)

        return messages

    def _extract_content(self, content: object) -> str | None:
        """Extract text content from Claude's message content field.

        Claude messages can have content as:
        - A plain string
        - A list of content blocks (each with "type" and "text" fields)

        Args:
            content: The raw content field from the message.

        Returns:
            Extracted text string, or None if no text content found.
        """
        if isinstance(content, str):
            return content

        if isinstance(content, list):
            text_parts: list[str] = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text = block.get("text", "")
                    if text:
                        text_parts.append(text)
            return "".join(text_parts) if text_parts else None

        return None

    def _map_role(self, record_type: str, message_role: str) -> str:
        """Map Claude record type and message role to our role convention.

        Args:
            record_type: The Claude record type (human, assistant, system).
            message_role: The role field from the message object.

        Returns:
            Normalized role string: "human", "assistant", or "system".
        """
        # Record type is more reliable than message role for Claude
        if record_type in _MESSAGE_TYPES:
            return record_type
        # Fallback to message role mapping
        role_map = {"user": "human", "assistant": "assistant", "system": "system"}
        return role_map.get(message_role, record_type)
