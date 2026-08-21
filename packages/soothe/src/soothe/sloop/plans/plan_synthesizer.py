"""LLM-driven plan synthesis from step execution evidence.

Instead of extracting the plan from raw step output (which contains
intermediate narration, tool results, and reasoning mixed together),
this module makes a dedicated LLM call with:

1. The step's execute_step ledger messages (tool calls + results + AI text)
   projected via the standard ledger projection infrastructure.
2. A plan synthesis system prompt (``plan_synthesis_system.xml``) that
   instructs the LLM to produce a structured plan document from the evidence.

This mirrors how ``node_goal_completion`` synthesizes a completion report
from execution evidence, but with a plan-specific prompt.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from langchain_core.messages import HumanMessage, SystemMessage

from soothe.prompts.graph_wrapper import GraphPromptWrapper
from soothe.sloop.orchestrator.runtime_context import LoopRuntimeContext

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

    from soothe.config import SootheConfig

logger = logging.getLogger(__name__)

_PLAN_SYNTHESIS_HUMAN_TRIGGER = (
    "Synthesize the implementation plan from the research evidence above. "
    "Output only the plan document following the template."
)


async def synthesize_plan(
    ctx: LoopRuntimeContext,
    *,
    llm: BaseChatModel,
    config: SootheConfig | None = None,
) -> str:
    """Generate a plan document from step execution evidence via LLM.

    Projects the ``execute_step`` ledger messages (tool calls, results,
    AI text) and makes a single LLM call with the plan synthesis system
    prompt. Returns the generated plan text.

    Args:
        ctx: Loop runtime context with ``loop_state`` containing the ledger.
        llm: Chat model for the synthesis call.
        config: Optional SootheConfig for ledger projection caps.

    Returns:
        Generated plan document text (may be empty on failure).
    """
    state = ctx.loop_state
    goal = state.goal or "No goal specified"

    # Build system prompt from the plan synthesis template.
    system_text = _render_plan_synthesis_system_prompt(
        user_goal=goal,
        workspace=getattr(state, "workspace", None),
        config=config,
    )

    # Project execute_step ledger messages as evidence.
    wrapper = GraphPromptWrapper(config)
    ledger_cfg = None
    if config is not None:
        ledger_cfg = config.agent.loop.plan_prompt_ledger
    projection = wrapper.project_ledger(
        kind="synthesis",
        state=state,
        ledger_cfg=ledger_cfg,
    )
    ledger_msgs = list(projection.messages)

    # Assemble the message list: system + ledger evidence + human trigger.
    messages: list[Any] = [SystemMessage(content=system_text)]
    messages.extend(ledger_msgs)
    messages.append(HumanMessage(content=_PLAN_SYNTHESIS_HUMAN_TRIGGER))

    approx_chars = sum(len(str(getattr(m, "content", ""))) for m in messages)
    logger.info(
        "[PlanSynthesis] LLM call starting: evidence_msgs=%d approx_chars=%d",
        len(ledger_msgs),
        approx_chars,
    )

    start = time.perf_counter()
    try:
        response = await llm.ainvoke(messages)
    except Exception:
        logger.exception("[PlanSynthesis] LLM call failed")
        return ""

    elapsed_ms = int((time.perf_counter() - start) * 1000)
    plan_text = _extract_text(response).strip()

    logger.info(
        "[PlanSynthesis] LLM call completed: elapsed_ms=%d plan_chars=%d",
        elapsed_ms,
        len(plan_text),
    )
    return plan_text


def _render_plan_synthesis_system_prompt(
    *,
    user_goal: str,
    workspace: str | None,
    config: SootheConfig | None = None,
) -> str:
    """Render the plan synthesis system prompt from the Jinja2 template."""
    from soothe.prompts import build_timestamp_xml_footer, load_agent_instructions
    from soothe.prompts.loader import load_prompt_fragment

    template = load_prompt_fragment("instructions/plan_synthesis_system.xml")
    parts = [
        template.render(user_goal=user_goal),
    ]
    if workspace:
        agent_instructions_max_chars = 8000
        if config is not None:
            agent_instructions_max_chars = int(config.agent.agent_instructions_max_chars)
        block = load_agent_instructions(
            workspace,
            headline_max_chars=agent_instructions_max_chars,
        )
        if block:
            parts.append(block)
    parts.append(build_timestamp_xml_footer())
    return "\n\n".join(parts)


def _extract_text(response: Any) -> str:
    """Extract text content from an LLM response (AIMessage or str)."""
    if isinstance(response, str):
        return response
    content = getattr(response, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        # Multimodal response — extract text blocks.
        texts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                text = block.get("text")
                if isinstance(text, str):
                    texts.append(text)
            elif isinstance(block, str):
                texts.append(block)
        return "\n".join(texts)
    return str(content)


__all__ = ["synthesize_plan"]
