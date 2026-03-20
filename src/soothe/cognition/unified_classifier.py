"""Unified two-tier LLM-based classification system.

This module provides a two-tier classification system that uses fast LLM
calls for intelligent query analysis:

- **Tier 1 (routing):** A fast routing call (~2-4s) determines chitchat
  vs. non-chitchat.  Chitchat queries are answered immediately.
- **Tier 2 (enrichment):** For non-chitchat, a separate enrichment call
  runs concurrently with pre-stream work.

Architecture Decision (RFC-0012, RFC-0014):
- Tier 1 is a tiny prompt (~100 input tokens, 2 output fields) for
  fast routing.  Chitchat queries are answered immediately.
- Tier 2 enriches with template_intent, capability_domains, etc.
  and is overlapped with memory/context work.
- Returns safe default ("medium") if LLM fails or unavailable.

Classification Tiers:
- chitchat: Simple greetings and conversational fillers (skips planning/memory)
- medium: Questions requiring research/planning, multi-step tasks (default)
- complex: Architecture design, migrations, large refactoring
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

logger = logging.getLogger(__name__)


def _looks_chinese(text: str) -> bool:
    """Return True if the text contains CJK Unified Ideographs."""
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


CapabilityDomain = Literal["research", "workspace", "execute", "data", "browse", "reason", "compose"]


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class RoutingResult(BaseModel):
    """Tier-1 fast routing result (2 fields only)."""

    task_complexity: Literal["chitchat", "medium", "complex"] = Field(description="chitchat | medium | complex")
    chitchat_response: str | None = Field(
        default=None,
        description="Friendly response when chitchat, null otherwise.",
    )
    preferred_subagent: str | None = Field(
        default=None,
        description="Preferred subagent name for direct routing (e.g., 'browser', 'claude').",
    )
    routing_hint: str | None = Field(
        default=None,
        description="Routing hint: 'subagent', 'tool', 'llm_only', etc.",
    )


class EnrichmentResult(BaseModel):
    """Tier-2 enrichment result for non-chitchat queries."""

    is_plan_only: bool = Field(default=False, description="True if user only wants planning")
    template_intent: Literal["question", "search", "analysis", "implementation", "compose"] | None = Field(
        default=None,
        description="question|search|analysis|implementation|compose|null",
    )
    capability_domains: list[CapabilityDomain] = Field(
        default_factory=list,
        description="Needed capability domains.",
    )
    reasoning: str | None = Field(default=None, description="Brief explanation")


class UnifiedClassification(BaseModel):
    """Full classification result (merged from tier-1 + tier-2)."""

    task_complexity: Literal["chitchat", "medium", "complex"] = Field(
        description="Query complexity for routing: chitchat (direct LLM), medium (subagent), complex (Claude)"
    )
    is_plan_only: bool = Field(default=False, description="True if user only wants planning without execution")
    template_intent: Literal["question", "search", "analysis", "implementation", "compose"] | None = Field(
        default=None,
        description="Template intent for planning (question|search|analysis|implementation|compose|null)",
    )
    capability_domains: list[CapabilityDomain] = Field(
        default_factory=list,
        description=(
            "Capability domains the query likely needs. "
            "Options: research (web/deep search), workspace (file ops), "
            "execute (shell/python), data (tabular/document inspection), "
            "browse (interactive web), reason (complex thinking), "
            "compose (agent/skill generation). Empty for chitchat."
        ),
    )
    chitchat_response: str | None = Field(
        default=None,
        description="Direct response for chitchat queries. Only set when task_complexity is 'chitchat'.",
    )
    preferred_subagent: str | None = Field(
        default=None,
        description="Preferred subagent name for direct routing (e.g., 'browser', 'claude').",
    )
    routing_hint: str | None = Field(
        default=None,
        description="Routing hint: 'subagent', 'tool', 'llm_only', etc.",
    )
    reasoning: str | None = Field(default=None, description="Brief explanation of classification")

    @staticmethod
    def from_tiers(routing: RoutingResult, enrichment: EnrichmentResult | None = None) -> UnifiedClassification:
        """Merge tier-1 routing and tier-2 enrichment into a full classification.

        Args:
            routing: Tier-1 routing result.
            enrichment: Tier-2 enrichment result (None for chitchat).

        Returns:
            Merged UnifiedClassification.
        """
        if enrichment is None:
            return UnifiedClassification(
                task_complexity=routing.task_complexity,
                chitchat_response=routing.chitchat_response,
                preferred_subagent=routing.preferred_subagent,
                routing_hint=routing.routing_hint,
            )
        return UnifiedClassification(
            task_complexity=routing.task_complexity,
            is_plan_only=enrichment.is_plan_only,
            template_intent=enrichment.template_intent,
            capability_domains=enrichment.capability_domains,
            chitchat_response=routing.chitchat_response,
            preferred_subagent=routing.preferred_subagent,
            routing_hint=routing.routing_hint,
            reasoning=enrichment.reasoning,
        )


# ---------------------------------------------------------------------------
# Prompts -- kept compact to minimise input/output tokens
# ---------------------------------------------------------------------------

_ROUTING_PROMPT = """\
You are {assistant_name}, created by Dr. Xiaming Chen. Classify this request and respond with JSON only.
Current time: {current_time}

Request: {query}

{{"task_complexity":"chitchat"|"medium"|"complex","chitchat_response":"string or null"}}

chitchat=greetings/thanks/fillers needing no action.
medium=research/questions/tasks/debugging (DEFAULT when uncertain).
complex=architecture design/large migrations/major refactoring.
If chitchat, set chitchat_response to a warm reply in the user's language \
mentioning you're {assistant_name} and that you were created by Dr. Xiaming Chen. Otherwise null.\
"""

_ENRICHMENT_PROMPT = """\
Classify this {complexity} request for planning. JSON only.

Request: {query}

{{"is_plan_only":bool,"template_intent":"question"|"search"|"analysis"\
|"implementation"|"compose"|null,"capability_domains":[...],"reasoning":"brief"}}

Intents: question(who/what/how), search(find/lookup), analysis(analyze/review), \
implementation(create/build), compose(create agent/skill), null(other).
Domains: research, workspace, execute, data, browse, reason, compose.
"plan only" -> is_plan_only=true. Agent/skill creation -> \
template_intent="compose", include "compose" in domains.\
"""

# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------


class UnifiedClassifier:
    """Two-tier LLM-based classification system.

    Use ``classify_routing`` for fast tier-1 routing, then
    ``classify_enrichment`` (concurrently with pre-stream I/O) for
    tier-2 enrichment metadata.

    Args:
        fast_model: Fast LLM for classification (e.g., gpt-4o-mini).
        classification_mode: "llm" or "disabled".
        assistant_name: Name used in chitchat responses.
    """

    def __init__(
        self,
        fast_model: BaseChatModel | None = None,
        classification_mode: Literal["llm", "disabled"] = "llm",
        assistant_name: str = "Soothe",
    ) -> None:
        """Initialize the unified classifier.

        Args:
            fast_model: Fast LLM for classification (e.g., gpt-4o-mini).
            classification_mode: "llm" or "disabled".
            assistant_name: Name used in chitchat responses.
        """
        self._fast_model = fast_model
        self._mode = classification_mode
        self._assistant_name = assistant_name

        if fast_model:
            self._routing_model = fast_model.with_structured_output(RoutingResult, method="json_mode")
            self._enrichment_model = fast_model.with_structured_output(EnrichmentResult, method="json_mode")
        else:
            self._routing_model = None
            self._enrichment_model = None

    # -- two-tier public API ------------------------------------------------

    async def classify_routing(self, query: str) -> RoutingResult:
        """Tier-1: fast routing classification (~2-4s).

        Returns task_complexity and, for chitchat, a piggybacked response.
        This is the minimum information needed to decide the execution path.

        Args:
            query: User input text.

        Returns:
            RoutingResult with task_complexity and optional chitchat_response.
        """
        if self._mode == "disabled" or not self._fast_model:
            return RoutingResult(task_complexity="medium")

        try:
            result = await self._llm_routing(query)
        except Exception:
            logger.exception("Tier-1 routing classification failed")
            return RoutingResult(task_complexity="medium")

        if result.task_complexity == "chitchat" and not result.chitchat_response:
            result.chitchat_response = self._fallback_chitchat_response(query)
            logger.debug("Patched missing chitchat_response for query: %s", query[:50])

        logger.debug("Tier-1 routing: task_complexity=%s", result.task_complexity)
        return result

    async def classify_enrichment(
        self,
        query: str,
        complexity: str = "medium",
    ) -> EnrichmentResult:
        """Tier-2: enrichment classification for non-chitchat queries.

        Provides template_intent, capability_domains, is_plan_only, reasoning.
        Designed to run concurrently with pre-stream I/O.

        Args:
            query: User input text.
            complexity: The task_complexity from tier-1 (for prompt context).

        Returns:
            EnrichmentResult with planning metadata.
        """
        if self._mode == "disabled" or not self._fast_model:
            return EnrichmentResult(
                capability_domains=["research", "workspace", "execute"],
                reasoning="Classification disabled",
            )

        try:
            result = await self._llm_enrichment(query, complexity)
        except Exception:
            logger.exception("Tier-2 enrichment classification failed")
            return EnrichmentResult(
                capability_domains=["research", "workspace", "execute"],
                reasoning="Enrichment failed, using defaults",
            )

        logger.debug(
            "Tier-2 enrichment: template_intent=%s, plan_only=%s, reasoning=%s",
            result.template_intent,
            result.is_plan_only,
            result.reasoning,
        )
        return result

    # -- internal LLM calls -------------------------------------------------

    async def _llm_routing(self, query: str) -> RoutingResult:
        """Tier-1 LLM call with compact routing prompt."""
        from datetime import UTC, datetime

        current_time = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
        prompt = _ROUTING_PROMPT.format(
            query=query,
            current_time=current_time,
            assistant_name=self._assistant_name,
        )
        return await self._routing_model.ainvoke(prompt)

    async def _llm_enrichment(self, query: str, complexity: str) -> EnrichmentResult:
        """Tier-2 LLM call with compact enrichment prompt."""
        prompt = _ENRICHMENT_PROMPT.format(query=query, complexity=complexity)
        return await self._enrichment_model.ainvoke(prompt)

    # -- helpers ------------------------------------------------------------

    def _fallback_chitchat_response(self, query: str) -> str:
        """Generate a default chitchat response when the LLM omits one.

        Args:
            query: Original user query (used for language detection heuristic).

        Returns:
            A friendly greeting string.
        """
        name = self._assistant_name
        if _looks_chinese(query):
            return f"你好! 我是 {name}, 由陈晓明博士创造。有什么可以帮你的吗?"
        return f"Hello! I'm {name}, created by Dr. Xiaming Chen. How can I help you today?"

    def _default_classification(self, reason: str = "Default") -> UnifiedClassification:
        """Safe default when everything fails."""
        return UnifiedClassification(
            task_complexity="medium",
            is_plan_only=False,
            capability_domains=["research", "workspace", "execute"],
            reasoning=reason,
        )
