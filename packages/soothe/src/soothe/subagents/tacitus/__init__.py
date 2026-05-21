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
    description="Public-domain research subagent (web, Wikipedia, academic, URLs)",
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
            "Tacitus: deep public-domain research across web search, Wikipedia, academic "
            "papers, and public URLs. Use for thorough investigation and cross-validation. "
            "Do not use for local codebase exploration (use explore)."
        ),
        system_context="""<TACITUS_RULES>
<source_verification>
Cross-reference claims across multiple independent public sources.
Prefer primary sources (original papers, official docs) over secondary.
Check publication dates and relevance to current context.
</source_verification>
<citation_format>
Use markdown links for sources: [Title](URL)
Include timestamps when available: [Title](URL) (accessed YYYY-MM-DD)
</citation_format>
<depth_guidelines>
Start broad, then narrow. Investigate contradictions. Document sources consulted.
</depth_guidelines>
</TACITUS_RULES>""",
        triggers=["TACITUS_RULES", "context"],
    )
    async def create_subagent(
        self,
        model: Any,
        config: Any,
        context: Any,
    ) -> Any:
        context_dict = {
            "work_dir": getattr(context, "work_dir", ""),
            "max_loops": getattr(context, "max_loops", 3),
            "domain": getattr(context, "domain", "public"),
        }
        return create_tacitus_subagent(model, config, context_dict)
