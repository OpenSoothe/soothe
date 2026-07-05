"""Tacitus subagent — public-domain iterative research (RFC-619)."""

from typing import Any

from soothe_sdk.plugin import plugin, subagent

from . import events as _events  # noqa: F401 — register soothe.subagent.tacitus.* wire types
from .implementation import create_tacitus_subagent
from .protocol import (
    GatherContext,
    InformationSource,
    PublicInformationSource,
    SourceResult,
    TacitusConfig,
)

__all__ = [
    "GatherContext",
    "InformationSource",
    "PublicInformationSource",
    "SourceResult",
    "TacitusConfig",
    "TacitusPlugin",
    "create_tacitus_subagent",
]


@plugin(
    name="tacitus",
    version="3.0.0",
    description="Public-domain research subagent (web, academic, URLs)",
    trust_level="built-in",
)
class TacitusPlugin:
    """Tacitus built-in subagent plugin."""

    def __init__(self) -> None:
        self._subagent: Any = None

    async def on_load(self, context: Any) -> None:
        context.logger.info("Loaded Tacitus subagent v3.0.0")

    @subagent(
        name="tacitus",
        description=(
            "Tacitus: deep public-domain research across web search, academic "
            "papers, and public URLs. Use for thorough investigation and cross-validation. "
            "Do not use for local codebase exploration."
        ),
        system_context="""<TACITUS_RULES>
<SOURCE_VERIFICATION>
Cross-reference claims across multiple independent public sources.
Prefer primary sources (original papers, official docs) over secondary.
Check publication dates and relevance to current context.
</SOURCE_VERIFICATION>
<CITATION_FORMAT>
Use markdown links for sources: [Title](URL)
Include timestamps when available: [Title](URL) (accessed YYYY-MM-DD)
A formatted References section is appended to the final report automatically.
</CITATION_FORMAT>
<EFFORT_LEVELS>
Default depth is normal. Optional: effort: normal | high | xhigh in the task description.
- normal: fewer sub-questions and loops (faster)
- high: balanced depth (~3 reflection loops)
- xhigh: maximum breadth and follow-up depth
</EFFORT_LEVELS>
<DEPTH_GUIDELINES>
Start broad, then narrow. Investigate contradictions. Document sources consulted.
</DEPTH_GUIDELINES>
</TACITUS_RULES>""",
        triggers=["TACITUS_RULES", "context"],
    )
    async def create_subagent(
        self,
        model: Any,
        config: Any,
        context: Any,
    ) -> Any:
        context_dict: dict[str, Any] = {
            "work_dir": getattr(context, "work_dir", ""),
            "domain": getattr(context, "domain", "public"),
        }
        if hasattr(context, "effort"):
            context_dict["effort"] = getattr(context, "effort", None)
        if hasattr(context, "max_loops"):
            context_dict["max_loops"] = getattr(context, "max_loops", None)
        return create_tacitus_subagent(model, config, context_dict)
