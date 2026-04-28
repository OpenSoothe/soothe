"""Response categorization for goal completion (RFC-615, IG-297).

Determines response length category and goal type from execution evidence,
separating classification logic from execution and orchestration.
"""

from __future__ import annotations

import logging

from langchain_core.language_models.chat_models import BaseChatModel

from soothe.cognition.agent_loop.analysis.synthesis import SynthesisPhase
from soothe.cognition.agent_loop.policies.response_length_policy import (
    ResponseLengthCategory,
    calculate_evidence_metrics,
    determine_response_length,
)
from soothe.cognition.agent_loop.state.schemas import LoopState, PlanResult

logger = logging.getLogger(__name__)


class ResponseCategorizer:
    """Determines response length category and goal type from execution evidence.

    Responsibilities:
    - Calculate evidence metrics (volume, diversity)
    - Extract intent classification from state
    - Classify goal type from evidence patterns
    - Determine response length category

    Separation of concerns:
    - Classification only (no execution logic)
    - Depends on synthesis module for goal type classification
    - Depends on response_length_policy for categorization
    """

    def __init__(self, planner_model: BaseChatModel) -> None:
        """Initialize categorizer with planner model for goal type classification.

        Args:
            planner_model: Model instance for SynthesisPhase goal type classification.
        """
        self.planner_model = planner_model

    def categorize(self, state: LoopState, plan_result: PlanResult) -> ResponseLengthCategory:
        """Determine response length category from execution evidence.

        Args:
            state: Loop state with step results and intent metadata.
            plan_result: Plan result (reserved for future use).

        Returns:
            ResponseLengthCategory with min_words, max_words bounds.
        """
        _ = plan_result  # Reserved for future hints

        # Calculate evidence metrics
        evidence_volume, evidence_diversity = calculate_evidence_metrics(state.step_results)

        # Determine intent and complexity
        intent_type = "new_goal"  # Default
        goal_type = "general_synthesis"  # Default
        task_complexity = "medium"  # Default

        # Extract intent classification metadata if available
        if state.intent and hasattr(state.intent, "intent_type"):
            intent_type = state.intent.intent_type
            task_complexity = getattr(state.intent, "task_complexity", "medium")

        # Classify goal type from evidence patterns (reuse synthesis logic)
        evidence_for_classification = "\n\n".join(
            r.to_evidence_string(truncate=False) for r in state.step_results if r.success
        )
        goal_type = SynthesisPhase(self.planner_model)._classify_goal_type(
            evidence_for_classification
        )

        # Determine response length
        length_category = determine_response_length(
            intent_type=intent_type,
            goal_type=goal_type,
            task_complexity=task_complexity,
            evidence_volume=evidence_volume,
            evidence_diversity=evidence_diversity,
        )

        logger.info(
            "Response length category: %s (%d-%d words, intent=%s, goal_type=%s, evidence_volume=%d chars, diversity=%d steps)",
            length_category.value,
            length_category.min_words,
            length_category.max_words,
            intent_type,
            goal_type,
            evidence_volume,
            evidence_diversity,
        )

        return length_category
