"""Tests for transcript parser base types and abstract interface.

RED phase: These tests define the expected behavior of TranscriptMessage
and TranscriptParser before any implementation exists.
"""

import pytest

from hestai_context_mcp.core.transcript.base import TranscriptMessage, TranscriptParser


class TestTranscriptMessage:
    """Tests for the TranscriptMessage dataclass."""

    def test_create_with_required_fields(self):
        """TranscriptMessage can be created with role and content."""
        msg = TranscriptMessage(role="human", content="Hello")
        assert msg.role == "human"
        assert msg.content == "Hello"

    def test_timestamp_defaults_to_none(self):
        """Timestamp should default to None when not provided."""
        msg = TranscriptMessage(role="assistant", content="Reply")
        assert msg.timestamp is None

    def test_metadata_defaults_to_empty_dict(self):
        """Metadata should default to an empty dict when not provided."""
        msg = TranscriptMessage(role="system", content="System prompt")
        assert msg.metadata == {}

    def test_create_with_all_fields(self):
        """TranscriptMessage accepts all optional fields."""
        msg = TranscriptMessage(
            role="assistant",
            content="Response text",
            timestamp="2026-04-17T10:00:00Z",
            metadata={"model": "claude-4"},
        )
        assert msg.role == "assistant"
        assert msg.content == "Response text"
        assert msg.timestamp == "2026-04-17T10:00:00Z"
        assert msg.metadata == {"model": "claude-4"}

    def test_valid_roles(self):
        """TranscriptMessage supports human, assistant, and system roles."""
        for role in ("human", "assistant", "system"):
            msg = TranscriptMessage(role=role, content="test")
            assert msg.role == role

    def test_metadata_is_independent_per_instance(self):
        """Each instance should get its own metadata dict (no mutable default sharing)."""
        msg1 = TranscriptMessage(role="human", content="a")
        msg2 = TranscriptMessage(role="human", content="b")
        msg1.metadata["key"] = "value"
        assert "key" not in msg2.metadata


class TestTranscriptParserAbstract:
    """Tests for the TranscriptParser abstract base class."""

    def test_cannot_instantiate_directly(self):
        """TranscriptParser is abstract and cannot be instantiated."""
        with pytest.raises(TypeError):
            TranscriptParser()  # type: ignore[abstract]

    def test_subclass_must_implement_can_parse(self):
        """A subclass that only implements parse should fail to instantiate."""

        class IncompleteParser(TranscriptParser):
            def parse(self, path):  # type: ignore[override]
                return []

        with pytest.raises(TypeError):
            IncompleteParser()  # type: ignore[abstract]

    def test_subclass_must_implement_parse(self):
        """A subclass that only implements can_parse should fail to instantiate."""

        class IncompleteParser(TranscriptParser):
            def can_parse(self, path):  # type: ignore[override]
                return True

        with pytest.raises(TypeError):
            IncompleteParser()  # type: ignore[abstract]

    def test_complete_subclass_can_instantiate(self):
        """A subclass implementing both methods can be instantiated."""

        class ConcreteParser(TranscriptParser):
            def can_parse(self, path):  # type: ignore[override]
                return True

            def parse(self, path):  # type: ignore[override]
                return []

        parser = ConcreteParser()
        assert parser.can_parse("anything") is True
        assert parser.parse("anything") == []
