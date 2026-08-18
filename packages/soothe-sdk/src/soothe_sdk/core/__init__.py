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
    # Event registry (canonical, shared across the stack)
    "EventMeta",
    "EventPriority",
    "EventRegistry",
    "REGISTRY",
    "EventHandler",
    "register_event",
    # Event type constants - plan
    "PLAN_CREATED",
    # Agent loop (DEBUG)
    "STRANGE_LOOP_STARTED",
    "STRANGE_LOOP_COMPLETED",
    "STRANGE_LOOP_STEP_STARTED",
    "STRANGE_LOOP_STEP_QUEUED",
    "STRANGE_LOOP_STEP_COMPLETED",
    "STRANGE_LOOP_PLAN_DECISION",
    "STRANGE_LOOP_PLAN_PHASE",
    "WIRED_SUBAGENT_STARTED",
    "WIRED_SUBAGENT_COMPLETED",
    "WIRED_SUBAGENT_FAILED",
    "WIRED_SUBAGENT_CANCELLED",
    # Display card wire (RFC-413)
    "CARD_CREATED",
    "CARD_UPDATED",
    "CARD_FINALIZED",
    "CARD_REPLAY_BEGIN",
    "CARD_REPLAY_END",
    "CARD_WIRE_TYPES",
    "CARD_REPLAY_WIRE_TYPES",
    "STREAM_END",
    # Protocol-primitive constants (canonical home; re-exported by nano + host)
    "ERROR",
    "LLM_RETRY_ATTEMPT",
    "MEMORY_RECALLED",
    "MEMORY_STORED",
    "POLICY_CHECKED",
    "POLICY_DENIED",
    # Constants
    "DEFAULT_STRANGE_LOOP_MAX_ITERATIONS",
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
    CARD_CREATED,
    CARD_FINALIZED,
    CARD_REPLAY_BEGIN,
    CARD_REPLAY_END,
    CARD_REPLAY_WIRE_TYPES,
    CARD_UPDATED,
    CARD_WIRE_TYPES,
    DEFAULT_STRANGE_LOOP_MAX_ITERATIONS,
    ERROR,
    LLM_RETRY_ATTEMPT,
    MEMORY_RECALLED,
    MEMORY_STORED,
    PLAN_CREATED,
    POLICY_CHECKED,
    POLICY_DENIED,
    STRANGE_LOOP_COMPLETED,
    STRANGE_LOOP_PLAN_DECISION,
    STRANGE_LOOP_PLAN_PHASE,
    STRANGE_LOOP_STARTED,
    STRANGE_LOOP_STEP_COMPLETED,
    STRANGE_LOOP_STEP_QUEUED,
    STRANGE_LOOP_STEP_STARTED,
    STREAM_END,
    WIRED_SUBAGENT_CANCELLED,
    WIRED_SUBAGENT_COMPLETED,
    WIRED_SUBAGENT_FAILED,
    WIRED_SUBAGENT_STARTED,
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
from soothe_sdk.core.registry import (
    REGISTRY,
    EventHandler,
    EventMeta,
    EventPriority,
    EventRegistry,
    register_event,
)
from soothe_sdk.core.types import VerbosityLevel
from soothe_sdk.core.verbosity import VerbosityTier, should_show
