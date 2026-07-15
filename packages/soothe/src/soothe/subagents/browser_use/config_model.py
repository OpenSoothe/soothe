"""Typed YAML for the browser_use community subagent (IG-415)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class BrowserUseSubagentConfig(BaseModel):
    """Configuration for the browser_use subagent runtime.

    Args:
        runtime_dir: Base directory for browser runtime files.
        downloads_dir: Directory for browser downloads.
        user_data_dir: Persistent browser profile directory.
        extensions_dir: Browser extensions directory.
        cleanup_on_exit: Clean up temporary files when session ends.
        disable_extensions: Disable browser extensions.
        disable_cloud: Disable browser-use cloud service.
        disable_telemetry: Disable usage telemetry.
        enable_existing_browser: Allow connecting to existing Chrome instance via CDP.
        browser_start_timeout: Timeout in seconds for browser launch events.
        profile_mode: Browser profile lifecycle. ``persistent`` reuses a shared
            profile across invocations (keeps cookies/sessions). ``ephemeral``
            creates a fresh UUID-named profile per invocation and deletes it on
            exit -- safe for concurrent browser tasks.
        max_steps: Maximum browser automation steps per delegated task (browser-use
            loop). Override via YAML ``subagents.browser_use.config.max_steps``.
        synthesis_role: Router role used for post-run result synthesis/quality gate.
        synthesis_timeout_sec: Timeout budget for synthesis LLM call.
    """

    max_steps: int = Field(
        default=10, ge=1, description="Maximum browser automation steps per task."
    )
    runtime_dir: str = ""
    downloads_dir: str = ""
    user_data_dir: str = ""
    extensions_dir: str = ""
    cleanup_on_exit: bool = True
    disable_extensions: bool = True
    disable_cloud: bool = True
    disable_telemetry: bool = True
    enable_existing_browser: bool = True
    browser_start_timeout: int = 90
    profile_mode: Literal["persistent", "ephemeral"] = "ephemeral"
    synthesis_role: str = Field(
        default="default",
        description="Router role for browser_use result synthesis/quality gate.",
    )
    synthesis_timeout_sec: float = Field(
        default=30.0,
        ge=5.0,
        le=120.0,
        description="Timeout in seconds for browser_use synthesis call.",
    )


__all__ = ["BrowserUseSubagentConfig"]
