"""Merge Langfuse LangChain callbacks into RunnableConfig for LangGraph streams (IG-367)."""

from __future__ import annotations

import logging
import re
import threading
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from soothe.config import SootheConfig

logger = logging.getLogger(__name__)

_ENV_REF = re.compile(r"^\$\{(\w+)\}$")
_INIT_LOCK = threading.Lock()
_CLIENT_INITIALIZED_FOR_PUBLIC_KEY: set[str] = set()
_HANDLERS: dict[str, Any] = {}


def _resolved_langfuse_tags(soothe_config: SootheConfig) -> list[str] | None:
    """Normalize ``observability.langfuse.tags`` to non-empty stripped strings."""
    raw = soothe_config.observability.langfuse.tags
    if not raw:
        return None
    out = [str(t).strip() for t in raw if str(t).strip()]
    return out or None


def _resolve_str(value: str | None) -> str | None:
    """Strip and resolve ``${ENV}`` placeholders; return None if unresolved or empty."""
    from soothe.config.env import _resolve_env

    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    out = _resolve_env(s)
    if _ENV_REF.match(out):
        return None
    return out


def _ensure_langfuse_client(soothe_config: SootheConfig) -> None:
    """Register a Langfuse SDK client when both public and secret keys are configured."""
    lf = soothe_config.observability.langfuse
    pub = _resolve_str(lf.public_key)
    sec = _resolve_str(lf.secret_key)
    if not pub or not sec:
        return
    with _INIT_LOCK:
        if pub in _CLIENT_INITIALIZED_FOR_PUBLIC_KEY:
            return
        from langfuse import Langfuse

        kwargs: dict[str, Any] = {"public_key": pub, "secret_key": sec}
        host = _resolve_str(lf.host)
        if host:
            kwargs["host"] = host
        if lf.environment:
            env_label = _resolve_str(lf.environment)
            if env_label:
                kwargs["environment"] = env_label
        if lf.release:
            rel = _resolve_str(lf.release)
            if rel:
                kwargs["release"] = rel
        if lf.sample_rate is not None:
            kwargs["sample_rate"] = float(lf.sample_rate)
        Langfuse(**kwargs)
        _CLIENT_INITIALIZED_FOR_PUBLIC_KEY.add(pub)


def _langfuse_callback_handler(soothe_config: SootheConfig) -> Any | None:
    lf = soothe_config.observability.langfuse
    try:
        import langfuse.langchain  # noqa: F401 - optional extra soothe[langfuse]
    except ImportError:
        logger.warning(
            "observability.langfuse.enabled is true but langfuse is not installed; "
            "install optional dependency (e.g. pip install 'soothe[langfuse]')"
        )
        return None

    _ensure_langfuse_client(soothe_config)
    pub_resolved = _resolve_str(lf.public_key)
    cache_key = pub_resolved or "__env__"
    with _INIT_LOCK:
        if cache_key not in _HANDLERS:
            from soothe.utils.observability.langfuse_callback_handler import (
                SootheLangfuseCallbackHandler,
            )

            if pub_resolved:
                _HANDLERS[cache_key] = SootheLangfuseCallbackHandler(public_key=pub_resolved)
            else:
                _HANDLERS[cache_key] = SootheLangfuseCallbackHandler()
        return _HANDLERS[cache_key]


def merge_langfuse_runnable_config(
    base: dict[str, Any],
    soothe_config: SootheConfig,
    *,
    session_id: str | None = None,
    run_name: str | None = None,
) -> dict[str, Any]:
    """Return Runnable config like ``base`` with Langfuse callbacks and session metadata merged in.

    When Langfuse is disabled, missing, or the package is not installed, returns ``base``
    unchanged (same object).

    Args:
        base: RunnableConfig-compatible dict (e.g. ``{"configurable": {...}}``).
        soothe_config: Active Soothe configuration.
        session_id: Optional thread id stored as ``langfuse_session_id`` metadata.
        run_name: Optional root run name (e.g. ``soothe-dev:plan-assess``, ``soothe-dev:execute-step``). When omitted,
            uses ``observability.langfuse.trace_name`` when set.

    When ``observability.langfuse.tags`` / ``user_id`` are set, merges ``langfuse_tags`` /
    ``langfuse_user_id`` into metadata if those keys are not already present (Langfuse
    LangChain ``CallbackHandler`` reads them for trace attributes and Cost Dashboard filters).

    Returns:
        New dict with merged ``callbacks`` / ``metadata`` / ``run_name``, or ``base``.
    """
    if not soothe_config.observability.langfuse.enabled:
        return base
    handler = _langfuse_callback_handler(soothe_config)
    if handler is None:
        return base
    out: dict[str, Any] = dict(base)
    if "configurable" in base:
        out["configurable"] = dict(base["configurable"])
    prev = list(out.get("callbacks") or [])
    out["callbacks"] = prev + [handler]
    meta = dict(out.get("metadata") or {})
    if session_id:
        meta.setdefault("langfuse_session_id", session_id)
    tags_cfg = _resolved_langfuse_tags(soothe_config)
    if tags_cfg is not None and "langfuse_tags" not in meta:
        meta["langfuse_tags"] = tags_cfg
    uid = _resolve_str(soothe_config.observability.langfuse.user_id)
    if uid and "langfuse_user_id" not in meta:
        meta["langfuse_user_id"] = uid
    if meta:
        out["metadata"] = meta
    name = (run_name or "").strip()
    if not name:
        name = (soothe_config.observability.langfuse.trace_name or "").strip()
    if name:
        out["run_name"] = name
    return out
