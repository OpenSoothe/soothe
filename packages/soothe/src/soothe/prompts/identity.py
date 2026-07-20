"""Unified assistant identity for system prompts."""

from __future__ import annotations

from soothe.prompts.fragments import ASSISTANT_IDENTITY_FRAGMENT


def normalize_assistant_name(assistant_name: str) -> str:
    """Return a non-empty configured assistant display name."""
    name = (assistant_name or "Soothe").strip()
    return name or "Soothe"


def build_assistant_identity_block(assistant_name: str) -> str:
    """Build the cache-stable ``<ASSISTANT_IDENTITY>`` XML block.

    Args:
        assistant_name: Configured assistant display name (e.g. ``Soothe``).

    Returns:
        Formatted identity block (single source of truth for prompt injection).
    """
    name = normalize_assistant_name(assistant_name)
    return ASSISTANT_IDENTITY_FRAGMENT.format(assistant_name=name).strip()


def prepend_assistant_identity(system_body: str, assistant_name: str) -> str:
    """Prepend the canonical identity block to a system prompt body.

    Use for CoreAgent system prompts (``resolve_system_prompt``, middleware).
    Pass 1 intake uses ``build_intake_pass1_system_prompt`` which appends live
    timestamp context at the tail for prompt-cache stability.

    Args:
        system_body: Phase-specific instructions without identity.
        assistant_name: Configured assistant display name.

    Returns:
        Identity block followed by the body.
    """
    identity = build_assistant_identity_block(assistant_name)
    body = system_body.strip()
    if not body:
        return identity
    return f"{identity}\n\n{body}"


__all__ = [
    "build_assistant_identity_block",
    "normalize_assistant_name",
    "prepend_assistant_identity",
]
