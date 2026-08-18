"""Langfuse LangChain callback with system-prompt and structured-output fixes."""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from uuid import UUID

from langchain_core.messages import AIMessage, BaseMessage, SystemMessage

try:
    from langfuse.langchain import CallbackHandler as LangfuseCallbackHandler

    LANGFUSE_AVAILABLE = True
except ImportError:
    LangfuseCallbackHandler = None  # type: ignore[misc,assignment]
    LANGFUSE_AVAILABLE = False

from soothe_sdk.observability.langfuse.system_hint import get_langfuse_system_prompt_hint

logger = logging.getLogger(__name__)


def _extract_structured_output_from_message(message: AIMessage) -> dict[str, Any] | None:
    """Extract structured output from AIMessage for Langfuse generation output."""
    if not hasattr(message, "tool_calls") or not message.tool_calls:
        return None

    tool_calls_data = []
    for tc in message.tool_calls:
        tool_calls_data.append(
            {
                "name": tc.get("name", ""),
                "args": tc.get("args", {}),
                "id": tc.get("id", ""),
            }
        )

    return {
        "role": "assistant",
        "content": message.content or "",
        "tool_calls": tool_calls_data,
    }


def _apply_effective_system_prompt_to_batches(
    messages: list[list[BaseMessage]],
    hint: str,
) -> list[list[BaseMessage]]:
    """Ensure Langfuse sees the middleware-built system prompt."""
    out: list[list[BaseMessage]] = []
    for batch in messages:
        b = list(batch)
        if not b:
            out.append([SystemMessage(content=hint)])
            continue
        first = b[0]
        if isinstance(first, SystemMessage):
            b = [SystemMessage(content=hint), *b[1:]]
        else:
            b = [SystemMessage(content=hint), *b]
        out.append(b)
    if not out:
        logger.debug("Langfuse system hint: empty message batches after patch")
        return messages
    return out


def _message_to_langfuse_dict(msg: BaseMessage) -> dict[str, Any]:
    """Best-effort OpenAI-style message dict for Langfuse generation input."""
    from langchain_core.messages import AIMessage, ToolMessage

    if isinstance(msg, SystemMessage):
        role = "system"
    elif isinstance(msg, AIMessage):
        role = "assistant"
    elif isinstance(msg, ToolMessage):
        role = "tool"
    else:
        role = "user"
    content = msg.content
    if not isinstance(content, (str, list)):
        content = str(content)
    out: dict[str, Any] = {"role": role, "content": content}
    if isinstance(msg, ToolMessage) and getattr(msg, "tool_call_id", None):
        out["tool_call_id"] = msg.tool_call_id
    return out


def _serialize_message_batches_for_langfuse(
    messages: list[list[BaseMessage]],
) -> list[dict[str, Any]] | None:
    """Serialize patched chat batches for explicit generation input updates."""
    try:
        from langfuse.langchain.CallbackHandler import (  # type: ignore[attr-defined]
            _create_message_dicts,
            _flatten_comprehension,
        )

        return list(
            _flatten_comprehension([_create_message_dicts(m) for m in messages]),
        )
    except Exception:
        flattened: list[dict[str, Any]] = []
        for batch in messages:
            for msg in batch:
                flattened.append(_message_to_langfuse_dict(msg))
        return flattened or None


def _configurable_thread_key(runnable_config: dict[str, Any] | None) -> str | None:
    if not runnable_config:
        return None
    conf = runnable_config.get("configurable")
    if not isinstance(conf, dict):
        return None
    raw = conf.get("thread_id")
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


class _LangfuseTracePinnedParent:
    """Inject ``trace_context`` into root LLM observations (Langfuse chain-only gap)."""

    __slots__ = ("_client", "_trace_context")

    def __init__(self, client: Any, trace_context: dict[str, str]) -> None:
        self._client = client
        self._trace_context = trace_context

    def start_observation(self, *args: Any, **kwargs: Any) -> Any:
        if kwargs.get("trace_context") is None:
            kwargs = {**kwargs, "trace_context": self._trace_context}
        return self._client.start_observation(*args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)


def _is_langfuse_root_client(obs: Any) -> bool:
    try:
        from langfuse._client.client import Langfuse
    except ImportError:
        return False
    return isinstance(obs, Langfuse)


if LANGFUSE_AVAILABLE:

    class SootheLangfuseCallbackHandler(LangfuseCallbackHandler):
        """Extend Langfuse handler so traces include the effective system prompt."""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self._system_hint_by_thread: dict[str, str] = {}
            self._generation_traced_inputs: dict[UUID, list[Any]] = {}

        def _get_parent_observation(self, parent_run_id: UUID | None) -> Any:
            obs = super()._get_parent_observation(parent_run_id)
            trace_context = getattr(self, "trace_context", None)
            if parent_run_id is not None or not trace_context:
                return obs
            if _is_langfuse_root_client(obs):
                return _LangfuseTracePinnedParent(obs, trace_context)
            return obs

        def register_system_prompt_hint_for_config(
            self,
            runnable_config: dict[str, Any] | None,
            text: str,
        ) -> None:
            """Store hint keyed by ``configurable.thread_id`` for parallel execute isolation."""
            key = _configurable_thread_key(runnable_config)
            if not key:
                return
            stripped = str(text).strip()
            if stripped:
                self._system_hint_by_thread[key] = stripped

        def clear_system_prompt_hint_for_config(
            self,
            runnable_config: dict[str, Any] | None,
        ) -> None:
            """Drop thread-keyed hint after the model call completes."""
            key = _configurable_thread_key(runnable_config)
            if key:
                self._system_hint_by_thread.pop(key, None)

        def _resolve_system_prompt_hint(
            self,
            *,
            metadata: dict[str, Any] | None,
        ) -> str | None:
            hint = get_langfuse_system_prompt_hint()
            if hint:
                return hint
            thread_key = None
            if metadata:
                for candidate in (
                    metadata.get("thread_id"),
                    metadata.get("langfuse_session_id"),
                ):
                    if candidate is not None and str(candidate).strip():
                        thread_key = str(candidate).strip()
                        break
            if thread_key:
                return self._system_hint_by_thread.get(thread_key)
            return None

        def on_chat_model_start(
            self,
            serialized: dict[str, Any] | None,
            messages: list[list[BaseMessage]],
            *,
            run_id: UUID,
            parent_run_id: UUID | None = None,
            tags: list[str] | None = None,
            metadata: dict[str, Any] | None = None,
            **kwargs: Any,
        ) -> Any:
            hint = self._resolve_system_prompt_hint(metadata=metadata)
            patched = messages
            if hint:
                patched = _apply_effective_system_prompt_to_batches(messages, hint)
                traced_input = _serialize_message_batches_for_langfuse(patched)
                if traced_input is not None:
                    self._generation_traced_inputs[run_id] = traced_input
            return super().on_chat_model_start(
                serialized,
                patched,
                run_id=run_id,
                parent_run_id=parent_run_id,
                tags=tags,
                metadata=metadata,
                **kwargs,
            )

        @staticmethod
        def _sanitize_cancelled_error(error: BaseException) -> BaseException:
            """Replace unreadable cancellation payload text in status messages."""
            if isinstance(error, asyncio.CancelledError):
                return asyncio.CancelledError("Cancelled")
            return error

        def on_chain_error(
            self,
            error: BaseException,
            *,
            run_id: UUID,
            parent_run_id: UUID | None = None,
            tags: list[str] | None = None,
            **kwargs: Any,
        ) -> Any:
            return super().on_chain_error(
                self._sanitize_cancelled_error(error),
                run_id=run_id,
                parent_run_id=parent_run_id,
                tags=tags,
                **kwargs,
            )

        def on_llm_error(
            self,
            error: BaseException,
            *,
            run_id: UUID,
            parent_run_id: UUID | None = None,
            tags: list[str] | None = None,
            **kwargs: Any,
        ) -> Any:
            return super().on_llm_error(
                self._sanitize_cancelled_error(error),
                run_id=run_id,
                parent_run_id=parent_run_id,
                tags=tags,
                **kwargs,
            )

        def on_llm_end(self, response: Any, *, run_id: UUID, **kwargs: Any) -> Any:
            """Handle LLM completion, ensuring structured output (tool_calls) is captured."""
            traced_input = self._generation_traced_inputs.pop(run_id, None)
            kwargs = dict(kwargs)

            if traced_input is not None:
                kwargs["inputs"] = traced_input

            try:
                if response.generations and response.generations[0]:
                    gen = response.generations[0][0]
                    if hasattr(gen, "message") and isinstance(gen.message, AIMessage):
                        structured_output = _extract_structured_output_from_message(gen.message)
                        if structured_output is not None:
                            kwargs["output"] = structured_output
                            logger.debug(
                                "Langfuse: captured structured output with %d tool_calls for run_id=%s",
                                len(structured_output.get("tool_calls", [])),
                                run_id,
                            )
            except Exception:
                logger.debug(
                    "Langfuse: failed to extract structured output (non-fatal)",
                    exc_info=True,
                )

            return super().on_llm_end(response, run_id=run_id, **kwargs)


else:

    class SootheLangfuseCallbackHandler:
        """Placeholder when langfuse is not installed."""

        pass
