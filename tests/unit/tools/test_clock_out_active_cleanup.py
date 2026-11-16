"""Active-session cleanup in clock_out on SMB/LucidLink mounts (issue #199).

On an SMB-backed mount, deleting a file another process holds open renames it
to a hidden ``.smbdelete*`` placeholder that lasts until the last handle
closes, so the final rmdir of ``shutil.rmtree(session_dir)`` fails with
``OSError(66, 'Directory not empty')``. Local APFS cannot produce
placeholders, so the ENOTEMPTY path is driven by monkeypatching
``shutil.rmtree`` for the session directory only.

Contract:
- a short bounded in-line retry (3 attempts, 0.25s apart);
- an additive ``active_session_cleanup: "removed" | "pending"`` field, with
  ``status`` still ``"success"`` because archive and learnings succeeded;
- a later clock_out sweeps leftover ``sessions/active/<id>/`` directories that
  have no session.json, hold nothing but ``.smbdelete*`` entries (or nothing),
  and are older than a generous threshold (1h). The age guard protects the
  other machine's brand-new session between its mkdir and session.json write.
"""

import errno
import json
import logging
import os
import shutil
import time
from pathlib import Path

import pytest

from hestai_context_mcp.tools import clock_out as clock_out_module
from hestai_context_mcp.tools.clock_out import clock_out

SESSION_ID = "TESTONLY_session_cleanup199"
TWO_HOURS = 2 * 60 * 60


def _active_dir(working_dir: Path) -> Path:
    return working_dir / ".hestai" / "state" / "sessions" / "active"


def _setup_active_session(
    working_dir: Path, session_id: str = SESSION_ID, transcript_path: Path | None = None
) -> Path:
    active = _active_dir(working_dir)
    (working_dir / ".hestai" / "state" / "sessions" / "archive").mkdir(parents=True, exist_ok=True)
    session_dir = active / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "session.json").write_text(
        json.dumps(
            {
                "session_id": session_id,
                "role": "implementation-lead",
                "working_dir": str(working_dir),
                "focus": "test-focus",
                "started_at": "2026-04-17T10:00:00+00:00",
                "branch": "main",
                **({"transcript_path": str(transcript_path)} if transcript_path else {}),
            }
        )
    )
    return session_dir


def _write_transcript(path: Path) -> Path:
    record = {
        "type": "human",
        "message": {"role": "user", "content": "LEARNING_1: retry SMB deletes."},
        "timestamp": "2026-04-17T10:00:00Z",
    }
    path.write_text(json.dumps(record) + "\n")
    return path


def _leftover(working_dir: Path, name: str, entries: list[str], age_seconds: int) -> Path:
    """Create sessions/active/<name>/ holding the given file entries, aged by mtime."""
    d = _active_dir(working_dir) / name
    d.mkdir(parents=True, exist_ok=True)
    for entry in entries:
        (d / entry).write_text("held-open content")
    then = time.time() - age_seconds
    os.utime(d, (then, then))
    return d


@pytest.fixture
def no_sleep(monkeypatch):
    """Record retry delays without sleeping."""
    delays: list[float] = []
    monkeypatch.setattr(time, "sleep", lambda s: delays.append(s))
    return delays


def _enotempty_rmtree(monkeypatch, target: Path, failures: int | None):
    """Make rmtree(target) raise ENOTEMPTY `failures` times (None = always).

    Other paths use the real rmtree, so the sweep and pytest cleanup still work.
    """
    real_rmtree = shutil.rmtree
    calls = {"target": 0}

    def fake(path, *args, **kwargs):
        if Path(path) == target:
            calls["target"] += 1
            if failures is None or calls["target"] <= failures:
                raise OSError(errno.ENOTEMPTY, "Directory not empty", str(path))
        return real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(clock_out_module.shutil, "rmtree", fake)
    return calls


class TestActiveSessionRemoval:
    """Bounded retry and the active_session_cleanup report."""

    def test_clean_removal_reports_removed(self, tmp_path, no_sleep):
        session_dir = _setup_active_session(tmp_path)

        result = clock_out(session_id=SESSION_ID, working_dir=str(tmp_path))

        assert result["status"] == "success"
        assert result["active_session_cleanup"] == "removed"
        assert not session_dir.exists()
        assert no_sleep == []

    def test_transient_enotempty_is_retried_then_removed(self, tmp_path, monkeypatch, no_sleep):
        session_dir = _setup_active_session(tmp_path)
        calls = _enotempty_rmtree(monkeypatch, session_dir, failures=2)

        result = clock_out(session_id=SESSION_ID, working_dir=str(tmp_path))

        assert result["status"] == "success"
        assert result["active_session_cleanup"] == "removed"
        assert calls["target"] == 3
        assert no_sleep == [0.25, 0.25]
        assert not session_dir.exists()

    def test_persistent_enotempty_reports_pending_and_still_succeeds(
        self, tmp_path, monkeypatch, no_sleep, caplog
    ):
        transcript = _write_transcript(tmp_path / "transcript.jsonl")
        session_dir = _setup_active_session(tmp_path, transcript_path=transcript)
        calls = _enotempty_rmtree(monkeypatch, session_dir, failures=None)

        with caplog.at_level(logging.WARNING, logger="hestai_context_mcp.tools.clock_out"):
            result = clock_out(session_id=SESSION_ID, working_dir=str(tmp_path))

        assert result["status"] == "success"
        assert result["active_session_cleanup"] == "pending"
        assert calls["target"] == 3  # bounded: no more than 3 attempts
        assert no_sleep == [0.25, 0.25]  # no sleep after the last attempt
        assert session_dir.exists()
        # The archive and learnings index were still written.
        assert result["archive_path"] is not None
        assert Path(result["archive_path"]).exists()
        assert (tmp_path / ".hestai" / "state" / "learnings-index.jsonl").exists()
        assert any(r.levelno == logging.WARNING for r in caplog.records)

    def test_directory_already_gone_counts_as_removed(self, tmp_path, monkeypatch, no_sleep):
        """If another process removed the directory first, the cleanup is done."""
        session_dir = _setup_active_session(tmp_path)
        real_rmtree = shutil.rmtree

        def vanish_then_fail(path, *args, **kwargs):
            if Path(path) == session_dir:
                real_rmtree(path)
                raise FileNotFoundError(errno.ENOENT, "No such file or directory", str(path))
            return real_rmtree(path, *args, **kwargs)

        monkeypatch.setattr(clock_out_module.shutil, "rmtree", vanish_then_fail)

        result = clock_out(session_id=SESSION_ID, working_dir=str(tmp_path))

        assert result["active_session_cleanup"] == "removed"
        assert no_sleep == []


class TestLeftoverActiveDirectorySweep:
    """A later clock_out removes only leftovers that cannot be a live session."""

    def test_old_empty_leftover_is_swept(self, tmp_path, no_sleep):
        _setup_active_session(tmp_path)
        leftover = _leftover(tmp_path, "old-empty", [], TWO_HOURS)

        clock_out(session_id=SESSION_ID, working_dir=str(tmp_path))

        assert not leftover.exists()

    def test_old_leftover_with_only_smbdelete_placeholders_is_swept(self, tmp_path, no_sleep):
        _setup_active_session(tmp_path)
        leftover = _leftover(
            tmp_path,
            "old-placeholders",
            [".smbdeleteAAA200000918", ".smbdeleteBBB200000919"],
            TWO_HOURS,
        )

        clock_out(session_id=SESSION_ID, working_dir=str(tmp_path))

        assert not leftover.exists()

    def test_old_directory_with_session_json_is_kept(self, tmp_path, no_sleep):
        """A directory with session.json is a session (maybe the other machine's)."""
        _setup_active_session(tmp_path)
        live = _leftover(tmp_path, "old-live", ["session.json"], TWO_HOURS)

        clock_out(session_id=SESSION_ID, working_dir=str(tmp_path))

        assert (live / "session.json").exists()

    def test_young_empty_directory_is_kept(self, tmp_path, no_sleep):
        """Guard: the other machine's new session between mkdir and session.json write."""
        _setup_active_session(tmp_path)
        young = _leftover(tmp_path, "young-empty", [], 60)

        clock_out(session_id=SESSION_ID, working_dir=str(tmp_path))

        assert young.exists()

    def test_young_placeholder_directory_is_kept(self, tmp_path, no_sleep):
        _setup_active_session(tmp_path)
        young = _leftover(tmp_path, "young-placeholders", [".smbdeleteCCC1"], 60)

        clock_out(session_id=SESSION_ID, working_dir=str(tmp_path))

        assert young.exists()

    def test_old_directory_with_other_content_is_kept(self, tmp_path, no_sleep):
        """Anything other than .smbdelete* placeholders is not ours to delete."""
        _setup_active_session(tmp_path)
        other = _leftover(tmp_path, "old-other", [".smbdeleteDDD1", "notes.txt"], TWO_HOURS)

        clock_out(session_id=SESSION_ID, working_dir=str(tmp_path))

        assert (other / "notes.txt").exists()

    def test_old_directory_with_subdirectory_is_kept(self, tmp_path, no_sleep):
        _setup_active_session(tmp_path)
        nested = _leftover(tmp_path, "old-nested", [], TWO_HOURS)
        (nested / ".smbdeleteDIR").mkdir()
        then = time.time() - TWO_HOURS
        os.utime(nested, (then, then))

        clock_out(session_id=SESSION_ID, working_dir=str(tmp_path))

        assert (nested / ".smbdeleteDIR").is_dir()

    def test_symlink_and_plain_file_in_active_are_ignored(self, tmp_path, no_sleep):
        _setup_active_session(tmp_path)
        target = tmp_path / "elsewhere"
        target.mkdir()
        link = _active_dir(tmp_path) / "linked"
        link.symlink_to(target)
        stray = _active_dir(tmp_path) / "stray-file"
        stray.write_text("x")
        then = time.time() - TWO_HOURS
        os.utime(link, (then, then), follow_symlinks=False)
        os.utime(stray, (then, then))

        clock_out(session_id=SESSION_ID, working_dir=str(tmp_path))

        assert link.is_symlink() and target.is_dir()
        assert stray.read_text() == "x"

    def test_own_pending_directory_is_not_swept_in_the_same_call(
        self, tmp_path, monkeypatch, no_sleep
    ):
        """The session just left pending is reported, not deleted behind the report."""
        session_dir = _setup_active_session(tmp_path)
        real_rmtree = shutil.rmtree

        def smb_rmtree(path, *args, **kwargs):
            """SMB shape: session.json becomes a held-open placeholder, rmdir fails."""
            if Path(path) == session_dir:
                held = session_dir / "session.json"
                if held.exists():
                    held.rename(session_dir / ".smbdeleteOWN0001")
                then = time.time() - TWO_HOURS  # old enough that only exclusion saves it
                os.utime(session_dir, (then, then))
                raise OSError(errno.ENOTEMPTY, "Directory not empty", str(path))
            return real_rmtree(path, *args, **kwargs)

        monkeypatch.setattr(clock_out_module.shutil, "rmtree", smb_rmtree)

        result = clock_out(session_id=SESSION_ID, working_dir=str(tmp_path))

        assert result["active_session_cleanup"] == "pending"
        assert (session_dir / ".smbdeleteOWN0001").exists()

    def test_sweep_failure_does_not_fail_clock_out(self, tmp_path, monkeypatch, no_sleep):
        """A leftover that is still held open stays for a later sweep."""
        _setup_active_session(tmp_path)
        leftover = _leftover(tmp_path, "old-held", [".smbdeleteEEE1"], TWO_HOURS)
        _enotempty_rmtree(monkeypatch, leftover, failures=None)

        result = clock_out(session_id=SESSION_ID, working_dir=str(tmp_path))

        assert result["status"] == "success"
        assert result["active_session_cleanup"] == "removed"
        assert leftover.exists()

    def test_error_return_does_not_sweep(self, tmp_path, no_sleep):
        """Only a successful clock_out sweeps; an unknown session id touches nothing."""
        _active_dir(tmp_path).mkdir(parents=True)
        leftover = _leftover(tmp_path, "old-empty", [], TWO_HOURS)

        result = clock_out(session_id="TESTONLY_missing", working_dir=str(tmp_path))

        assert result["status"] == "error"
        assert leftover.exists()
