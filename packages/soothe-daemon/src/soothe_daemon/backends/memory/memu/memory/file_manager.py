"""File-based Memory Management for MemU.

Provides file operations for storing and retrieving character memory data
in markdown format.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from soothe_daemon.backends.memory.memu.config.markdown_config import get_config_manager

logger = logging.getLogger(__name__)


class MemoryFileManager:
    """File-based memory manager for character profiles and memories.

    Manages memory storage in markdown files:
    - profile.md: Character profile information
    - events.md: Character event records
    - xxx.md: Other memory files
    """

    # Default file extension for all categories
    DEFAULT_EXTENSION = ".md"

    def __init__(
        self,
        memory_dir: str = "memu/server/memory",
        agent_id: str | None = None,
        user_id: str | None = None,
    ) -> None:
        """Initialize File Manager.

        Args:
            memory_dir: Directory to store memory files
            agent_id: Agent identifier for context
            user_id: User identifier for context
        """
        self.memory_dir = Path(memory_dir)
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.embeddings_dir = self.memory_dir / "embeddings"
        self.embeddings_dir.mkdir(parents=True, exist_ok=True)

        # Context for current agent/user (optional)
        self.agent_id = agent_id
        self.user_id = user_id

        self.config_manager = get_config_manager()

        # Maintain memory types by group
        self.memory_types: dict[str, dict[str, str]] = {"basic": {}, "cluster": {}}
        self._initialize_memory_types()

        logger.info("MemoryFileManager initialized with directory: %s", self.memory_dir)

    def _initialize_memory_types(self) -> None:
        """Load basic categories from MarkdownConfigManager into memory_types['basic']."""
        basic_map = self.config_manager.get_file_types_mapping()
        # Ensure a copy to avoid accidental external mutation
        self.memory_types["basic"] = dict(basic_map)
        cluster_set = self._get_cluster_categories(
            self.agent_id, self.user_id, set(self.memory_types["basic"].keys())
        )
        self.memory_types["cluster"] = cluster_set
        # Do not touch cluster here; it's context dependent

    # set_context removed: context is now provided at initialization time

    def get_flat_memory_types(self) -> dict[str, str]:
        """Return a flattened mapping of all categories (basic + cluster) to filenames."""
        flat: dict[str, str] = {}
        flat.update(self.memory_types.get("basic", {}))
        flat.update(self.memory_types.get("cluster", {}))
        return flat

    def _get_memory_file_path(self, agent_id: str, user_id: str, category: str) -> Path:
        """Get the file path for a memory file with agent_id/user_id structure.

        Args:
            agent_id: Agent identifier
            user_id: User identifier
            category: Memory category

        Returns:
            Path: Full path to the memory file
        """
        if category in self.memory_types["basic"]:
            filename = self.memory_types["basic"][category]
        elif category in self.memory_types["cluster"]:
            filename = self.memory_types["cluster"][category]
        else:
            filename = f"{category.replace(' ', '_')}{self.DEFAULT_EXTENSION}"
        return self.memory_dir / agent_id / user_id / filename

    def read_memory_file(self, category: str) -> str:
        """Read content from a memory file using agent_id/user_id structure.

        Args:
            agent_id: Agent identifier
            user_id: User identifier
            category: Category to read

        Returns:
            str: File content or empty string if not found
        """
        try:
            file_path = self._get_memory_file_path(self.agent_id, self.user_id, category)
            if file_path.exists():
                return file_path.read_text(encoding="utf-8")
        except Exception:
            logger.exception(
                "Error reading %s for agent %s, user %s", category, self.agent_id, self.user_id
            )
            return ""
        else:
            return ""

    def write_memory_file(self, category: str, content: str) -> bool:
        """Write content to a memory file using agent_id/user_id structure.

        Args:
            agent_id: Agent identifier
            user_id: User identifier
            category: Category to write
            content: Content to write

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            file_path = self._get_memory_file_path(self.agent_id, self.user_id, category)
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")
            logger.debug("Written %s for agent %s, user %s", category, self.agent_id, self.user_id)
        except Exception:
            logger.exception(
                "Error writing %s for agent %s, user %s", category, self.agent_id, self.user_id
            )
            return False
        else:
            return True

    def append_memory_file(self, category: str, content: str) -> bool:
        """Append content to a memory file using agent_id/user_id structure.

        Args:
            agent_id: Agent identifier
            user_id: User identifier
            category: Category to append to
            content: Content to append

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            existing_content = self.read_memory_file(category)
            new_content = existing_content + "\n" + content if existing_content else content
            return self.write_memory_file(category, new_content)
        except Exception:
            logger.exception(
                "Error appending %s for agent %s, user %s", category, self.agent_id, self.user_id
            )
            return False

    def delete_memory_file(self, category: str) -> bool:
        """Delete a memory file using agent_id/user_id structure.

        Args:
            agent_id: Agent identifier
            user_id: User identifier
            category: Category to delete

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            file_path = self._get_memory_file_path(self.agent_id, self.user_id, category)
            if file_path.exists():
                file_path.unlink()
                logger.debug(
                    "Deleted %s for agent %s, user %s", category, self.agent_id, self.user_id
                )
        except Exception:
            logger.exception(
                "Error deleting %s for agent %s, user %s", category, self.agent_id, self.user_id
            )
            return False
        else:
            return True

    def list_memory_files(
        self,
        category_group: Literal["basic", "cluster", "all"] = "basic",
    ) -> list[str]:
        """List memory categories for an agent-user pair.

        Args:
            agent_id: Agent identifier
            user_id: User identifier
            category_group: Which group to list: "basic", "cluster", or "all".

        Returns:
            List[str]: List of category names
        """
        basic_categories = self._get_basic_categories()
        cluster_categories = self._get_cluster_categories(
            self.agent_id, self.user_id, basic_categories
        ).keys()

        if category_group == "basic":
            # Return all basic categories from config (not filtered by existence)
            return sorted(basic_categories)
        if category_group == "cluster":
            return sorted(cluster_categories)
        # all
        # all = all basic categories + cluster categories
        return sorted(basic_categories.union(cluster_categories))

    def _get_basic_categories(self) -> set[str]:
        """Get basic categories from MarkdownConfigManager."""
        return set(self.config_manager.get_all_file_types())

    def _get_cluster_categories(
        self, agent_id: str, user_id: str, basic_categories: set[str]
    ) -> dict[str, str]:
        """Scan existing files and derive cluster categories not in basic."""
        user_dir = self.memory_dir / agent_id / user_id
        if not user_dir.exists():
            return {}
        cluster: dict[str, str] = {}
        for item in user_dir.glob(f"*{self.DEFAULT_EXTENSION}"):
            if item.is_file():
                category_name = item.stem
                if category_name not in basic_categories:
                    cluster[category_name.replace("_", " ")] = (
                        f"{category_name}{self.DEFAULT_EXTENSION}"
                    )
        return cluster

    def create_cluster_category(self, category: str) -> bool:
        """Create a new empty cluster category file if it does not exist.

        Args:
            agent_id: Agent identifier
            user_id: User identifier
            category: New cluster category name

        Returns:
            bool: True if created or already exists, False on error
        """
        try:
            _category = category.replace(" ", "_")
            file_path = self._get_memory_file_path(self.agent_id, self.user_id, _category)
            file_path.parent.mkdir(parents=True, exist_ok=True)
            if not file_path.exists():
                file_path.write_text("", encoding="utf-8")
            # Update in-memory cluster categories mapping
            self.memory_types.setdefault("cluster", {})[category] = (
                f"{_category}{self.DEFAULT_EXTENSION}"
            )
        except Exception:
            logger.exception(
                "Error creating cluster category %s for agent %s, user %s",
                category,
                self.agent_id,
                self.user_id,
            )
            return False
        else:
            return True

    def get_char_embeddings_dir(self) -> Path:
        """Get the embeddings directory path for the current agent/user context.

        Args:
            embeddings_base_dir: Base embeddings directory (usually memory_dir/embeddings)

        Returns:
            Path: Full path to the character's embeddings directory
        """
        if not self.agent_id or not self.user_id:
            raise ValueError("agent_id and user_id must be set to get embeddings directory")

        char_embeddings_dir = self.embeddings_dir / self.agent_id / self.user_id
        char_embeddings_dir.mkdir(parents=True, exist_ok=True)
        return char_embeddings_dir

    def get_file_info(self, category: str) -> dict[str, Any]:
        """Get information about a memory file using agent_id/user_id structure.

        Args:
            agent_id: Agent identifier
            user_id: User identifier
            category: Category name

        Returns:
            Dict containing file information
        """
        file_path = self._get_memory_file_path(self.agent_id, self.user_id, category)

        if file_path.exists():
            stat = file_path.stat()
            content = self.read_memory_file(category)
            return {
                "exists": True,
                "file_size": stat.st_size,
                "last_modified": datetime.fromtimestamp(stat.st_mtime, tz=datetime.UTC).isoformat(),
                "content_length": len(content),
                "file_path": str(file_path),
                "agent_id": self.agent_id,
                "user_id": self.user_id,
            }
        return {
            "exists": False,
            "file_size": 0,
            "last_modified": None,
            "content_length": 0,
            "file_path": str(file_path),
            "agent_id": self.agent_id,
            "user_id": self.user_id,
        }
