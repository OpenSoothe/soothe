"""System and human message builders for intake classification (IG-540)."""

from __future__ import annotations

from soothe.foundation.sloop.prompts.system_templates import build_timestamp_xml_footer
from soothe.foundation.sloop.prompts.user_message import _goal_text, _render_sections

from .identity_messages import build_intake_identity_message
from .prompts import (
    INTAKE_CLASSIFICATION_HUMAN_TASK,
    INTAKE_CLASSIFICATION_HUMAN_TASK_RETRY,
    INTAKE_CLASSIFICATION_RETRY_SYSTEM_PROMPT,
    INTAKE_CLASSIFICATION_SYSTEM_PROMPT,
)


def build_intake_system_message(assistant_name: str, *, retry: bool = False) -> str:
    """Build the system message for 4-class intake classification.

    Combines assistant identity, static task-agnostic rules, and a volatile
    ``<TIMESTAMP>`` footer (same placement as plan prompts).

    Args:
        assistant_name: Configured assistant display name.
        retry: When True, use the shorter retry rule set.

    Returns:
        Full system prompt text for the intake LLM call.
    """
    rules_template = (
        INTAKE_CLASSIFICATION_RETRY_SYSTEM_PROMPT if retry else INTAKE_CLASSIFICATION_SYSTEM_PROMPT
    )
    rules = rules_template.format(assistant_name=assistant_name).strip()
    identity = build_intake_identity_message(assistant_name).strip()
    timestamp = build_timestamp_xml_footer()
    return f"{identity}\n\n{rules}\n\n{timestamp}"


def build_intake_human_message(*, query: str, retry: bool = False) -> str:
    """Build the human message for intake classification.

    Uses ``GOAL:`` (same shape as plan-assess) plus a ``TASK:`` envelope that
    restates the JSON output contract at invocation time. Prior goal completion
    is supplied via projected ledger messages, not inline here.

    Args:
        query: Current user goal text.
        retry: When True, use the shorter retry task line.

    Returns:
        Plain-text human message body (``GOAL:\\n…\\n\\nTASK:\\n…``).
    """
    task = INTAKE_CLASSIFICATION_HUMAN_TASK_RETRY if retry else INTAKE_CLASSIFICATION_HUMAN_TASK
    return _render_sections([("GOAL", _goal_text(query)), ("TASK", task)])


__all__ = ["build_intake_human_message", "build_intake_system_message"]
