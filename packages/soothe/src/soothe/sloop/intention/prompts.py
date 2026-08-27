"""LLM prompts for intake classification (RFC-630 / RFC-904).

- ``INTAKE_CLASSIFY_SYSTEM_PROMPT``: social vs task + task complexity + short description.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import soothe.prompts.fragments as _prompt_fragments

if TYPE_CHECKING:
    from soothe.config.models import AssistantIdentity

_INTAKE_FRAGMENTS_DIR = Path(_prompt_fragments.__file__).resolve().parent / "intake"


def _read_intake_fragment(name: str) -> str:
    return (_INTAKE_FRAGMENTS_DIR / name).read_text(encoding="utf-8")


def build_prompt_timestamp_block(
    ctx: dict[str, str] | None = None,
) -> str:
    """Build the live ``<PROMPT_TIMESTAMP>`` block for LLM system prompts.

    Pass a pre-fetched ``ctx`` (from :func:`prompt_datetime_context`) to
    avoid a timestamp race when the caller already captured the context.
    """
    from soothe.prompts.fragments import PROMPT_TIMESTAMP_FRAGMENT
    from soothe.utils.prompt_clock import prompt_datetime_context

    if ctx is None:
        ctx = prompt_datetime_context()
    return PROMPT_TIMESTAMP_FRAGMENT.format(**ctx).strip()


INTAKE_CLASSIFY_SYSTEM_PROMPT = _read_intake_fragment("intake_classify_system.xml")
INTAKE_SOCIAL_REPLY_PROMPT = _read_intake_fragment("social_reply.xml")

INTAKE_CLASSIFY_HUMAN_TASK = "Classify the user message above. JSON only."
INTAKE_PRIOR_LANGUAGE_PREFIX = "PRIOR_RESPONSE_LANGUAGE: {language}"


def build_intake_human_content(
    query: str,
    *,
    prior_response_language: str | None = None,
) -> str:
    """Assemble the intake human message with optional prior-language structural hint."""
    parts = [query.strip()]
    if prior_response_language:
        parts.append(INTAKE_PRIOR_LANGUAGE_PREFIX.format(language=prior_response_language))
    parts.append(INTAKE_CLASSIFY_HUMAN_TASK)
    return "\n\n".join(parts)


INTAKE_SOCIAL_REPLY_HUMAN_TASK = "Write the social_response reply. JSON only."


def _substitute_prompt_placeholders(template: str, values: dict[str, str]) -> str:
    """Replace ``{key}`` placeholders without interpreting other braces (e.g. JSON)."""
    result = template
    for key, value in values.items():
        result = result.replace(f"{{{key}}}", value)
    return result


def build_intake_system_prompt(
    body: str,
    assistant_name: str,
    *,
    ctx: dict[str, str] | None = None,
    identity: AssistantIdentity | None = None,
) -> str:
    """Assemble the intake system prompt with identity and live timestamp at the tail.

    Pass a pre-fetched ``ctx`` (from :func:`prompt_datetime_context`) to
    avoid a timestamp race when the caller already captured the context.

    Args:
        body: Intake fragment text (from ``_read_intake_fragment``).
        assistant_name: Configured assistant display name.
        ctx: Optional pre-fetched datetime context.
        identity: Optional configured persona; ``None`` falls back to the
            built-in identity line.
    """
    from soothe.identity.persona import _format_vendor_denylist, build_assistant_identity_block
    from soothe.prompts import normalize_assistant_name
    from soothe.utils.prompt_clock import prompt_datetime_context

    name = normalize_assistant_name(assistant_name)
    # Capture the datetime context once to avoid a timestamp race where
    # the second ticks over between independent calls.
    if ctx is None:
        ctx = prompt_datetime_context()
    format_ctx = {
        "assistant_name": name,
        "assistant_creator": "Dr. Xiaming Chen",
        "assistant_role": "a helpful AI assistant",
        "assistant_vendor_denylist": _format_vendor_denylist(
            ["Claude", "ChatGPT", "Gemini", "Anthropic", "OpenAI", "Google"]
        ),
        **ctx,
    }
    if identity is not None:
        format_ctx["assistant_creator"] = identity.creator.strip() or "Dr. Xiaming Chen"
        format_ctx["assistant_role"] = identity.role_description.strip() or "a helpful AI assistant"
        format_ctx["assistant_vendor_denylist"] = _format_vendor_denylist(
            list(identity.vendor_denylist)
        )
    formatted_body = _substitute_prompt_placeholders(body.strip(), format_ctx)

    parts = [
        build_assistant_identity_block(name, identity=identity),
        formatted_body,
        build_prompt_timestamp_block(format_ctx),
    ]
    return "\n\n".join(part for part in parts if part)


__all__ = [
    "INTAKE_CLASSIFY_HUMAN_TASK",
    "INTAKE_CLASSIFY_SYSTEM_PROMPT",
    "INTAKE_PRIOR_LANGUAGE_PREFIX",
    "INTAKE_SOCIAL_REPLY_HUMAN_TASK",
    "INTAKE_SOCIAL_REPLY_PROMPT",
    "build_intake_human_content",
    "build_intake_system_prompt",
    "build_prompt_timestamp_block",
]
