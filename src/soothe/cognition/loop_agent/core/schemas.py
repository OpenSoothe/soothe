"""Schemas for LoopAgent structured outputs.

This module defines structured schemas for the PLAN → ACT → JUDGE loop:
- AgentDecision: LLM's decision (tool call or final answer)
- JudgeResult: LLM's judgment after tool execution
- ToolOutput: Structured tool return value

These schemas enable reliable LLM-based evaluation replacing text patterns.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class AgentDecision(BaseModel):
    """LLM's decision on next action in the agentic loop.

    The LLM can either:
    1. Call a tool (type="tool")
    2. Return a final answer (type="final")

    This structured decision replaces implicit tool calling,
    enabling explicit control over the planning phase.

    Attributes:
        type: "tool" or "final"
        tool: Tool name (if type="tool")
        args: Tool arguments (if type="tool")
        reasoning: LLM's rationale for this decision
        answer: Final answer (if type="final")

    Example:
        >>> decision = AgentDecision(
        ...     type="tool",
        ...     tool="read_file",
        ...     args={"path": "/tmp/test.txt"},
        ...     reasoning="Need to read the file to answer the question",
        ... )
    """

    type: Literal["tool", "final"]
    tool: str | None = Field(None, description="Tool name if type='tool'")
    args: dict[str, Any] | None = Field(None, description="Tool arguments if type='tool'")
    reasoning: str = Field(..., description="LLM's rationale for this decision")
    answer: str | None = Field(None, description="Final answer if type='final'")

    @model_validator(mode="after")
    def validate_decision(self) -> AgentDecision:
        """Validate that tool decisions have required fields."""
        if self.type == "tool":
            if not self.tool:
                raise ValueError("Tool decision requires 'tool' field")
        elif self.type == "final" and not self.answer:
            raise ValueError("Final decision requires 'answer' field")
        return self

    def is_tool_call(self) -> bool:
        """Check if this decision is a tool call."""
        return self.type == "tool"

    def is_final(self) -> bool:
        """Check if this decision is a final answer."""
        return self.type == "final"


class JudgeResult(BaseModel):
    """LLM's judgment after evaluating tool execution result.

    The judge decides what action to take next:
    - "continue": Keep going with next iteration
    - "retry": Retry the current step with adjustments
    - "replan": Trigger higher-level plan revision
    - "done": Task complete, return final answer

    This structured judgment replaces text pattern matching
    ("done", "complete", etc.) with explicit status codes.

    Attributes:
        status: Next action ("continue", "retry", "replan", "done")
        reason: Explanation for the judgment
        next_hint: Hint for retry (if status="retry")
        final_answer: Final answer (if status="done")
        confidence: Judge's confidence (0.0-1.0)

    Example:
        >>> judgment = JudgeResult(
        ...     status="done",
        ...     reason="Found the answer in the file",
        ...     final_answer="The file contains 42 lines",
        ...     confidence=0.95,
        ... )
    """

    status: Literal["continue", "retry", "replan", "done"]
    reason: str = Field(..., description="Explanation for the judgment")
    next_hint: str | None = Field(None, description="Hint for retry if status='retry'")
    final_answer: str | None = Field(None, description="Final answer if status='done'")
    confidence: float | None = Field(None, ge=0.0, le=1.0, description="Judge's confidence (0.0-1.0)")

    def should_continue(self) -> bool:
        """Check if loop should continue."""
        return self.status == "continue"

    def should_retry(self) -> bool:
        """Check if current step should be retried."""
        return self.status == "retry"

    def should_replan(self) -> bool:
        """Check if higher-level plan should be revised."""
        return self.status == "replan"

    def is_done(self) -> bool:
        """Check if task is complete."""
        return self.status == "done"


class ToolOutput(BaseModel):
    """Structured return value from tool execution.

    All tools must return this structured output for reliable
    judgment. This replaces plain string returns and enables:

    1. Explicit success/failure detection
    2. Error classification (transient vs permanent)
    3. Silent failure detection
    4. Structured data extraction

    Attributes:
        success: Whether tool execution succeeded
        data: Result data (structure depends on tool)
        error: Error message (if success=False)
        error_type: Error classification ("transient", "permanent", "user_error")

    Example:
        >>> output = ToolOutput(success=True, data={"lines": 42, "content": "..."}, error=None, error_type=None)
    """

    success: bool = Field(..., description="Whether tool execution succeeded")
    data: Any | None = Field(None, description="Result data")
    error: str | None = Field(None, description="Error message if failed")
    error_type: Literal["transient", "permanent", "user_error"] | None = Field(None, description="Error classification")

    @classmethod
    def ok(cls, data: Any, **metadata: Any) -> ToolOutput:
        """Create a successful tool output.

        Args:
            data: Result data
            **metadata: Additional metadata to include in data

        Returns:
            ToolOutput with success=True

        Example:
            >>> output = ToolOutput.ok({"count": 42})
        """
        if metadata and isinstance(data, dict):
            data = {**data, **metadata}
        return cls(success=True, data=data, error=None, error_type=None)

    @classmethod
    def fail(
        cls,
        error: str,
        error_type: Literal["transient", "permanent", "user_error"] = "permanent",
    ) -> ToolOutput:
        """Create a failed tool output.

        Args:
            error: Error message
            error_type: Error classification

        Returns:
            ToolOutput with success=False

        Example:
            >>> output = ToolOutput.fail("File not found", "user_error")
        """
        return cls(success=False, data=None, error=error, error_type=error_type)

    def is_silent_failure(self) -> bool:
        """Detect silent failure (success but no data)."""
        return self.success and self.data is None
