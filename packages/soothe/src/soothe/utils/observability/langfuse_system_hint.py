"""Thread-local hint so Langfuse can record CoreAgent system prompts on generations (IG-385).

``SystemPromptOptimizationMiddleware`` sets the effective system text before each model
call; :class:`SootheLangfuseCallbackHandler` reads it and injects a ``SystemMessage``
into LangChain's traced message list when the batch has no usable system content, so
Langfuse generations show the same prompt the model received.
"""

from __future__ import annotations

from contextvars import ContextVar, Token

_VAR: ContextVar[str | None] = ContextVar("soothe_langfuse_system_prompt_hint", default=None)


def push_langfuse_system_prompt_hint(text: str | None) -> Token | None:
    """Attach plain-text system prompt for the next traced chat model start in this context.

    Args:
        text: Full system prompt, or None to skip.

    Returns:
        Token for :func:`reset_langfuse_system_prompt_hint`, or None if nothing pushed.
    """
    if not text or not str(text).strip():
        return None
    return _VAR.set(str(text))


def reset_langfuse_system_prompt_hint(token: Token | None) -> None:
    """Clear hint pushed by :func:`push_langfuse_system_prompt_hint`."""
    if token is not None:
        _VAR.reset(token)


def get_langfuse_system_prompt_hint() -> str | None:
    """Return the active hint, if any."""
    v = _VAR.get()
    return v if v else None
