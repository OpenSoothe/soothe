"""Thread-local hint so Langfuse can record system prompts on generations."""

from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Any

_VAR: ContextVar[str | None] = ContextVar("soothe_langfuse_system_prompt_hint", default=None)


def push_langfuse_system_prompt_hint(text: str | None) -> Token | None:
    """Attach plain-text system prompt for the next traced chat model start in this context."""
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


def publish_langfuse_system_prompt_hint(
    text: str | None,
    *,
    runnable_config: dict[str, Any] | None = None,
) -> Token | None:
    """Push ContextVar hint and register on the Langfuse handler for this thread."""
    tok = push_langfuse_system_prompt_hint(text)
    if not text or not str(text).strip():
        return tok
    if runnable_config is None:
        try:
            from langgraph.config import get_config

            runnable_config = get_config()
        except Exception:
            runnable_config = None
    if not isinstance(runnable_config, dict):
        return tok
    try:
        from soothe_sdk.observability.langfuse._merge import (
            langfuse_handler_from_runnable_config,
        )
        from soothe_sdk.observability.langfuse.callback_handler import (
            SootheLangfuseCallbackHandler,
        )

        handler = langfuse_handler_from_runnable_config(runnable_config)
        if isinstance(handler, SootheLangfuseCallbackHandler):
            handler.register_system_prompt_hint_for_config(runnable_config, str(text))
    except Exception:
        pass
    return tok


def clear_langfuse_system_prompt_hint(
    token: Token | None,
    *,
    runnable_config: dict[str, Any] | None = None,
) -> None:
    """Reset ContextVar hint and drop thread-keyed handler registration."""
    reset_langfuse_system_prompt_hint(token)
    if runnable_config is None:
        try:
            from langgraph.config import get_config

            runnable_config = get_config()
        except Exception:
            runnable_config = None
    if not isinstance(runnable_config, dict):
        return
    try:
        from soothe_sdk.observability.langfuse._merge import (
            langfuse_handler_from_runnable_config,
        )
        from soothe_sdk.observability.langfuse.callback_handler import (
            SootheLangfuseCallbackHandler,
        )

        handler = langfuse_handler_from_runnable_config(runnable_config)
        if isinstance(handler, SootheLangfuseCallbackHandler):
            handler.clear_system_prompt_hint_for_config(runnable_config)
    except Exception:
        pass
