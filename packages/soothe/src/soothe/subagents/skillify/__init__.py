"""Skillify subagent — semantic skill warehouse indexing and retrieval."""

from typing import Any

from soothe_sdk.plugin import plugin, subagent

from . import events as _events  # noqa: F401 — register soothe.subagent.skillify.* wire types
from .implementation import SKILLIFY_DESCRIPTION, create_skillify_subagent
from .models import SkillBundle, SkillRecord, SkillSearchResult
from .retriever import SkillRetriever
from .schemas import SkillifySubagentConfig

__all__ = [
    "SKILLIFY_DESCRIPTION",
    "SkillBundle",
    "SkillRecord",
    "SkillRetriever",
    "SkillSearchResult",
    "SkillifyPlugin",
    "SkillifySubagentConfig",
    "create_skillify_subagent",
]


@plugin(
    name="skillify",
    version="1.0.0",
    description="Skill warehouse indexing and semantic retrieval",
    trust_level="built-in",
)
class SkillifyPlugin:
    """Built-in Skillify subagent plugin."""

    def __init__(self) -> None:
        self._subagent: Any = None

    async def on_load(self, context: Any) -> None:
        context.logger.info("Loaded Skillify subagent v1.0.0")

    @subagent(
        name="skillify",
        description=SKILLIFY_DESCRIPTION,
    )
    async def create_subagent(
        self,
        model: Any,
        config: Any,
        context: Any,
    ) -> Any:
        context_dict = {
            "work_dir": getattr(context, "work_dir", ""),
        }
        return create_skillify_subagent(model, config, context_dict)
