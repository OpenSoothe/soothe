"""Browser subagent events."""

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


__all__ = ["BrowserCdpEvent", "BrowserStepEvent"]
