"""Langfuse SDK client resolution for host-side spans."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def host_langfuse_client(soothe_config: Any) -> Any:
    """Return the Langfuse client for this config's public key.

    Raises:
        Exception: When langfuse is unavailable; callers keep observability soft.
    """
    from langfuse import get_client
    from soothe_sdk.observability.langfuse._client import ensure_langfuse_client, resolve_str

    ensure_langfuse_client(soothe_config)
    pub = resolve_str(soothe_config.observability.langfuse.public_key)
    return get_client(public_key=pub) if pub else get_client()


def flush_langfuse_events(soothe_config: Any) -> None:
    """Export buffered observations now; best-effort."""
    try:
        host_langfuse_client(soothe_config).flush()
    except Exception:
        logger.debug("Langfuse flush failed", exc_info=True)


__all__ = ["flush_langfuse_events", "host_langfuse_client"]
