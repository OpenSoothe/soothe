"""DreamingDistillationReasoner - LLM-based memory distillation (RFC-625 §6).

Provides structured LLM calls for 4 distillation modes:
- Episodic: Transform goals into narrative episode summaries
- Procedure: Extract reusable procedures (Skills)
- Semantic: Update project MEMORY.md
- Profile: Extract user preferences and patterns

Uses structured output parsing following BackoffReasoner pattern.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from soothe.foundation.autopilot.monitor.dreaming_prompts import (
    EPISODIC_DISTILLATION_PROMPT,
    PROCEDURE_DISTILLATION_PROMPT,
    PROFILE_DISTILLATION_PROMPT,
    SEMANTIC_DISTILLATION_PROMPT,
    format_goals_for_episodic,
    format_ledger_summary,
    format_successful_goals,
)

if TYPE_CHECKING:
    from soothe.config import SootheConfig
    from soothe.foundation.autopilot.monitor.models import DreamingContext

logger = logging.getLogger(__name__)


# ── LLM Response Models (structured output) ───────────────────────────────────────


class EpisodeDistillationItem(BaseModel):
    """One episode extracted by LLM distillation."""

    goal_id: str
    description: str
    outcome_summary: str
    key_steps: list[str] = Field(default_factory=list)
    lessons_learned: str = ""


class EpisodicDistillationResponse(BaseModel):
    """LLM response for episodic distillation."""

    episodes: list[EpisodeDistillationItem] = Field(default_factory=list)
    reasoning: str


class ProcedureDistillationItem(BaseModel):
    """One procedure extracted by LLM distillation."""

    name: str
    description: str
    trigger_conditions: list[str] = Field(default_factory=list)
    steps: list[str] = Field(default_factory=list)
    tools_used: list[str] = Field(default_factory=list)


class ProcedureDistillationResponse(BaseModel):
    """LLM response for procedure distillation."""

    procedures: list[ProcedureDistillationItem] = Field(default_factory=list)
    reasoning: str


class SemanticDistillationResponse(BaseModel):
    """LLM response for semantic distillation."""

    additions: list[str] = Field(default_factory=list)
    modifications: dict[str, str] = Field(default_factory=dict)
    sections_to_update: list[str] = Field(default_factory=list)
    reasoning: str


class ProfileDistillationResponse(BaseModel):
    """LLM response for profile distillation."""

    communication_style: str = ""
    preferences: list[str] = Field(default_factory=list)
    recurring_goals: list[str] = Field(default_factory=list)
    expertise_level: str = "intermediate"  # beginner, intermediate, advanced, expert
    reasoning: str


# ── Context input models ───────────────────────────────────────────────────────────


class EpisodicDistillationContext(BaseModel):
    """Context for episodic LLM distillation."""

    goals_detail: str = ""
    ledger_summary: str = ""
    max_episodes: int = 10

    @classmethod
    def from_context(
        cls, context: DreamingContext, max_episodes: int = 10
    ) -> EpisodicDistillationContext:
        """Build context from DreamingContext."""
        return cls(
            goals_detail=format_goals_for_episodic(context.goals),
            ledger_summary=format_ledger_summary(context.ledger),
            max_episodes=max_episodes,
        )


class ProcedureDistillationContext(BaseModel):
    """Context for procedure LLM distillation."""

    successful_goals: str = ""
    execution_patterns: str = ""
    min_success_rate: float = 0.8

    @classmethod
    def from_context(
        cls, context: DreamingContext, min_success_rate: float = 0.8
    ) -> ProcedureDistillationContext:
        """Build context from DreamingContext."""
        return cls(
            successful_goals=format_successful_goals(context.goals),
            execution_patterns=format_ledger_summary(context.ledger),
            min_success_rate=min_success_rate,
        )


class SemanticDistillationContext(BaseModel):
    """Context for semantic LLM distillation."""

    project_context: str = ""
    goal_findings: str = ""
    current_sections: str = ""

    @classmethod
    def from_context(
        cls, context: DreamingContext, project_context: str = "", current_sections: str = ""
    ) -> SemanticDistillationContext:
        """Build context from DreamingContext."""
        # Gather findings from completed goals
        findings = []
        for g in context.goals:
            if getattr(g, "status", "") == "completed":
                goal_findings = getattr(g, "findings", [])
                for f in goal_findings:
                    findings.append(f)

        return cls(
            project_context=project_context,
            goal_findings=", ".join(findings[:20]) if findings else "no findings",
            current_sections=current_sections,
        )


class ProfileDistillationContext(BaseModel):
    """Context for profile LLM distillation."""

    user_interactions: str = ""
    goal_patterns: str = ""
    communication_samples: str = ""

    @classmethod
    def from_context(cls, context: DreamingContext) -> ProfileDistillationContext:
        """Build context from DreamingContext."""
        # Analyze goal patterns
        goal_types = {}
        for g in context.goals:
            desc = getattr(g, "description", "").lower()
            # Simple categorization
            if "debug" in desc or "fix" in desc or "error" in desc:
                goal_types["debug_and_fix"] = goal_types.get("debug_and_fix", 0) + 1
            elif "implement" in desc or "add" in desc or "create" in desc:
                goal_types["feature_implementation"] = (
                    goal_types.get("feature_implementation", 0) + 1
                )
            elif "test" in desc:
                goal_types["testing"] = goal_types.get("testing", 0) + 1
            elif "doc" in desc or "document" in desc:
                goal_types["documentation"] = goal_types.get("documentation", 0) + 1
            else:
                goal_types["other"] = goal_types.get("other", 0) + 1

        goal_patterns = "\n".join([f"  - {k}: {v}" for k, v in sorted(goal_types.items())])

        return cls(
            user_interactions=f"Total goals: {len(context.goals)}",
            goal_patterns=goal_patterns,
            communication_samples="Samples from ledger analysis",
        )


# ── DreamingDistillationReasoner ───────────────────────────────────────────────────


class DreamingDistillationReasoner:
    """LLM-based reasoning for memory distillation (RFC-625 §6).

    Provides structured LLM calls for 4 distillation modes:
    - Episodic: Goal → episode summary
    - Procedure: Success patterns → reusable skills
    - Semantic: Findings → MEMORY.md updates
    - Profile: Interaction patterns → user profile

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

    async def distill_episodic(
        self,
        context: EpisodicDistillationContext,
    ) -> EpisodicDistillationResponse:
        """Call LLM for episodic memory distillation.

        Args:
            context: Goals and ledger context for distillation.

        Returns:
            EpisodicDistillationResponse with episode summaries.

        Raises:
            json.JSONDecodeError: If LLM response is not valid JSON.
        """
        prompt = EPISODIC_DISTILLATION_PROMPT.format(
            goals_detail=context.goals_detail,
            ledger_summary=context.ledger_summary,
            max_episodes=context.max_episodes,
        )

        response_text = await self._invoke_llm(
            prompt,
            system_prompt="You are an expert at analyzing goal execution and extracting memorable episodes for future reference.",
        )

        return self._parse_episodic_response(response_text)

    async def distill_procedure(
        self,
        context: ProcedureDistillationContext,
    ) -> ProcedureDistillationResponse:
        """Call LLM for procedure/skill extraction.

        Args:
            context: Successful goals context for procedure extraction.

        Returns:
            ProcedureDistillationResponse with reusable procedures.

        Raises:
            json.JSONDecodeError: If LLM response is not valid JSON.
        """
        prompt = PROCEDURE_DISTILLATION_PROMPT.format(
            successful_goals=context.successful_goals,
            execution_patterns=context.execution_patterns,
            min_success_rate=context.min_success_rate,
        )

        response_text = await self._invoke_llm(
            prompt,
            system_prompt="You are an expert at identifying reusable procedures from successful execution patterns.",
        )

        return self._parse_procedure_response(response_text)

    async def distill_semantic(
        self,
        context: SemanticDistillationContext,
    ) -> SemanticDistillationResponse:
        """Call LLM for semantic MEMORY.md update.

        Args:
            context: Project context and goal findings.

        Returns:
            SemanticDistillationResponse with MEMORY.md updates.

        Raises:
            json.JSONDecodeError: If LLM response is not valid JSON.
        """
        prompt = SEMANTIC_DISTILLATION_PROMPT.format(
            project_context=context.project_context,
            goal_findings=context.goal_findings,
            current_sections=context.current_sections,
        )

        response_text = await self._invoke_llm(
            prompt,
            system_prompt="You are an expert at updating project documentation with actionable knowledge from execution.",
        )

        return self._parse_semantic_response(response_text)

    async def distill_profile(
        self,
        context: ProfileDistillationContext,
    ) -> ProfileDistillationResponse:
        """Call LLM for user profile extraction.

        Args:
            context: User interaction patterns and goal patterns.

        Returns:
            ProfileDistillationResponse with user profile updates.

        Raises:
            json.JSONDecodeError: If LLM response is not valid JSON.
        """
        prompt = PROFILE_DISTILLATION_PROMPT.format(
            user_interactions=context.user_interactions,
            goal_patterns=context.goal_patterns,
            communication_samples=context.communication_samples,
        )

        response_text = await self._invoke_llm(
            prompt,
            system_prompt="You are an expert at analyzing user interaction patterns to extract preferences.",
        )

        return self._parse_profile_response(response_text)

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
        from soothe.utils.observability.langfuse import SootheLangfuse

        invoke_config = SootheLangfuse(self._soothe_config).traced_llm(
            purpose="dreaming_distillation",
            component="autopilot.monitor.dreaming_reasoner",
            phase="dreaming",
            run_name="soothe:dreaming-distill",
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

    def _parse_episodic_response(self, response_text: str) -> EpisodicDistillationResponse:
        """Parse LLM episodic response.

        Args:
            response_text: Raw LLM response.

        Returns:
            Validated EpisodicDistillationResponse.
        """
        data = self._extract_json(response_text)

        episodes = []
        for ep in data.get("episodes", []):
            episodes.append(
                EpisodeDistillationItem(
                    goal_id=ep.get("goal_id", ""),
                    description=ep.get("description", ""),
                    outcome_summary=ep.get("outcome_summary", ""),
                    key_steps=ep.get("key_steps", []),
                    lessons_learned=ep.get("lessons_learned", ""),
                )
            )

        return EpisodicDistillationResponse(
            episodes=episodes,
            reasoning=data.get("reasoning", ""),
        )

    def _parse_procedure_response(self, response_text: str) -> ProcedureDistillationResponse:
        """Parse LLM procedure response.

        Args:
            response_text: Raw LLM response.

        Returns:
            Validated ProcedureDistillationResponse.
        """
        data = self._extract_json(response_text)

        procedures = []
        for proc in data.get("procedures", []):
            procedures.append(
                ProcedureDistillationItem(
                    name=proc.get("name", ""),
                    description=proc.get("description", ""),
                    trigger_conditions=proc.get("trigger_conditions", []),
                    steps=proc.get("steps", []),
                    tools_used=proc.get("tools_used", []),
                )
            )

        return ProcedureDistillationResponse(
            procedures=procedures,
            reasoning=data.get("reasoning", ""),
        )

    def _parse_semantic_response(self, response_text: str) -> SemanticDistillationResponse:
        """Parse LLM semantic response.

        Args:
            response_text: Raw LLM response.

        Returns:
            Validated SemanticDistillationResponse.
        """
        data = self._extract_json(response_text)

        return SemanticDistillationResponse(
            additions=data.get("additions", []),
            modifications=data.get("modifications", {}),
            sections_to_update=data.get("sections_to_update", []),
            reasoning=data.get("reasoning", ""),
        )

    def _parse_profile_response(self, response_text: str) -> ProfileDistillationResponse:
        """Parse LLM profile response.

        Args:
            response_text: Raw LLM response.

        Returns:
            Validated ProfileDistillationResponse.
        """
        data = self._extract_json(response_text)

        return ProfileDistillationResponse(
            communication_style=data.get("communication_style", ""),
            preferences=data.get("preferences", []),
            recurring_goals=data.get("recurring_goals", []),
            expertise_level=data.get("expertise_level", "intermediate"),
            reasoning=data.get("reasoning", ""),
        )
