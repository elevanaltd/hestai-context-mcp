"""Session management: Handles session lifecycle operations.

Manages session creation, context path discovery, focus conflict detection,
and FAST layer file management.

Harvested from legacy hestai-mcp clock_in.py and fast_layer.py.
"""

import json
import logging
import os
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Standard OCTAVE context files to discover
STANDARD_CONTEXT_FILES = [
    "PROJECT-CONTEXT.oct.md",
    "PROJECT-ROADMAP.oct.md",
    "PROJECT-CHECKLIST.oct.md",
    "PROJECT-HISTORY.oct.md",
    "context-negatives.oct.md",
]


class SessionManager:
    """Manages agent session lifecycle.

    Handles session creation, tracking, context discovery, conflict detection,
    and FAST layer management.
    """

    def __init__(self, working_dir: str) -> None:
        """Initialize the session manager.

        Args:
            working_dir: Project working directory path.
        """
        self.working_dir = Path(working_dir).resolve()

    def create_session(
        self,
        role: str,
        focus: str,
        branch: str = "unknown",
    ) -> dict[str, Any]:
        """Create a new session directory and metadata.

        Creates the session directory under .hestai/state/sessions/active/{uuid}/
        and writes session.json with session metadata. Also updates FAST layer files.

        Args:
            role: Agent role name.
            focus: Resolved focus value.
            branch: Current git branch.

        Returns:
            Dict with session_id and metadata.
        """
        # Ensure directory structure exists
        self.ensure_hestai_structure()

        session_id = str(uuid.uuid4())
        active_dir = self.working_dir / ".hestai" / "state" / "sessions" / "active"
        session_dir = active_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)

        session_data = {
            "session_id": session_id,
            "role": role,
            "working_dir": str(self.working_dir),
            "focus": focus,
            "started_at": datetime.now(UTC).isoformat(),
            "branch": branch,
        }

        session_file = session_dir / "session.json"
        session_file.write_text(json.dumps(session_data, indent=2))

        logger.info(f"Created session {session_id} for role {role} with focus {focus}")

        # Update FAST layer
        self._update_fast_layer(session_id, role, focus, branch)

        return {"session_id": session_id}

    def detect_focus_conflicts(
        self,
        focus: str,
        current_session_id: str,
    ) -> list[str]:
        """Detect other active sessions with the same focus.

        Args:
            focus: Focus to check for conflicts.
            current_session_id: Session ID to exclude from check.

        Returns:
            List of conflicting focus values (duplicates of the input focus).
        """
        active_dir = self.working_dir / ".hestai" / "state" / "sessions" / "active"
        if not active_dir.exists():
            return []

        conflicts: list[str] = []
        for session_dir in active_dir.iterdir():
            if not session_dir.is_dir():
                continue
            if session_dir.name == current_session_id:
                continue

            session_file = session_dir / "session.json"
            if not session_file.exists():
                continue

            try:
                data = json.loads(session_file.read_text())
                if data.get("focus") == focus:
                    conflicts.append(data["focus"])
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"Error reading session file {session_file}: {e}")
                continue

        return conflicts

    def get_active_session_focuses(self) -> list[str]:
        """Get focus values of all active sessions.

        Returns:
            List of focus strings from active sessions.
        """
        active_dir = self.working_dir / ".hestai" / "state" / "sessions" / "active"
        if not active_dir.exists():
            return []

        focuses: list[str] = []
        for session_dir in active_dir.iterdir():
            if not session_dir.is_dir():
                continue
            session_file = session_dir / "session.json"
            if not session_file.exists():
                continue
            try:
                data = json.loads(session_file.read_text())
                focus = data.get("focus")
                if focus:
                    focuses.append(focus)
            except (json.JSONDecodeError, OSError):
                continue

        return focuses

    def discover_context_paths(self) -> list[str]:
        """Discover OCTAVE context file paths.

        Scans .hestai/state/context/ for standard OCTAVE files and
        .hestai/north-star/ for North Star files.

        Returns:
            List of absolute paths to context files that exist.
        """
        context_paths: list[str] = []
        context_dir = self.working_dir / ".hestai" / "state" / "context"

        # Standard OCTAVE context files
        for file_name in STANDARD_CONTEXT_FILES:
            path = context_dir / file_name
            if path.exists():
                context_paths.append(str(path))

        # North Star file
        north_star_path = self._find_north_star_file()
        if north_star_path:
            context_paths.append(str(north_star_path))

        return context_paths

    def ensure_hestai_structure(self) -> str:
        """Ensure .hestai/ directory structure exists with three-tier symlink convention.

        Three-tier convention:
            .hestai/         - committed project governance (north-star, decisions)
            .hestai-state/   - uncommitted working state (sessions, context)
            .hestai/state    - symlink to ../.hestai-state

        Returns:
            'present' if .hestai/ already existed, 'created' if newly created.
        """
        hestai_dir = self.working_dir / ".hestai"
        state_link = hestai_dir / "state"
        state_real = self.working_dir / ".hestai-state"

        if hestai_dir.exists() and hestai_dir.is_dir():
            # Already exists, ensure subdirs and symlink
            self._ensure_state_directory(state_real)
            self._ensure_state_symlink(state_link, state_real)
            (hestai_dir / "north-star").mkdir(parents=True, exist_ok=True)
            return "present"

        # Create new structure
        hestai_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_state_directory(state_real)
        self._ensure_state_symlink(state_link, state_real)
        (hestai_dir / "north-star").mkdir(parents=True, exist_ok=True)

        logger.info(f"Created .hestai/ directory structure at {self.working_dir}")
        return "created"

    def _ensure_state_directory(self, state_real: Path) -> None:
        """Create .hestai-state/ with required subdirectories.

        Args:
            state_real: Path to the .hestai-state/ directory.
        """
        (state_real / "sessions" / "active").mkdir(parents=True, exist_ok=True)
        (state_real / "sessions" / "archive").mkdir(parents=True, exist_ok=True)
        (state_real / "context").mkdir(parents=True, exist_ok=True)
        (state_real / "context" / "state").mkdir(parents=True, exist_ok=True)

    def _ensure_state_symlink(self, state_link: Path, state_real: Path) -> None:
        """Create .hestai/state symlink pointing to ../.hestai-state.

        If the symlink already exists and points to the correct target, it is left alone.
        If the symlink points to the wrong target or is broken, it is replaced.
        If a real directory exists at the symlink path, it is replaced.

        Args:
            state_link: Path where the symlink should be (.hestai/state).
            state_real: Path to the real state directory (.hestai-state/).
        """
        expected_target = "../.hestai-state"

        if state_link.is_symlink():
            current_target = os.readlink(str(state_link))
            if current_target == expected_target:
                # Correct symlink, leave it alone
                return

            # Wrong target or broken symlink — remove and recreate
            logger.warning(
                f"Symlink {state_link} points to '{current_target}' "
                f"instead of '{expected_target}', correcting"
            )
            state_link.unlink()
            # Fall through to create the correct symlink below

        if state_link.exists():
            if state_link.is_dir():
                # Real directory exists where symlink should be — migrate contents
                # to .hestai-state/ then replace with symlink
                import shutil

                self._migrate_state_contents(state_link, state_real)
                shutil.rmtree(state_link)
                logger.warning(
                    f"Migrated real directory at {state_link} to {state_real} "
                    f"and replaced with symlink to enforce three-tier convention"
                )
            else:
                # Plain file or other non-directory — remove to make way for symlink
                state_link.unlink()
                logger.warning(
                    f"Removed unexpected file at {state_link} "
                    f"to create symlink (three-tier convention)"
                )

        state_link.symlink_to("../.hestai-state")
        logger.info(f"Created symlink {state_link} -> ../.hestai-state " f"(three-tier convention)")

    @staticmethod
    def _migrate_state_contents(source: Path, target: Path) -> None:
        """Migrate files from a real .hestai/state/ directory to .hestai-state/.

        Walks the source directory and copies any files that don't already exist
        in the target, preserving directory structure. This handles the upgrade
        path from a pre-symlink layout to the three-tier convention.

        Args:
            source: The real directory at .hestai/state/ (will be removed after).
            target: The .hestai-state/ directory to migrate into.
        """
        import shutil

        for item in source.rglob("*"):
            if item.is_file():
                relative = item.relative_to(source)
                dest = target / relative
                if not dest.exists():
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(item, dest)
                    logger.info(f"Migrated {relative} to {target}")

    def read_file_contents(self, path: Path) -> str | None:
        """Read file contents, returning None if file doesn't exist or fails.

        Args:
            path: Path to file.

        Returns:
            File contents or None.
        """
        try:
            if path.exists():
                return path.read_text()
        except OSError as e:
            logger.warning(f"Could not read file {path}: {e}")
        return None

    def _find_north_star_file(self) -> Path | None:
        """Find North Star file in .hestai/north-star/ using flexible naming.

        Supports patterns: 000-{PROJECT}-NORTH-STAR(-SUMMARY)?(.oct)?.md
        Prefers .oct.md over .md, excludes -SUMMARY files.
        """
        for dir_name in ("north-star", "workflow"):
            ns_dir = self.working_dir / ".hestai" / dir_name
            if not ns_dir.exists():
                continue

            candidates = self._find_north_star_candidates(ns_dir)
            if candidates:
                # Sort: .oct.md before .md, then alphabetical
                def sort_key(p: Path) -> tuple[int, str]:
                    return (0 if p.name.endswith(".oct.md") else 1, p.name)

                candidates.sort(key=sort_key)
                return candidates[0]

        return None

    def _find_north_star_candidates(self, ns_dir: Path) -> list[Path]:
        """Find North Star candidate files in the given directory."""
        try:
            candidates = []
            for path in ns_dir.iterdir():
                name = path.name
                if (
                    name.startswith("000-")
                    and "NORTH-STAR" in name
                    and "-SUMMARY" not in name
                    and name.endswith(".md")
                ):
                    candidates.append(path)
            return candidates
        except OSError:
            return []

    def _update_fast_layer(
        self,
        session_id: str,
        role: str,
        focus: str,
        branch: str,
    ) -> None:
        """Update FAST layer files during session creation.

        Writes current-focus.oct.md, checklist.oct.md, and blockers.oct.md.
        """
        state_dir = self.working_dir / ".hestai" / "state" / "context" / "state"
        state_dir.mkdir(parents=True, exist_ok=True)

        self._populate_current_focus(state_dir, session_id, role, focus, branch)
        self._populate_checklist(state_dir, session_id, focus)
        self._populate_blockers(state_dir, session_id)

    def _populate_current_focus(
        self,
        state_dir: Path,
        session_id: str,
        role: str,
        focus: str,
        branch: str,
    ) -> None:
        """Write current-focus.oct.md with session info."""
        timestamp = datetime.now(UTC).isoformat()
        content = f"""===CURRENT_FOCUS===
META:
  TYPE::SESSION_FOCUS
  VELOCITY::HOURLY_DAILY

SESSION:
  ID::"{session_id}"
  ROLE::{role}
  FOCUS::"{focus}"
  BRANCH::{branch}
  STARTED::"{timestamp}"

===END===
"""
        (state_dir / "current-focus.oct.md").write_text(content)

    def _populate_checklist(
        self,
        state_dir: Path,
        session_id: str,
        focus: str,
    ) -> None:
        """Write checklist.oct.md, carrying forward incomplete items."""
        checklist_path = state_dir / "checklist.oct.md"

        # Carry forward incomplete items from previous session
        carried_forward = self._extract_incomplete_items(checklist_path)
        carried_section = ""
        if carried_forward:
            carried_section = "\nCARRIED_FORWARD:\n"
            for item, status in carried_forward:
                carried_section += f"  {item}::{status}[from_previous_session]\n"

        content = f"""===SESSION_CHECKLIST===
META:
  TYPE::FAST_CHECKLIST
  VELOCITY::HOURLY_DAILY
  SESSION::"{session_id}"

CURRENT_TASK::"{focus}"

ITEMS:
  session_task::IN_PROGRESS
{carried_section}
===END===
"""
        checklist_path.write_text(content)

    def _populate_blockers(
        self,
        state_dir: Path,
        session_id: str,
    ) -> None:
        """Write or update blockers.oct.md, preserving existing blockers."""
        blockers_path = state_dir / "blockers.oct.md"

        if blockers_path.exists():
            # Preserve existing content, update session reference
            content = blockers_path.read_text()
            if 'SESSION::"' in content:
                content = re.sub(
                    r'SESSION::"[^"]*"',
                    f'SESSION::"{session_id}"',
                    content,
                )
                blockers_path.write_text(content)
            return

        # Create new blockers file
        content = f"""===BLOCKERS===
META:
  TYPE::FAST_BLOCKERS
  VELOCITY::HOURLY_DAILY
  SESSION::"{session_id}"

ACTIVE:

===END===
"""
        blockers_path.write_text(content)

    def _extract_incomplete_items(self, checklist_path: Path) -> list[tuple[str, str]]:
        """Extract incomplete items (PENDING, IN_PROGRESS) from existing checklist."""
        if not checklist_path.exists():
            return []

        content = checklist_path.read_text()
        incomplete = []
        pattern = r"^\s+(\w+)::(PENDING|IN_PROGRESS)"
        for match in re.finditer(pattern, content, re.MULTILINE):
            item_name = match.group(1)
            status = match.group(2)
            if item_name != "session_task":
                incomplete.append((item_name, status))

        return incomplete
