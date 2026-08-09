"""LoopRail guard prompt assembly (IG-736)."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from soothe.autopilot.prompts.envelopes import wrap_untrusted
from soothe.autopilot.prompts.fragments import GUARD_SYSTEM_FRAGMENT

__all__ = ["build_guard_messages", "build_guard_user_prompt"]


def build_guard_user_prompt(
    *,
    event: str,
    goal_id: str | None,
    trigger_tags: list[str],
    condition_name: str | None,
    structural: dict[str, Any],
    sibling_statuses: dict[str, str],
    tags_by_goal: dict[str, list[str]],
    retry_count: int,
    condition_text: str,
    goal_summary: str,
) -> str:
    """Build the guard evaluator user message (trusted facts + untrusted block)."""
    trusted = (
        f"Event: {event}\n"
        f"Trigger goal_id: {goal_id}\n"
        f"Trigger goal tags: {trigger_tags}\n"
        f"Condition name: {condition_name or '(inline)'}\n"
        f"STRUCTURAL FACTS: {structural}\n"
        f"Sibling/descendant statuses (goal_id -> status): {sibling_statuses}\n"
        f"Tags by goal: {tags_by_goal}\n"
        f"Trigger goal retry_count: {retry_count}\n"
    )
    untrusted_body = (
        f"Condition text:\n{condition_text}\n\nTrigger goal summary: {goal_summary or '(none)'}\n"
    )
    return f"{trusted}\n{wrap_untrusted(untrusted_body)}"


def build_guard_messages(
    *,
    event: str,
    goal_id: str | None,
    trigger_tags: list[str],
    condition_name: str | None,
    structural: dict[str, Any],
    sibling_statuses: dict[str, str],
    tags_by_goal: dict[str, list[str]],
    retry_count: int,
    condition_text: str,
    goal_summary: str,
) -> list[BaseMessage]:
    """Build System + Human messages for the LoopRail guard LLM call."""
    user_prompt = build_guard_user_prompt(
        event=event,
        goal_id=goal_id,
        trigger_tags=trigger_tags,
        condition_name=condition_name,
        structural=structural,
        sibling_statuses=sibling_statuses,
        tags_by_goal=tags_by_goal,
        retry_count=retry_count,
        condition_text=condition_text,
        goal_summary=goal_summary,
    )
    return [
        SystemMessage(content=GUARD_SYSTEM_FRAGMENT),
        HumanMessage(content=user_prompt),
    ]
