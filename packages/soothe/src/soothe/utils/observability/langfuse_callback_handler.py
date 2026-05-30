"""Langfuse LangChain callback that preserves CoreAgent system prompts on generations (IG-385)."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from langchain_core.messages import BaseMessage, SystemMessage

# Optional dependency - langfuse may not be installed
try:
    from langfuse.langchain import CallbackHandler as LangfuseCallbackHandler

    LANGFUSE_AVAILABLE = True
except ImportError:
    LangfuseCallbackHandler = None  # type: ignore[misc,assignment]
    LANGFUSE_AVAILABLE = False

from soothe.utils.observability.langfuse_system_hint import get_langfuse_system_prompt_hint

logger = logging.getLogger(__name__)


def _system_message_has_visible_text(msg: SystemMessage) -> bool:
    if isinstance(msg.content, str):
        return bool(msg.content.strip())
    if isinstance(msg.content, list):
        return bool(msg.content)
    return bool(str(msg.content).strip())


def _apply_effective_system_prompt_to_batches(
    messages: list[list[BaseMessage]],
    hint: str,
) -> list[list[BaseMessage]]:
    """Ensure Langfuse sees the middleware-built system prompt (includes WORKSPACE_* blocks)."""
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


# Only define the handler class when langfuse is available
if LANGFUSE_AVAILABLE:

    class SootheLangfuseCallbackHandler(LangfuseCallbackHandler):
        """Extends Langfuse's handler so chat model traces include the effective system prompt.

        ``SystemPromptMiddleware`` registers the effective system text (with
        ``WORKSPACE_RULES`` / ``WORKSPACE_INSTRUCTIONS`` when applicable) before each model
        call. LangChain often passes only the shorter graph ``resolve_system_prompt()`` text;
        this handler replaces or prepends the effective prompt on the traced message batch and
        reaffirms generation ``input`` on ``on_llm_end`` so Langfuse UI and exports show it.
        """

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self._system_hint_by_thread: dict[str, str] = {}
            self._generation_traced_inputs: dict[UUID, list[Any]] = {}

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

        def on_llm_end(self, response: Any, *, run_id: UUID, **kwargs: Any) -> Any:
            traced_input = self._generation_traced_inputs.pop(run_id, None)
            if traced_input is not None:
                observation = self._runs.get(run_id)
                if observation is not None and hasattr(observation, "update"):
                    try:
                        observation.update(input=traced_input)
                    except Exception:
                        logger.debug(
                            "Langfuse: generation input reaffirm failed (non-fatal)",
                            exc_info=True,
                        )
            return super().on_llm_end(response, run_id=run_id, **kwargs)


else:
    # Placeholder when langfuse is not installed
    class SootheLangfuseCallbackHandler:
        """Placeholder when langfuse is not installed."""

        pass


# Backward-compatible alias used by tests
_ensure_system_in_message_batches = _apply_effective_system_prompt_to_batches
