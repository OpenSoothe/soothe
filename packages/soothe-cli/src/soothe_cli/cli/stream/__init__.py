"""CLI stream display pipeline for progress output.

This package implements RFC-0020 CLI Stream Display Pipeline,
providing a unified event-to-output pipeline with integrated
verbosity filtering and context tracking.
"""

from soothe_cli.cli.stream.context import PipelineContext, ToolCallInfo
from soothe_cli.cli.stream.display_line import DisplayLine
from soothe_cli.cli.stream.pipeline import StreamDisplayPipeline

__all__ = [
    "DisplayLine",
    "PipelineContext",
    "StreamDisplayPipeline",
    "ToolCallInfo",
]
