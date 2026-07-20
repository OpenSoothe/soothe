"""Langfuse LangChain callback that preserves CoreAgent system prompts on generations (IG-385).

Also ensures structured output (tool_calls) is properly captured for Langfuse traces
when using `with_structured_output` with OpenAI-compatible providers.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from uuid import UUID

from langchain_core.messages import AIMessage, BaseMessage, SystemMessage

# Optional dependency - langfuse may not be installed
try:
    from langfuse.langchain import CallbackHandler as LangfuseCallbackHandler

    LANGFUSE_AVAILABLE = True
except ImportError:
    LangfuseCallbackHandler = None  # type: ignore[misc,assignment]
    LANGFUSE_AVAILABLE = False

from soothe_nano.utils.observability.langfuse_system_hint import get_langfuse_system_prompt_hint

logger = logging.getLogger(__name__)


def _extract_structured_output_from_message(message: AIMessage) -> dict[str, Any] | None:
    """Extract structured output from AIMessage for Langfuse generation output.

    When models return structured output via tool calling, the JSON is in `tool_calls`
    while `content` may be empty or contain thinking text. This ensures Langfuse
    captures the actual structured response.

    Args:
        message: AIMessage from LLM response.

    Returns:
        Dict with tool_calls for structured output, or None if no tool_calls.
    """
    if not hasattr(message, "tool_calls") or not message.tool_calls:
        return None

    # Format tool_calls for Langfuse (matches their expected structure)
    tool_calls_data = []
    for tc in message.tool_calls:
        # Tool call format: {"name": "...", "args": {...}, "id": "..."}
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


_EXECUTE_STEP_NAME = "execute-step"
_MODEL_CHAIN_NAME = "model"


def _is_execute_step_run_name(name: str | None) -> bool:
    """True when a chain run_name marks an Execute phase wave (``...:execute-step``)."""
    if not name:
        return False
    text = str(name).strip()
    return text == _EXECUTE_STEP_NAME or text.endswith(f":{_EXECUTE_STEP_NAME}")


def _is_model_chain_run_name(name: str | None) -> bool:
    """True when a chain run_name marks LangGraph's inner model node."""
    if not name:
        return False
    return str(name).strip() == _MODEL_CHAIN_NAME


def _should_mirror_system_prompt_on_chain(name: str | None) -> bool:
    """Chain spans no longer receive mirrored system prompts (generation-only)."""
    _ = name
    return False


class _LangfuseTracePinnedParent:
    """Inject ``trace_context`` into root LLM observations (Langfuse chain-only gap).

    Langfuse's ``LangchainCallbackHandler`` passes ``trace_context`` for root chains but
    not for root chat-model generations. Goal-loop intake uses standalone structured LLM
    calls, so we wrap the client returned by ``_get_parent_observation(None)``.
    """

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


def _patch_chain_input_with_system_message(
    inputs: Any,
    system_prompt: str,
) -> Any:
    """Prepend a SystemMessage to the chain's ``messages`` list so Langfuse renders it.

    Mirrors ``_apply_effective_system_prompt_to_batches`` semantics: replace the leading
    SystemMessage when present, otherwise prepend. Returns ``inputs`` unchanged when it
    is not a dict carrying a ``messages`` list (no safe place to inject).
    """
    if not isinstance(inputs, dict):
        return inputs
    msgs = inputs.get("messages")
    if not isinstance(msgs, list):
        return inputs
    out = dict(inputs)
    if msgs and isinstance(msgs[0], SystemMessage):
        out["messages"] = [SystemMessage(content=system_prompt), *msgs[1:]]
    else:
        out["messages"] = [SystemMessage(content=system_prompt), *msgs]
    return out


# Only define the handler class when langfuse is available
if LANGFUSE_AVAILABLE:

    class SootheLangfuseCallbackHandler(LangfuseCallbackHandler):
        """Extends Langfuse's handler so chat model traces include the effective system prompt.

        ``SystemPromptMiddleware`` registers the effective system text (with
        ``WORKSPACE_RULES`` / ``AGENT_INSTRUCTIONS`` when applicable) before each model
        call. LangChain often passes only the shorter graph ``resolve_system_prompt()`` text;
        this handler replaces or prepends the effective prompt on the traced message batch and
        reaffirms generation ``input`` on ``on_llm_end`` so Langfuse UI and exports show it.
        """

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
            """Replace unreadable ``<object object at 0x...>`` in CancelledError status messages.

            LangGraph's ``AsyncBackgroundExecutor`` cancels tasks with ``task.cancel(object())``,
            making ``str(CancelledError)`` render as the useless ``<object object at 0x...>``.
            Return a clean CancelledError so Langfuse records a readable status message.
            """
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
            """Handle LLM completion, ensuring structured output (tool_calls) is captured.

            Langfuse's default handler may not properly capture tool_calls from structured
            output responses. This override ensures the full tool_call data is included
            in the generation output for traces.

            Args:
                response: LLMResult from the model call.
                run_id: UUID for this run.
                **kwargs: Additional arguments including potential output override.
            """
            traced_input = self._generation_traced_inputs.pop(run_id, None)
            kwargs = dict(kwargs)

            if traced_input is not None:
                # Parent handler overwrites generation input with kwargs["inputs"], which
                # lacks middleware-built system text. Inject the patched batch here.
                kwargs["inputs"] = traced_input

            # Extract structured output from tool_calls if present
            # This fixes the issue where Langfuse shows empty {"json": null} for structured output
            try:
                if response.generations and response.generations[0]:
                    gen = response.generations[0][0]
                    if hasattr(gen, "message") and isinstance(gen.message, AIMessage):
                        structured_output = _extract_structured_output_from_message(gen.message)
                        if structured_output is not None:
                            # Override the output to include tool_calls
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
    # Placeholder when langfuse is not installed
    class SootheLangfuseCallbackHandler:
        """Placeholder when langfuse is not installed."""

        pass
