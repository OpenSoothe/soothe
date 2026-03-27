"""LoopAgent - Layer 2 reflection loop with PLAN → ACT → JUDGE.

This module implements the agentic loop (RFC-0008):
- Core: State management and schemas
- Integration: Cross-layer communication (goal delegation, context borrowing)
- Execution: Judge logic and failure detection

Public API:
- LoopState, StepRecord: State models
- AgentDecision, JudgeResult, ToolOutput: Schemas
- JudgeEngine: LLM-based judgment
- FailureDetector: Guardrails and failure modes
"""

from soothe.cognition.loop_agent.core.schemas import (
    AgentDecision,
    JudgeResult,
    ToolOutput,
)
from soothe.cognition.loop_agent.core.state import (
    LoopState,
    StepRecord,
)

__all__ = [
    "AgentDecision",
    "JudgeResult",
    "LoopState",
    "StepRecord",
    "ToolOutput",
]
