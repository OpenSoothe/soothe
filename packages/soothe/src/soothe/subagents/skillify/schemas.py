"""Skillify subagent configuration."""

from __future__ import annotations

from pydantic import BaseModel, Field


class SkillifySubagentConfig(BaseModel):
    """Options under ``subagents.skillify.config``."""

    warehouse_paths: list[str] = Field(
        default_factory=list,
        description=(
            "Extra SKILL.md roots for vector indexing. "
            "Defaults (~/.soothe/skills and ~/.agents/skills) are always prepended when absent."
        ),
    )
    index_collection: str = "soothe_skillify"
    index_interval_seconds: int = 300
    retrieval_top_k: int = 10
