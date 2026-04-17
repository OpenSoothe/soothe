"""Research subagent package.

Provides deep research capability with iterative reflection across multiple
information sources. Converted from tool to subagent following RFC-0021.
"""

from typing import Any

from soothe_sdk.plugin import plugin, subagent

from .events import (
    SUBAGENT_RESEARCH_ANALYZE,
    SUBAGENT_RESEARCH_COMPLETED,
    SUBAGENT_RESEARCH_GATHER,
    SUBAGENT_RESEARCH_GATHER_DONE,
    SUBAGENT_RESEARCH_INTERNAL_LLM,
    SUBAGENT_RESEARCH_QUERIES_GENERATED,
    SUBAGENT_RESEARCH_REFLECT,
    SUBAGENT_RESEARCH_REFLECTION_DONE,
    SUBAGENT_RESEARCH_SUB_QUESTIONS,
    SUBAGENT_RESEARCH_SUMMARIZE,
    SUBAGENT_RESEARCH_SYNTHESIZE,
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
    ResearchConfig,
    SourceResult,
)

__all__ = [
    # Event type constants
    "SUBAGENT_RESEARCH_ANALYZE",
    "SUBAGENT_RESEARCH_COMPLETED",
    "SUBAGENT_RESEARCH_GATHER",
    "SUBAGENT_RESEARCH_GATHER_DONE",
    "SUBAGENT_RESEARCH_INTERNAL_LLM",
    "SUBAGENT_RESEARCH_QUERIES_GENERATED",
    "SUBAGENT_RESEARCH_REFLECT",
    "SUBAGENT_RESEARCH_REFLECTION_DONE",
    "SUBAGENT_RESEARCH_SUB_QUESTIONS",
    "SUBAGENT_RESEARCH_SUMMARIZE",
    "SUBAGENT_RESEARCH_SYNTHESIZE",
    # Protocol
    "GatherContext",
    "InformationSource",
    "InquiryConfig",  # Backward compatibility alias
    # Events
    "ResearchAnalyzeEvent",
    "ResearchCompletedEvent",
    "ResearchConfig",
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
            "information from multiple sources. "
            "Use for: thorough investigation, cross-validation, multi-step research. "
            "DO NOT use for: simple file listing (list_files), single file reads (read_file). "
            "Inputs: `topic` (required), `domain` (optional: 'web', 'code', 'deep', 'auto'). "
            "Returns a comprehensive answer with citations."
        ),
        model="openai:gpt-4o-mini",
        system_context="""<RESEARCH_RULES>
<source_verification>
Cross-reference claims across multiple independent sources.
Prefer primary sources (original papers, official docs) over secondary.
Check publication dates and relevance to current context.
Identify and note potential conflicts of interest or bias.
</source_verification>
<citation_format>
Use markdown links for sources: [Title](URL)
Include timestamps when available: [Title](URL) (accessed YYYY-MM-DD)
Format quotes clearly with attribution.
</citation_format>
<depth_guidelines>
Start broad to understand context, then narrow to specifics.
Investigate contradictory information thoroughly.
Document search strategy and sources consulted.
Provide confidence levels for claims based on evidence strength.
</depth_guidelines>
</RESEARCH_RULES>""",
        triggers=["RESEARCH_RULES", "context"],
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
