"""Synthesis phase for comprehensive final report generation (RFC-603).

This module implements an optional synthesis phase that generates comprehensive
final reports from accumulated evidence using evidence-based trigger criteria.
"""

import re

from langchain_core.language_models.chat_models import BaseChatModel

from soothe.cognition.loop_agent.schemas import LoopState, ReasonResult

# Synthesis trigger thresholds (internal constants, not exposed to users)
_SYNTHESIS_MIN_STEPS = 2
_SYNTHESIS_MIN_SUCCESS_RATE = 0.6
_SYNTHESIS_MIN_EVIDENCE_LENGTH = 500
_SYNTHESIS_MIN_UNIQUE_STEPS = 2

# Goal classification thresholds
_MIN_DIRECTORIES_FOR_ARCHITECTURE = 3
_MIN_FINDINGS_FOR_RESEARCH = 3
_MIN_CODE_MENTIONS_FOR_IMPLEMENTATION = 5


class SynthesisPhase:
    """Generate comprehensive final reports from evidence.

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

    def should_synthesize(self, _goal: str, state: LoopState, _reason_result: ReasonResult) -> bool:
        """Determine if synthesis phase should run.

        Uses evidence-based heuristics only (no keyword matching).

        Args:
            _goal: Goal description (reserved for future use).
            state: Loop state with accumulated evidence.
            _reason_result: Final reason result (reserved for future use).

        Returns:
            True if synthesis should run.
        """
        # Criterion 1: Enough evidence
        if len(state.step_results) < _SYNTHESIS_MIN_STEPS:
            return False

        # Criterion 2: High success rate
        successful_steps = [r for r in state.step_results if r.success]
        if not successful_steps:
            return False
        success_rate = len(successful_steps) / len(state.step_results)
        if success_rate < _SYNTHESIS_MIN_SUCCESS_RATE:
            return False

        # Criterion 3: Sufficient evidence volume
        total_evidence_length = sum(len(r.output or "") for r in successful_steps)
        if total_evidence_length < _SYNTHESIS_MIN_EVIDENCE_LENGTH:
            return False

        # Criterion 4: Multiple perspectives (unique step types)
        unique_step_ids = {r.step_id for r in successful_steps}
        return len(unique_step_ids) >= _SYNTHESIS_MIN_UNIQUE_STEPS

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

    async def synthesize(self, goal: str, state: LoopState, reason_result: ReasonResult) -> str:
        """Generate comprehensive synthesis report.

        Args:
            goal: Goal description.
            state: Loop state with evidence.
            reason_result: Reason result with summary.

        Returns:
            Comprehensive synthesis text (300-600 words for complex goals).

        Raises:
            Exception: If synthesis fails (caller should fallback).
        """
        # Gather evidence
        evidence_parts = [result.output for result in state.step_results if result.success and result.output]

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
            previous_summary=reason_result.evidence_summary or "",
        )

        # Call LLM for synthesis
        from langchain_core.messages import HumanMessage

        response = await self.llm.ainvoke([HumanMessage(content=synthesis_prompt)])

        synthesis_text = response.content or ""

        return synthesis_text.strip()
