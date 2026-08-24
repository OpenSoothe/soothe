"""Thread-local hint so Langfuse can record system prompts on generations."""

from __future__ import annotations

from contextvars import ContextVar

_VAR: ContextVar[str | None] = ContextVar("soothe_langfuse_system_prompt_hint", default=None)


def get_langfuse_system_prompt_hint() -> str | None:
    """Return the active hint, if any."""
    v = _VAR.get()
    return v if v else None
