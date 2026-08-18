"""Langfuse LangChain callback handler lifecycle (cache, fresh instances, trace pinning)."""

from __future__ import annotations

import logging
import threading
from typing import Any

from soothe_sdk.observability.langfuse._client import ensure_langfuse_client, resolve_str
from soothe_sdk.observability.langfuse._types import SootheConfigLike

logger = logging.getLogger(__name__)

_INIT_LOCK = threading.Lock()
_HANDLERS: dict[str, Any] = {}
_LANGFUSE_NOT_INSTALLED_WARNED = False
_LANGFUSE_HANDLER_UNAVAILABLE_WARNED = False


def _import_langfuse_langchain() -> bool:
    try:
        import langfuse.langchain  # noqa: F401 - external langfuse package
    except ImportError:
        return False
    return True


def _warn_langfuse_not_installed() -> None:
    global _LANGFUSE_NOT_INSTALLED_WARNED
    if not _LANGFUSE_NOT_INSTALLED_WARNED:
        logger.warning(
            "observability.langfuse.enabled is true but langfuse is not installed; "
            "install dependency (e.g. pip install langfuse)"
        )
        _LANGFUSE_NOT_INSTALLED_WARNED = True


def _warn_handler_unavailable() -> None:
    global _LANGFUSE_HANDLER_UNAVAILABLE_WARNED
    if not _LANGFUSE_HANDLER_UNAVAILABLE_WARNED:
        logger.warning(
            "observability.langfuse.enabled is true but Langfuse callback handler "
            "is unavailable; ensure langfuse and langchain are both installed"
        )
        _LANGFUSE_HANDLER_UNAVAILABLE_WARNED = True


def cached_langfuse_callback_handler(soothe_config: SootheConfigLike) -> Any | None:
    """Return the process-wide cached handler for standalone LLM calls."""
    lf = soothe_config.observability.langfuse
    if not _import_langfuse_langchain():
        _warn_langfuse_not_installed()
        return None

    ensure_langfuse_client(soothe_config)
    pub_resolved = resolve_str(lf.public_key)
    cache_key = pub_resolved or "__env__"
    with _INIT_LOCK:
        if cache_key not in _HANDLERS:
            from soothe_sdk.observability.langfuse.callback_handler import (
                LANGFUSE_AVAILABLE,
                SootheLangfuseCallbackHandler,
            )

            if not LANGFUSE_AVAILABLE:
                _warn_handler_unavailable()
                return None

            if pub_resolved:
                try:
                    _HANDLERS[cache_key] = SootheLangfuseCallbackHandler(public_key=pub_resolved)
                except TypeError:
                    logger.warning(
                        "Langfuse callback handler does not accept public_key; "
                        "falling back to default constructor"
                    )
                    _HANDLERS[cache_key] = SootheLangfuseCallbackHandler()
            else:
                _HANDLERS[cache_key] = SootheLangfuseCallbackHandler()
        return _HANDLERS[cache_key]


def create_fresh_langfuse_handler(soothe_config: SootheConfigLike) -> Any | None:
    """Create a new Langfuse handler (not cached) for independent root traces."""
    if not _import_langfuse_langchain():
        _warn_langfuse_not_installed()
        return None

    ensure_langfuse_client(soothe_config)

    from soothe_sdk.observability.langfuse.callback_handler import (
        LANGFUSE_AVAILABLE,
        SootheLangfuseCallbackHandler,
    )

    if not LANGFUSE_AVAILABLE:
        _warn_handler_unavailable()
        return None

    pub_resolved = resolve_str(soothe_config.observability.langfuse.public_key)
    if pub_resolved:
        try:
            return SootheLangfuseCallbackHandler(public_key=pub_resolved)
        except TypeError:
            logger.warning(
                "Langfuse callback handler does not accept public_key; "
                "falling back to default constructor"
            )
            return SootheLangfuseCallbackHandler()
    return SootheLangfuseCallbackHandler()


def allocate_langfuse_trace_id(soothe_config: SootheConfigLike) -> str | None:
    """Reserve a Langfuse trace id for one grouped multi-stage execution."""
    try:
        from langfuse import get_client

        pub_resolved = resolve_str(soothe_config.observability.langfuse.public_key)
        ensure_langfuse_client(soothe_config)
        client = get_client(public_key=pub_resolved) if pub_resolved else get_client()
        return str(client.create_trace_id())
    except Exception:
        logger.debug("Langfuse trace id allocation failed", exc_info=True)
        return None


def new_soothe_langfuse_handler(
    soothe_config: SootheConfigLike,
    *,
    trace_context: dict[str, str] | None = None,
) -> Any | None:
    """Create a non-cached callback handler (optional pinned ``trace_context``)."""
    handler = create_fresh_langfuse_handler(soothe_config)
    if handler is None or trace_context is None:
        return handler
    pub_resolved = resolve_str(soothe_config.observability.langfuse.public_key)
    from soothe_sdk.observability.langfuse.callback_handler import (
        SootheLangfuseCallbackHandler,
    )

    kwargs: dict[str, Any] = {"trace_context": trace_context}
    if pub_resolved:
        kwargs["public_key"] = pub_resolved
    try:
        return SootheLangfuseCallbackHandler(**kwargs)
    except TypeError:
        try:
            return SootheLangfuseCallbackHandler(trace_context=trace_context)
        except TypeError:
            logger.debug("Langfuse handler does not accept trace_context; using fresh handler")
            return handler


def handler_for_pinned_trace(
    soothe_config: SootheConfigLike,
    trace_id: str | None,
) -> Any | None:
    """Fresh handler pinned to ``trace_id`` (one per invocation, shared trace)."""
    if not trace_id:
        return create_fresh_langfuse_handler(soothe_config)
    return new_soothe_langfuse_handler(soothe_config, trace_context={"trace_id": trace_id})
