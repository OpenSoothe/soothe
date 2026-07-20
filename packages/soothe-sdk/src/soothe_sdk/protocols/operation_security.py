"""Operation security protocol for tool-level security checks (RFC-617)."""

from __future__ import annotations

from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field

OperationKind = Literal[
    "filesystem_read",
    "filesystem_write",
    "shell_execute",
    "python_execute",
    "process_control",
    "generic",
]


class OperationSecurityRequest(BaseModel):
    """Normalized security request for a single operation."""

    action_type: str
    tool_name: str | None = None
    tool_args: dict[str, Any] = Field(default_factory=dict)
    operation_kind: OperationKind = "generic"
    target_path: str | None = None
    command: str | None = None


class OperationSecurityContext(BaseModel):
    """Context for operation security evaluation."""

    thread_id: str | None = None
    workspace: str | None = None
    security_config: Any = None


class OperationSecurityDecision(BaseModel):
    """Security verdict for an operation request."""

    verdict: Literal["allow", "deny", "need_approval"]
    reason: str
    rule_id: str | None = None


@runtime_checkable
class OperationSecurityProtocol(Protocol):
    """Protocol for operation-level security checks."""

    def evaluate(
        self,
        request: OperationSecurityRequest,
        context: OperationSecurityContext,
    ) -> OperationSecurityDecision:
        """Evaluate whether an operation should be allowed."""
        ...
