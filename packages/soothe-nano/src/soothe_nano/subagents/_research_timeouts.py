"""Timeout helpers shared by research subagents."""

from __future__ import annotations

from typing import Any

_DEFAULT_WIZSEARCH_TIMEOUT_SEC = 30.0


def effective_source_timeout_sec(
    configured: float,
    soothe_config: Any | None = None,
    *,
    slack_sec: float = 5.0,
) -> float:
    """Return gather wait_for timeout that will not cancel wizsearch early.

    ``tools.wizsearch.timeout`` defaults to 30s. An outer ``source_timeout_sec``
    below that cancels in-flight duckduckgo/bing/tavily gathers as TimeoutError.
    """
    wiz = _DEFAULT_WIZSEARCH_TIMEOUT_SEC
    if soothe_config is not None:
        tools = getattr(soothe_config, "tools", None)
        wz = getattr(tools, "wizsearch", None) if tools is not None else None
        if wz is not None:
            raw = getattr(wz, "timeout", None)
            if raw is not None:
                try:
                    wiz = float(raw)
                except (TypeError, ValueError):
                    wiz = _DEFAULT_WIZSEARCH_TIMEOUT_SEC
    return max(float(configured), wiz + float(slack_sec))
