"""Semantic risk assessment for goal criticality (IG-433).

LLM-based risk evaluation with embedding similarity cache.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field

from soothe.config.models import SemanticRiskConfig
from soothe.foundation.autopilot.engine.criticality import (
    _MAX_DESCRIPTION_LENGTH,
    _MUST_REASONS_THRESHOLD,
    _PRIORITY_MUST_THRESHOLD,
    CriticalityResult,
    evaluate_criticality,
)
from soothe.utils.llm.structured_invoke import invoke_structured_chat_typed
from soothe.utils.similarity import async_get_embedding_model, cosine_similarity, encode_texts

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

logger = logging.getLogger(__name__)

RiskLevel = Literal["critical", "high", "medium", "low"]

_CACHE_MAX_ENTRIES = 256
_EXACT_MATCH_BONUS = 0.15  # Boost for exact text match


class RiskAssessment(BaseModel):
    """Structured risk assessment for a proposed goal."""

    risk_level: RiskLevel
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    reasoning: str = ""
    requires_confirmation: bool = False


@dataclass
class _CachedRiskEntry:
    """Cached risk assessment with exact text and embedding."""

    description: str
    description_normalized: str  # Lowercase, stripped for exact match
    embedding: list[float]
    assessment: RiskAssessment


@dataclass
class RiskCache:
    """Instance-level cache for semantic risk assessments."""

    entries: list[_CachedRiskEntry] = field(default_factory=list)
    max_entries: int = _CACHE_MAX_ENTRIES

    def lookup_exact(self, description: str) -> RiskAssessment | None:
        """Check for exact text match first (most reliable)."""
        normalized = description.lower().strip()
        for entry in self.entries:
            if entry.description_normalized == normalized:
                return entry.assessment
        return None

    async def lookup_embedding(
        self,
        description: str,
        embedding: list[float],
        threshold: float,
    ) -> RiskAssessment | None:
        """Find best embedding match above threshold."""
        best_score = 0.0
        best: RiskAssessment | None = None
        for entry in self.entries:
            score = cosine_similarity(embedding, entry.embedding)
            # Exact match bonus: if normalized text matches, boost score
            if entry.description_normalized == description.lower().strip():
                score = min(1.0, score + _EXACT_MATCH_BONUS)
            if score > best_score:
                best_score = score
                best = entry.assessment
        if best is not None and best_score >= threshold:
            logger.debug("Risk cache hit (similarity=%.3f)", best_score)
            return best
        return None

    def store(self, description: str, embedding: list[float], assessment: RiskAssessment) -> None:
        """Store assessment in LRU-bounded cache."""
        self.entries.append(
            _CachedRiskEntry(
                description=description,
                description_normalized=description.lower().strip(),
                embedding=embedding,
                assessment=assessment,
            )
        )
        if len(self.entries) > self.max_entries:
            self.entries = self.entries[-self.max_entries :]

    def clear(self) -> None:
        """Clear all cached entries."""
        self.entries.clear()


# Shared default cache for single-process usage
_default_cache: RiskCache = RiskCache()


def get_risk_cache() -> RiskCache:
    """Return the default risk cache instance."""
    return _default_cache


def clear_risk_cache() -> None:
    """Clear the default risk cache (for tests)."""
    _default_cache.clear()


def risk_assessment_to_criticality(
    assessment: RiskAssessment,
    *,
    priority: int = 50,
    extra_reasons: list[str] | None = None,
) -> CriticalityResult:
    """Map a semantic risk assessment to RFC-204 criticality levels."""
    reasons = list(extra_reasons or [])
    if assessment.reasoning:
        reasons.append(assessment.reasoning)

    if assessment.risk_level in ("critical", "high"):
        return CriticalityResult(
            level="must",
            reasons=reasons or ["High semantic risk"],
            requires_confirmation=True,
        )

    if assessment.risk_level == "medium" or assessment.requires_confirmation:
        return CriticalityResult(
            level="should",
            reasons=reasons or ["Moderate semantic risk"],
            requires_confirmation=True,
        )

    if priority >= _PRIORITY_MUST_THRESHOLD:
        reasons.append(f"Very high priority (>={_PRIORITY_MUST_THRESHOLD})")
        return CriticalityResult(
            level="should",
            reasons=reasons,
            requires_confirmation=True,
        )

    return CriticalityResult(
        level="nice",
        reasons=[],
        requires_confirmation=False,
    )


def _collect_hard_rule_reasons(description: str, priority: int) -> list[str]:
    """Non-keyword hard rules (priority, scope size)."""
    reasons: list[str] = []
    if priority >= _PRIORITY_MUST_THRESHOLD:
        reasons.append(f"Very high priority (>={_PRIORITY_MUST_THRESHOLD})")
    if len(description) > _MAX_DESCRIPTION_LENGTH:
        reasons.append(f"Large scope goal (>{_MAX_DESCRIPTION_LENGTH} chars)")
    return reasons


def _merge_with_hard_rules(
    result: CriticalityResult,
    hard_reasons: list[str],
) -> CriticalityResult:
    """Elevate criticality when hard rules apply alongside semantic assessment."""
    if not hard_reasons:
        return result

    merged_reasons = list(dict.fromkeys([*result.reasons, *hard_reasons]))
    if len(merged_reasons) >= _MUST_REASONS_THRESHOLD:
        return CriticalityResult(
            level="must",
            reasons=merged_reasons,
            requires_confirmation=True,
        )
    if merged_reasons and result.level == "nice":
        return CriticalityResult(
            level="should",
            reasons=merged_reasons,
            requires_confirmation=True,
        )
    if merged_reasons and result.level == "should":
        return CriticalityResult(
            level="should",
            reasons=merged_reasons,
            requires_confirmation=True,
        )
    return result


async def _embed_text(text: str) -> list[float] | None:
    """Embed a single text string using the shared FastEmbed model."""
    model = await async_get_embedding_model()
    if model is None:
        return None
    try:
        import asyncio

        loop = asyncio.get_running_loop()
        vectors = await loop.run_in_executor(None, lambda: encode_texts(model, [text[:500]]))
        return vectors[0] if vectors else None
    except Exception:
        logger.debug("Risk embedding failed", exc_info=True)
        return None


def _build_risk_prompt(
    description: str,
    priority: int,
    *,
    context: str | None = None,
) -> str:
    """Build the risk assessment prompt with optional context."""
    base = (
        "You are evaluating whether a proposed autonomous agent task requires human approval.\n"
        f"\nProposed task: {description}\n"
        f"\nPriority: {priority}/100\n"
    )
    if context:
        base += f"\nContext: {context}\n"
    base += (
        "\nAssess risk across: external systems, security, resource cost, data modification, "
        "irreversibility, and dependency breadth.\n"
        "\nSet risk_level to critical for irreversible production impact, high for significant "
        "risk, medium for moderate review, low for safe read-only work.\n"
        "Set requires_confirmation true when human approval is needed before execution.\n"
        "Set confidence high (0.8+) when assessment is clear; lower (0.5-0.7) when ambiguous.\n"
    )
    return base


async def _evaluate_with_llm_structured(
    description: str,
    priority: int,
    model: BaseChatModel,
    *,
    soothe_config: Any | None = None,
    context: str | None = None,
) -> RiskAssessment:
    """Evaluate risk via LLM with structured output (single call, no fallback retry)."""
    from langchain_core.messages import HumanMessage

    from soothe.utils.observability.langfuse import build_traced_config

    prompt = _build_risk_prompt(description, priority, context=context)

    invoke_config = build_traced_config(
        soothe_config,
        purpose="semantic_risk_assessment",
        component="goal_engine.semantic_risk",
        phase="pre-goal",
        run_name="soothe:semantic-risk-assess",
    )

    return await invoke_structured_chat_typed(
        model,
        [HumanMessage(content=prompt)],
        RiskAssessment,
        config=invoke_config,
    )


async def semantic_evaluate_risk(
    description: str,
    priority: int,
    model: BaseChatModel,
    *,
    config: SemanticRiskConfig | None = None,
    soothe_config: Any | None = None,
    cache: RiskCache | None = None,
    context: str | None = None,
) -> RiskAssessment:
    """LLM-based risk assessment with embedding similarity cache.

    Args:
        description: Goal description text.
        priority: Goal priority (0-100).
        model: Chat model for LLM evaluation.
        config: Semantic risk configuration.
        soothe_config: Top-level Soothe config for tracing.
        cache: Optional cache instance (uses default if None).
        context: Optional context string (workspace, user info).

    Returns:
        RiskAssessment with risk level, confidence, and reasoning.
    """
    cfg = config or SemanticRiskConfig()
    risk_cache = cache or get_risk_cache()

    # 1. Check exact text match first (most reliable)
    if cfg.cache_enabled:
        exact_match = risk_cache.lookup_exact(description)
        if exact_match is not None:
            logger.debug("Risk cache exact match for: %s", description[:50])
            return exact_match

    # 2. Check embedding similarity cache
    embedding: list[float] | None = None
    if cfg.cache_enabled:
        embedding = await _embed_text(description)
        if embedding is not None:
            cached = await risk_cache.lookup_embedding(
                description,
                embedding,
                threshold=cfg.cache_similarity_threshold,
            )
            if cached is not None:
                return cached

    # 3. LLM evaluation
    try:
        assessment = await _evaluate_with_llm_structured(
            description,
            priority,
            model,
            soothe_config=soothe_config,
            context=context,
        )
    except Exception:
        logger.warning("Semantic risk LLM failed", exc_info=True)
        # Return low-confidence fallback assessment (caller will use keywords)
        return RiskAssessment(
            risk_level="medium",  # Safe default: triggers review
            confidence=0.0,  # Zero confidence → keyword fallback
            reasoning="LLM evaluation unavailable",
            requires_confirmation=True,
        )

    # 4. Cache the result
    if cfg.cache_enabled and embedding is not None:
        risk_cache.store(description, embedding, assessment)

    return assessment


async def evaluate_criticality_semantic(
    description: str,
    priority: int = 50,
    *,
    model: BaseChatModel | None,
    config: SemanticRiskConfig | None = None,
    soothe_config: Any | None = None,
    context: str | None = None,
) -> CriticalityResult:
    """Evaluate criticality using semantic risk assessment with keyword fallback.

    Args:
        description: Goal description text.
        priority: Goal priority (0-100).
        model: Chat model (required when semantic path is enabled).
        config: Semantic risk configuration.
        soothe_config: Top-level config for tracing.
        context: Optional context (workspace path, user info) for risk prompt.

    Returns:
        CriticalityResult from semantic assessment, hard rules, or keyword fallback.
    """
    cfg = config or SemanticRiskConfig()
    hard_reasons = _collect_hard_rule_reasons(description, priority)

    if not cfg.enabled or model is None:
        legacy = evaluate_criticality(description, priority)
        return _merge_with_hard_rules(legacy, hard_reasons)

    try:
        assessment = await semantic_evaluate_risk(
            description,
            priority,
            model,
            config=cfg,
            soothe_config=soothe_config,
            context=context,
        )

        # Low confidence → use keyword fallback instead
        if assessment.confidence < cfg.confidence_threshold:
            logger.debug(
                "Low confidence %.2f < %.2f, using keyword fallback",
                assessment.confidence,
                cfg.confidence_threshold,
            )
            legacy = evaluate_criticality(description, priority)
            return _merge_with_hard_rules(legacy, hard_reasons)

        result = risk_assessment_to_criticality(
            assessment,
            priority=priority,
            extra_reasons=hard_reasons,
        )
        return _merge_with_hard_rules(result, hard_reasons)
    except Exception:
        logger.warning("Semantic risk evaluation failed, falling back to keywords", exc_info=True)
        legacy = evaluate_criticality(description, priority)
        return _merge_with_hard_rules(legacy, hard_reasons)
