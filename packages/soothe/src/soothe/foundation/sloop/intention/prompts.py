"""LLM prompts for two-pass intake classification (RFC-630, IG-554).

- ``INTAKE_PASS1_SYSTEM_PROMPT``: Social vs task (no prior context).
- ``INTAKE_PASS2_SYSTEM_PROMPT``: Scope (trivial/simple/complex).
"""

from __future__ import annotations

from pathlib import Path

_CLASSIFIER_FRAGMENTS_DIR = (
    Path(__file__).resolve().parent.parent / "prompts" / "fragments" / "classifiers"
)


def _read_classifier_fragment(name: str) -> str:
    return (_CLASSIFIER_FRAGMENTS_DIR / name).read_text(encoding="utf-8")


def build_prompt_timestamp_block() -> str:
    """Build the live ``<PROMPT_TIMESTAMP>`` block for LLM system prompts."""
    from soothe.foundation.sloop.prompts.fragments import PROMPT_TIMESTAMP_FRAGMENT
    from soothe.utils.prompt_clock import prompt_datetime_context

    return PROMPT_TIMESTAMP_FRAGMENT.format(**prompt_datetime_context()).strip()


INTAKE_PASS1_SYSTEM_PROMPT = _read_classifier_fragment("intake_pass1_system.xml")
INTAKE_PASS2_SYSTEM_PROMPT = _read_classifier_fragment("intake_pass2_system.xml")
INTAKE_PASS1_SOCIAL_REPLY_PROMPT = _read_classifier_fragment("intake_pass1_social_reply.xml")

INTAKE_PASS1_HUMAN_TASK = "Classify above. JSON only."
INTAKE_PASS2_HUMAN_TASK = "Classify CURRENT_GOAL scope. JSON only."
INTAKE_PASS1_SOCIAL_REPLY_HUMAN_TASK = "Write the social_response reply. JSON only."


def build_intake_pass1_system_prompt(body: str, assistant_name: str) -> str:
    """Assemble Pass 1 system prompt with identity and live timestamp at the tail."""
    from soothe.foundation.sloop.prompts.identity import build_assistant_identity_block

    parts = [
        build_assistant_identity_block(assistant_name),
        body.strip(),
        build_prompt_timestamp_block(),
    ]
    return "\n\n".join(part for part in parts if part)


__all__ = [
    "INTAKE_PASS1_HUMAN_TASK",
    "INTAKE_PASS1_SOCIAL_REPLY_HUMAN_TASK",
    "INTAKE_PASS1_SOCIAL_REPLY_PROMPT",
    "INTAKE_PASS1_SYSTEM_PROMPT",
    "INTAKE_PASS2_HUMAN_TASK",
    "INTAKE_PASS2_SYSTEM_PROMPT",
    "build_intake_pass1_system_prompt",
    "build_prompt_timestamp_block",
]
