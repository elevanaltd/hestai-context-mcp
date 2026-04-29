"""ADR-0013 PSS Durable Outbound Queue — R7 status-only B1 implementation.

Owns ``.hestai/state/portable/outbox/{artifact_id}.json``: when an adapter
publish fails after a successful local archive, clock_out enqueues a
durable status record so the unpublished-memory state is visible to
operators and to subsequent ``clock_out`` / ``clock_in`` calls.

Binding rulings enforced here:

- RISK_008 + G7: B1 ships **status only** — no retry/drain orchestration.
  Future ADR may add a Publish Portable State tool. ``retry_count`` is
  recorded so a future driver can advance it; B1 never bumps it.
- A2 (CIV): clock_out emits a ``portable_publication`` status block even
  when publish is skipped. The store exposes
  :meth:`unpublished_memory_exists` for that surface.
- R7: queue path is one JSON-per-artifact under
  ``.hestai/state/portable/outbox/``. The queue is LOCAL_MUTABLE.
- R10: parse errors raise :class:`OutboxParseError` instead of silently
  skipping malformed entries.
- get_context purity: the store performs filesystem writes only via
  :meth:`enqueue`. Pure read APIs (``list_entries``,
  ``unpublished_memory_exists``) never create the outbox directory.

PROD::I5: ``get_context`` never imports this module. The clock_in /
clock_out tools are the only callers that may write here.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hestai_context_mcp.storage.types import (
    PublishAck,
    PublishStatus,
    StateClassification,
)


@dataclass(frozen=True, slots=True)
class OutboxParseError(Exception):
    """Raised when an outbox JSON entry cannot be parsed (R10 fail-closed)."""

    code: str
    message: str
    path: str

    def __post_init__(self) -> None:  # pragma: no cover - exception side-effect
        Exception.__init__(self, self.message)


def _serialize_ack(ack: PublishAck) -> dict[str, Any]:
    return {
        "artifact_id": ack.artifact_id,
        "identity": {
            "project_id": ack.identity.project_id,
            "workspace_id": ack.identity.workspace_id,
            "user_id": ack.identity.user_id,
            "state_schema_version": ack.identity.state_schema_version,
            "carrier_namespace": ack.identity.carrier_namespace,
        },
        "carrier_namespace": ack.carrier_namespace,
        "sequence_id": ack.sequence_id,
        "status": ack.status.value,
        "durable_carrier_receipt": ack.durable_carrier_receipt,
        "queued_path": ack.queued_path,
        "published_at": ack.published_at.isoformat() if ack.published_at else None,
    }


class OutboxStore:
    """Durable outbound queue for unpublished Portable Memory Artifacts.

    Args:
        working_dir: Project root containing ``.hestai/state/`` (or its
            symlink). The store writes only under
            ``working_dir/.hestai/state/portable/outbox/``.
    """

    classification: StateClassification = StateClassification.LOCAL_MUTABLE

    def __init__(self, working_dir: str | Path) -> None:
        self._working_dir = Path(working_dir).resolve()

    @property
    def root(self) -> Path:
        """Outbox root: ``.hestai/state/portable/outbox/`` (R7)."""

        return self._working_dir / ".hestai" / "state" / "portable" / "outbox"

    # ---- Write API -------------------------------------------------------

    def enqueue(
        self,
        *,
        ack: PublishAck,
        error_code: str,
        error_message: str,
    ) -> Path:
        """Enqueue a durable status record for an unpublished artifact.

        The on-disk shape is the union of the PublishAck payload, the
        original error reason, and B1 retry metadata
        (``retry_count``=0). Writes are atomic (tempfile + os.replace).

        Args:
            ack: Adapter PublishAck; ``status`` should be FAILED for the
                outbox path. Other statuses are still recorded so
                operators have an observable trail.
            error_code: Stable code from the failing adapter call.
            error_message: Human-readable failure description.

        Returns:
            Final on-disk path of the enqueued JSON entry.
        """

        self.root.mkdir(parents=True, exist_ok=True)
        target = self.root / f"{ack.artifact_id}.json"
        entry: dict[str, Any] = {
            **_serialize_ack(ack),
            "error_code": error_code,
            "error_message": error_message,
            "enqueued_at": datetime.now(UTC).isoformat(),
            "retry_count": 0,  # B1 never advances; future ADR owns retries.
        }

        fd, tmp_name = tempfile.mkstemp(dir=str(self.root), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(entry, f, sort_keys=True, separators=(",", ":"))
            os.replace(tmp_name, target)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp_name)
            raise
        return target

    # ---- Read API (no side-effects) --------------------------------------

    def unpublished_memory_exists(self) -> bool:
        """True iff at least one entry remains in the outbox.

        Pure read: does not create the outbox directory.
        """

        if not self.root.exists():
            return False
        return any(entry.is_file() and entry.suffix == ".json" for entry in self.root.iterdir())

    def list_entries(self) -> list[dict[str, Any]]:
        """List outbox entries deterministically by artifact_id.

        Raises:
            OutboxParseError: when any on-disk entry cannot be parsed.
        """

        if not self.root.exists():
            return []
        entries: list[dict[str, Any]] = []
        for path in sorted(self.root.glob("*.json")):
            try:
                entries.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError) as e:
                # Cubic P2 #9: ``ValueError`` is the structural superset:
                # ``json.JSONDecodeError`` is a ValueError subclass, and
                # ``UnicodeDecodeError`` (raised by read_text on non-UTF-8
                # bytes) is also a ValueError subclass. Catching ValueError
                # ensures every decode failure is wrapped as a structured
                # OutboxParseError per R10 fail-closed and PROD::I4
                # STRUCTURED_RETURN_SHAPES.
                raise OutboxParseError(
                    code="outbox_entry_parse_failed",
                    message=f"failed to parse outbox entry {path}: {e}",
                    path=str(path),
                ) from e
        entries.sort(key=lambda d: str(d.get("artifact_id", "")))
        return entries

    # ---- Convenience for clock_out (A2) ----------------------------------

    @staticmethod
    def skipped_publish_status(
        *, reason: str, error_code: str = "publish_skipped"
    ) -> dict[str, Any]:
        """Build the structured A2 skip-publish status record.

        Used by clock_out when publication is intentionally skipped (e.g.,
        no transcript / provenance unavailable). The record carries no
        artifact id because nothing was built; ``status`` is ``failed``
        from the adapter point of view but the message reason explains
        it was a skip rather than an I/O failure.
        """

        return {
            "status": PublishStatus.FAILED.value,
            "artifact_id": None,
            "sequence_id": None,
            "carrier_namespace": None,
            "queued_path": None,
            "error_code": error_code,
            "error_message": reason,
        }


__all__ = [
    "OutboxParseError",
    "OutboxStore",
]
