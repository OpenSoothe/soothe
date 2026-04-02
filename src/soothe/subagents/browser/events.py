"""Browser subagent events.

This module defines events for the browser subagent.
Events are self-registered at module load time.
"""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict

from soothe.foundation.base_events import SubagentEvent


class BrowserDispatchedEvent(SubagentEvent):
    """Browser subagent dispatched event."""

    type: Literal["soothe.subagent.browser.dispatched"] = "soothe.subagent.browser.dispatched"
    task: str = ""

    model_config = ConfigDict(extra="allow")


class BrowserCompletedEvent(SubagentEvent):
    """Browser subagent completed event."""

    type: Literal["soothe.subagent.browser.completed"] = "soothe.subagent.browser.completed"
    duration_ms: int = 0
    success: bool = True

    model_config = ConfigDict(extra="allow")


class BrowserStepEvent(SubagentEvent):
    """Browser automation step event."""

    type: Literal["soothe.subagent.browser.step"] = "soothe.subagent.browser.step"
    step: int | str = ""
    url: str = ""
    action: str = ""
    title: str = ""
    is_done: bool = False

    model_config = ConfigDict(extra="allow")


class BrowserCdpEvent(SubagentEvent):
    """Browser CDP connection event."""

    type: Literal["soothe.subagent.browser.cdp"] = "soothe.subagent.browser.cdp"
    status: str = ""
    cdp_url: str | None = None

    model_config = ConfigDict(extra="allow")


# Register all browser events with the global registry
from soothe.core.event_catalog import register_event  # noqa: E402
from soothe.foundation.verbosity_tier import VerbosityTier  # noqa: E402

# Dispatch/Complete events visible at NORMAL
register_event(
    BrowserDispatchedEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="Browser: {task}",
)
register_event(
    BrowserCompletedEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="Completed in {duration_ms}ms",
)

# IG-089: Internal browser steps at DETAILED (hidden at normal verbosity)
register_event(
    BrowserStepEvent,
    verbosity=VerbosityTier.DETAILED,
    summary_template="Step {step}",
)
register_event(
    BrowserCdpEvent,
    verbosity=VerbosityTier.DETAILED,
    summary_template="Browser CDP: {status}",
)

# Event type constants for convenient imports
SUBAGENT_BROWSER_DISPATCHED = "soothe.subagent.browser.dispatched"
SUBAGENT_BROWSER_COMPLETED = "soothe.subagent.browser.completed"
SUBAGENT_BROWSER_STEP = "soothe.subagent.browser.step"
SUBAGENT_BROWSER_CDP = "soothe.subagent.browser.cdp"

__all__ = [
    "SUBAGENT_BROWSER_CDP",
    "SUBAGENT_BROWSER_COMPLETED",
    "SUBAGENT_BROWSER_DISPATCHED",
    "SUBAGENT_BROWSER_STEP",
    "BrowserCdpEvent",
    "BrowserCompletedEvent",
    "BrowserDispatchedEvent",
    "BrowserStepEvent",
]
