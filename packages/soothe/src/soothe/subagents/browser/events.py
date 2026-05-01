"""Browser subagent wire events (curated ``soothe.subagent.*``, IG-338)."""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict
from soothe_sdk.core.events import SubagentEvent
from soothe_sdk.core.subagent_wire import (
    SUBAGENT_BROWSER_COMPLETED,
    SUBAGENT_BROWSER_STARTED,
    SUBAGENT_BROWSER_STEP_COMPLETED,
)
from soothe_sdk.core.verbosity import VerbosityTier

from soothe.core.events import register_event


class BrowserStartedEvent(SubagentEvent):
    """Browser run started."""

    type: Literal["soothe.subagent.browser.started"] = SUBAGENT_BROWSER_STARTED  # type: ignore[assignment]
    task_preview: str = ""

    model_config = ConfigDict(extra="allow")


class BrowserCompletedEvent(SubagentEvent):
    """Browser run finished."""

    type: Literal["soothe.subagent.browser.completed"] = SUBAGENT_BROWSER_COMPLETED  # type: ignore[assignment]
    duration_ms: int = 0
    success: bool = True

    model_config = ConfigDict(extra="allow")


class BrowserStepCompletedEvent(SubagentEvent):
    """One browser automation step completed (metadata only)."""

    type: Literal["soothe.subagent.browser.step.completed"] = SUBAGENT_BROWSER_STEP_COMPLETED  # type: ignore[assignment]
    step_index: int = 0
    url: str = ""
    title: str = ""
    action_preview: str = ""
    status: str = ""  # e.g. running / done

    model_config = ConfigDict(extra="allow")


register_event(
    BrowserStartedEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="Browser: {task_preview}",
)
register_event(
    BrowserCompletedEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="Browser done ({duration_ms}ms)",
)
register_event(
    BrowserStepCompletedEvent,
    verbosity=VerbosityTier.DETAILED,
    summary_template="Step {step_index}: {action_preview}",
)

SUBAGENT_BROWSER_DISPATCHED = SUBAGENT_BROWSER_STARTED
SUBAGENT_BROWSER_STEP = SUBAGENT_BROWSER_STEP_COMPLETED

__all__ = [
    "SUBAGENT_BROWSER_COMPLETED",
    "SUBAGENT_BROWSER_DISPATCHED",
    "SUBAGENT_BROWSER_STEP",
    "BrowserCompletedEvent",
    "BrowserStartedEvent",
    "BrowserStepCompletedEvent",
]
