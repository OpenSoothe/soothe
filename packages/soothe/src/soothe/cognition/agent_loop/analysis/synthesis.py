"""Synthesis execution logic for comprehensive final report generation (RFC-603, IG-299).

Consolidated execution module merging:
- SynthesisPhase (goal classification, LLM calls)
- ResponseCategorizer (response length categorization)
- SynthesisExecutor (streaming generation)

Separation of concerns (IG-299):
- policies/goal_completion_policy.py: Decision logic ("should we synthesize?")
- analysis/synthesis.py: Execution logic ("how to synthesize?")
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from soothe.cognition.agent_loop.policies.response_length_policy import (
    ResponseLengthCategory,
    calculate_evidence_metrics,
    determine_response_length,
)
from soothe.cognition.agent_loop.state.schemas import LoopState, PlanResult
from soothe.cognition.agent_loop.utils.messages import LoopHumanMessage

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from langchain_core.language_models.chat_models import BaseChatModel

    from soothe.core.agent import CoreAgent

logger = logging.getLogger(__name__)

# Goal classification thresholds (internal constants for execution logic)
_MIN_DIRECTORIES_FOR_ARCHITECTURE = 3
_MIN_FINDINGS_FOR_RESEARCH = 3
_MIN_CODE_MENTIONS_FOR_IMPLEMENTATION = 5


class SynthesisGenerator:
    """Generate synthesis reports from execution evidence (IG-299).

    Consolidated class merging SynthesisPhase, ResponseCategorizer, SynthesisExecutor.

    Responsibilities:
    - Goal classification from evidence patterns
    - Response length categorization from metrics
    - LLM synthesis generation with streaming
    """

    def __init__(self, llm_client: BaseChatModel, core_agent: CoreAgent) -> None:
        """Initialize synthesis generator with LLM client and CoreAgent.

        Args:
            llm_client: LLM for goal classification (unused, classification via regex).
            core_agent: CoreAgent for synthesis execution with streaming.
        """
        self.llm = llm_client
        self.core_agent = core_agent

    def classify_goal(self, evidence: str) -> str:
        """Classify goal type from evidence patterns.

        Args:
            evidence: Concatenated evidence from successful steps.

        Returns:
            Goal type: architecture_analysis, research_synthesis,
                      implementation_summary, general_synthesis.
        """
        evidence_lower = evidence.lower()

        # Architecture analysis: Multiple directories + layer mentions
        directory_pattern = r"(src/|docs/|core/|backends/|protocols/|tools/)"
        directories = len(re.findall(directory_pattern, evidence_lower))
        layer_mentions = bool(re.search(r"layer|architecture|component|module", evidence_lower))

        if directories >= _MIN_DIRECTORIES_FOR_ARCHITECTURE and layer_mentions:
            return "architecture_analysis"

        # Research synthesis: Multiple findings
        findings_pattern = r"(found|identified|discovered|located)\s+\d+"
        findings_count = len(re.findall(findings_pattern, evidence_lower))

        if findings_count >= _MIN_FINDINGS_FOR_RESEARCH:
            return "research_synthesis"

        # Implementation summary: Code mentions
        code_pattern = r"(function|class|method|implementation|def |async def)"
        code_mentions = len(re.findall(code_pattern, evidence_lower))

        if code_mentions >= _MIN_CODE_MENTIONS_FOR_IMPLEMENTATION:
            return "implementation_summary"

        return "general_synthesis"

    def categorize_response_length(
        self,
        state: LoopState,
        intent_type: str = "new_goal",
        task_complexity: str = "medium",
    ) -> ResponseLengthCategory:
        """Determine response length from evidence metrics (IG-299).

        Args:
            state: Loop state with step results.
            intent_type: Intent classification from state.intent.
            task_complexity: Task complexity from state.intent.

        Returns:
            ResponseLengthCategory with min_words, max_words bounds.
        """
        # Calculate metrics (from response_length_policy)
        evidence_volume, evidence_diversity = calculate_evidence_metrics(state.step_results)

        # Classify goal type
        evidence = self._extract_evidence(state)
        goal_type = self.classify_goal(evidence)

        # Determine length category
        return determine_response_length(
            intent_type=intent_type,
            goal_type=goal_type,
            task_complexity=task_complexity,
            evidence_volume=evidence_volume,
            evidence_diversity=evidence_diversity,
        )

    async def generate_synthesis(
        self,
        goal: str,
        state: LoopState,
        plan_result: PlanResult,
        length_category: ResponseLengthCategory,
    ) -> AsyncGenerator:
        """Generate synthesis via CoreAgent streaming (IG-299).

        Args:
            goal: Goal description.
            state: Loop state with thread context.
            plan_result: Plan result (reserved for future hints).
            length_category: Response length guidance.

        Returns:
            Async generator yielding stream chunks.
        """
        _ = plan_result  # Reserved for future use

        # Extract evidence
        evidence = self._extract_evidence(state)

        # Classify goal type
        goal_type = self.classify_goal(evidence)

        # Build synthesis prompt
        prompt = self._build_synthesis_prompt(goal, evidence, goal_type, length_category)

        # Create human message
        human_msg = LoopHumanMessage(
            content=prompt,
            thread_id=state.thread_id,
            iteration=state.iteration,
            goal_summary=state.goal[:200] if state.goal else None,
            phase="goal_completion",
        )

        logger.info(
            "Synthesis generator: goal_type=%s length_category=%s evidence_chars=%d",
            goal_type,
            length_category.value,
            len(evidence),
        )

        # Stream via CoreAgent (no custom accumulation - CoreAgent handles it)
        async for chunk in self.core_agent.astream(
            {"messages": [human_msg]},
            config={"configurable": {"thread_id": state.thread_id}},
            stream_mode=["messages"],
            subgraphs=False,
        ):
            yield ("goal_completion_stream", chunk)

    def _extract_evidence(self, state: LoopState) -> str:
        """Extract evidence from successful step results."""
        evidence_parts = []
        for result in state.step_results:
            if result.success:
                evidence_str = result.to_evidence_string(truncate=False)
                evidence_parts.append(evidence_str)
        return "\n\n".join(evidence_parts)

    def _build_synthesis_prompt(
        self,
        goal: str,
        evidence: str,
        goal_type: str,
        length_category: ResponseLengthCategory,
    ) -> str:
        """Build synthesis prompt with length guidance (IG-299).

        Args:
            goal: Goal description.
            evidence: Concatenated evidence from successful steps.
            goal_type: Classified goal type.
            length_category: Response length category.

        Returns:
            Complete synthesis prompt text.
        """
        length_guidance = self._get_length_guidance(length_category)

        return f"""Based on the complete execution history in this thread, generate a goal completion response for: {goal}

RESPONSE LENGTH: {length_category.min_words}-{length_category.max_words} words ({length_category.value} category)

{length_guidance}

The response should:
1. Summarize what was accomplished
2. **Include actual content** from content-retrieval tools (read_file, web_search, fetch_url, ls, glob, etc.)
   - ToolMessage.content contains the actual file content, search results, etc.
   - Extract and present this actual content directly, not just summaries
   - For file reading: show the actual file content (with line numbers if applicable)
   - For web/research: show actual search results or fetched content
3. Provide actionable results or deliverables
4. Be well-structured with clear sections
5. Match the response length guidance above

IMPORTANT: The user wants to see the actual content retrieved, not just confirmation messages. Extract content from ToolMessage.content in the conversation history and present it appropriately for the response length category.

Use all tool results and AI responses available in the conversation history."""

    def _get_length_guidance(self, length_category: ResponseLengthCategory) -> str:
        """Get response length guidance text for the given category (IG-299).

        Args:
            length_category: ResponseLengthCategory enum value.

        Returns:
            Guidance text for the response length category.
        """
        if length_category == ResponseLengthCategory.BRIEF:
            return """Be concise: Lead with answer, no preamble, 1-3 sentences.
Focus on essential information only."""
        elif length_category == ResponseLengthCategory.CONCISE:
            return """Be direct: Brief synthesis, 2-4 key points, avoid repetition.
Provide incremental updates building on prior context."""
        elif length_category == ResponseLengthCategory.STANDARD:
            return """Be comprehensive: 3-5 sections, specific numbers, clear structure.
Include methodology and key findings with concrete evidence."""
        elif length_category == ResponseLengthCategory.COMPREHENSIVE:
            return """Be thorough: Full structured report, concrete examples, detailed breakdown.
Provide complete analysis with all relevant details organized into clear sections."""
        else:
            return """Provide a well-structured response matching the task complexity."""
