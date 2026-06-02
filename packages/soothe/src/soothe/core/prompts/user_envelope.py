"""User message envelope builder for execute-step (RFC-214).

Builds the XML envelope that wraps per-turn dynamic content:
- <USER_QUERY> up front (what to do this turn)
- Slash-skill turns: optional ``<SKILL_CONTEXT>`` after ``<USER_QUERY>`` (skill reference
  only, not the full expanded goal prompt)
- ``--- Context ---`` then <DYNAMIC_CONTEXT>: execution hints, timestamp, language hint
- Optional ``<MCP_RESOURCE>`` blocks for ``@server:uri`` attachment references

This envelope keeps volatile content out of the system prompt,
maximizing prompt cache hits.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from soothe.core.loop.state.schemas import PriorProgressDigest

# Strip legacy AgentLoop suffix accidentally baked into goal text or stored checkpoints.
_GOAL_ITERATION_SUFFIX_RE = re.compile(
    r"\s*\(iteration\s+\d+/\d+\)\s*$",
    re.IGNORECASE,
)

# Language directive lives in the system prompt (`RESPONSE_LANGUAGE_HINT_FRAGMENT`)
# so the per-turn envelope stays cache-stable.

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
    """Resolve ``@server:uri`` refs into ``<MCP_RESOURCE>`` XML blocks.

    Args:
        refs: List of ``(server, uri)`` tuples from ``extract_mcp_resource_refs``.
        mcp_registry: Optional ``MCPRegistry`` for reading resources.

    Returns:
        List of ``<MCP_RESOURCE>`` XML block strings.
    """
    if not refs or mcp_registry is None:
        return []
    blocks: list[str] = []
    for server, uri in refs:
        try:
            content = await mcp_registry.read_resource(server, uri)
        except Exception:  # noqa: BLE001
            content = f"<error>Failed to read resource {server}:{uri}</error>"
        blocks.append(f'<MCP_RESOURCE server="{server}" uri="{uri}">\n{content}\n</MCP_RESOURCE>')
    return blocks


def _goal_text_for_execute_step_envelope(goal: str | None) -> str:
    """Normalize goal string (strip iteration suffix)."""
    raw = (goal or "").strip()
    if not raw:
        return "No goal specified"
    stripped = _GOAL_ITERATION_SUFFIX_RE.sub("", raw).strip()
    return stripped if stripped else "No goal specified"


def build_execute_step_envelope(
    step_description: str,
    *,
    execution_hints: str | None = None,
    workspace_state: str | None = None,
    skill_context: str | None = None,
    mcp_resource_blocks: list[str] | None = None,
) -> str:
    """Build the user message envelope for an execute-step (RFC-214).

    The envelope contains all per-turn volatile content that should NOT
    be in the system prompt (date, execution hints, optional skill reference).

    Args:
        step_description: The step's description (what to execute).
        execution_hints: Optional hints text from ExecutionHintsMiddleware.
        workspace_state: Optional lightweight workspace diff summary.
        skill_context: Skill reference only (SKILL.md); omitted when not a slash-skill turn.
        mcp_resource_blocks: Optional pre-resolved ``<MCP_RESOURCE>`` XML blocks.

    Returns:
        XML envelope string for the LoopHumanMessage content.
    """
    now = dt.datetime.now(dt.UTC).astimezone()
    date_str = now.strftime("%Y-%m-%d")
    timestamp = now.isoformat()

    user_query = f"<USER_QUERY>\n{step_description}\n</USER_QUERY>"

    body_parts: list[str] = [user_query]
    skill_ref = (skill_context or "").strip()
    if skill_ref:
        body_parts.append(f"<SKILL_CONTEXT>\n{skill_ref}\n</SKILL_CONTEXT>")
    for block in mcp_resource_blocks or []:
        body_parts.append(block)

    # <DYNAMIC_CONTEXT>: hints + context only (step instruction is above the fold)
    dynamic_parts: list[str] = []

    if execution_hints:
        dynamic_parts.append(f"<EXECUTION_HINTS>\n{execution_hints}\n</EXECUTION_HINTS>")

    context_info_parts = [
        f"<timestamp>{timestamp}</timestamp>",
        f"<date>{date_str}</date>",
    ]
    if workspace_state:
        context_info_parts.append(f"<workspace_state>{workspace_state}</workspace_state>")
    dynamic_parts.append("<CONTEXT_INFO>\n" + "\n".join(context_info_parts) + "\n</CONTEXT_INFO>")

    dynamic_context = "<DYNAMIC_CONTEXT>\n" + "\n".join(dynamic_parts) + "\n</DYNAMIC_CONTEXT>"

    return "\n\n".join(body_parts) + _EXECUTE_STEP_CONTEXT_SEPARATOR + dynamic_context


# Hard cap on the rendered <PRIOR_PROGRESS> block (RFC-227). Evidence lines
# are dropped first when the budget is exceeded, then tool lines.
PRIOR_PROGRESS_MAX_CHARS = 600


def _render_prior_progress_block(
    digest: PriorProgressDigest,
) -> str:
    """Render a PriorProgressDigest as the <PRIOR_PROGRESS> envelope block.

    Hard-capped at ``PRIOR_PROGRESS_MAX_CHARS``; trailing evidence lines drop
    first, then trailing tool lines.
    """
    header = (
        f"iter={digest.iteration} wave={digest.wave_index} "
        f"done={digest.steps_completed} failed={digest.steps_failed} "
        f"hint={digest.derived_progress_hint}"
    )
    tool_lines = [
        f"- {t.name}: {json.dumps(t.head, ensure_ascii=False)}" for t in digest.tool_calls
    ]
    evidence_lines = [f"- {json.dumps(e, ensure_ascii=False)}" for e in digest.evidence_excerpts]

    def _assemble(tools: list[str], evidence: list[str]) -> str:
        parts = [header]
        if tools:
            parts.append("tools:")
            parts.extend(tools)
        if evidence:
            parts.append("evidence:")
            parts.extend(evidence)
        return "<PRIOR_PROGRESS>\n" + "\n".join(parts) + "\n</PRIOR_PROGRESS>"

    rendered = _assemble(tool_lines, evidence_lines)
    while len(rendered) > PRIOR_PROGRESS_MAX_CHARS and evidence_lines:
        evidence_lines.pop()
        rendered = _assemble(tool_lines, evidence_lines)
    while len(rendered) > PRIOR_PROGRESS_MAX_CHARS and tool_lines:
        tool_lines.pop()
        rendered = _assemble(tool_lines, evidence_lines)
    return rendered


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
    """Build the user message envelope for plan-assess/plan-generate (RFC-214).

    Uses ``<USER_QUERY>`` for the goal — same tag as execute-step envelope,
    avoiding redundant nesting now that ``state.goal`` carries only the user
    instruction (not the full skill body).

    Args:
        goal: Current goal text (user instruction only).
        dag_context: Optional DAG planning context XML.
        step_id_hint: Optional next step ID hint text.
        goal_user_submission: Original ``/skill:`` line when applicable; unused
            since the goal split (kept for API compat).
        skill_context: Skill reference body for ``<SKILL_REFERENCE>`` when slash-skill
            invoked; injected once per turn so the body is not duplicated elsewhere.
        prior_progress: RFC-227 per-wave digest. When present and not stale
            (``digest.iteration >= current_iteration - 1``), rendered as a
            ``<PRIOR_PROGRESS>`` block before ``<CONTEXT_INFO>``. Omitted
            otherwise; never raises.
        current_iteration: Current loop iteration used for the prior-progress
            staleness check. When ``None``, the digest is treated as fresh.

    Returns:
        XML envelope string for the plan-context LoopHumanMessage.
    """
    now = dt.datetime.now(dt.UTC).astimezone()
    date_str = now.strftime("%Y-%m-%d")
    timestamp = now.isoformat()

    goal_display = _goal_text_for_execute_step_envelope(goal)
    user_query = f"<USER_QUERY>\n{goal_display}\n</USER_QUERY>"

    # Optional hints
    extra_parts: list[str] = []
    skill_ref_body = (skill_context or "").strip()
    if skill_ref_body:
        extra_parts.append(f"<SKILL_REFERENCE>\n{skill_ref_body}\n</SKILL_REFERENCE>")
    if step_id_hint:
        extra_parts.append(step_id_hint)
    if dag_context:
        extra_parts.append(dag_context)
    if prior_progress is not None:
        is_stale = (
            current_iteration is not None and prior_progress.iteration < current_iteration - 1
        )
        if not is_stale:
            extra_parts.append(_render_prior_progress_block(prior_progress))

    # <CONTEXT_INFO>
    context_info_parts = [
        f"<timestamp>{timestamp}</timestamp>",
        f"<date>{date_str}</date>",
    ]
    context_info = "<CONTEXT_INFO>\n" + "\n".join(context_info_parts) + "\n</CONTEXT_INFO>"

    parts = [user_query] + extra_parts + [context_info]
    return "\n".join(parts)
