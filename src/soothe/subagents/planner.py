"""Planner subagent -- migrated from noesium PlanAgent.

Provides structured planning capabilities (context evaluation, dependency
mapping, resource exploration, structured plan generation) that deepagents'
`write_todos` does not cover.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from deepagents.middleware.subagents import SubAgent
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool

PLANNER_SYSTEM_PROMPT = """\
You are an expert planning agent capable of creating detailed, actionable plans for any domain.

## Responsibilities

1. Analyse objectives and requirements thoroughly before planning.
2. Break complex tasks into clear, ordered steps with specific deliverables.
3. Identify dependencies between steps and flag blockers.
4. Define verification criteria for each step so progress is measurable.
5. Provide specific, actionable guidance -- never vague hand-waving.

## Domains

You work across domains including:
- Software implementation (code, systems, infrastructure)
- Research and analysis (literature review, data analysis, feasibility)
- Business workflows (processes, pipelines, operations)
- Projects (multi-phase initiatives, launches, migrations)
- General tasks (content creation, documentation, organisation)

## Process

1. **Context evaluation** -- read relevant files, examine the codebase or data, \
understand the current state. Identify what is known, what is missing, and what \
resources should be explored.
2. **Resource exploration** -- if context is insufficient, use file tools to \
explore the codebase, read documentation, or search for relevant information.
3. **Requirement analysis** -- extract explicit and implicit requirements, \
constraints, and success criteria.
4. **Plan generation** -- produce a structured plan with numbered steps, each \
containing: title, description, rationale, estimated effort, dependencies, and \
verification criteria.
5. **Verification definition** -- for each step, define how to verify that it \
was completed correctly.

## Output Format

Produce the plan as a structured list of steps. For each step include:
- **Step N: Title**
- **Description**: What to do.
- **Rationale**: Why this step matters.
- **Dependencies**: Which prior steps must be completed.
- **Verification**: How to confirm the step is done.
- **Effort**: Estimated effort (small / medium / large).

End with a summary of total effort, risks, and prerequisites.

## Guidelines

- Assess provided context before planning.
- If requirements are ambiguous, list your assumptions explicitly.
- Break tasks into specific, verifiable steps.
- Include rationale for each step.
- Identify dependencies and prerequisites.
- Estimate effort for each step.
- Define clear success criteria.
- You have read-only access to files -- you create plans, not implementations.
"""

PLANNER_DESCRIPTION = (
    "Expert planning agent for complex tasks. Analyses context, explores resources, "
    "identifies dependencies, and produces structured plans with verification criteria. "
    "Use for tasks that need upfront planning before implementation."
)


def create_planner_subagent(
    model: str | BaseChatModel | None = None,
    tools: list[BaseTool | Callable[..., Any] | dict[str, Any]] | None = None,
    **kwargs: object,
) -> SubAgent:
    """Create a Planner subagent spec.

    Args:
        model: Optional model override (string or BaseChatModel instance).
        tools: Optional list of tools. If not specified, the planner will be
            restricted to read-only tools (ls, read_file, glob, grep) to ensure
            it only creates plans and does not implement them.
        **kwargs: Additional config (ignored for forward compat).

    Returns:
        `SubAgent` dict compatible with deepagents.
    """
    spec: SubAgent = {
        "name": "planner",
        "description": PLANNER_DESCRIPTION,
        "system_prompt": PLANNER_SYSTEM_PROMPT,
    }
    if model:
        spec["model"] = model

    # Restrict to read-only tools if not specified
    if tools is not None:
        spec["tools"] = tools
    else:
        # Import here to avoid circular dependency
        from deepagents.middleware.filesystem import FilesystemMiddleware

        # Create a filesystem middleware to get read-only tools
        # We use an empty backend since we only need the tool definitions
        fs_middleware = FilesystemMiddleware()
        read_only_tools = [
            fs_middleware._create_ls_tool(),
            fs_middleware._create_read_file_tool(),
            fs_middleware._create_glob_tool(),
            fs_middleware._create_grep_tool(),
        ]
        spec["tools"] = read_only_tools

    return spec
