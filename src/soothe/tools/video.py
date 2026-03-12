"""Video analysis tool (placeholder).

Ported from noesium's video toolkit. The noesium implementation is also a stub;
real video analysis requires multimodal model integration (e.g. Gemini).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool


class VideoInfoTool(BaseTool):
    """Get basic metadata about a video file."""

    name: str = "get_video_info"
    description: str = "Get basic metadata about a video file. Provide `video_path` (local file path)."

    def _run(self, video_path: str) -> dict[str, Any]:
        path = Path(video_path)
        if not path.exists():
            return {"error": f"File not found: {video_path}"}

        stat = path.stat()
        return {
            "path": str(path),
            "name": path.name,
            "suffix": path.suffix,
            "size_bytes": stat.st_size,
            "size_mb": round(stat.st_size / (1024 * 1024), 2),
        }

    async def _arun(self, video_path: str) -> dict[str, Any]:
        return self._run(video_path)


def create_video_tools() -> list[BaseTool]:
    """Create video analysis tools.

    Returns:
        List containing the `VideoInfoTool`.
    """
    return [VideoInfoTool()]
