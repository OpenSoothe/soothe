"""academic_research subagent — iterative academic literature research (RFC-619)."""

from typing import Any

from soothe_sdk.plugin import plugin, subagent

from . import (
    events as _events,  # noqa: F401 — register soothe.subagent.academic_research.* wire types
)
from .implementation import create_academic_research_subagent
from .protocol import AcademicResearchConfig, GatherContext, SourceResult

__all__ = [
    "AcademicResearchConfig",
    "AcademicResearchPlugin",
    "GatherContext",
    "SourceResult",
    "create_academic_research_subagent",
]


@plugin(
    name="academic_research",
    version="1.0.0",
    description="Academic literature research subagent with adaptive reports",
    trust_level="built-in",
)
class AcademicResearchPlugin:
    """academic_research built-in subagent plugin."""

    def __init__(self) -> None:
        self._subagent: Any = None

    async def on_load(self, context: Any) -> None:
        context.logger.info("Loaded academic_research subagent v1.0.0")

    @subagent(
        name="academic_research",
        description=(
            "academic_research: iterative academic literature research with URL crawling and "
            "adaptive report generation. Use for papers, literature reviews, and citations. "
            "Do NOT use for local codebase files or general web news."
        ),
        system_context="""<ACADEMIC_RESEARCH_RULES>
<BOUNDARY>
Academic literature sources only (papers, preprints). Never read local repository files.
Local codebase analysis belongs to the main agent file tools.
</BOUNDARY>
<REPORT>
Produce structured adaptive literature reports with a mandatory Scope section.
Prefer primary papers and preprints; cite sources clearly.
</REPORT>
<EFFORT>
Optional: effort: normal | thorough in the task description.
- normal: faster (~2 loops, crawl top 3 paper URLs per search)
- thorough: deeper (~4 loops, crawl top 5 URLs per search)
</EFFORT>
</ACADEMIC_RESEARCH_RULES>""",
        triggers=["ACADEMIC_RESEARCH_RULES", "context"],
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
        return create_academic_research_subagent(model, config, context_dict)
