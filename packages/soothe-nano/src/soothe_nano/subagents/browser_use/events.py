"""BrowserUse subagent wire events (curated ``soothe.subagent.*``, IG-338)."""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict
from soothe_sdk.core.events import SubagentEvent
from soothe_sdk.core.verbosity import VerbosityTier

from soothe_nano.events.catalog import register_event

# Event type constants defined locally (self-contained pattern, RFC-0018)
SUBAGENT_BROWSER_USE_STARTED = "soothe.subagent.browser_use.started"
SUBAGENT_BROWSER_USE_COMPLETED = "soothe.subagent.browser_use.completed"
SUBAGENT_BROWSER_USE_STEP_COMPLETED = "soothe.subagent.browser_use.step.completed"


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
    tool_name: str = ""
    url: str = ""
    title: str = ""
    action_preview: str = ""
    status: str = "done"
    duration_ms: int = 0

    model_config = ConfigDict(extra="allow")


# Foundation register_event → NORMAL client-wire visibility for stream forwards.
register_event(
    BrowserUseStartedEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="BrowserUse: {task_preview}",
)
register_event(
    BrowserUseCompletedEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="BrowserUse: {summary}",
)
register_event(
    BrowserUseStepCompletedEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="{tool_name}: {action_preview}",
)

__all__ = [
    "SUBAGENT_BROWSER_USE_COMPLETED",
    "SUBAGENT_BROWSER_USE_STARTED",
    "SUBAGENT_BROWSER_USE_STEP_COMPLETED",
    "BrowserUseCompletedEvent",
    "BrowserUseStartedEvent",
    "BrowserUseStepCompletedEvent",
]
