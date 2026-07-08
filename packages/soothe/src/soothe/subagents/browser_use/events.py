"""BrowserUse subagent wire events (curated ``soothe.subagent.*``, IG-338)."""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict
from soothe_sdk.core.events import SubagentEvent
from soothe_sdk.core.subagent_wire import register_subagent_wire_event_types
from soothe_sdk.core.verbosity import VerbosityTier
from soothe_sdk.plugin.registry import register_event

# Event type constants defined locally (self-contained pattern, RFC-0018)
SUBAGENT_BROWSER_USE_STARTED = "soothe.subagent.browser_use.started"
SUBAGENT_BROWSER_USE_COMPLETED = "soothe.subagent.browser_use.completed"
SUBAGENT_BROWSER_USE_STEP_COMPLETED = "soothe.subagent.browser_use.step.completed"

# Register wire types for emission allowlisting
register_subagent_wire_event_types(
    SUBAGENT_BROWSER_USE_STARTED,
    SUBAGENT_BROWSER_USE_COMPLETED,
    SUBAGENT_BROWSER_USE_STEP_COMPLETED,
)


class BrowserUseStartedEvent(SubagentEvent):
    """BrowserUse run started."""

    type: Literal["soothe.subagent.browser_use.started"] = SUBAGENT_BROWSER_USE_STARTED
    task_preview: str = ""

    model_config = ConfigDict(extra="allow")


class BrowserUseCompletedEvent(SubagentEvent):
    """BrowserUse run finished."""

    type: Literal["soothe.subagent.browser_use.completed"] = SUBAGENT_BROWSER_USE_COMPLETED
    duration_ms: int = 0
    success: bool = True
    summary: str = ""

    model_config = ConfigDict(extra="allow")


class BrowserUseStepCompletedEvent(SubagentEvent):
    """One browser automation step completed (metadata only)."""

    type: Literal["soothe.subagent.browser_use.step.completed"] = (
        SUBAGENT_BROWSER_USE_STEP_COMPLETED
    )
    step_index: int = 0
    url: str = ""
    title: str = ""
    action_preview: str = ""
    status: str = ""  # e.g. running / done

    model_config = ConfigDict(extra="allow")


register_event(
    BrowserUseStartedEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="BrowserUse: {task_preview}",
)
register_event(
    BrowserUseCompletedEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="BrowserUse done ({duration_ms}ms)",
)
register_event(
    BrowserUseStepCompletedEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="Step {step_index}: {action_preview}",
)

__all__ = [
    "SUBAGENT_BROWSER_USE_COMPLETED",
    "SUBAGENT_BROWSER_USE_STARTED",
    "SUBAGENT_BROWSER_USE_STEP_COMPLETED",
    "BrowserUseCompletedEvent",
    "BrowserUseStartedEvent",
    "BrowserUseStepCompletedEvent",
]
