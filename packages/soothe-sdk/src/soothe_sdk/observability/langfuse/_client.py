"""Langfuse SDK client initialization and config field resolution."""

from __future__ import annotations

import logging
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from soothe_sdk.observability.langfuse._types import SootheConfigLike

logger = logging.getLogger(__name__)

_ENV_REF = re.compile(r"^\$\{(\w+)\}$")
_ENV_VAR_RE = re.compile(r"\$\{(\w+)\}")
_INIT_LOCK = threading.Lock()
_CLIENT_INITIALIZED_FOR_PUBLIC_KEY: set[str] = set()
_LANGFUSE_EXECUTOR: ThreadPoolExecutor | None = None


def _resolve_env(value: str) -> str:
    """Resolve ``${ENV_VAR}`` placeholders in a string."""

    def replacer(match: re.Match[str]) -> str:
        var_name = match.group(1)
        resolved = os.environ.get(var_name)
        if resolved is not None:
            return resolved
        return match.group(0)

    return _ENV_VAR_RE.sub(replacer, value)


def resolved_langfuse_tags(soothe_config: SootheConfigLike) -> list[str] | None:
    """Normalize ``observability.langfuse.tags`` to non-empty stripped strings."""
    raw = soothe_config.observability.langfuse.tags
    if not raw:
        return None
    out = [str(t).strip() for t in raw if str(t).strip()]
    return out or None


def resolve_str(value: str | None) -> str | None:
    """Strip and resolve ``${ENV}`` placeholders; return None if unresolved or empty."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    out = _resolve_env(s)
    if _ENV_REF.match(out):
        return None
    return out


def resolve_langfuse_config_str(value: str | None) -> str | None:
    """Public wrapper for Langfuse YAML/env field resolution (keys, host, etc.)."""
    return resolve_str(value)


def _get_executor() -> ThreadPoolExecutor:
    """Get or create the thread pool executor for Langfuse initialization."""
    global _LANGFUSE_EXECUTOR
    if _LANGFUSE_EXECUTOR is None:
        _LANGFUSE_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="langfuse-init")
    return _LANGFUSE_EXECUTOR


def _init_langfuse_client_sync(kwargs: dict[str, Any]) -> None:
    """Synchronous Langfuse client initialization (runs in thread pool)."""
    from langfuse import Langfuse

    Langfuse(**kwargs)


def ensure_langfuse_client(soothe_config: SootheConfigLike) -> None:
    """Register a Langfuse SDK client when both public and secret keys are configured."""
    lf = soothe_config.observability.langfuse
    pub = resolve_str(lf.public_key)
    sec = resolve_str(lf.secret_key)
    if not pub or not sec:
        return
    with _INIT_LOCK:
        if pub in _CLIENT_INITIALIZED_FOR_PUBLIC_KEY:
            return

        _CLIENT_INITIALIZED_FOR_PUBLIC_KEY.add(pub)

        kwargs: dict[str, Any] = {"public_key": pub, "secret_key": sec}
        host = resolve_str(lf.host)
        if host:
            kwargs["host"] = host
        if lf.environment:
            env_label = resolve_str(lf.environment)
            if env_label:
                kwargs["environment"] = env_label
        if lf.release:
            rel = resolve_str(lf.release)
            if rel:
                kwargs["release"] = rel
        if lf.sample_rate is not None:
            kwargs["sample_rate"] = float(lf.sample_rate)

        executor = _get_executor()
        executor.submit(_init_langfuse_client_sync, kwargs)
        logger.debug("Langfuse client initialization submitted to background thread")
