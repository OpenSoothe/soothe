"""Formatter for media tools."""

from __future__ import annotations

from typing import Any

from soothe_cli.shared.tool_formatters.base import BaseFormatter
from soothe_cli.shared.tool_output_formatter import ToolBrief


class MediaFormatter(BaseFormatter):
    """Formatter for media tools.

    Handles: transcribe_audio, get_video_info, analyze_image

    Provides semantic summaries with duration, resolution, and format metrics.
    """

    def format(self, tool_name: str, result: Any) -> ToolBrief:
        """Format media tool result.

        Args:
            tool_name: Name of the media tool.
            result: Tool result (dict with media metadata).

        Returns:
            ToolBrief with media summary.

        Raises:
            ValueError: If tool_name is not a recognized media tool.

        Example:
            >>> formatter = MediaFormatter()
            >>> brief = formatter.format("transcribe_audio", {"duration": 45.2, "language": "en"})
            >>> brief.to_display()
            '✓ Transcribed 45.2s (en)'
        """
        # Normalize tool name
        normalized = tool_name.lower().replace("-", "_").replace(" ", "_")

        # Route to specific formatter
        if normalized == "transcribe_audio":
            return self._format_transcribe_audio(result)
        if normalized == "get_video_info":
            return self._format_get_video_info(result)
        if normalized == "analyze_image":
            return self._format_analyze_image(result)
        msg = f"Unknown media tool: {tool_name}"
        raise ValueError(msg)

    def _format_transcribe_audio(self, result: dict[str, Any]) -> ToolBrief:
        """Format transcribe_audio result.

        Shows duration and language.

        Args:
            result: Dict with 'text', 'duration', 'language', and optional 'error'.

        Returns:
            ToolBrief with transcription summary.

        Example:
            >>> brief = formatter._format_transcribe_audio(
            ...     {"duration": 45.2, "language": "en", "text": "hello"}
            ... )
            >>> brief.summary
            'Transcribed 45.2s'
            >>> brief.detail
            'language: en'
        """
        # Handle dict result
        if isinstance(result, dict):
            # Check for error
            if "error" in result:
                error_msg = str(result["error"])
                return ToolBrief(
                    icon="✗",
                    summary="Transcription failed",
                    detail=self._truncate_text(error_msg, 80),
                    metrics={"error": True},
                )

            # Extract metadata
            duration = result.get("duration", 0.0)
            language = result.get("language", "unknown")
            text_length = len(result.get("text", ""))

            # Build summary
            summary = f"Transcribed {duration:.1f}s"

            # Build detail
            detail = f"language: {language}"

            return ToolBrief(
                icon="✓",
                summary=summary,
                detail=detail,
                metrics={
                    "duration": duration,
                    "language": language,
                    "text_length": text_length,
                },
            )

        # Handle string result (fallback)
        if isinstance(result, str):
            if "error" in result.lower() or "failed" in result.lower():
                return ToolBrief(
                    icon="✗",
                    summary="Transcription failed",
                    detail=self._truncate_text(result, 80),
                    metrics={"error": True},
                )

            return ToolBrief(
                icon="✓",
                summary="Transcribed",
                detail=f"{len(result)} chars",
                metrics={},
            )

        # Unknown type
        return ToolBrief(
            icon="✓",
            summary="Transcribed",
            detail=None,
            metrics={},
        )

    def _format_get_video_info(self, result: dict[str, Any]) -> ToolBrief:
        """Format get_video_info result.

        Shows duration, resolution, and format.

        Args:
            result: Dict with 'duration_seconds', 'format', 'codec', and optional 'error'.

        Returns:
            ToolBrief with video info summary.

        Example:
            >>> brief = formatter._format_get_video_info({"duration_seconds": 120, "format": "mp4"})
            >>> brief.summary
            'Video: 120s'
        """
        # Handle dict result
        if isinstance(result, dict):
            # Check for error
            if "error" in result:
                error_msg = str(result["error"])
                return ToolBrief(
                    icon="✗",
                    summary="Video info failed",
                    detail=self._truncate_text(error_msg, 80),
                    metrics={"error": True},
                )

            # Extract metadata
            duration = result.get("duration_seconds", 0.0)
            video_format = result.get("format", "unknown")
            codec = result.get("codec", "unknown")
            size_bytes = result.get("size_bytes", 0)

            # Build summary
            summary = f"Video: {duration:.0f}s"

            # Build detail with resolution if available (not in basic schema)
            # Just show format for now
            detail = f"{video_format}, {codec}"

            return ToolBrief(
                icon="✓",
                summary=summary,
                detail=detail,
                metrics={
                    "duration": duration,
                    "format": video_format,
                    "codec": codec,
                    "size_bytes": size_bytes,
                },
            )

        # Handle string result (fallback)
        if isinstance(result, str):
            if "error" in result.lower() or "failed" in result.lower():
                return ToolBrief(
                    icon="✗",
                    summary="Video info failed",
                    detail=self._truncate_text(result, 80),
                    metrics={"error": True},
                )

            return ToolBrief(
                icon="✓",
                summary="Video info retrieved",
                detail=self._truncate_text(result, 80),
                metrics={},
            )

        # Unknown type
        return ToolBrief(
            icon="✓",
            summary="Video info retrieved",
            detail=None,
            metrics={},
        )

    def _format_analyze_image(self, result: dict[str, Any]) -> ToolBrief:
        """Format analyze_image result.

        Shows size and format.

        Args:
            result: Dict with image metadata and optional 'error'.

        Returns:
            ToolBrief with image analysis summary.

        Example:
            >>> brief = formatter._format_analyze_image({"size_bytes": 2400000, "format": "PNG"})
            >>> brief.summary
            'Analyzed image'
            >>> brief.detail
            '2.3 MB, PNG'
        """
        # Handle dict result
        if isinstance(result, dict):
            # Check for error
            if "error" in result:
                error_msg = str(result["error"])
                return ToolBrief(
                    icon="✗",
                    summary="Image analysis failed",
                    detail=self._truncate_text(error_msg, 80),
                    metrics={"error": True},
                )

            # Extract metadata
            size_bytes = result.get("size_bytes", 0)
            image_format = result.get("format", "unknown")
            width = result.get("width")
            height = result.get("height")

            # Build summary
            summary = "Analyzed image"

            # Build detail
            size_str = self._format_size(size_bytes)
            detail_parts = [size_str, image_format]

            if width and height:
                detail_parts.append(f"{width}x{height}")

            detail = ", ".join(detail_parts)

            return ToolBrief(
                icon="✓",
                summary=summary,
                detail=detail,
                metrics={
                    "size_bytes": size_bytes,
                    "format": image_format,
                    "width": width,
                    "height": height,
                },
            )

        # Handle string result (fallback)
        if isinstance(result, str):
            if "error" in result.lower() or "failed" in result.lower():
                return ToolBrief(
                    icon="✗",
                    summary="Image analysis failed",
                    detail=self._truncate_text(result, 80),
                    metrics={"error": True},
                )

            return ToolBrief(
                icon="✓",
                summary="Analyzed image",
                detail=self._truncate_text(result, 80),
                metrics={},
            )

        # Unknown type
        return ToolBrief(
            icon="✓",
            summary="Analyzed image",
            detail=None,
            metrics={},
        )
