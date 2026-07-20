"""LLM token usage extraction, Langfuse-friendly ``llm_output`` enrichment, and debug logging.

Moved from ``utils/observability/llm_token_observability.py`` to consolidate
all LLM-related utilities under ``utils/llm/`` per RFC-627.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.language_models import BaseChatModel
from langchain_core.outputs import ChatGeneration, LLMResult

logger = logging.getLogger(__name__)


def create_llm_call_metadata(
    purpose: str,
    component: str,
    phase: str = "unknown",
    **extra: Any,
) -> dict[str, Any]:
    """Create standardized metadata for LLM calls."""
    metadata = {
        "soothe_call_purpose": purpose,
        "soothe_call_component": component,
        "soothe_call_phase": phase,
    }
    metadata.update(extra)
    return metadata


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    return n if n >= 0 else None


def extract_token_counts_from_llm_result(response: LLMResult) -> dict[str, int] | None:
    """Best-effort token totals from ``LLMResult`` (``llm_output`` and chat generations).

    Returns:
        Dict with ``input_tokens``, ``output_tokens``, and ``total_tokens`` when any
        counts are found; otherwise ``None``.
    """
    inp: int | None = None
    out: int | None = None
    tot: int | None = None

    llm_out = response.llm_output or {}
    tu = llm_out.get("token_usage") if isinstance(llm_out, dict) else None
    if isinstance(tu, dict):
        inp = _coerce_int(tu.get("prompt_tokens") or tu.get("input_tokens"))
        out = _coerce_int(tu.get("completion_tokens") or tu.get("output_tokens"))
        tot = _coerce_int(tu.get("total_tokens"))

    usage_obj = llm_out.get("usage") if isinstance(llm_out, dict) else None
    if isinstance(usage_obj, dict) and inp is None and out is None:
        inp = _coerce_int(usage_obj.get("input_tokens") or usage_obj.get("prompt_tokens"))
        out = _coerce_int(usage_obj.get("output_tokens") or usage_obj.get("completion_tokens"))
        if tot is None:
            tot = _coerce_int(usage_obj.get("total_tokens"))

    for row in response.generations:
        for gen in row:
            if not isinstance(gen, ChatGeneration):
                continue
            msg = gen.message
            um = getattr(msg, "usage_metadata", None)
            if isinstance(um, dict):
                if inp is None:
                    inp = _coerce_int(um.get("input_tokens"))
                if out is None:
                    out = _coerce_int(um.get("output_tokens"))
                if tot is None:
                    tot = _coerce_int(um.get("total_tokens"))
            rm = getattr(msg, "response_metadata", None) or {}
            if isinstance(rm, dict):
                nested = rm.get("token_usage")
                if isinstance(nested, dict):
                    if inp is None:
                        inp = _coerce_int(nested.get("prompt_tokens") or nested.get("input_tokens"))
                    if out is None:
                        out = _coerce_int(
                            nested.get("completion_tokens") or nested.get("output_tokens")
                        )
                    if tot is None:
                        tot = _coerce_int(nested.get("total_tokens"))

    if inp is None and out is None and tot is None:
        return None
    if tot is None and inp is not None and out is not None:
        tot = inp + out
    if inp is None and tot is not None and out is not None:
        inp = max(0, tot - out)
    if out is None and tot is not None and inp is not None:
        out = max(0, tot - inp)
    return {
        "input_tokens": int(inp or 0),
        "output_tokens": int(out or 0),
        "total_tokens": int(tot or (inp or 0) + (out or 0)),
    }


def ensure_openai_style_token_usage_on_llm_result(response: LLMResult) -> None:
    """Mutate ``response.llm_output`` so Langfuse's LangChain parser sees ``token_usage``.

    Langfuse reads ``LLMResult.llm_output['token_usage']`` (and ``usage``) before message
    metadata. Some providers only populate ``AIMessage.usage_metadata``; copying those
    counts here lets generation usage flow into Langfuse without duplicate API calls.

    Args:
        response: The LangChain result passed to ``on_llm_end`` callbacks.
    """
    llm_out = response.llm_output
    if isinstance(llm_out, dict):
        existing = llm_out.get("token_usage")
        if isinstance(existing, dict) and (
            _coerce_int(existing.get("prompt_tokens")) or _coerce_int(existing.get("total_tokens"))
        ):
            return

    counts = extract_token_counts_from_llm_result(response)
    if not counts:
        return

    token_usage = {
        "prompt_tokens": counts["input_tokens"],
        "completion_tokens": counts["output_tokens"],
        "total_tokens": counts["total_tokens"],
    }
    merged = dict(llm_out) if isinstance(llm_out, dict) else {}
    merged["token_usage"] = token_usage
    response.llm_output = merged


class SootheLLMTokenUsageCallbackHandler(BaseCallbackHandler):
    """``on_llm_end``: enrich ``llm_output`` for Langfuse and emit structured debug logs."""

    run_inline: bool = True

    def on_llm_end(
        self,
        response: LLMResult,
        *,
        run_id: Any,
        parent_run_id: Any = None,
        tags: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        ensure_openai_style_token_usage_on_llm_result(response)
        counts = extract_token_counts_from_llm_result(response)
        if not counts:
            logger.debug(
                "[LLM tokens] run_id=%s tags=%s (no usage metadata from provider)",
                run_id,
                tags,
            )
            return
        logger.debug(
            "[LLM tokens] run_id=%s input=%s output=%s total=%s tags=%s",
            run_id,
            counts["input_tokens"],
            counts["output_tokens"],
            counts["total_tokens"],
            tags,
        )
        try:
            from soothe_nano.utils.token_usage import (
                accumulate_loop_tokens_from_llm_result,
            )

            accumulate_loop_tokens_from_llm_result(response)
        except Exception:
            logger.debug("Loop token accumulation from direct LLM failed", exc_info=True)


_TOKEN_HANDLER_SINGLETON = SootheLLMTokenUsageCallbackHandler()


def get_llm_token_usage_callback_handler() -> SootheLLMTokenUsageCallbackHandler:
    """Return the shared token-usage callback (safe for all factory-cached models)."""
    return _TOKEN_HANDLER_SINGLETON


def merge_token_usage_callbacks(config: dict[str, Any] | None) -> dict[str, Any]:
    """Merge the shared token-usage callback into a LangChain ``RunnableConfig`` dict.

    Structured-output runnables invoke the inner chat model without passing through
    ``SootheTokenUsageChatModel._agenerate``; attaching the handler here ensures
    planner/intent calls still fold usage into scoped token targets when active.
    """
    from langchain_core.runnables.config import merge_configs

    handler = _TOKEN_HANDLER_SINGLETON
    token_cfg: dict[str, Any] = {"callbacks": [handler]}
    if config is None:
        return token_cfg
    return merge_configs(config, token_cfg)


def _prepend_token_usage_handler(run_manager: Any) -> None:
    """Ensure the shared token handler runs before other LLM callbacks (e.g. Langfuse)."""
    if run_manager is None:
        return
    h = _TOKEN_HANDLER_SINGLETON
    handlers = getattr(run_manager, "handlers", None)
    if not isinstance(handlers, list) or h in handlers:
        return
    handlers.insert(0, h)


class SootheTokenUsageChatModel(BaseChatModel):
    """``BaseChatModel`` wrapper that prepends token usage handling on every generate path.

    Applied automatically by ``LLMFactory`` to all models for consistent token tracking
    across provider types. Ensures Langfuse callbacks receive properly formatted token
    counts even when providers only populate ``AIMessage.usage_metadata``.
    """

    def __init__(self, model: BaseChatModel) -> None:
        self._model = model

    def bind_tools(self, tools: list[Any], **kwargs: Any) -> Any:
        """Delegate so ``type(self).bind_tools is not BaseChatModel.bind_tools`` (structured output)."""
        return self._model.bind_tools(tools, **kwargs)

    def with_structured_output(self, schema: Any, **kwargs: Any) -> Any:
        """Delegate structured output and wrap for json_object prompt compatibility."""
        from soothe_nano.utils.llm.structured import wrap_json_keyword_safe

        return wrap_json_keyword_safe(self._model.with_structured_output(schema, **kwargs))

    def _generate(
        self,
        messages: list[Any],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> Any:
        _prepend_token_usage_handler(run_manager)
        return self._model._generate(messages, stop=stop, run_manager=run_manager, **kwargs)

    async def _agenerate(
        self,
        messages: list[Any],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> Any:
        _prepend_token_usage_handler(run_manager)
        return await self._model._agenerate(messages, stop=stop, run_manager=run_manager, **kwargs)

    def _stream(
        self,
        messages: list[Any],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> Any:
        _prepend_token_usage_handler(run_manager)
        return self._model._stream(messages, stop=stop, run_manager=run_manager, **kwargs)

    async def _astream(
        self,
        messages: list[Any],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> Any:
        _prepend_token_usage_handler(run_manager)
        async for chunk in self._model._astream(
            messages, stop=stop, run_manager=run_manager, **kwargs
        ):
            yield chunk

    @property
    def _llm_type(self) -> str:
        return getattr(self._model, "_llm_type", "unknown")

    @property
    def _identifying_params(self) -> dict[str, Any]:
        return getattr(self._model, "_identifying_params", {})

    @property
    def _model_name(self) -> str:
        return getattr(self._model, "_model_name", "unknown")

    def __getattr__(self, name: str) -> Any:
        return getattr(self._model, name)


def bind_llm_token_observability(model: BaseChatModel | None) -> BaseChatModel | None:
    """Wrap a chat model so token stats run on every LLM call (idempotent).

    Uses a ``BaseChatModel`` subclass so downstream code (e.g. profile lookup)
    still receives a real chat model, not a ``RunnableBinding``.
    """
    if model is None:
        return None
    if isinstance(model, SootheTokenUsageChatModel):
        return model
    return SootheTokenUsageChatModel(model)


__all__ = [
    "create_llm_call_metadata",
    "SootheLLMTokenUsageCallbackHandler",
    "SootheTokenUsageChatModel",
    "bind_llm_token_observability",
    "extract_token_counts_from_llm_result",
    "ensure_openai_style_token_usage_on_llm_result",
    "get_llm_token_usage_callback_handler",
    "merge_token_usage_callbacks",
]
