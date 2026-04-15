"""RFC-204: File-based channel inbox.

Accepts .md files from inbox directory. Each file represents a user message
submitted to the autopilot system.
"""

from __future__ import annotations

import logging
from pathlib import Path

from .models import ChannelMessage

logger = logging.getLogger(__name__)

_FRONTMATTER_SPLIT_MIN = 3


class ChannelInbox:
    """Read messages from the autopilot inbox directory.

    Args:
        inbox_dir: Path to inbox directory. Defaults to $SOOTHE_HOME/autopilot/inbox.
    """

    def __init__(self, inbox_dir: str | Path | None = None) -> None:
        """Initialize inbox.

        Args:
            inbox_dir: Path to inbox directory.
        """
        self._inbox_dir = Path(inbox_dir) if inbox_dir else None
        self._processed: list[str] = []

    def set_directory(self, path: str | Path) -> None:
        """Set inbox directory path.

        Args:
            path: New inbox directory path.
        """
        self._inbox_dir = Path(path)
        self._inbox_dir.mkdir(parents=True, exist_ok=True)

    def read_pending(self) -> list[ChannelMessage]:
        """Read all unprocessed markdown files from inbox.

        Returns:
            List of ChannelMessages from inbox files.
        """
        if not self._inbox_dir or not self._inbox_dir.exists():
            return []

        messages = []
        for fpath in sorted(self._inbox_dir.glob("*.md")):
            if fpath.name not in self._processed:
                msg = self._parse_inbox_file(fpath)
                if msg:
                    messages.append(msg)
                    self._processed.append(fpath.name)

        return messages

    def archive_processed(self) -> int:
        """Move processed inbox files to archive subdir.

        Returns:
            Number of files archived.
        """
        if not self._inbox_dir:
            return 0

        archive_dir = self._inbox_dir / "processed"
        archive_dir.mkdir(exist_ok=True)
        count = 0
        for fname in self._processed:
            src = self._inbox_dir / fname
            dst = archive_dir / fname
            if src.exists():
                src.rename(dst)
                count += 1
        self._processed.clear()
        return count

    def _parse_inbox_file(self, path: Path) -> ChannelMessage | None:
        """Parse an inbox markdown file into a ChannelMessage.

        Expected format:
        ```
        ---
        type: task_submit
        priority: 80
        ---

        Task description text.
        ```

        Args:
            path: Path to inbox file.

        Returns:
            ChannelMessage or None if parsing fails.
        """
        text = path.read_text()

        # Try to extract frontmatter
        if text.startswith("---"):
            parts = text.split("---", 2)
            if len(parts) >= _FRONTMATTER_SPLIT_MIN:
                import yaml

                fm = yaml.safe_load(parts[1]) or {}
                body = parts[2].strip()

                msg_type = fm.get("type", "task_submit")
                payload = {"description": body}
                # Copy extra frontmatter fields to payload
                for key in ("priority", "context"):
                    if key in fm:
                        payload[key] = fm[key]

                return ChannelMessage(
                    type=msg_type,
                    payload=payload,
                    sender="user",
                )

        # No frontmatter — treat entire file as task_submit
        return ChannelMessage(
            type="task_submit",
            payload={"description": text},
            sender="user",
        )
