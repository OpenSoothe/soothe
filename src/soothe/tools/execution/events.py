"""Execution tool events.

This module defines events for execution tools (run_command, run_python, run_background, kill_process).
Events are self-registered at module load time.
"""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict

from soothe.core.base_events import ToolEvent


class CommandStartedEvent(ToolEvent):
    """Command execution started event."""

    type: Literal["soothe.tool.execution.command_started"] = "soothe.tool.execution.command_started"
    tool: str = "run_command"
    command: str = ""
    timeout: int | None = None

    model_config = ConfigDict(extra="allow")


class CommandCompletedEvent(ToolEvent):
    """Command execution completed event."""

    type: Literal["soothe.tool.execution.command_completed"] = "soothe.tool.execution.command_completed"
    tool: str = "run_command"
    command: str = ""
    exit_code: int = 0
    duration_ms: int = 0

    model_config = ConfigDict(extra="allow")


class CommandFailedEvent(ToolEvent):
    """Command execution failed event."""

    type: Literal["soothe.tool.execution.command_failed"] = "soothe.tool.execution.command_failed"
    tool: str = "run_command"
    command: str = ""
    error: str = ""
    timeout_occurred: bool = False

    model_config = ConfigDict(extra="allow")


class CommandTimeoutEvent(ToolEvent):
    """Command execution timeout event."""

    type: Literal["soothe.tool.execution.command_timeout"] = "soothe.tool.execution.command_timeout"
    tool: str = "run_command"
    command: str = ""
    timeout_seconds: int = 0

    model_config = ConfigDict(extra="allow")


class PythonExecutionStartedEvent(ToolEvent):
    """Python execution started event."""

    type: Literal["soothe.tool.execution.python_started"] = "soothe.tool.execution.python_started"
    session_id: str = ""

    model_config = ConfigDict(extra="allow")


class PythonExecutionCompletedEvent(ToolEvent):
    """Python execution completed event."""

    type: Literal["soothe.tool.execution.python_completed"] = "soothe.tool.execution.python_completed"
    session_id: str = ""
    success: bool = False

    model_config = ConfigDict(extra="allow")


class BackgroundProcessStartedEvent(ToolEvent):
    """Background process started event."""

    type: Literal["soothe.tool.execution.background_started"] = "soothe.tool.execution.background_started"
    tool: str = "run_background"
    command: str = ""
    pid: int = 0

    model_config = ConfigDict(extra="allow")


class ProcessKilledEvent(ToolEvent):
    """Process killed event."""

    type: Literal["soothe.tool.execution.process_killed"] = "soothe.tool.execution.process_killed"
    tool: str = "kill_process"
    pid: int = 0

    model_config = ConfigDict(extra="allow")


class ShellRecoveryEvent(ToolEvent):
    """Shell recovery event."""

    type: Literal["soothe.tool.execution.shell_recovery"] = "soothe.tool.execution.shell_recovery"
    tool: str = "run_command"
    reason: str = ""

    model_config = ConfigDict(extra="allow")


# Register all execution events with the global registry
from soothe.core.event_catalog import register_event  # noqa: E402
from soothe.core.verbosity_tier import VerbosityTier  # noqa: E402

register_event(
    CommandStartedEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="Running: {command}",
)
register_event(
    CommandCompletedEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="Command completed (exit={exit_code})",
)
register_event(
    CommandFailedEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="Command failed: {error}",
)
register_event(
    CommandTimeoutEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="Command timed out after {timeout_seconds}s",
)
register_event(
    PythonExecutionStartedEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="Running Python code (session={session_id})",
)
register_event(
    PythonExecutionCompletedEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="Python execution: {success}",
)
register_event(
    BackgroundProcessStartedEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="Background process: PID {pid}",
)
register_event(
    ProcessKilledEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="Killed process {pid}",
)
register_event(
    ShellRecoveryEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="Shell recovered: {reason}",
)

# Event type constants for convenient imports
TOOL_EXECUTION_COMMAND_STARTED = "soothe.tool.execution.command_started"
TOOL_EXECUTION_COMMAND_COMPLETED = "soothe.tool.execution.command_completed"
TOOL_EXECUTION_COMMAND_FAILED = "soothe.tool.execution.command_failed"
TOOL_EXECUTION_COMMAND_TIMEOUT = "soothe.tool.execution.command_timeout"
TOOL_EXECUTION_PYTHON_STARTED = "soothe.tool.execution.python_started"
TOOL_EXECUTION_PYTHON_COMPLETED = "soothe.tool.execution.python_completed"
TOOL_EXECUTION_BACKGROUND_STARTED = "soothe.tool.execution.background_started"
TOOL_EXECUTION_PROCESS_KILLED = "soothe.tool.execution.process_killed"
TOOL_EXECUTION_SHELL_RECOVERY = "soothe.tool.execution.shell_recovery"

__all__ = [
    # Constants first (alphabetically)
    "TOOL_EXECUTION_BACKGROUND_STARTED",
    "TOOL_EXECUTION_COMMAND_COMPLETED",
    "TOOL_EXECUTION_COMMAND_FAILED",
    "TOOL_EXECUTION_COMMAND_STARTED",
    "TOOL_EXECUTION_COMMAND_TIMEOUT",
    "TOOL_EXECUTION_PROCESS_KILLED",
    "TOOL_EXECUTION_PYTHON_COMPLETED",
    "TOOL_EXECUTION_PYTHON_STARTED",
    "TOOL_EXECUTION_SHELL_RECOVERY",
    # Event classes (alphabetically)
    "BackgroundProcessStartedEvent",
    "CommandCompletedEvent",
    "CommandFailedEvent",
    "CommandStartedEvent",
    "CommandTimeoutEvent",
    "ProcessKilledEvent",
    "PythonExecutionCompletedEvent",
    "PythonExecutionStartedEvent",
    "ShellRecoveryEvent",
]
