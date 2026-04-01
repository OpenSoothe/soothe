"""Base event classes for Soothe events.

This module provides the base event classes that all specific events inherit from.
Module-specific events are defined in their respective modules and registered via
``register_event()``.

RFC-0015: All progress events use 4-segment type strings
``soothe.<domain>.<component>.<action>`` with six domains:
lifecycle, protocol, tool, subagent, output, error.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, ConfigDict


class SootheEvent(BaseModel):
    """Base class for all Soothe progress events."""

    type: str

    model_config = ConfigDict(extra="allow")

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict for wire-format emission."""
        return self.model_dump(exclude_none=True)

    def emit(self, logger: logging.Logger) -> None:
        """Emit this event via the LangGraph stream writer."""
        from soothe.utils.progress import emit_progress

        emit_progress(self.to_dict(), logger)


class LifecycleEvent(SootheEvent):
    """Thread and session lifecycle events."""


class ProtocolEvent(SootheEvent):
    """Core protocol activity events."""


class SubagentEvent(SootheEvent):
    """Subagent activity events."""


class OutputEvent(SootheEvent):
    """Content destined for user display."""


class ErrorEvent(SootheEvent):
    """Error events."""

    error: str


__all__ = [
    "ErrorEvent",
    "LifecycleEvent",
    "OutputEvent",
    "ProtocolEvent",
    "SootheEvent",
    "SubagentEvent",
]
