"""RFC-204: Criticality Evaluator for MUST goal confirmation.

Determines whether a proposed goal requires user approval before creation.
Uses rule-based signals + optional LLM judgment.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

logger = logging.getLogger(__name__)

CriticalityLevel = Literal["must", "should", "nice"]

# Thresholds
_PRIORITY_MUST_THRESHOLD = 90
_MAX_DESCRIPTION_LENGTH = 500
_MUST_REASONS_THRESHOLD = 2

# Rule-based signals that trigger MUST level
HIGH_RISK_KEYWORDS = frozenset(
    {
        "deploy",
        "delete",
        "drop",
        "destroy",
        "wipe",
        "erase",
        "migrate",
        "provision",
        "format",
        "shutdown",
        "kill",
        "root",
        "admin",
        "credential",
        "secret",
        "key",
        "billing",
        "payment",
        "subscription",
        "invoice",
    }
)


@dataclass
class CriticalityResult:
    """Result of criticality evaluation."""

    level: CriticalityLevel
    reasons: list[str]
    requires_confirmation: bool = False

    @property
    def is_must(self) -> bool:
        """Check if level is 'must' (requires confirmation)."""
        return self.level == "must"

    @property
    def is_should(self) -> bool:
        """Check if level is 'should' (recommended review)."""
        return self.level == "should"


async def _evaluate_with_llm(
    description: str,
    priority: int,
    model: BaseChatModel,
    config: Any | None = None,  # IG-143: Add config for tracing
) -> tuple[str, list[str]]:
    """Evaluate goal criticality using an LLM.

    Prompts the LLM to assess risk across multiple dimensions:
    external systems impact, security implications, resource cost,
    data modification, irreversibility, and dependency breadth.

    Args:
        description: Goal description text.
        priority: Goal priority (0-100).
        model: Chat model to use for evaluation.
        config: Optional SootheConfig for LLM tracing support.

    Returns:
        Tuple of (risk_level, reasons) where risk_level is "high", "medium", or "low".
    """
    # IG-143: Wrap model with tracing if enabled
    from soothe.middleware._utils import create_llm_call_metadata

    if config and hasattr(config, "llm_tracing") and config.llm_tracing.enabled:
        from soothe.middleware._wrapper import LLMTracingWrapper

        model = LLMTracingWrapper(model)

    prompt_text = (
        "You are evaluating whether a proposed autonomous agent task requires human approval.\n"
        f"\nProposed task: {description}\n"
        f"\nPriority: {priority}/100\n"
        "\nAssess the risk across these dimensions:\n"
        "  - Affects external systems (APIs, databases, services)\n"
        "  - Security implications (credentials, access, data exposure)\n"
        "  - High resource cost (compute, time, API calls)\n"
        "  - Modifies user data or external state\n"
        "  - Irreversible operations\n"
        "  - Broad dependency chain\n"
        "\nRespond with exactly two lines:\n"
        "RISK_LEVEL: <high|medium|low>\n"
        "REASONS: <comma-separated list of specific concerns>\n"
    )

    try:
        response = await model.ainvoke(
            prompt_text,
            config={
                "metadata": create_llm_call_metadata(
                    purpose="criticality_assessment",
                    component="cognition.criticality",
                    phase="pre-goal",
                )
            },
        )
        content = response.content.strip() if hasattr(response, "content") else ""

        risk_level = "medium"
        reasons: list[str] = []

        for line in content.splitlines():
            if line.upper().startswith("RISK_LEVEL:"):
                risk_level = line.split(":", 1)[1].strip().lower()
            elif line.upper().startswith("REASONS:"):
                reasons = [r.strip() for r in line.split(":", 1)[1].split(",") if r.strip()]

        if not reasons:
            reasons = ["LLM identified concerns without specifics"]
        return risk_level, reasons  # noqa: TRY300
    except Exception:
        logger.debug("LLM criticality evaluation failed, using medium risk", exc_info=True)
        return "medium", ["LLM evaluation unavailable"]


def evaluate_criticality(
    description: str,
    priority: int = 50,
    *,
    use_llm: bool = False,  # noqa: ARG001
    model: BaseChatModel | None = None,  # noqa: ARG001
) -> CriticalityResult:
    """RFC-204: Evaluate if a proposed goal requires user confirmation.

    Combines rule-based signals with optional LLM judgment.

    Args:
        description: Goal description text.
        priority: Goal priority (0-100).
        use_llm: Whether to apply LLM-based evaluation.
            Note: The sync version does not await LLM calls;
            use ``evaluate_criticality_async()`` for full LLM support.
        model: Optional chat model for LLM evaluation.

    Returns:
        CriticalityResult with level, reasons, and confirmation flag.

    Note:
        For async callers, prefer ``evaluate_criticality_async()`` which
        properly awaits LLM evaluation.
    """
    reasons: list[str] = []
    desc_lower = description.lower()

    # Rule-based signals
    if _matches_risk_keywords(desc_lower, HIGH_RISK_KEYWORDS):
        reasons.append("Contains high-risk operation keywords")

    if priority >= _PRIORITY_MUST_THRESHOLD:
        reasons.append(f"Very high priority (>={_PRIORITY_MUST_THRESHOLD})")

    if len(description) > _MAX_DESCRIPTION_LENGTH:
        reasons.append(f"Large scope goal (>{_MAX_DESCRIPTION_LENGTH} chars)")

    # Determine level from rules
    if len(reasons) >= _MUST_REASONS_THRESHOLD:
        return CriticalityResult(
            level="must",
            reasons=reasons,
            requires_confirmation=True,
        )

    if reasons:
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


async def evaluate_criticality_async(
    description: str,
    priority: int = 50,
    *,
    use_llm: bool = False,
    model: BaseChatModel | None = None,
    config: Any | None = None,  # IG-143: Add config for tracing
) -> CriticalityResult:
    """Async version of ``evaluate_criticality`` with full LLM support.

    Args:
        description: Goal description text.
        priority: Goal priority (0-100).
        use_llm: Whether to apply LLM-based evaluation.
        model: Chat model for LLM evaluation. Required when use_llm=True.
        config: Optional SootheConfig for LLM tracing support.

    Returns:
        CriticalityResult with level, reasons, and confirmation flag.
    """
    reasons: list[str] = []
    desc_lower = description.lower()

    # Rule-based signals
    if _matches_risk_keywords(desc_lower, HIGH_RISK_KEYWORDS):
        reasons.append("Contains high-risk operation keywords")

    if priority >= _PRIORITY_MUST_THRESHOLD:
        reasons.append(f"Very high priority (>={_PRIORITY_MUST_THRESHOLD})")

    if len(description) > _MAX_DESCRIPTION_LENGTH:
        reasons.append(f"Large scope goal (>{_MAX_DESCRIPTION_LENGTH} chars)")

    # Determine level from rules
    if len(reasons) >= _MUST_REASONS_THRESHOLD:
        return CriticalityResult(
            level="must",
            reasons=reasons,
            requires_confirmation=True,
        )

    if reasons:
        return CriticalityResult(
            level="should",
            reasons=reasons,
            requires_confirmation=True,
        )

    # LLM-based evaluation if available and no rule triggers
    if use_llm and model:
        try:
            risk_level, llm_reasons = await _evaluate_with_llm(
                description, priority, model, config=config
            )  # IG-143
        except Exception:
            risk_level, llm_reasons = "medium", ["LLM evaluation unavailable"]

        if risk_level == "high":
            return CriticalityResult(
                level="must",
                reasons=llm_reasons,
                requires_confirmation=True,
            )
        if risk_level == "medium":
            return CriticalityResult(
                level="should",
                reasons=llm_reasons,
                requires_confirmation=True,
            )

    return CriticalityResult(
        level="nice",
        reasons=[],
        requires_confirmation=False,
    )


def _matches_risk_keywords(text: str, keywords: frozenset[str]) -> bool:
    """Check if text contains any high-risk keywords.

    Args:
        text: Text to scan (should be lowercased).
        keywords: Set of keywords to match.

    Returns:
        True if any keyword is found.
    """
    return any(kw in text for kw in keywords)
