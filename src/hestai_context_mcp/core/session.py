"""Session management: Handles session lifecycle operations."""


class SessionManager:
    """Manages agent session lifecycle.

    Handles session creation, tracking, archival, and cleanup.
    Each session has a unique ID and tracks the agent role, focus area,
    and working directory.
    """

    def __init__(self, working_dir: str) -> None:
        """Initialize the session manager.

        Args:
            working_dir: Project working directory path.
        """
        self.working_dir = working_dir
