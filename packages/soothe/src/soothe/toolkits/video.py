"""Video analysis using Google Gemini.

Enhanced version with full Gemini integration for video understanding.
Ported from noesium's video_toolkit.py.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool
from pydantic import Field
from soothe_sdk.plugin import plugin

from soothe.toolkits._internal.local_path_resolution import resolve_toolkit_local_path

logger = logging.getLogger(__name__)


class VideoAnalysisTool(BaseTool):
    """Analyze video content using Google Gemini.

    Supports video file upload, content analysis, and Q&A.
    Requires Google API key for Gemini access.
    """

    name: str = "analyze_video"
    description: str = (
        "Analyze video content using Google Gemini. "
        "Provide `video_path` (local file path). "
        "Optional `question` about the video (default: general description). "
        "Requires GOOGLE_API_KEY environment variable. "
        "Returns analysis or error message."
    )

    google_api_key: str | None = Field(default=None)
    model_name: str = Field(default="gemini-1.5-pro")
    max_file_size: int = Field(default=2 * 1024 * 1024 * 1024)  # 2GB
    config: Any = Field(default=None, exclude=True)  # SootheConfig for local path sandboxing

    def _get_api_key(self) -> str | None:
        """Get Google API key from instance or environment."""
        if self.google_api_key:
            return self.google_api_key
        return os.getenv("GOOGLE_API_KEY")

    def _validate_file(self, video_path: str) -> tuple[Path, str | None]:
        """Validate video file exists and is within size limit.

        Args:
            video_path: Path to video file.

        Returns:
            Tuple of (resolved_path, error_message).
        """
        try:
            path = resolve_toolkit_local_path(video_path, config=self.config)
        except ValueError as e:
            return Path(video_path), str(e)

        if not path.exists():
            return path, f"Video file not found: {video_path}"

        if not path.is_file():
            return path, f"Not a file: {video_path}"

        file_size = path.stat().st_size
        if file_size > self.max_file_size:
            size_mb = file_size / (1024 * 1024)
            max_mb = self.max_file_size / (1024 * 1024)
            return path, f"Video file too large: {size_mb:.1f}MB (max: {max_mb:.0f}MB)"

        return path, None

    def _raise_video_failed(self, error: str) -> None:
        """Raise RuntimeError for video processing failure.

        Args:
            error: Error message from video processing.

        Raises:
            RuntimeError: Always raised with the error message.
        """
        msg = f"Video processing failed: {error}"
        raise RuntimeError(msg)

    def _upload_video(self, client: Any, video_path: Path) -> Any:
        """Upload video file to Gemini File API.

        Args:
            client: Gemini client instance.
            video_path: Path to video file.

        Returns:
            Uploaded file object.

        Raises:
            RuntimeError: If upload fails.
        """
        try:
            _ = video_path.stat().st_size / (1024 * 1024)  # Check file size

            logger.info("Uploading video: %s", video_path)

            video_file = client.files.upload(file=str(video_path))

            # Wait for processing
            import time

            while video_file.state.name == "PROCESSING":
                logger.debug("Waiting for video processing...")
                time.sleep(2)
                video_file = client.files.get(name=video_file.name)

            if video_file.state.name == "FAILED":
                self._raise_video_failed(video_file.error)

            logger.info("Video uploaded and processed: %s", video_file.name)
        except Exception as e:
            msg = f"Failed to upload video: {e}"
            raise RuntimeError(msg) from e
        else:
            return video_file

    def _run(self, video_path: str, question: str = "Describe this video in detail") -> str:
        """Analyze video content.

        Args:
            video_path: Local file path to video.
            question: Question about the video.

        Returns:
            Video analysis or error message.
        """
        # Check API key
        api_key = self._get_api_key()
        if not api_key:
            return "Error: Google API key required. Set GOOGLE_API_KEY environment variable."

        # Validate file
        path, error = self._validate_file(video_path)
        if error:
            return f"Error: {error}"

        try:
            from google import genai
            from google.genai.types import HttpOptions

            # Initialize client
            client = genai.Client(
                api_key=api_key,
                http_options=HttpOptions(api_version="v1alpha"),
            )

            # Upload video
            video_file = self._upload_video(client, path)

            # Generate content
            model = client.get_model(self.model_name)

            response = model.generate_content(
                [video_file, question],
                request_kwargs={"timeout": 300},  # 5 minute timeout
            )

            # Clean up uploaded file
            try:
                client.files.delete(name=video_file.name)
                logger.debug("Deleted uploaded video: %s", video_file.name)
            except Exception:
                logger.debug("Failed to delete uploaded video")

        except ImportError:
            error_msg = "google-genai not installed. Install with: pip install google-genai"
            return f"Error: {error_msg}"
        except Exception as e:
            logger.exception("Video analysis failed")
            return f"Error analyzing video: {e}"
        else:
            return response.text

    async def _arun(self, video_path: str, question: str = "Describe this video in detail") -> str:
        return self._run(video_path, question)


class VideoInfoTool(BaseTool):
    """Get basic metadata about a video file."""

    name: str = "get_video_info"
    description: str = (
        "Get basic metadata about a video file. "
        "Provide `video_path` (local file path). "
        "Returns file size, format, and other basic info."
    )

    config: Any = Field(default=None, exclude=True)  # SootheConfig for local path sandboxing

    def _run(self, video_path: str) -> dict[str, Any]:
        """Get video file metadata.

        Args:
            video_path: Path to video file.

        Returns:
            Dict with file metadata or error.
        """
        try:
            path = resolve_toolkit_local_path(video_path, config=self.config)
        except ValueError as e:
            return {"error": str(e)}

        if not path.exists():
            return {"error": f"File not found: {video_path}"}

        if not path.is_file():
            return {"error": f"Not a file: {video_path}"}

        stat = path.stat()

        return {
            "path": str(path),
            "name": path.name,
            "suffix": path.suffix,
            "size_bytes": stat.st_size,
            "size_mb": round(stat.st_size / (1024 * 1024), 2),
            "modified": stat.st_mtime,
        }

    async def _arun(self, video_path: str) -> dict[str, Any]:
        return self._run(video_path)


class VideoToolkit:
    """Toolkit for video analysis operations."""

    def __init__(self, *, config: Any = None) -> None:
        """Initialize the toolkit.

        Args:
            config: Optional SootheConfig for path sandboxing.
        """
        self._config = config

    def get_tools(self) -> list[BaseTool]:
        """Get list of langchain tools.

        Returns:
            List containing VideoAnalysisTool and VideoInfoTool.
        """
        return [
            VideoAnalysisTool(config=self._config),
            VideoInfoTool(config=self._config),
        ]


@plugin(name="video", version="1.0.0", description="Video analysis", trust_level="built-in")
class VideoPlugin:
    """Video analysis tools plugin.

    Provides analyze_video and get_video_info tools.
    """

    def __init__(self) -> None:
        """Initialize the plugin."""
        self._tools: list[BaseTool] = []

    async def on_load(self, context) -> None:
        """Initialize tools.

        Args:
            context: Plugin context with config and logger.
        """
        toolkit = VideoToolkit(config=context.soothe_config)
        self._tools = toolkit.get_tools()

        context.logger.info("Loaded %d video tools", len(self._tools))

    def get_tools(self) -> list[BaseTool]:
        """Get list of langchain tools.

        Returns:
            List of video tool instances.
        """
        return self._tools
