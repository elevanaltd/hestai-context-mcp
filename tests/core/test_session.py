"""Tests for SessionManager - session creation, conflict detection, FAST layer."""

import json

from hestai_context_mcp.core.session import SessionManager


class TestSessionCreation:
    """Test session directory and metadata creation."""

    def test_creates_session_directory(self, tmp_path):
        """Session creation creates the session directory."""
        mgr = SessionManager(str(tmp_path))
        result = mgr.create_session(role="implementation-lead", focus="general")
        session_dir = tmp_path / ".hestai" / "state" / "sessions" / "active" / result["session_id"]
        assert session_dir.exists()

    def test_writes_session_json(self, tmp_path):
        """Session creation writes session.json with correct fields."""
        mgr = SessionManager(str(tmp_path))
        result = mgr.create_session(role="implementation-lead", focus="my-task")
        session_file = (
            tmp_path
            / ".hestai"
            / "state"
            / "sessions"
            / "active"
            / result["session_id"]
            / "session.json"
        )
        assert session_file.exists()
        data = json.loads(session_file.read_text())
        assert data["role"] == "implementation-lead"
        assert data["focus"] == "my-task"
        assert "session_id" in data
        assert "started_at" in data

    def test_session_id_is_uuid_format(self, tmp_path):
        """Session ID is a valid UUID string."""
        import uuid

        mgr = SessionManager(str(tmp_path))
        result = mgr.create_session(role="test-role", focus="general")
        # Should not raise
        uuid.UUID(result["session_id"])

    def test_returns_session_id(self, tmp_path):
        """create_session returns dict with session_id."""
        mgr = SessionManager(str(tmp_path))
        result = mgr.create_session(role="test-role", focus="general")
        assert "session_id" in result
        assert isinstance(result["session_id"], str)


class TestFocusConflictDetection:
    """Test detection of sessions with conflicting focus areas."""

    def test_no_conflict_when_no_active_sessions(self, tmp_path):
        """No conflict when active directory is empty."""
        mgr = SessionManager(str(tmp_path))
        conflicts = mgr.detect_focus_conflicts("my-focus", "current-id")
        assert conflicts == []

    def test_detects_same_focus_conflict(self, tmp_path):
        """Detects conflict when another session has the same focus."""
        # Create an existing active session
        active_dir = tmp_path / ".hestai" / "state" / "sessions" / "active"
        existing_session = active_dir / "existing-session-id"
        existing_session.mkdir(parents=True)
        (existing_session / "session.json").write_text(
            json.dumps(
                {
                    "session_id": "existing-session-id",
                    "role": "other-role",
                    "focus": "same-focus",
                }
            )
        )

        mgr = SessionManager(str(tmp_path))
        conflicts = mgr.detect_focus_conflicts("same-focus", "new-session-id")
        assert len(conflicts) == 1
        assert conflicts[0] == "same-focus"

    def test_no_conflict_with_different_focus(self, tmp_path):
        """No conflict when other sessions have different focuses."""
        active_dir = tmp_path / ".hestai" / "state" / "sessions" / "active"
        existing_session = active_dir / "existing-session-id"
        existing_session.mkdir(parents=True)
        (existing_session / "session.json").write_text(
            json.dumps(
                {
                    "session_id": "existing-session-id",
                    "role": "other-role",
                    "focus": "different-focus",
                }
            )
        )

        mgr = SessionManager(str(tmp_path))
        conflicts = mgr.detect_focus_conflicts("my-focus", "new-session-id")
        assert conflicts == []

    def test_excludes_own_session_from_conflict_check(self, tmp_path):
        """Does not report conflict with the current session itself."""
        active_dir = tmp_path / ".hestai" / "state" / "sessions" / "active"
        own_session = active_dir / "my-session-id"
        own_session.mkdir(parents=True)
        (own_session / "session.json").write_text(
            json.dumps(
                {
                    "session_id": "my-session-id",
                    "role": "my-role",
                    "focus": "same-focus",
                }
            )
        )

        mgr = SessionManager(str(tmp_path))
        conflicts = mgr.detect_focus_conflicts("same-focus", "my-session-id")
        assert conflicts == []

    def test_handles_corrupted_session_json(self, tmp_path):
        """Gracefully handles corrupted session.json files."""
        active_dir = tmp_path / ".hestai" / "state" / "sessions" / "active"
        bad_session = active_dir / "bad-session"
        bad_session.mkdir(parents=True)
        (bad_session / "session.json").write_text("not valid json")

        mgr = SessionManager(str(tmp_path))
        # Should not raise
        conflicts = mgr.detect_focus_conflicts("some-focus", "new-id")
        assert conflicts == []


class TestGetActiveSessions:
    """Test listing active session focuses."""

    def test_returns_empty_when_no_sessions(self, tmp_path):
        """Returns empty list when no active sessions exist."""
        mgr = SessionManager(str(tmp_path))
        result = mgr.get_active_session_focuses()
        assert result == []

    def test_returns_focuses_of_active_sessions(self, tmp_path):
        """Returns focus values from all active sessions."""
        active_dir = tmp_path / ".hestai" / "state" / "sessions" / "active"
        for i, focus in enumerate(["task-a", "task-b"]):
            session_dir = active_dir / f"session-{i}"
            session_dir.mkdir(parents=True)
            (session_dir / "session.json").write_text(
                json.dumps({"session_id": f"session-{i}", "focus": focus})
            )

        mgr = SessionManager(str(tmp_path))
        result = mgr.get_active_session_focuses()
        assert "task-a" in result
        assert "task-b" in result


class TestContextPathDiscovery:
    """Test discovery of context OCTAVE files."""

    def test_discovers_existing_context_files(self, tmp_path):
        """Finds OCTAVE files that exist in .hestai/state/context/."""
        context_dir = tmp_path / ".hestai" / "state" / "context"
        context_dir.mkdir(parents=True)
        (context_dir / "PROJECT-CONTEXT.oct.md").write_text("test")

        mgr = SessionManager(str(tmp_path))
        paths = mgr.discover_context_paths()
        assert any("PROJECT-CONTEXT.oct.md" in p for p in paths)

    def test_skips_missing_context_files(self, tmp_path):
        """Does not include files that don't exist."""
        mgr = SessionManager(str(tmp_path))
        paths = mgr.discover_context_paths()
        # Should not include any standard files since none exist
        assert not any("PROJECT-CONTEXT.oct.md" in p for p in paths)

    def test_discovers_north_star(self, tmp_path):
        """Finds North Star file in .hestai/north-star/."""
        ns_dir = tmp_path / ".hestai" / "north-star"
        ns_dir.mkdir(parents=True)
        (ns_dir / "000-MCP-PRODUCT-NORTH-STAR.oct.md").write_text("test")

        mgr = SessionManager(str(tmp_path))
        paths = mgr.discover_context_paths()
        assert any("NORTH-STAR" in p for p in paths)

    def test_prefers_oct_md_over_md_for_north_star(self, tmp_path):
        """Prefers .oct.md extension over .md for North Star."""
        ns_dir = tmp_path / ".hestai" / "north-star"
        ns_dir.mkdir(parents=True)
        (ns_dir / "000-MCP-PRODUCT-NORTH-STAR.oct.md").write_text("octave version")
        (ns_dir / "000-MCP-PRODUCT-NORTH-STAR.md").write_text("plain version")

        mgr = SessionManager(str(tmp_path))
        paths = mgr.discover_context_paths()
        ns_paths = [p for p in paths if "NORTH-STAR" in p]
        assert len(ns_paths) == 1
        assert ns_paths[0].endswith(".oct.md")


class TestFASTLayer:
    """Test FAST layer file writing during session creation."""

    def test_writes_current_focus(self, tmp_path):
        """Session creation writes current-focus.oct.md."""
        mgr = SessionManager(str(tmp_path))
        mgr.create_session(role="test-role", focus="my-focus", branch="main")
        focus_file = tmp_path / ".hestai" / "state" / "context" / "state" / "current-focus.oct.md"
        assert focus_file.exists()
        content = focus_file.read_text()
        assert "test-role" in content
        assert "my-focus" in content

    def test_writes_checklist(self, tmp_path):
        """Session creation writes checklist.oct.md."""
        mgr = SessionManager(str(tmp_path))
        mgr.create_session(role="test-role", focus="my-focus")
        checklist_file = tmp_path / ".hestai" / "state" / "context" / "state" / "checklist.oct.md"
        assert checklist_file.exists()

    def test_writes_blockers(self, tmp_path):
        """Session creation writes blockers.oct.md."""
        mgr = SessionManager(str(tmp_path))
        mgr.create_session(role="test-role", focus="my-focus")
        blockers_file = tmp_path / ".hestai" / "state" / "context" / "state" / "blockers.oct.md"
        assert blockers_file.exists()

    def test_preserves_existing_blockers(self, tmp_path):
        """Existing blockers are preserved during new session creation."""
        state_dir = tmp_path / ".hestai" / "state" / "context" / "state"
        state_dir.mkdir(parents=True)
        (state_dir / "blockers.oct.md").write_text("""===BLOCKERS===
META:
  TYPE::FAST_BLOCKERS
  SESSION::"old-session"
ACTIVE:
  blocker_001:
    DESCRIPTION::Something is broken
===END===
""")

        mgr = SessionManager(str(tmp_path))
        mgr.create_session(role="test-role", focus="my-focus")
        content = (state_dir / "blockers.oct.md").read_text()
        assert "Something is broken" in content


class TestEnsureHestaiStructure:
    """Test .hestai/ directory structure creation with three-tier symlink convention."""

    def test_creates_structure_when_missing(self, tmp_path):
        """Creates full three-tier structure: .hestai/, .hestai-state/, and symlink."""
        mgr = SessionManager(str(tmp_path))
        status = mgr.ensure_hestai_structure()
        assert status == "created"

        # .hestai/ committed governance exists
        assert (tmp_path / ".hestai").is_dir()
        assert (tmp_path / ".hestai" / "north-star").is_dir()

        # .hestai-state/ uncommitted working state exists with subdirs
        assert (tmp_path / ".hestai-state").is_dir()
        assert (tmp_path / ".hestai-state" / "sessions" / "active").is_dir()
        assert (tmp_path / ".hestai-state" / "sessions" / "archive").is_dir()
        assert (tmp_path / ".hestai-state" / "context").is_dir()
        assert (tmp_path / ".hestai-state" / "context" / "state").is_dir()

        # .hestai/state is a symlink to ../.hestai-state
        state_link = tmp_path / ".hestai" / "state"
        assert state_link.is_symlink()
        assert state_link.resolve() == (tmp_path / ".hestai-state").resolve()

    def test_returns_present_when_exists_and_creates_symlink(self, tmp_path):
        """Returns 'present' when .hestai/ exists, creates symlink if missing."""
        (tmp_path / ".hestai").mkdir()
        mgr = SessionManager(str(tmp_path))
        status = mgr.ensure_hestai_structure()
        assert status == "present"

        # Symlink must still be created
        state_link = tmp_path / ".hestai" / "state"
        assert state_link.is_symlink()
        assert (tmp_path / ".hestai-state" / "sessions" / "active").is_dir()

    def test_leaves_existing_symlink_alone(self, tmp_path):
        """Does not recreate symlink if .hestai/state is already a valid symlink."""
        # Pre-create the three-tier structure
        (tmp_path / ".hestai").mkdir()
        (tmp_path / ".hestai-state").mkdir()
        (tmp_path / ".hestai" / "state").symlink_to("../.hestai-state")

        mgr = SessionManager(str(tmp_path))
        status = mgr.ensure_hestai_structure()
        assert status == "present"

        # Symlink is still there, pointing to the same target
        state_link = tmp_path / ".hestai" / "state"
        assert state_link.is_symlink()
        assert state_link.resolve() == (tmp_path / ".hestai-state").resolve()

    def test_state_dir_accessible_through_symlink(self, tmp_path):
        """Session directories are accessible via .hestai/state/ symlink path."""
        mgr = SessionManager(str(tmp_path))
        mgr.ensure_hestai_structure()

        # Write through symlink path, verify in real path
        active_via_link = tmp_path / ".hestai" / "state" / "sessions" / "active"
        active_real = tmp_path / ".hestai-state" / "sessions" / "active"
        assert active_via_link.resolve() == active_real.resolve()
        assert active_via_link.is_dir()
