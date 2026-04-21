"""GoalBackoffReasoner: LLM-driven backoff reasoning for goal DAG restructuring.

RFC-200 §205-541: Implements LLM-based analysis for goal failure recovery,
replacing hardcoded retry logic with reasoning-based backoff decisions.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from soothe.cognition.goal_engine.models import BackoffDecision, EvidenceBundle, Goal

if TYPE_CHECKING:
    from soothe.config import SootheConfig


# RFC-200 §205-541: Backoff reasoning prompt template
BACKOFF_REASONING_PROMPT = """Analyze goal execution failure and determine optimal backoff point in goal DAG.

## Current Goal Context

Failed Goal ID: {goal_id}
Goal Description: {goal_description}

Goal DAG State:
{goal_dag_state}

Dependency Chain:
{dependency_chain}

## Failure Evidence

Evidence Type: {evidence_source}
Execution Metrics: {structured_metrics}
Narrative Summary: {failure_narrative}

## Decision Required

You must decide WHERE to backoff in the goal DAG. Consider:
1. Root cause analysis: Is the failure isolated to current goal or systemic?
2. Dependency validity: Are prerequisite goals still valid?
3. Recovery strategy: Should we retry current goal, backoff to parent, or create new goals?

Output JSON structure (strict format):
```json
{
  "backoff_to_goal_id": "<goal_id>",
  "reason": "<natural language reasoning for backoff decision>",
  "new_directives": [],
  "evidence_summary": "<condensed failure analysis>"
}
```

Constraints:
- backoff_to_goal_id MUST exist in current goal DAG
- Prefer backing off to parent goal if dependency assumption failed
- Use new_directives to create corrective goals if needed (optional, leave empty array if not needed)
- reason should be clear and actionable for operator visibility
"""


class GoalBackoffReasoner:
    """LLM-driven backoff reasoning for goal DAG restructuring.

    RFC-200 §205-541: Analyzes goal context and evidence to decide
    WHERE to backoff in the goal DAG. Replaces hardcoded retry logic.

    Args:
        config: SootheConfig with model provider settings.

    Attributes:
        _model: LangChain chat model for reasoning.
        _prompt_template: Backoff reasoning prompt template.
    """

    def __init__(self, config: SootheConfig) -> None:
        """Initialize reasoner with chat model from config.

        Args:
            config: SootheConfig with model provider settings
        """
        self._model: BaseChatModel = config.create_chat_model("reason")
        self._prompt_template: str = BACKOFF_REASONING_PROMPT

    async def reason_backoff(
        self,
        goal_id: str,
        goals: dict[str, Goal],
        failed_evidence: EvidenceBundle,
    ) -> BackoffDecision:
        """LLM analyzes full goal context and decides WHERE to backoff.

        Args:
            goal_id: Failed goal identifier.
            goals: Snapshot of all goals in current DAG (goal_id → Goal mapping).
            failed_evidence: Evidence from Layer 2 execution.

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
        5. Return decision for GoalEngine application
        """
        # Get failed goal
        failed_goal = goals.get(goal_id)
        if not failed_goal:
            raise ValueError(f"Goal {goal_id} not found in goal DAG")

        # Build goal DAG state representation
        goal_dag_state = self._format_goal_dag_state(goals)

        # Build dependency chain
        dependency_chain = self._format_dependency_chain(goal_id, goals)

        # Construct prompt
        prompt = self._prompt_template.format(
            goal_id=goal_id,
            goal_description=failed_goal.description,
            goal_dag_state=goal_dag_state,
            dependency_chain=dependency_chain,
            evidence_source=failed_evidence.source,
            structured_metrics=json.dumps(failed_evidence.structured, indent=2),
            failure_narrative=failed_evidence.narrative,
        )

        # Invoke LLM
        messages = [
            SystemMessage(
                content="You are an expert at analyzing goal execution failures and determining optimal recovery strategies in goal DAGs."
            ),
            HumanMessage(content=prompt),
        ]

        response = await self._model.ainvoke(messages)

        # Parse response
        response_text = response.content
        # Extract JSON from response (handle markdown code blocks)
        if "```json" in response_text:
            json_start = response_text.find("```json") + 7
            json_end = response_text.find("```", json_start)
            json_text = response_text[json_start:json_end].strip()
        else:
            json_text = response_text.strip()

        decision_data = json.loads(json_text)

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

        return decision

    def _format_goal_dag_state(self, goals: dict[str, Goal]) -> str:
        """Format goal DAG state for prompt.

        Args:
            goals: Goal dictionary.

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

    def _format_dependency_chain(self, goal_id: str, goals: dict[str, Goal]) -> str:
        """Format dependency chain for prompt.

        Args:
            goal_id: Failed goal ID.
            goals: Goal dictionary.

        Returns:
            Formatted string representing dependency chain.
        """
        goal = goals.get(goal_id)
        if not goal:
            return "No dependency chain found"

        # Build dependency chain from root to current goal
        chain = []
        current = goal

        while current:
            chain.append(f"  {current.id}: {current.description[:60]}")
            if current.depends_on:
                # Get first dependency (simplified for prompt)
                parent_id = current.depends_on[0]
                current = goals.get(parent_id)
            else:
                break

        return "\n".join(chain[::-1])  # Reverse to show root first
