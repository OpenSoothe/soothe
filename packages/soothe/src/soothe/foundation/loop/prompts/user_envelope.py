"""User message envelope builder for execute-step (RFC-214).

.. deprecated::
    Use :class:`soothe.foundation.loop.prompts.user_message.UserMessageBuilder`
    instead. This module provides backward-compatible wrappers that delegate to
    the new builder.
"""

from __future__ import annotations

import re
import warnings
from typing import TYPE_CHECKING, Any

from soothe.foundation.loop.prompts.user_message import (
    UserMessageBuilder,
)

if TYPE_CHECKING:
    from soothe.foundation.loop.state.schemas import PriorProgressDigest

# Strip legacy AgentLoop suffix accidentally baked into goal text or stored checkpoints.
_GOAL_ITERATION_SUFFIX_RE = re.compile(
    r"\s*\(iteration\s+\d+/\d+\)\s*$",
    re.IGNORECASE,
)

_EXECUTE_STEP_CONTEXT_SEPARATOR = "\n\n--- Context ---\n\n"

# Pattern for @server:uri references in user messages (e.g. @github:issue://123)
_MCP_RESOURCE_REF_RE = re.compile(r"@(\w+):(\S+)")


def extract_mcp_resource_refs(text: str) -> list[tuple[str, str]]:
    """Extract ``@server:uri`` references from user text.

    Returns:
        List of ``(server, uri)`` tuples.
    """
    return [(m.group(1), m.group(2)) for m in _MCP_RESOURCE_REF_RE.finditer(text)]


async def resolve_mcp_resource_blocks(
    refs: list[tuple[str, str]],
    mcp_registry: Any | None,
) -> list[str]:
    """Resolve ``@server:uri`` refs into MCP resource content blocks.

    Args:
        refs: List of ``(server, uri)`` tuples from ``extract_mcp_resource_refs``.
        mcp_registry: Optional ``MCPRegistry`` for reading resources.

    Returns:
        List of MCP resource content strings.
    """
    if not refs or mcp_registry is None:
        return []
    blocks: list[str] = []
    for server, uri in refs:
        try:
            content = await mcp_registry.read_resource(server, uri)
        except Exception:  # noqa: BLE001
            content = f"<error>Failed to read resource {server}:{uri}</error>"
        blocks.append(f"[MCP {server}:{uri}]\n{content}")
    return blocks


_builder = UserMessageBuilder()


def build_execute_step_envelope(
    step_description: str,
    *,
    execution_hints: str | None = None,
    workspace_state: str | None = None,
    skill_context: str | None = None,
    mcp_resource_blocks: list[str] | None = None,
) -> str:
    """Build the user message for an execute-step.

    .. deprecated::
        Use :meth:`UserMessageBuilder.build_execute_step_message` instead.
    """
    warnings.warn(
        "build_execute_step_envelope is deprecated; use UserMessageBuilder.build_execute_step_message",
        DeprecationWarning,
        stacklevel=2,
    )
    return _builder.build_execute_step_message(
        step_description,
        execution_hints=execution_hints,
        workspace_state=workspace_state,
        skill_context=skill_context,
        mcp_resource_blocks=mcp_resource_blocks,
    )


def _render_prior_progress_block(
    digest: PriorProgressDigest,
) -> str:
    """Render a PriorProgressDigest as the PRIOR PROGRESS section.

    .. deprecated::
        Use :func:`soothe.foundation.loop.prompts.user_message._render_prior_progress` instead.
    """
    from soothe.foundation.loop.prompts.user_message import _render_prior_progress

    warnings.warn(
        "_render_prior_progress_block is deprecated; use _render_prior_progress",
        DeprecationWarning,
        stacklevel=2,
    )
    return _render_prior_progress(digest)


def build_plan_context_envelope(
    goal: str,
    *,
    dag_context: str | None = None,
    step_id_hint: str | None = None,
    goal_user_submission: str | None = None,
    skill_context: str | None = None,
    prior_progress: PriorProgressDigest | None = None,
    current_iteration: int | None = None,
) -> str:
    """Build the user message for plan-assess/plan-generate.

    .. deprecated::
        Use :meth:`UserMessageBuilder.build_plan_assess_message` or
        :meth:`UserMessageBuilder.build_plan_generate_message` instead.
    """
    warnings.warn(
        "build_plan_context_envelope is deprecated; use UserMessageBuilder.build_plan_assess_message "
        "or UserMessageBuilder.build_plan_generate_message",
        DeprecationWarning,
        stacklevel=2,
    )
    return _builder.build_plan_assess_message(
        goal=goal,
        dag_context=dag_context,
        skill_context=skill_context,
        prior_progress=prior_progress,
        current_iteration=current_iteration,
    )
