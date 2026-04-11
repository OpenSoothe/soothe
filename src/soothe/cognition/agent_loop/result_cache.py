"""File system cache for large tool results.

This module implements a file-based cache for tool results that exceed a size
threshold, enabling the agentic loop to avoid context bloat while preserving access
to full content when needed.

RFC-211: Agentic Loop Tool Result Optimization
"""

from __future__ import annotations

import json
import logging
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from soothe.config import SOOTHE_HOME

logger = logging.getLogger(__name__)


class ToolResultCache:
    """Manages file system cache for large tool results.

    Cache location: ~/.soothe/runs/{thread_id}/tool_results/{tool_call_id}.json

    File naming uses tool_call_id to guarantee uniqueness even when the same
    tool is called multiple times in a single run.

    Attributes:
        thread_id: Thread identifier for cache directory
        size_threshold: Minimum size (bytes) to trigger caching
        cache_dir: Cache directory path
    """

    def __init__(self, thread_id: str, size_threshold: int = 50_000) -> None:
        """Initialize cache for a specific thread.

        Args:
            thread_id: Thread identifier for cache directory
            size_threshold: Minimum size (bytes) to trigger caching (default: 50KB)
        """
        self.thread_id = thread_id
        self.size_threshold = size_threshold
        self.cache_dir = Path(SOOTHE_HOME).expanduser() / "runs" / thread_id / "tool_results"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def should_cache(self, size_bytes: int) -> bool:
        """Check if result should be cached based on size.

        Args:
            size_bytes: Size of the result in bytes

        Returns:
            True if result should be cached
        """
        return size_bytes > self.size_threshold

    def save(self, tool_call_id: str, content: str, metadata: dict[str, Any]) -> str | None:
        """Save large result to file cache.

        Args:
            tool_call_id: Unique identifier for this tool call
            content: Full tool result content
            metadata: Tool metadata (tool_name, type, etc.)

        Returns:
            File reference if spilled, None if not spilled
        """
        size_bytes = len(content.encode("utf-8"))

        if not self.should_cache(size_bytes):
            logger.debug(
                "Tool result %s not spilled (size %d < threshold %d)",
                tool_call_id,
                size_bytes,
                self.size_threshold,
            )
            return None

        file_path = self.cache_dir / f"{tool_call_id}.json"

        cache_data = {
            "tool_call_id": tool_call_id,
            "tool_name": metadata.get("tool_name", "unknown"),
            "timestamp": datetime.now(UTC).isoformat(),
            "content": content,
            "metadata": {
                "size_bytes": size_bytes,
                "type": metadata.get("type", "generic"),
            },
        }

        try:
            file_path.write_text(json.dumps(cache_data, indent=2, ensure_ascii=False), encoding="utf-8")
            logger.info(
                "Cached large tool result %s to %s (size: %d bytes)",
                tool_call_id,
                file_path,
                size_bytes,
            )
            return f"{tool_call_id}.json"
        except OSError:
            logger.exception("Failed to cache tool result %s", tool_call_id)
            return None

    def load(self, tool_call_id: str) -> dict[str, Any] | None:
        """Load cached result by tool_call_id.

        Args:
            tool_call_id: Unique identifier for the tool call

        Returns:
            Cached data dict or None if not found
        """
        file_path = self.cache_dir / f"{tool_call_id}.json"

        if not file_path.exists():
            logger.debug("Cache miss for tool result %s", tool_call_id)
            return None

        try:
            data = json.loads(file_path.read_text(encoding="utf-8"))
            logger.debug("Cache hit for tool result %s", tool_call_id)
            return data
        except (json.JSONDecodeError, OSError):
            logger.exception("Failed to load cached tool result %s", tool_call_id)
            return None

    def cleanup(self) -> None:
        """Remove entire cache directory for this thread.

        Called when thread completes or is deleted.
        """
        if self.cache_dir.exists():
            try:
                shutil.rmtree(self.cache_dir)
                logger.info("Cleaned up tool result cache for thread %s", self.thread_id)
            except OSError:
                logger.exception("Failed to cleanup cache for thread %s", self.thread_id)

    def get_cache_stats(self) -> dict[str, Any]:
        """Get cache statistics for this thread.

        Returns:
            Dict with file_count, total_bytes, cache_dir
        """
        if not self.cache_dir.exists():
            return {"file_count": 0, "total_bytes": 0, "cache_dir": str(self.cache_dir)}

        files = list(self.cache_dir.glob("*.json"))
        total_bytes = sum(f.stat().st_size for f in files)

        return {
            "file_count": len(files),
            "total_bytes": total_bytes,
            "cache_dir": str(self.cache_dir),
        }
