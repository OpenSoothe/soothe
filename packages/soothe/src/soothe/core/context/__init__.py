"""Context management package - tool context and trigger registries.

This package provides:
- Tool context registry for system message fragments
- Tool trigger registry for tool→section mappings
- Stream model override for per-async-task model swapping

Architecture:
- tool_registry.py: Tool context fragments registry
- trigger_registry.py: Tool trigger mappings
- model_override.py: Per-async-task model override via ContextVar

Usage:
    from soothe.core.context import (
        ToolContextRegistry,
        ToolTriggerRegistry,
        BUILTIN_TOOL_TRIGGERS,
        attach_stream_model_override,
        get_stream_model_override,
    )
"""

from __future__ import annotations

# Stream model override
from .model_override import (
    attach_stream_model_override,
    get_stream_model_override,
    reset_stream_model_override,
)

# Tool context registry
from .tool_registry import ToolContextRegistry

# Tool trigger registry
from .trigger_registry import (
    BUILTIN_TOOL_TRIGGERS,
    ToolTriggerRegistry,
)

__all__ = [
    # Tool context
    "ToolContextRegistry",
    # Tool triggers
    "ToolTriggerRegistry",
    "BUILTIN_TOOL_TRIGGERS",
    # Model override
    "attach_stream_model_override",
    "reset_stream_model_override",
    "get_stream_model_override",
]
