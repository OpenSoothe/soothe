"""Browser subagent events.

This module defines events for the browser subagent.
Events are self-registered at module load time.
"""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict

from soothe.core.base_events import SubagentEvent


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

register_event(
    BrowserStepEvent,
    verbosity="subagent_progress",
    summary_template="Step {step}",
)
register_event(
    BrowserCdpEvent,
    verbosity="subagent_progress",
    summary_template="Browser CDP: {status}",
)

# Event type constants for convenient imports
SUBAGENT_BROWSER_STEP = "soothe.subagent.browser.step"
SUBAGENT_BROWSER_CDP = "soothe.subagent.browser.cdp"

__all__ = [
    "SUBAGENT_BROWSER_CDP",
    "SUBAGENT_BROWSER_STEP",
    "BrowserCdpEvent",
    "BrowserStepEvent",
]
