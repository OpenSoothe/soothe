"""Error types for the unified interrupt relay."""

from __future__ import annotations


class RelayError(Exception):
    """Base class for all relay errors."""


class RelayStateConflictError(RelayError):
    """Three-way reconciliation mismatch (relay store, CE, CoreAgent).

    Attributes:
        relay_id: The clarification row's durable key.
        conflict: Diagnostic string.
    """

    def __init__(self, relay_id: str, conflict: str) -> None:
        super().__init__(f"relay {relay_id}: {conflict}")
        self.relay_id = relay_id
        self.conflict = conflict


class CoreAgentThreadEvictedError(RelayError):
    """The CoreAgent thread's suspended interrupt is gone from the checkpointer.

    Attributes:
        relay_id: The clarification row's durable key.
        thread_id: The evicted CoreAgent thread.
    """

    def __init__(self, relay_id: str, thread_id: str) -> None:
        super().__init__(
            f"relay {relay_id}: CoreAgent thread {thread_id} "
            "no longer has a resumable interrupt (evicted by checkpointer)"
        )
        self.relay_id = relay_id
        self.thread_id = thread_id


class RelayCircuitBreakerError(RelayError):
    """Consecutive retry sentinels exceeded the configured cap.

    Attributes:
        relay_id: The clarification row's durable key.
        retry_count: Consecutive retries so far.
        max_retries: The configured cap.
    """

    def __init__(self, relay_id: str, retry_count: int, max_retries: int) -> None:
        super().__init__(
            f"relay {relay_id}: circuit breaker tripped "
            f"({retry_count}/{max_retries} consecutive retries)"
        )
        self.relay_id = relay_id
        self.retry_count = retry_count
        self.max_retries = max_retries


class InvalidAnswerSchemaError(RelayError):
    """Answer failed origin-specific schema validation.

    Attributes:
        relay_id: The clarification row's durable key.
        detail: Validation error detail.
    """

    def __init__(self, relay_id: str, detail: str) -> None:
        super().__init__(f"relay {relay_id}: invalid answer schema — {detail}")
        self.relay_id = relay_id
        self.detail = detail


class RelayQueueFullError(RelayError):
    """Per-goal FIFO cap exceeded.

    Attributes:
        goal_id: The goal that hit the cap.
        max_pending: The configured cap.
    """

    def __init__(self, goal_id: str, max_pending: int) -> None:
        super().__init__(f"goal {goal_id}: clarification queue full ({max_pending} pending)")
        self.goal_id = goal_id
        self.max_pending = max_pending


__all__ = [
    "CoreAgentThreadEvictedError",
    "InvalidAnswerSchemaError",
    "RelayCircuitBreakerError",
    "RelayError",
    "RelayQueueFullError",
    "RelayStateConflictError",
]
