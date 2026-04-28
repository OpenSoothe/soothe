"""Synthesis execution logic for comprehensive final report generation (RFC-603, IG-296).

This module contains ONLY execution logic:
- SynthesisPhase class (LLM calls, goal classification, prompt building)
- Implementation of synthesis generation

Decision logic moved to synthesis_policy.py (IG-296).

Separation of concerns:
- policies/synthesis_policy.py: Decision logic ("should we synthesize?")
- analysis/synthesis.py: Execution logic ("how to synthesize?")
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from soothe.cognition.agent_loop.policies.synthesis_policy import evidence_requires_final_synthesis
from soothe.cognition.agent_loop.state.schemas import LoopState, PlanResult
from soothe.cognition.agent_loop.utils.messages import LoopHumanMessage

if TYPE_CHECKING:
    from langchain_core.language_models.chat_models import BaseChatModel

# Goal classification thresholds (internal constants for execution logic)
_MIN_DIRECTORIES_FOR_ARCHITECTURE = 3
_MIN_FINDINGS_FOR_RESEARCH = 3
_MIN_CODE_MENTIONS_FOR_IMPLEMENTATION = 5


class SynthesisPhase:
    """Generate comprehensive final reports from execution results.

    Trigger criteria (all must be met):
    1. ≥2 successful steps
    2. ≥60% success rate
    3. ≥500 chars total evidence
    4. ≥2 unique step types

    Goal classification (from evidence patterns):
    - Architecture analysis: Multiple directories + layer/structure mentions
    - Research synthesis: Multiple findings/discoveries counts
    - Implementation summary: Code patterns, function/class mentions
    - General synthesis: Default
    """

    def __init__(self, llm_client: BaseChatModel) -> None:
        """Initialize synthesis phase with LLM client.

        Args:
            llm_client: LLM for synthesis generation.
        """
        self.llm = llm_client

    def should_synthesize(self, _goal: str, state: LoopState, plan_result: PlanResult) -> bool:
        """Determine if synthesis phase should run.

        Uses evidence-based heuristics only (no keyword matching).

        Args:
            _goal: Goal description (reserved for future use).
            state: Loop state with accumulated evidence.
            plan_result: Final plan result (reserved for future use).

        Returns:
            True if synthesis should run.
        """
        return evidence_requires_final_synthesis(state, plan_result)

    def _classify_goal_type(self, evidence: str) -> str:
        """Classify goal type from evidence patterns.

        Args:
            evidence: Concatenated evidence from all steps.

        Returns:
            Goal type: 'architecture_analysis', 'research_synthesis',
                      'implementation_summary', or 'general_synthesis'.
        """
        evidence_lower = evidence.lower()

        # Architecture analysis: Multiple directories + layer/structure mentions
        directory_pattern = r"(src/|docs/|core/|backends/|protocols/|tools/)"
        directories = len(re.findall(directory_pattern, evidence_lower))
        layer_mentions = bool(re.search(r"layer|architecture|component|module", evidence_lower))

        if directories >= _MIN_DIRECTORIES_FOR_ARCHITECTURE and layer_mentions:
            return "architecture_analysis"

        # Research synthesis: Multiple findings/discoveries
        findings_pattern = r"(found|identified|discovered|located)\s+\d+"
        findings_count = len(re.findall(findings_pattern, evidence_lower))

        if findings_count >= _MIN_FINDINGS_FOR_RESEARCH:
            return "research_synthesis"

        # Implementation summary: Code patterns, function/class mentions
        code_pattern = r"(function|class|method|implementation|def |async def)"
        code_mentions = len(re.findall(code_pattern, evidence_lower))

        if code_mentions >= _MIN_CODE_MENTIONS_FOR_IMPLEMENTATION:
            return "implementation_summary"

        # Default: general synthesis
        return "general_synthesis"

    async def synthesize(self, goal: str, state: LoopState, plan_result: PlanResult) -> str:
        """Generate comprehensive synthesis report.

        Args:
            goal: Goal description.
            state: Loop state with evidence.
            plan_result: Plan result with summary.

        Returns:
            Comprehensive synthesis text (300-600 words for complex goals).

        Raises:
            Exception: If synthesis fails (caller should fallback).
        """
        # Gather evidence - use outcome metadata for full evidence
        evidence_parts = []
        for result in state.step_results:
            if result.success:
                # Use outcome metadata to get full evidence
                evidence_str = result.to_evidence_string(truncate=False)
                evidence_parts.append(evidence_str)

        evidence = "\n\n".join(evidence_parts)

        # Classify goal type
        goal_type = self._classify_goal_type(evidence)

        # Build synthesis prompt
        from soothe.core.prompts.loader import load_prompt_fragment

        synthesis_template = load_prompt_fragment("instructions/synthesis_format.xml")

        synthesis_prompt = synthesis_template.render(
            goal=goal,
            goal_type=goal_type,
            evidence=evidence,
            previous_summary=plan_result.evidence_summary or "",
        )

        # Call LLM for synthesis
        human_msg = LoopHumanMessage(content=synthesis_prompt)  # No thread context
        response = await self.llm.ainvoke([human_msg])

        synthesis_text = response.content or ""

        return synthesis_text.strip()
