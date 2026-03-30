"""CLI stream display pipeline for progress output.

This package implements RFC-0020 CLI Stream Display Pipeline,
providing a unified event-to-output pipeline with integrated
verbosity filtering and context tracking.
"""

from soothe.ux.cli.stream.context import PipelineContext, ToolCallInfo
from soothe.ux.cli.stream.display_line import DisplayLine
from soothe.ux.cli.stream.pipeline import StreamDisplayPipeline

__all__ = [
    "DisplayLine",
    "PipelineContext",
    "StreamDisplayPipeline",
    "ToolCallInfo",
]
