"""Model-facing skill discovery and invocation tools (RFC-105 / IG-543)."""

from __future__ import annotations

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field


class SearchSkillsInput(BaseModel):
    """Input schema for search_skills."""

    query: str = Field(description="Substring to match deferred skill names, descriptions, or tags")
    limit: int = Field(default=5, ge=1, le=50, description="Maximum matches to return")


class InvokeSkillInput(BaseModel):
    """Input schema for invoke_skill."""

    name: str = Field(description="Skill name to load (from search_skills or AVAILABLE_SKILLS)")
    args: str = Field(
        default="",
        description="Optional user instruction passed alongside the skill reference",
    )


def create_search_skills_tool() -> StructuredTool:
    """Return the search_skills stub; discovery is handled by SkillActivationMiddleware."""

    def _search_skills(query: str, limit: int = 5) -> str:
        return (
            f"search_skills is handled by SkillActivationMiddleware. Query={query!r} limit={limit}."
        )

    return StructuredTool.from_function(
        func=_search_skills,
        name="search_skills",
        description=(
            "Search deferred skills by name, description, or tags. "
            "Returns matching skills and discovers them for subsequent hops. "
            "Call invoke_skill(name) to load full instructions."
        ),
        args_schema=SearchSkillsInput,
    )


def create_invoke_skill_tool() -> StructuredTool:
    """Return the invoke_skill stub; body load is handled by SkillActivationMiddleware."""

    def _invoke_skill(name: str, args: str = "") -> str:
        return f"invoke_skill is handled by SkillActivationMiddleware. name={name!r} args={args!r}."

    return StructuredTool.from_function(
        func=_invoke_skill,
        name="invoke_skill",
        description=(
            "Load a skill's full SKILL.md instructions into context. "
            "Use after search_skills or when a skill is listed in AVAILABLE_SKILLS."
        ),
        args_schema=InvokeSkillInput,
    )
