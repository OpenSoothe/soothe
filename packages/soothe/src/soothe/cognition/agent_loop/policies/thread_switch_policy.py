"""Thread Switching Policy Manager (RFC-608).

Extensible policy for automatic thread switching triggers.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from soothe.cognition.agent_loop.state.checkpoint import (
    AgentLoopCheckpoint,
    CustomSwitchTrigger,
    ThreadHealthMetrics,
    ThreadSwitchPolicy,
)

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

logger = logging.getLogger(__name__)


class ThreadSwitchPolicyManager:
    """Manages thread switching policy evaluation (RFC-608)."""

    def __init__(self, policy: ThreadSwitchPolicy | None = None):
        """Initialize with policy configuration.

        Args:
            policy: Thread switching policy (defaults to default policy)
        """
        self.policy = policy or ThreadSwitchPolicy()

    def evaluate(
        self,
        checkpoint: AgentLoopCheckpoint,
        next_goal: str | None = None,
        model: BaseChatModel | None = None,
    ) -> tuple[bool, str]:
        """Evaluate all triggers for thread switching.

        Args:
            checkpoint: Loop checkpoint with thread health metrics
            next_goal: Next goal to execute (for relevance analysis)
            model: LLM model for semantic analysis (optional)

        Returns:
            Tuple of (should_switch: bool, reason: str)
        """
        if not self.policy.auto_switch_enabled:
            return False, "Auto-switch disabled"

        # Check switch limit
        if self.policy.max_thread_switches_per_loop is not None:
            if checkpoint.total_thread_switches >= self.policy.max_thread_switches_per_loop:
                return False, "Thread switch limit reached"

        metrics = checkpoint.thread_health_metrics
        reasons = []

        # Quantitative triggers

        # Message history token threshold
        if self.policy.message_history_token_threshold:
            if metrics.estimated_tokens > self.policy.message_history_token_threshold:
                reasons.append(
                    f"Message history tokens ({metrics.estimated_tokens}) > "
                    f"threshold ({self.policy.message_history_token_threshold})"
                )

        # Consecutive goal failures
        if self.policy.consecutive_goal_failure_threshold:
            if metrics.consecutive_goal_failures >= self.policy.consecutive_goal_failure_threshold:
                reasons.append(
                    f"Consecutive failures ({metrics.consecutive_goal_failures}) >= "
                    f"threshold ({self.policy.consecutive_goal_failure_threshold})"
                )

        # Checkpoint errors
        if self.policy.checkpoint_error_threshold:
            if metrics.checkpoint_errors >= self.policy.checkpoint_error_threshold:
                reasons.append(
                    f"Checkpoint errors ({metrics.checkpoint_errors}) >= "
                    f"threshold ({self.policy.checkpoint_error_threshold})"
                )

        # Subagent timeouts
        if self.policy.subagent_timeout_threshold:
            if metrics.subagent_timeout_count >= self.policy.subagent_timeout_threshold:
                reasons.append(
                    f"Subagent timeouts ({metrics.subagent_timeout_count}) >= "
                    f"threshold ({self.policy.subagent_timeout_threshold})"
                )

        # Checkpoint corruption (always trigger)
        if metrics.checkpoint_corruption_detected:
            reasons.append("Checkpoint corruption detected")

        # Semantic trigger: Goal-thread relevance analysis
        # TODO: Integrate goal_thread_relevance.analyze_goal_thread_relevance()
        # Placeholder: Will be added after goal_thread_relevance.py implementation

        # Custom triggers (extensible)
        for custom_trigger in self.policy.custom_triggers:
            if self._evaluate_custom_trigger(metrics, custom_trigger):
                reasons.append(f"Custom trigger: {custom_trigger.trigger_name}")

        should_switch = len(reasons) > 0
        reason_str = "; ".join(reasons) if reasons else "No trigger met"

        if should_switch:
            logger.info("Thread switch triggered for loop %s: %s", checkpoint.loop_id, reason_str)

        return should_switch, reason_str

    def _evaluate_custom_trigger(
        self, metrics: ThreadHealthMetrics, trigger: CustomSwitchTrigger
    ) -> bool:
        """Evaluate custom trigger condition (extensible).

        Placeholder implementation - custom triggers use predefined operators.

        Args:
            metrics: Thread health metrics
            trigger: Custom trigger configuration

        Returns:
            True if trigger condition met, False otherwise
        """
        # Placeholder for custom trigger evaluation
        # Could use safe expression parser or predefined operators
        # Example: {"trigger_condition": "custom_metrics.error_rate > threshold"}
        logger.debug("Custom trigger '%s' evaluation (placeholder)", trigger.trigger_name)

        # Safe custom metric evaluation (predefined operators only)
        try:
            # Extract metric value from custom_metrics
            metric_key = trigger.trigger_condition
            if metric_key in metrics.custom_metrics:
                metric_value = metrics.custom_metrics[metric_key]
                return metric_value > trigger.trigger_threshold
        except (KeyError, TypeError) as e:
            logger.warning("Custom trigger '%s' evaluation failed: %s", trigger.trigger_name, e)

        return False


def get_default_policy() -> ThreadSwitchPolicy:
    """Get default thread switching policy.

    Returns:
        ThreadSwitchPolicy with default thresholds
    """
    return ThreadSwitchPolicy()


def load_policy_from_config(config_dict: dict) -> ThreadSwitchPolicy:
    """Load thread switching policy from configuration.

    Args:
        config_dict: Policy configuration dictionary

    Returns:
        ThreadSwitchPolicy instance
    """
    return ThreadSwitchPolicy.model_validate(config_dict)
