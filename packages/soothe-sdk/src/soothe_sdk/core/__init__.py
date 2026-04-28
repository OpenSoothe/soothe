"""Core domain concepts: events, exceptions, verbosity types.

This package provides the foundational types and concepts used throughout
the Soothe SDK and daemon server.
"""

__all__ = [
    # Events
    "SootheEvent",
    "LifecycleEvent",
    "ProtocolEvent",
    "SubagentEvent",
    "OutputEvent",
    "ErrorEvent",
    # Event type constants - plan
    "PLAN_CREATED",
    "PLAN_STEP_STARTED",
    "PLAN_STEP_COMPLETED",
    # Thread lifecycle (DEBUG/DETAILED)
    "THREAD_CREATED",
    "THREAD_RESUMED",
    "THREAD_COMPLETED",
    "THREAD_ERROR",
    # Tool (DEBUG/DETAILED)
    "TOOL_STARTED",
    "TOOL_COMPLETED",
    "TOOL_ERROR",
    # Agent loop (DEBUG)
    "AGENT_LOOP_STARTED",
    "AGENT_LOOP_ITERATION",
    "AGENT_LOOP_COMPLETED",
    # Message (DETAILED)
    "MESSAGE_RECEIVED",
    "MESSAGE_SENT",
    # Output
    "CHITCHAT_RESPONSE",
    "QUIZ_RESPONSE",
    "GOAL_COMPLETION_STREAMING",
    "GOAL_COMPLETION_RESPONDED",
    "AUTONOMOUS_GOAL_COMPLETION",
    # Constants
    "DEFAULT_AGENT_LOOP_MAX_ITERATIONS",
    # Exceptions
    "PluginError",
    "DiscoveryError",
    "ValidationError",
    "DependencyError",
    "InitializationError",
    "ToolCreationError",
    "SubagentCreationError",
    "ConfigurationError",
    # Types
    "VerbosityLevel",
    # Verbosity
    "VerbosityTier",
    "should_show",
]

from soothe_sdk.core.events import (
    AGENT_LOOP_COMPLETED,
    AGENT_LOOP_ITERATION,
    AGENT_LOOP_STARTED,
    AUTONOMOUS_GOAL_COMPLETION,
    CHITCHAT_RESPONSE,
    DEFAULT_AGENT_LOOP_MAX_ITERATIONS,
    GOAL_COMPLETION_RESPONDED,
    GOAL_COMPLETION_STREAMING,
    MESSAGE_RECEIVED,
    MESSAGE_SENT,
    PLAN_CREATED,
    PLAN_STEP_COMPLETED,
    PLAN_STEP_STARTED,
    QUIZ_RESPONSE,
    THREAD_COMPLETED,
    THREAD_CREATED,
    THREAD_ERROR,
    THREAD_RESUMED,
    TOOL_COMPLETED,
    TOOL_ERROR,
    TOOL_STARTED,
    ErrorEvent,
    LifecycleEvent,
    OutputEvent,
    ProtocolEvent,
    SootheEvent,
    SubagentEvent,
)
from soothe_sdk.core.exceptions import (
    ConfigurationError,
    DependencyError,
    DiscoveryError,
    InitializationError,
    PluginError,
    SubagentCreationError,
    ToolCreationError,
    ValidationError,
)
from soothe_sdk.core.types import VerbosityLevel
from soothe_sdk.core.verbosity import VerbosityTier, should_show
