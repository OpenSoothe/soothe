"""Langfuse LangChain callback that preserves CoreAgent system prompts on generations (IG-385)."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from langchain_core.messages import BaseMessage, SystemMessage
from langfuse.langchain import CallbackHandler as LangfuseCallbackHandler

from soothe.utils.observability.langfuse_system_hint import get_langfuse_system_prompt_hint

logger = logging.getLogger(__name__)


class SootheLangfuseCallbackHandler(LangfuseCallbackHandler):
    """Extends Langfuse's handler so chat model traces include the effective system prompt.

    Some agent / provider paths omit or flatten system content in the message batch
    passed to ``on_chat_model_start``. The active hint (set by
    ``SystemPromptOptimizationMiddleware``) is merged in when the batch has no
    non-empty ``SystemMessage`` first.
    """

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
        hint = get_langfuse_system_prompt_hint()
        if hint:
            messages = _ensure_system_in_message_batches(messages, hint)
        return super().on_chat_model_start(
            serialized,
            messages,
            run_id=run_id,
            parent_run_id=parent_run_id,
            tags=tags,
            metadata=metadata,
            **kwargs,
        )


def _system_message_has_visible_text(msg: SystemMessage) -> bool:
    if isinstance(msg.content, str):
        return bool(msg.content.strip())
    if isinstance(msg.content, list):
        return bool(msg.content)
    return bool(str(msg.content).strip())


def _ensure_system_in_message_batches(
    messages: list[list[BaseMessage]],
    hint: str,
) -> list[list[BaseMessage]]:
    """Prepend ``SystemMessage(hint)`` when the batch lacks a usable system message."""
    out: list[list[BaseMessage]] = []
    for batch in messages:
        b = list(batch)
        if not b:
            out.append([SystemMessage(content=hint)])
            continue
        first = b[0]
        if isinstance(first, SystemMessage) and _system_message_has_visible_text(first):
            out.append(b)
            continue
        if isinstance(first, SystemMessage):
            b = [SystemMessage(content=hint), *b[1:]]
        else:
            b = [SystemMessage(content=hint), *b]
        out.append(b)
    if not out:
        logger.debug("Langfuse system hint: empty message batches after patch")
        return messages
    return out
