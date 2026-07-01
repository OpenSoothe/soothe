"""DagVerificationReasoner - LLM-based DAG verification (RFC-625 §4).

Provides structured LLM calls for:
- Background health verification (periodic)
- Post-completion analysis (event-triggered)
- Placement analysis for new goal intake

Uses structured output parsing following BackoffReasoner pattern.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from soothe.foundation.autopilot.monitor.verifier_prompts import (
    DAG_HEALTH_VERIFICATION_PROMPT,
    GOAL_PLACEMENT_PROMPT,
    POST_COMPLETION_VERIFICATION_PROMPT,
    format_goals_detail,
    format_step_progress,
)

if TYPE_CHECKING:
    from soothe.config import SootheConfig
    from soothe.foundation.context.models import GoalNode

logger = logging.getLogger(__name__)


# ── LLM Response Models (structured output) ───────────────────────────────────────


class MergeSuggestionResponse(BaseModel):
    """LLM response for merge suggestion."""

    goal_ids: list[str]
    merged_description: str


class DecomposeSuggestionResponse(BaseModel):
    """LLM response for decomposition suggestion."""

    goal_id: str
    subgoals: list[dict[str, Any]]


class DagHealthResponse(BaseModel):
    """LLM response for DAG health verification."""

    reset_goals: list[str] = Field(default_factory=list)
    remove_goals: list[str] = Field(default_factory=list)
    merge_goals: list[MergeSuggestionResponse] = Field(default_factory=list)
    decompose_goals: list[DecomposeSuggestionResponse] = Field(default_factory=list)
    priority_adjustments: dict[str, int] = Field(default_factory=dict)
    reasoning: str


class NewGoalSuggestion(BaseModel):
    """LLM response for new goal suggestion."""

    description: str
    priority: int = 50
    depends_on: list[str] = Field(default_factory=list)


class CompletionVerificationResponse(BaseModel):
    """LLM response for post-completion analysis."""

    new_goals: list[NewGoalSuggestion] = Field(default_factory=list)
    redundant_goals: list[str] = Field(default_factory=list)
    ready_goals: list[str] = Field(default_factory=list)
    decomposition: DecomposeSuggestionResponse | None = None
    reasoning: str


class GoalPlacementResponse(BaseModel):
    """LLM response for placement analysis."""

    priority: int = Field(default=50, ge=0, le=100)
    depends_on: list[str] = Field(default_factory=list)
    informs: list[str] = Field(default_factory=list)
    merge_with: str | None = None
    complexity: str = Field(default="moderate")  # simple, moderate, complex
    reasoning: str


# ── Context input models ───────────────────────────────────────────────────────────


class DagSnapshot(BaseModel):
    """Snapshot for LLM health verification."""

    total_goals: int = 0
    active_count: int = 0
    pending_count: int = 0
    completed_count: int = 0
    failed_count: int = 0
    goals_detail: str = ""
    step_progress: str = ""

    @classmethod
    def from_goals(cls, goals: list[GoalNode]) -> DagSnapshot:
        """Build snapshot from GoalNode list."""
        goal_dicts = [
            {
                "id": g.id,
                "status": g.status,
                "priority": g.priority,
                "description": g.description,
                "depends_on": list(g.depends_on),
                "step_count": g.steps.total_steps,
                "completed_steps": g.steps.completed_steps,
                "failed_steps": g.steps.failed_steps,
            }
            for g in goals
        ]
        return cls(
            total_goals=len(goals),
            active_count=sum(1 for g in goals if g.status == "active"),
            pending_count=sum(1 for g in goals if g.status == "pending"),
            completed_count=sum(1 for g in goals if g.status == "completed"),
            failed_count=sum(1 for g in goals if g.status == "failed"),
            goals_detail=format_goals_detail(goal_dicts),
            step_progress=format_step_progress(goal_dicts),
        )


class CompletionVerificationContext(BaseModel):
    """Context for post-completion LLM analysis."""

    completed_goal_id: str
    completed_description: str
    outcome_summary: str = ""
    steps_executed: int = 0
    key_findings: list[str] = Field(default_factory=list)
    total_duration_ms: int = 0
    total_tokens_used: int = 0
    pending_goals: str = ""
    active_goals: str = ""

    @classmethod
    def from_goal(
        cls,
        goal: GoalNode,
        pending: list[GoalNode],
        active: list[GoalNode],
    ) -> CompletionVerificationContext:
        """Build context from completed goal and current DAG state."""
        pending_dicts = [
            {
                "id": g.id,
                "description": g.description[:80],
                "priority": g.priority,
                "depends_on": list(g.depends_on),
            }
            for g in pending
        ]
        active_dicts = [
            {
                "id": g.id,
                "description": g.description[:80],
                "priority": g.priority,
            }
            for g in active
        ]
        return cls(
            completed_goal_id=goal.id,
            completed_description=goal.description,
            outcome_summary=goal.report.get("summary", "") if goal.report else "",
            steps_executed=goal.steps.completed_steps,
            key_findings=list(goal.findings),
            total_duration_ms=goal.total_duration_ms,
            total_tokens_used=goal.total_tokens_used,
            pending_goals=format_goals_detail(pending_dicts),
            active_goals=format_goals_detail(active_dicts),
        )


class GoalPlacementContext(BaseModel):
    """Context for placement LLM analysis."""

    goal_description: str
    active_count: int = 0
    pending_count: int = 0
    recently_completed: int = 0
    existing_goals: str = ""

    @classmethod
    def from_description(
        cls,
        description: str,
        goals: list[GoalNode],
    ) -> GoalPlacementContext:
        """Build context for new goal placement."""
        goal_dicts = [
            {
                "id": g.id,
                "status": g.status,
                "description": g.description[:60],
                "priority": g.priority,
                "depends_on": list(g.depends_on),
            }
            for g in goals
            if g.status in ("active", "pending", "completed")
        ]
        return cls(
            goal_description=description,
            active_count=sum(1 for g in goals if g.status == "active"),
            pending_count=sum(1 for g in goals if g.status == "pending"),
            recently_completed=sum(1 for g in goals if g.status == "completed"),
            existing_goals=format_goals_detail(goal_dicts),
        )


# ── DagVerificationReasoner ───────────────────────────────────────────────────────


class DagVerificationReasoner:
    """LLM-based reasoning for DAG verification (RFC-625 §4).

    Provides structured LLM calls for:
    - Background health verification
    - Post-completion analysis
    - Placement analysis for goal intake

    Args:
        config: SootheConfig with model provider settings.

    Attributes:
        _model: LangChain chat model for reasoning.
    """

    def __init__(self, config: SootheConfig) -> None:
        """Initialize reasoner with chat model from config.

        Args:
            config: SootheConfig with model provider settings
        """
        self._model: BaseChatModel = config.create_chat_model("think")
        self._soothe_config = config

    async def verify_health(self, snapshot: DagSnapshot) -> DagHealthResponse:
        """Call LLM for background health verification.

        Args:
            snapshot: DAG snapshot with goal states and step progress.

        Returns:
            DagHealthResponse with restructuring suggestions.

        Raises:
            json.JSONDecodeError: If LLM response is not valid JSON.
        """
        prompt = DAG_HEALTH_VERIFICATION_PROMPT.format(
            total_goals=snapshot.total_goals,
            active_count=snapshot.active_count,
            pending_count=snapshot.pending_count,
            completed_count=snapshot.completed_count,
            failed_count=snapshot.failed_count,
            goals_detail=snapshot.goals_detail,
            step_progress=snapshot.step_progress,
        )

        response_text = await self._invoke_llm(
            prompt,
            system_prompt="You are an expert at analyzing goal DAGs and identifying optimization opportunities.",
        )

        return self._parse_health_response(response_text)

    async def verify_post_completion(
        self,
        context: CompletionVerificationContext,
    ) -> CompletionVerificationResponse:
        """Call LLM for post-completion analysis.

        Args:
            context: Completed goal context with DAG state.

        Returns:
            CompletionVerificationResponse with new goals, redundancy analysis.

        Raises:
            json.JSONDecodeError: If LLM response is not valid JSON.
        """
        prompt = POST_COMPLETION_VERIFICATION_PROMPT.format(
            completed_goal_id=context.completed_goal_id,
            completed_description=context.completed_description,
            outcome_summary=context.outcome_summary,
            steps_executed=context.steps_executed,
            key_findings=", ".join(context.key_findings) if context.key_findings else "none",
            total_duration_ms=context.total_duration_ms,
            total_tokens_used=context.total_tokens_used,
            pending_goals=context.pending_goals,
            active_goals=context.active_goals,
        )

        response_text = await self._invoke_llm(
            prompt,
            system_prompt="You are an expert at analyzing goal completion outcomes and determining follow-up actions.",
        )

        return self._parse_completion_response(response_text, context.completed_goal_id)

    async def analyze_placement(
        self,
        context: GoalPlacementContext,
    ) -> GoalPlacementResponse:
        """Call LLM for placement analysis.

        Args:
            context: New goal description with existing DAG state.

        Returns:
            GoalPlacementResponse with priority, dependencies, merge suggestion.

        Raises:
            json.JSONDecodeError: If LLM response is not valid JSON.
        """
        prompt = GOAL_PLACEMENT_PROMPT.format(
            goal_description=context.goal_description,
            active_count=context.active_count,
            pending_count=context.pending_count,
            recently_completed=context.recently_completed,
            existing_goals=context.existing_goals,
        )

        response_text = await self._invoke_llm(
            prompt,
            system_prompt="You are an expert at analyzing goal placement in existing DAGs for optimal scheduling.",
        )

        return self._parse_placement_response(response_text)

    # ── LLM invocation ──────────────────────────────────────────────────────────────

    async def _invoke_llm(self, prompt: str, system_prompt: str) -> str:
        """Invoke LLM with prompt and return response text.

        Args:
            prompt: User prompt content.
            system_prompt: System message for LLM role.

        Returns:
            Raw response text from LLM.
        """
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=prompt),
        ]

        from soothe.utils.llm.invoke_policy import (
            await_with_llm_call_policy,
            llm_rate_limit_config_from,
        )
        from soothe.utils.observability.langfuse import build_traced_config

        invoke_config = build_traced_config(
            self._soothe_config,
            purpose="dag_verification",
            component="autopilot.monitor.verifier_reasoner",
            phase="background",
            run_name="soothe:dag-verify",
        )

        async def _invoke() -> Any:
            return await self._model.ainvoke(messages, config=invoke_config)

        response = await await_with_llm_call_policy(
            _invoke,
            config=llm_rate_limit_config_from(self._soothe_config),
        )

        return response.content

    # ── Response parsing ────────────────────────────────────────────────────────────

    def _extract_json(self, response_text: str) -> dict:
        """Extract JSON from LLM response (handle markdown code blocks).

        Args:
            response_text: Raw LLM response.

        Returns:
            Parsed JSON dictionary.

        Raises:
            json.JSONDecodeError: If no valid JSON found.
        """
        # Handle markdown code blocks
        if "```json" in response_text:
            json_start = response_text.find("```json") + 7
            json_end = response_text.find("```", json_start)
            json_text = response_text[json_start:json_end].strip()
        elif "```" in response_text:
            json_start = response_text.find("```") + 3
            json_end = response_text.find("```", json_start)
            json_text = response_text[json_start:json_end].strip()
        else:
            json_text = response_text.strip()

        return json.loads(json_text)

    def _parse_health_response(self, response_text: str) -> DagHealthResponse:
        """Parse LLM health response into DagHealthResponse.

        Args:
            response_text: Raw LLM response.

        Returns:
            Validated DagHealthResponse.
        """
        data = self._extract_json(response_text)

        # Parse merge suggestions
        merge_goals = []
        for merge in data.get("merge_goals", []):
            merge_goals.append(
                MergeSuggestionResponse(
                    goal_ids=merge.get("goal_ids", []),
                    merged_description=merge.get("merged_description", ""),
                )
            )

        # Parse decompose suggestions
        decompose_goals = []
        for decomp in data.get("decompose_goals", []):
            decompose_goals.append(
                DecomposeSuggestionResponse(
                    goal_id=decomp.get("goal_id", ""),
                    subgoals=decomp.get("subgoals", []),
                )
            )

        return DagHealthResponse(
            reset_goals=data.get("reset_goals", []),
            remove_goals=data.get("remove_goals", []),
            merge_goals=merge_goals,
            decompose_goals=decompose_goals,
            priority_adjustments=data.get("priority_adjustments", {}),
            reasoning=data.get("reasoning", ""),
        )

    def _parse_completion_response(
        self,
        response_text: str,
        completed_goal_id: str,
    ) -> CompletionVerificationResponse:
        """Parse LLM completion response.

        Args:
            response_text: Raw LLM response.
            completed_goal_id: ID of completed goal (for dependency injection).

        Returns:
            Validated CompletionVerificationResponse.
        """
        data = self._extract_json(response_text)

        # Parse new goals
        new_goals = []
        for ng in data.get("new_goals", []):
            deps = ng.get("depends_on", [])
            # Ensure completed goal is in dependencies
            if completed_goal_id not in deps:
                deps.append(completed_goal_id)
            new_goals.append(
                NewGoalSuggestion(
                    description=ng.get("description", ""),
                    priority=ng.get("priority", 50),
                    depends_on=deps,
                )
            )

        # Parse decomposition
        decomposition = None
        decomp_data = data.get("decomposition")
        if decomp_data:
            decomposition = DecomposeSuggestionResponse(
                goal_id=decomp_data.get("goal_id", completed_goal_id),
                subgoals=decomp_data.get("subgoals", []),
            )

        return CompletionVerificationResponse(
            new_goals=new_goals,
            redundant_goals=data.get("redundant_goals", []),
            ready_goals=data.get("ready_goals", []),
            decomposition=decomposition,
            reasoning=data.get("reasoning", ""),
        )

    def _parse_placement_response(self, response_text: str) -> GoalPlacementResponse:
        """Parse LLM placement response.

        Args:
            response_text: Raw LLM response.

        Returns:
            Validated GoalPlacementResponse.
        """
        data = self._extract_json(response_text)

        return GoalPlacementResponse(
            priority=data.get("priority", 50),
            depends_on=data.get("depends_on", []),
            informs=data.get("informs", []),
            merge_with=data.get("merge_with"),
            complexity=data.get("complexity", "moderate"),
            reasoning=data.get("reasoning", ""),
        )
