"""Merge Langfuse LangChain callbacks into RunnableConfig."""

from __future__ import annotations

from typing import Any

from soothe_sdk.observability.langfuse._client import resolve_str, resolved_langfuse_tags
from soothe_sdk.observability.langfuse._handlers import (
    cached_langfuse_callback_handler,
    create_fresh_langfuse_handler,
    handler_for_pinned_trace,
)
from soothe_sdk.observability.langfuse._types import SootheConfigLike


def iter_callback_handlers(callbacks: Any) -> list[Any]:
    """Flatten LangChain ``callbacks`` (list or ``CallbackManager``) to handler instances."""
    out: list[Any] = []
    if callbacks is None:
        return out
    if isinstance(callbacks, (list, tuple)):
        for item in callbacks:
            out.extend(iter_callback_handlers(item))
        return out
    nested = getattr(callbacks, "handlers", None)
    if isinstance(nested, (list, tuple)):
        for h in nested:
            out.extend(iter_callback_handlers(h))
        inheritable = getattr(callbacks, "inheritable_handlers", None)
        if isinstance(inheritable, (list, tuple)):
            for h in inheritable:
                for item in iter_callback_handlers(h):
                    if item not in out:
                        out.append(item)
        return out
    out.append(callbacks)
    return out


def langfuse_handler_from_runnable_config(config: dict[str, Any]) -> Any | None:
    """Return the SDK Langfuse LangChain handler from RunnableConfig if present."""
    from soothe_sdk.observability.langfuse.callback_handler import (
        SootheLangfuseCallbackHandler,
    )

    for h in iter_callback_handlers(config.get("callbacks")):
        if isinstance(h, SootheLangfuseCallbackHandler):
            return h
    return None


def pinned_trace_id_from_config(config: dict[str, Any] | None) -> str | None:
    """Read ``langfuse_trace_id`` from RunnableConfig metadata when present."""
    if not config:
        return None
    meta = config.get("metadata")
    if not isinstance(meta, dict):
        return None
    raw = meta.get("langfuse_trace_id")
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def merge_langfuse_runnable_config(
    base: dict[str, Any],
    soothe_config: SootheConfigLike | None,
    *,
    session_id: str | None = None,
    run_name: str | None = None,
    loop_id: str | None = None,
    inherit_callbacks_from: dict[str, Any] | None = None,
    fresh_handler: bool = False,
    pinned_trace_id: str | None = None,
) -> dict[str, Any]:
    """Return Runnable config with Langfuse callbacks and session metadata merged in."""
    if soothe_config is None or not soothe_config.observability.langfuse.enabled:
        return base

    inherit_handler = (
        langfuse_handler_from_runnable_config(inherit_callbacks_from)
        if inherit_callbacks_from is not None
        else None
    )
    effective_pinned = pinned_trace_id or pinned_trace_id_from_config(inherit_callbacks_from)

    if fresh_handler:
        handler = create_fresh_langfuse_handler(soothe_config)
    elif inherit_handler is not None:
        handler = inherit_handler
    elif effective_pinned:
        handler = handler_for_pinned_trace(soothe_config, effective_pinned)
    else:
        handler = cached_langfuse_callback_handler(soothe_config)

    if handler is None:
        return base

    out: dict[str, Any] = dict(base)
    if "configurable" in base:
        out["configurable"] = dict(base["configurable"])

    # Always emit a handler *list*. LangGraph node configs carry an
    # ``AsyncCallbackManager``; leaving ``callbacks`` unset lets
    # ``ensure_config`` / ``merge_configs`` leak that manager into child
    # LLM invokes, and nano structured-output then does ``list(callbacks)``.
    handlers = iter_callback_handlers(out.get("callbacks"))
    if inherit_callbacks_from is not None:
        for h in iter_callback_handlers(inherit_callbacks_from.get("callbacks")):
            if h not in handlers:
                handlers.append(h)
    if handler is not None and handler not in handlers:
        handlers.append(handler)
    if handlers:
        out["callbacks"] = handlers

    meta = dict(out.get("metadata") or {})
    if session_id:
        meta.setdefault("langfuse_session_id", session_id)
        meta.setdefault("thread_id", session_id)
    if loop_id:
        meta.setdefault("loop_id", loop_id)
    if effective_pinned:
        meta.setdefault("langfuse_trace_id", effective_pinned)

    tags_cfg = resolved_langfuse_tags(soothe_config)
    if tags_cfg is not None and "langfuse_tags" not in meta:
        meta["langfuse_tags"] = tags_cfg
    uid = resolve_str(soothe_config.observability.langfuse.user_id)
    if uid and "langfuse_user_id" not in meta:
        meta["langfuse_user_id"] = uid
    if meta:
        out["metadata"] = meta

    name = (run_name or "").strip()
    if not name:
        name = (soothe_config.observability.langfuse.trace_name or "").strip()
    if name:
        out["run_name"] = name
        meta.setdefault("langfuse_trace_name", name)

    return out
