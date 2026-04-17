"""Abstract transcript parser base types.

Defines the TranscriptMessage common format and TranscriptParser abstract
interface that all provider-specific parsers must implement.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class TranscriptMessage:
    """A single message extracted from a transcript.

    Common format across all transcript providers. Provider-specific
    details are stored in the metadata dict.

    Attributes:
        role: Message role - "human", "assistant", or "system".
        content: The text content of the message.
        timestamp: ISO timestamp if available, None otherwise.
        metadata: Provider-specific metadata (e.g., model name, tool calls).
    """

    role: str
    content: str
    timestamp: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)


class TranscriptParser(ABC):
    """Abstract base class for transcript parsers.

    Each provider (Claude, GPT, etc.) implements this interface to parse
    their specific transcript format into a common TranscriptMessage list.

    Subclasses must implement:
        can_parse: Detect whether a file matches this parser's format.
        parse: Extract messages from a transcript file.
    """

    @abstractmethod
    def can_parse(self, path: Path) -> bool:
        """Detect whether the given file matches this parser's format.

        Should be lightweight (read first few lines, check structure).
        Must not raise exceptions for missing/invalid files.

        Args:
            path: Path to the transcript file.

        Returns:
            True if this parser can handle the file format.
        """

    @abstractmethod
    def parse(self, path: Path) -> list[TranscriptMessage]:
        """Parse a transcript file into a list of messages.

        Args:
            path: Path to the transcript file.

        Returns:
            List of TranscriptMessage instances extracted from the file.
            Returns empty list for missing/empty/unparseable files.
        """
