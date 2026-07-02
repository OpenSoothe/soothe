"""Project StrangeLoop state into user-safe synthesis context (RFC-603, RFC-214).

Goal-synthesis injects ``execute_step`` ledger turns as native messages (like
plan-assess) for prompt-cache alignment. Plan-phase ledger rows stay out of the
message list. Scenario, focus, emphasis, and the verbatim user request live in
the system prompt; the closing human message is a short TASK trigger only.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from soothe.foundation.sloop.engine.scenario_classifier import ScenarioClassification
from soothe.foundation.sloop.prompts.plan_ledger_projection import (
    project_loop_messages_for_synthesis,
)
from soothe.foundation.sloop.prompts.user_message import (
    _goal_text,
    flatten_user_message_content,
)
from soothe.foundation.sloop.utils.stream_normalize import extract_text_from_message_content

if TYPE_CHECKING:
    from soothe.config.models import PlanPromptLedgerConfig
    from soothe.foundation.sloop.state.schemas import LoopState


def normalize_user_query(goal: str | None) -> str:
    """Normalize stored goal text for the user-facing synthesis request."""
    text = _goal_text(goal)
    if text == "No goal specified":
        return "No request specified"
    return text


def flatten_execute_human_content(content: str) -> str:
    """Extract task-focused text from an execute-step human envelope.

    Handles both the new scenario-based format (extracts GOAL: line)
    and legacy XML format (extracts <USER_QUERY> body). Returns raw
    content unchanged when neither marker is present.
    """
    return flatten_user_message_content(content)


def _messages_text_len(messages: list[BaseMessage]) -> int:
    return sum(len(extract_text_from_message_content(getattr(m, "content", ""))) for m in messages)


def render_synthesis_system_prompt(
    classification: ScenarioClassification,
    *,
    user_goal: str,
    workspace: str | None = None,
    agent_instructions_max_chars: int = 8000,
) -> str:
    """Render system instructions from the synthesis template (no orchestration terms)."""
    from soothe.foundation.sloop.prompts.loader import load_prompt_fragment
    from soothe.foundation.sloop.prompts.project_instructions import load_agent_instructions
    from soothe.foundation.sloop.prompts.system_templates import build_timestamp_xml_footer

    template = load_prompt_fragment("instructions/synthesis_report_system.xml")
    focus_items = "\n".join(f"- {item}" for item in classification.contextual_focus)
    parts = [
        template.render(
            scenario=classification.scenario,
            sections=classification.sections,
            contextual_focus=focus_items,
            evidence_emphasis=classification.evidence_emphasis,
            user_goal=user_goal,
        )
    ]
    if workspace:
        block = load_agent_instructions(
            workspace,
            headline_max_chars=agent_instructions_max_chars,
        )
        if block:
            parts.append(block)
    parts.append(build_timestamp_xml_footer())
    return "\n\n".join(parts)


def build_synthesis_messages(
    state: LoopState,
    classification: ScenarioClassification,
    *,
    user_query: str | None = None,
    max_chars: int,
    ledger_cfg: PlanPromptLedgerConfig | None = None,
    agent_instructions_max_chars: int = 8000,
) -> list[BaseMessage]:
    """Assemble system + execute ledger + TASK human for goal-completion synthesis."""
    from soothe.foundation.sloop.prompts.user_message import UserMessageBuilder

    user_goal = normalize_user_query(user_query if user_query is not None else state.goal)
    system_text = render_synthesis_system_prompt(
        classification,
        user_goal=user_goal,
        workspace=state.workspace,
        agent_instructions_max_chars=agent_instructions_max_chars,
    )
    ledger_msgs = list(
        project_loop_messages_for_synthesis(state.loop_messages, ledger_cfg),
    )
    human_text = UserMessageBuilder().build_synthesis_message()

    while max_chars > 0:
        total = len(system_text) + _messages_text_len(ledger_msgs) + len(human_text)
        if total <= max_chars:
            break
        if ledger_msgs:
            ledger_msgs.pop(0)
            continue
        break

    out: list[BaseMessage] = [SystemMessage(content=system_text)]
    out.extend(ledger_msgs)
    out.append(HumanMessage(content=human_text))
    return out


__all__ = [
    "build_synthesis_messages",
    "flatten_execute_human_content",
    "normalize_user_query",
    "render_synthesis_system_prompt",
]
