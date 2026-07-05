"""Assistant identity block for intake classification system prompts."""

from __future__ import annotations

from soothe.foundation.sloop.prompts.identity import build_assistant_identity_block


def build_intake_identity_message(assistant_name: str) -> str:
    """Build the assistant identity block for intake classification.

    Intake classification does not go through ``SystemPromptMiddleware``, so
    identity must be set here explicitly using the same block as CoreAgent.

    Args:
        assistant_name: Configured assistant display name (e.g. ``Soothe``).

    Returns:
        System prompt text including assistant identity.
    """
    return build_assistant_identity_block(assistant_name)


__all__ = ["build_intake_identity_message"]
