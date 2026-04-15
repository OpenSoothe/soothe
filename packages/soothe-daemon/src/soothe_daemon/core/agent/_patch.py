"""Deepagents compatibility patches.

Patches are applied at import time and isolated from CoreAgent logic.
These patches fix upstream issues in deepagents that affect Soothe's execution.
"""

from __future__ import annotations

from typing import Any


def _patch_summarization_overwrite_handling() -> None:
    """Patch deepagents SummarizationMiddleware for Overwrite wrapper handling.

    deepagents' SummarizationMiddleware._apply_event_to_messages does not
    handle langgraph's Overwrite wrapper that PatchToolCallsMiddleware may
    leave in request.messages. This patch unwraps it so ``list(messages)`` succeeds.

    This is a temporary workaround until fixed upstream in deepagents.
    """
    try:
        from deepagents.middleware.summarization import SummarizationMiddleware
        from langgraph.types import Overwrite
    except ImportError:
        return

    _original = SummarizationMiddleware._apply_event_to_messages

    @staticmethod  # type: ignore[misc]
    def _patched(messages: Any, event: Any) -> list[Any]:
        if isinstance(messages, Overwrite):
            messages = messages.value
        return _original(messages, event)

    SummarizationMiddleware._apply_event_to_messages = _patched  # type: ignore[assignment]


# Apply patches at module import time
_patch_summarization_overwrite_handling()
