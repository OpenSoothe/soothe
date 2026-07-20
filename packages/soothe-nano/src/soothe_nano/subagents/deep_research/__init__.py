"""deep_research subagent — iterative public web research (RFC-619)."""

from typing import Any

from soothe_sdk.plugin import plugin, subagent

from . import events as _events  # noqa: F401 — register soothe.subagent.deep_research.* wire types
from .implementation import create_deep_research_subagent
from .protocol import DeepResearchConfig, GatherContext, SourceResult

__all__ = [
    "DeepResearchConfig",
    "DeepResearchPlugin",
    "GatherContext",
    "SourceResult",
    "create_deep_research_subagent",
]


@plugin(
    name="deep_research",
    version="1.0.0",
    description="Public web research subagent with adaptive reports",
    trust_level="built-in",
)
class DeepResearchPlugin:
    """deep_research built-in subagent plugin."""

    def __init__(self) -> None:
        self._subagent: Any = None

    async def on_load(self, context: Any) -> None:
        context.logger.info("Loaded deep_research subagent v1.0.0")

    @subagent(
        name="deep_research",
        description=(
            "deep_research: iterative public web research with URL crawling and adaptive "
            "report generation. Use for external facts, comparisons, how-tos, and industry "
            "landscape. Do NOT use for local codebase, repository files, or academic papers "
            "(use academic_research)."
        ),
        system_context="""<DEEP_RESEARCH_RULES>
<BOUNDARY>
Public web sources only. Never read local repository files.
Local codebase analysis belongs to the main agent file tools.
</BOUNDARY>
<REPORT>
Produce structured adaptive research reports with a mandatory Scope section.
Cross-reference claims across independent web sources when possible.
</REPORT>
<EFFORT>
Optional: effort: normal | thorough in the task description.
- normal: faster (~2 loops, crawl top 3 URLs per search)
- thorough: deeper (~4 loops, crawl top 5 URLs per search)
</EFFORT>
</DEEP_RESEARCH_RULES>""",
        triggers=["DEEP_RESEARCH_RULES", "context"],
    )
    async def create_subagent(
        self,
        model: Any,
        config: Any,
        context: Any,
    ) -> Any:
        context_dict: dict[str, Any] = {"work_dir": getattr(context, "work_dir", "")}
        if hasattr(context, "effort"):
            context_dict["effort"] = getattr(context, "effort", None)
        if hasattr(context, "max_loops"):
            context_dict["max_loops"] = getattr(context, "max_loops", None)
        return create_deep_research_subagent(model, config, context_dict)
