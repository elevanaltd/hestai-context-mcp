"""Cubic rework cycle 2 — Finding #9 (P2, outbox.py:169).

RED-first test: ``OutboxStore.list_entries`` must raise ``OutboxParseError``
for ALL parse failures, not just JSONDecodeError. ``read_text(encoding=
"utf-8")`` raises UnicodeDecodeError when the file contains non-UTF-8
bytes. The current ``except (OSError, json.JSONDecodeError)`` misses
this case and the UnicodeDecodeError leaks unstructured (PROD::I4
STRUCTURED_RETURN_SHAPES violation, R10 fail-closed).
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.mark.unit
class TestOutboxNonUtf8DecodeFailsStructured:
    """Cubic P2 #9: UnicodeDecodeError must be wrapped as OutboxParseError."""

    def test_non_utf8_bytes_raise_outbox_parse_error_not_unicode_decode_error(
        self, tmp_path: Path
    ) -> None:
        from hestai_context_mcp.storage.outbox import OutboxParseError, OutboxStore

        store = OutboxStore(working_dir=tmp_path)
        # Create a non-UTF-8 outbox entry — invalid byte 0xFF in standalone.
        store.root.mkdir(parents=True, exist_ok=True)
        bad = store.root / "bad.json"
        bad.write_bytes(b"\xff\xfe\xfd not utf-8")

        # Must wrap the decode failure structurally; no UnicodeDecodeError leak.
        with pytest.raises(OutboxParseError) as excinfo:
            store.list_entries()

        assert excinfo.value.code == "outbox_entry_parse_failed"
        assert str(bad) == excinfo.value.path
