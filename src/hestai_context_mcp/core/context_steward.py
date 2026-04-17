"""Context steward: Manages context synthesis and delivery."""


class ContextSteward:
    """Manages context synthesis and delivery for agent sessions.

    Responsible for reading project context files, synthesizing them
    into coherent context views, and managing context freshness.
    """

    def __init__(self, working_dir: str) -> None:
        """Initialize the context steward.

        Args:
            working_dir: Project working directory path.
        """
        self.working_dir = working_dir
