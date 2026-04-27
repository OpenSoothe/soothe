"""Failure analyzer for LLM-based learning insights.

Analyzes execution failures using LLM to extract root causes,
avoid patterns, and suggested adjustments for smart retry.

RFC-611: AgentLoop Checkpoint Tree Architecture
"""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from soothe.cognition.agent_loop.persistence.manager import AgentLoopCheckpointPersistenceManager
from soothe.config import SootheConfig

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class FailureAnalyzer:
    """LLM-based failure analysis for learning insights."""

    def __init__(self, config: SootheConfig) -> None:
        """Initialize failure analyzer.

        Args:
            config: Soothe configuration.
        """
        self.config = config

    async def analyze_failure(
        self,
        branch: dict[str, Any],
        failure_context: str,
    ) -> dict[str, Any]:
        """Analyze failure and compute learning insights.

        Args:
            branch: Failed branch record (dict).
            failure_context: Failure context from execution.

        Returns:
            Updated branch with learning insights.
        """
        # Create LLM analysis prompt
        analysis_prompt = f"""
Analyze this execution failure and provide structured insights:

Failure Reason: {branch.get("failure_reason", "Unknown")}

Execution Context:
{failure_context}

Provide analysis in JSON format:
```json
{{
    "root_cause": "<string - root cause of failure>",
    "context": "<string - execution context that led to failure>",
    "patterns": ["<pattern1>", "<pattern2>"],
    "suggestions": ["<suggestion1>", "<suggestion2>"]
}}
```
"""

        try:
            # Call LLM for analysis
            model = self.config.create_chat_model("default")
            response = await model.ainvoke(analysis_prompt)

            # Parse LLM response
            insights = self._parse_llm_response(response.content)

            # Update branch with learning
            branch["failure_insights"] = {
                "root_cause": insights.get("root_cause", ""),
                "context": insights.get("context", ""),
            }
            branch["avoid_patterns"] = insights.get("patterns", [])
            branch["suggested_adjustments"] = insights.get("suggestions", [])
            branch["analyzed_at"] = datetime.now(UTC)

            # Save updated branch to persistence
            persistence_manager = AgentLoopCheckpointPersistenceManager(config=self.config)
            await persistence_manager.update_branch_analysis(
                branch_id=branch["branch_id"],
                loop_id=branch["loop_id"],
                failure_insights=branch["failure_insights"],
                avoid_patterns=branch["avoid_patterns"],
                suggested_adjustments=branch["suggested_adjustments"],
            )

            logger.info(
                "Analyzed failure: branch=%s loop=%s patterns=%d adjustments=%d",
                branch["branch_id"],
                branch["loop_id"],
                len(branch["avoid_patterns"]),
                len(branch["suggested_adjustments"]),
            )

        except Exception as e:
            logger.error(
                "Failed to analyze failure: branch=%s loop=%s error=%s",
                branch["branch_id"],
                branch["loop_id"],
                str(e),
            )
            # Set empty insights on failure
            branch["failure_insights"] = {}
            branch["avoid_patterns"] = []
            branch["suggested_adjustments"] = []
            branch["analyzed_at"] = None

        return branch

    def _parse_llm_response(self, response_content: str) -> dict[str, Any]:
        """Parse LLM JSON response.

        Args:
            response_content: LLM response content.

        Returns:
            Parsed insights dictionary.
        """
        try:
            # Extract JSON from response (handle markdown code blocks)
            json_match = re.search(r"```json\s*(.*?)\s*```", response_content, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                # Assume response is plain JSON
                json_str = response_content

            return json.loads(json_str)

        except Exception as e:
            logger.warning("Failed to parse LLM response: %s", str(e))
            return {
                "root_cause": "Unknown",
                "context": "Unable to extract context",
                "patterns": [],
                "suggestions": [],
            }


def extract_failure_context_from_exception(
    exception: Exception,
    execution_summary: dict[str, Any] | None = None,
) -> str:
    """Extract failure context from exception and execution summary.

    Args:
        exception: Exception that triggered failure.
        execution_summary: Optional execution summary before failure.

    Returns:
        Failure context string for LLM analysis.
    """
    context_parts = []

    # Exception details
    context_parts.append(f"Exception Type: {type(exception).__name__}")
    context_parts.append(f"Exception Message: {str(exception)}")

    # Execution summary (if available)
    if execution_summary:
        if execution_summary.get("reasoning_decision"):
            context_parts.append(f"Reasoning Decision: {execution_summary['reasoning_decision']}")
        if execution_summary.get("tools_executed"):
            context_parts.append(
                f"Tools Executed: {', '.join(execution_summary['tools_executed'])}"
            )
        if execution_summary.get("iteration_status"):
            context_parts.append(f"Iteration Status: {execution_summary['iteration_status']}")

    return "\n".join(context_parts)


__all__ = ["FailureAnalyzer", "extract_failure_context_from_exception"]
