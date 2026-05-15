"""Invoke-level recovery when the explore graph raises before finalize (RFC-613)."""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import AIMessage

from .partial import build_explore_result_from_findings
from .schemas import format_explore_result_markdown
from .search_target import resolve_explore_search_target

logger = logging.getLogger(__name__)


def recover_explore_invoke_result(
    inner: Any,
    state: dict[str, Any],
    config: dict[str, Any] | None,
    exc: BaseException,
    *,
    thoroughness: str,
    max_matches: int,
) -> dict[str, Any]:
    """Recover partial explore output from the last streamed graph state.

    Args:
        inner: Compiled explore graph.
        state: Input state passed to ``invoke`` / ``ainvoke``.
        config: LangGraph config, if any.
        exc: Exception from the failed invoke.
        thoroughness: Thoroughness label for the partial result.
        max_matches: Match cap for partial formatting.

    Returns:
        Invoke-shaped dict with markdown final message and structured_response.

    Raises:
        BaseException: Re-raises *exc* when no findings can be recovered.
    """
    logger.warning(
        "Explore: invoke failed (%s); attempting partial recovery via stream",
        exc,
        exc_info=True,
    )
    last_values: dict[str, Any] | None = None
    stream_config = config if config is not None else {}
    try:
        for chunk in inner.stream(state, stream_config, stream_mode="values"):
            if isinstance(chunk, dict):
                last_values = chunk
    except Exception as stream_exc:
        logger.debug("Explore: recovery stream also failed: %s", stream_exc)

    findings = list((last_values or {}).get("findings") or [])
    messages = state.get("messages") or (last_values or {}).get("messages") or []
    search_target = resolve_explore_search_target(
        messages,
        (last_values or {}).get("search_target") or state.get("search_target"),
    )
    if not findings:
        logger.error("Explore: invoke failed with no recoverable findings")
        raise exc from None

    failure_reason = str(exc)[:500]
    result = build_explore_result_from_findings(
        findings,
        search_target=search_target,
        thoroughness=thoroughness,
        max_matches=max_matches,
        status="partial",
        failure_reason=failure_reason,
    )
    md = format_explore_result_markdown(result)
    logger.warning(
        "Explore: recovered partial invoke result (%d findings → %d matches)",
        len(findings),
        len(result.matches),
    )
    return {
        "messages": [AIMessage(content=md)],
        "structured_response": result,
        "findings": findings,
        "search_target": search_target,
        "explore_completion_status": "partial",
        "explore_failure_reason": failure_reason,
    }


class ExploreRunnableRecoveryWrapper:
    """Wrap compiled explore graph to return partial results on catastrophic failure."""

    def __init__(
        self,
        inner: Any,
        *,
        thoroughness: str,
        max_matches: int,
    ) -> None:
        self._inner = inner
        self._thoroughness = thoroughness
        self._max_matches = max_matches

    def invoke(
        self,
        state: dict[str, Any],
        config: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        try:
            return self._inner.invoke(state, config, **kwargs)
        except Exception as exc:
            return recover_explore_invoke_result(
                self._inner,
                state,
                config,
                exc,
                thoroughness=self._thoroughness,
                max_matches=self._max_matches,
            )

    async def ainvoke(
        self,
        state: dict[str, Any],
        config: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        try:
            return await self._inner.ainvoke(state, config, **kwargs)
        except Exception as exc:
            return recover_explore_invoke_result(
                self._inner,
                state,
                config,
                exc,
                thoroughness=self._thoroughness,
                max_matches=self._max_matches,
            )

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)
