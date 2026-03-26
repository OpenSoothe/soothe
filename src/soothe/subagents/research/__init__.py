"""Research subagent package.

Provides deep research capability with iterative reflection across multiple
information sources. Converted from tool to subagent following RFC-0021.
"""

from typing import Any

from soothe_sdk import plugin, subagent

from .events import (
    TOOL_RESEARCH_ANALYZE,
    TOOL_RESEARCH_COMPLETED,
    TOOL_RESEARCH_GATHER,
    TOOL_RESEARCH_GATHER_DONE,
    TOOL_RESEARCH_INTERNAL_LLM,
    TOOL_RESEARCH_QUERIES_GENERATED,
    TOOL_RESEARCH_REFLECT,
    TOOL_RESEARCH_REFLECTION_DONE,
    TOOL_RESEARCH_SUB_QUESTIONS,
    TOOL_RESEARCH_SUMMARIZE,
    TOOL_RESEARCH_SYNTHESIZE,
    ResearchAnalyzeEvent,
    ResearchCompletedEvent,
    ResearchGatherDoneEvent,
    ResearchGatherEvent,
    ResearchInternalLLMResponseEvent,
    ResearchQueriesGeneratedEvent,
    ResearchReflectEvent,
    ResearchReflectionDoneEvent,
    ResearchSubQuestionsEvent,
    ResearchSummarizeEvent,
    ResearchSynthesizeEvent,
)
from .implementation import create_research_subagent
from .protocol import (
    GatherContext,
    InformationSource,
    InquiryConfig,
    SourceResult,
)

__all__ = [
    # Event type constants
    "TOOL_RESEARCH_ANALYZE",
    "TOOL_RESEARCH_COMPLETED",
    "TOOL_RESEARCH_GATHER",
    "TOOL_RESEARCH_GATHER_DONE",
    "TOOL_RESEARCH_INTERNAL_LLM",
    "TOOL_RESEARCH_QUERIES_GENERATED",
    "TOOL_RESEARCH_REFLECT",
    "TOOL_RESEARCH_REFLECTION_DONE",
    "TOOL_RESEARCH_SUB_QUESTIONS",
    "TOOL_RESEARCH_SUMMARIZE",
    "TOOL_RESEARCH_SYNTHESIZE",
    # Protocol
    "GatherContext",
    "InformationSource",
    "InquiryConfig",
    # Events
    "ResearchAnalyzeEvent",
    "ResearchCompletedEvent",
    "ResearchGatherDoneEvent",
    "ResearchGatherEvent",
    "ResearchInternalLLMResponseEvent",
    # Plugin
    "ResearchPlugin",
    "ResearchQueriesGeneratedEvent",
    "ResearchReflectEvent",
    "ResearchReflectionDoneEvent",
    "ResearchSubQuestionsEvent",
    "ResearchSummarizeEvent",
    "ResearchSynthesizeEvent",
    "SourceResult",
    # Factory
    "create_research_subagent",
]


@plugin(
    name="research",
    version="2.0.0",
    description="Deep research subagent with multi-source synthesis",
    trust_level="built-in",
)
class ResearchPlugin:
    """Research subagent plugin.

    Provides deep research capability with iterative reflection
    across multiple information sources. Converted from tool to
    subagent following RFC-0021.
    """

    def __init__(self) -> None:
        """Initialize the plugin."""
        self._subagent: Any = None

    async def on_load(self, context: Any) -> None:
        """Initialize research subagent.

        Args:
            context: Plugin context with config and logger.
        """
        context.logger.info("Loaded research subagent v2.0.0")

    @subagent(
        name="research",
        description=(
            "Deep research subagent that iteratively searches, analyses, and synthesizes "
            "information from multiple sources. Use when a question requires thorough "
            "investigation, cross-validation, or multi-step research beyond a single "
            "web search. "
            "Inputs: `topic` (required, the research question), "
            "`domain` (optional, one of 'auto', 'web', 'code', 'deep'; default 'auto'). "
            "- 'web': Internet research (web search + academic papers). "
            "- 'code': Codebase exploration (filesystem + CLI tools). "
            "- 'deep': All sources combined for comprehensive research. "
            "- 'auto': Automatically selects sources based on the topic. "
            "Returns a comprehensive answer with citations."
        ),
    )
    async def create_subagent(
        self,
        model: Any,
        config: Any,
        context: Any,
    ) -> Any:
        """Create research subagent.

        Args:
            model: LLM for research operations.
            config: Soothe configuration.
            context: Plugin context with work_dir and settings.

        Returns:
            Compiled LangGraph subagent.
        """
        # Extract context attributes to dict
        context_dict = {
            "work_dir": getattr(context, "work_dir", ""),
            "max_loops": getattr(context, "max_loops", 3),
            "domain": getattr(context, "domain", "auto"),
        }
        return create_research_subagent(model, config, context_dict)
