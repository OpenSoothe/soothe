"""GoalBackoffReasoner: LLM-driven backoff reasoning for goal DAG restructuring.

RFC-200 §205-541, RFC-625: Implements LLM-based analysis for goal failure recovery,
replacing hardcoded retry logic with reasoning-based backoff decisions.

Migrated to monitor module per RFC-625. Works with GoalNode from ContextEngine.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from soothe.context.models import GoalNode
from soothe.goal_contracts import BackoffDecision, EvidenceBundle
from soothe_nano.utils.text_preview import preview_first

from soothe_autopilot.prompts import SYSTEM_BACKOFF, render_backoff_prompt

if TYPE_CHECKING:
    from soothe.config import SootheConfig

logger = logging.getLogger(__name__)


class GoalBackoffReasoner:
    """LLM-driven backoff reasoning for goal DAG restructuring.

    Analyzes goal context and evidence to decide WHERE to backoff in the goal
    DAG. Replaces hardcoded retry logic. Prompt text lives in
    ``soothe_autopilot.prompts``.

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
        self._model: BaseChatModel = config.create_chat_model(
            config.agent.autopilot.monitor_model_role
        )
        self._soothe_config = config

    async def reason_backoff(
        self,
        goal_id: str,
        goals: dict[str, GoalNode],
        failed_evidence: EvidenceBundle,
        *,
        projector: Any,
    ) -> BackoffDecision:
        """LLM analyzes full goal context and decides WHERE to backoff.

        Args:
            goal_id: Failed goal identifier.
            goals: Snapshot of all goals in current DAG (goal_id → GoalNode mapping).
            failed_evidence: Evidence from StrangeLoop execution.
            projector: ``ContextProjector`` used to project the ancestor
                (user, ai) pair transcript (RFC-222 §Goal-Report-Pair) into
                the dependency-chain slot, matching the context the executing
                worker saw.

        Returns:
            BackoffDecision with backoff target goal ID, reasoning, and directives.

        Raises:
            ValueError: If backoff target not in goal DAG.
            json.JSONDecodeError: If LLM response is not valid JSON.

        Process:
        1. Construct LLM prompt with goal DAG state, failure evidence, dependency context
        2. Invoke chat model with structured reasoning prompt
        3. Parse LLM response into BackoffDecision model
        4. Validate backoff target exists in DAG
        5. Return decision for AutopilotMonitor application
        """
        # Get failed goal
        failed_goal = goals.get(goal_id)
        if not failed_goal:
            raise ValueError(f"Goal {goal_id} not found in goal DAG")

        # Build goal DAG state representation
        goal_dag_state = self._format_goal_dag_state(goals)

        # Build dependency chain: ancestor (user, ai) pair transcript via the
        # same projection path the executing worker uses (RFC-222 §Goal-Report-Pair).
        dependency_chain = await projector.build_preamble_text(failed_goal, goals)

        prompt = render_backoff_prompt(
            goal_id=goal_id,
            goal_description=failed_goal.description,
            goal_dag_state=goal_dag_state,
            dependency_chain=dependency_chain,
            evidence_source=failed_evidence.source,
            structured_metrics=json.dumps(failed_evidence.structured, indent=2),
            failure_narrative=failed_evidence.narrative,
        )

        messages = [
            SystemMessage(content=SYSTEM_BACKOFF),
            HumanMessage(content=prompt),
        ]

        from soothe_nano.llm.invoke_policy import (
            await_with_llm_call_policy,
            llm_rate_limit_config_from,
        )
        from soothe_nano.llm.observability import create_llm_call_metadata

        invoke_config = {
            "metadata": create_llm_call_metadata(
                purpose="backoff_reasoning",
                component="autopilot.backoff_reasoner",
                phase="post-loop",
            )
        }

        async def _invoke() -> Any:
            return await self._model.ainvoke(messages, config=invoke_config)

        response = await await_with_llm_call_policy(
            _invoke,
            config=llm_rate_limit_config_from(self._soothe_config),
        )

        # Parse response
        response_text = response.content
        # Extract JSON from response (handle markdown code blocks)
        if "```json" in response_text:
            json_start = response_text.find("```json") + 7
            json_end = response_text.find("```", json_start)
            json_text = response_text[json_start:json_end].strip()
        else:
            json_text = response_text.strip()

        # Tolerant parse: LLMs sometimes emit trailing prose or concatenated
        # JSON objects after the first valid object (causes "Extra data").
        decoder = json.JSONDecoder()
        decision_data, _end = decoder.raw_decode(json_text)

        # Create BackoffDecision
        decision = BackoffDecision(
            backoff_to_goal_id=decision_data["backoff_to_goal_id"],
            reason=decision_data["reason"],
            new_directives=decision_data.get("new_directives", []),
            evidence_summary=decision_data["evidence_summary"],
        )

        # Validate backoff target exists in DAG
        if decision.backoff_to_goal_id not in goals:
            raise ValueError(
                f"Backoff target goal {decision.backoff_to_goal_id} not found in current DAG"
            )

        logger.info(
            "Backoff reasoning: goal=%s backoff_to=%s directives=%d reason=%s",
            goal_id,
            decision.backoff_to_goal_id,
            len(decision.new_directives),
            preview_first(decision.reason),
        )
        return decision

    def _format_goal_dag_state(self, goals: dict[str, GoalNode]) -> str:
        """Format goal DAG state for prompt.

        Args:
            goals: GoalNode dictionary.

        Returns:
            Formatted string representing goal DAG state.
        """
        lines = []
        for goal_id, goal in goals.items():
            deps = ", ".join(goal.depends_on) if goal.depends_on else "None"
            conflicts = ", ".join(goal.conflicts_with) if goal.conflicts_with else "None"
            lines.append(
                f"  - {goal_id}: status={goal.status}, priority={goal.priority}, "
                f"deps=[{deps}], conflicts=[{conflicts}]"
            )
        return "\n".join(lines)
