"""Automatic context window compaction for StrangeLoop threads (RFC-224).

This module provides ContextWindowManager which handles:
- Estimating token count from checkpoint messages
- Checking if threshold exceeded (configurable percentage)
- Triggering in-place compaction via LLM summarization
- Updating LoopState metrics after compaction

RFC-224: When estimated token count exceeds threshold (default 80%),
in-place compaction is triggered to enable long-running goals to
continue autonomously without hitting model context limits.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from langchain_core.messages import AIMessage, HumanMessage

if TYPE_CHECKING:
    from langgraph.checkpoint.base import BaseCheckpointSaver

    from soothe.config import SootheConfig
    from soothe.sloop.state.schemas import LoopState

logger = logging.getLogger(__name__)

# Summarization prompt template
_SUMMARY_PROMPT = """<ROLE>
Context Extraction Assistant
</ROLE>

<PRIMARY_OBJECTIVE>
Your sole objective is to extract the highest quality/most relevant context from the conversation history below.
</PRIMARY_OBJECTIVE>

<OBJECTIVE_INFORMATION>
You're nearing the total number of input tokens you can accept, so you must extract the most important information.
This context will replace the conversation history. Ensure you capture only critical information to continue working toward the overall goal.
</OBJECTIVE_INFORMATION>

<INSTRUCTIONS>
Structure your summary using these sections. Each section acts as a checklist - populate with relevant information or state "None" if nothing to report:

## SESSION INTENT
What is the user's primary goal or request? What overall task is being accomplished? Concise but complete.

## SUMMARY
Extract and record the most important context. Include important choices, conclusions, strategies determined. Include reasoning behind key decisions. Document rejected options and why.

## ARTIFACTS
What artifacts, files, or resources were created, modified, or accessed? List file paths and describe changes.

## NEXT STEPS
What specific tasks remain to complete the session intent? What should be done next?

</INSTRUCTIONS>

Extract the most important and relevant context to replace the history. Respond ONLY with the extracted context.

<MESSAGES>
Messages to summarize:
{messages}
</MESSAGES>"""

# Keep recent messages after summarization (default: last 5)
_DEFAULT_KEEP_MESSAGES = 5

# Max messages to include in summary generation prompt (avoid LLM overflow)
_MAX_MESSAGES_FOR_SUMMARY_PROMPT = 100


@dataclass(frozen=True, slots=True)
class ContextCompactionResult:
    """Result from automatic context compaction (RFC-224).

    Attributes:
        thread_id: Thread that was compacted.
        tokens_before: Estimated tokens before compaction.
        tokens_after: Estimated tokens after compaction.
        messages_removed: Number of messages removed/summarized.
        summary_preview: Preview of summarization output (optional).
    """

    thread_id: str
    tokens_before: int
    tokens_after: int
    messages_removed: int
    summary_preview: str | None = None


class ContextWindowManager:
    """Manages automatic context window compaction for StrangeLoop threads.

    RFC-224: After execute waves, check estimated context size and trigger
    in-place summarization when threshold exceeded.

    Args:
        checkpointer: LangGraph checkpointer for checkpoint access.
        config: Soothe config for threshold and limit values.
    """

    def __init__(
        self,
        checkpointer: BaseCheckpointSaver | None,
        config: SootheConfig | None,
    ) -> None:
        """Initialize ContextWindowManager.

        Args:
            checkpointer: LangGraph checkpointer for checkpoint access.
            config: Soothe config for threshold and limit values.
        """
        self._checkpointer = checkpointer
        self._config = config

    def _context_limit(self) -> int:
        """Get context_window_limit from config."""
        if self._config is None:
            return 200_000  # Default fallback
        return self._config.agent.loop.context_window_limit

    def _threshold_pct(self) -> float:
        """Get overflow threshold percentage from config."""
        if self._config is None:
            return 0.80  # Default fallback
        return self._config.agent.loop.context_overflow_threshold_pct

    def _target_pct(self) -> float:
        """Get compaction target percentage from config."""
        if self._config is None:
            return 0.60  # Default fallback
        return self._config.agent.loop.context_compaction_target_pct

    async def estimate_checkpoint_tokens(self, thread_id: str) -> int:
        """Estimate token count from checkpoint messages (async).

        Fetches checkpoint via aget_tuple and counts tokens in messages.
        Uses tiktoken for accuracy with fallback estimation.
        Returns 0 if checkpoint unavailable or checkpointer not set.

        Args:
            thread_id: Thread to estimate.

        Returns:
            Estimated token count in checkpoint messages.
        """
        if self._checkpointer is None:
            return 0

        checkpoint_tuple = await self._checkpointer.aget_tuple(
            {"configurable": {"thread_id": thread_id}}
        )
        if checkpoint_tuple is None:
            return 0

        checkpoint = checkpoint_tuple.checkpoint
        return self.estimate_checkpoint_tokens_sync(checkpoint)

    def estimate_checkpoint_tokens_sync(self, checkpoint: Any) -> int:
        """Estimate token count from pre-loaded checkpoint (sync helper).

        Used internally when checkpoint is already loaded, avoiding
        redundant async call.

        Args:
            checkpoint: Pre-loaded checkpoint with channel_values.

        Returns:
            Estimated token count in checkpoint messages.
        """
        from soothe_nano.utils.token_counting import count_tokens

        # Get messages from checkpoint channel_values
        channel_values = getattr(checkpoint, "channel_values", None)
        if channel_values is None:
            return 0

        messages = channel_values.get("messages", [])
        if not messages:
            return 0

        total = 0
        for msg in messages:
            content = getattr(msg, "content", "")
            if isinstance(content, str):
                total += count_tokens(content)
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and "text" in block:
                        total += count_tokens(block["text"])
                    elif isinstance(block, str):
                        total += count_tokens(block)
                    # Skip non-text blocks (images, etc.)
        return total

    def should_compact(self, estimated_tokens: int) -> bool:
        """Check if estimated tokens exceed threshold percentage.

        Args:
            estimated_tokens: Current estimated token count.

        Returns:
            True if compaction should be triggered.
        """
        threshold = int(self._context_limit() * self._threshold_pct())
        return estimated_tokens >= threshold

    async def compact_checkpoint_inplace(
        self,
        thread_id: str,
        state: LoopState,
    ) -> ContextCompactionResult | None:
        """Trigger in-place compaction via LLM summarization.

        This method:
        1. Gets current checkpoint
        2. Estimates tokens
        3. Calls LLM to generate summary of old messages
        4. Replaces old messages with summary + recent messages
        5. Updates checkpoint in-place
        6. Updates LoopState metrics

        Args:
            thread_id: Thread to compact.
            state: LoopState to update with new metrics.

        Returns:
            Compaction result with before/after metrics, or None on failure.
        """
        if self._checkpointer is None:
            logger.debug("[ContextWindow] No checkpointer, skipping compaction")
            return None

        if self._config is None:
            logger.debug("[ContextWindow] No config, skipping compaction")
            return None

        try:
            # Get current checkpoint
            checkpoint_tuple = await self._checkpointer.aget_tuple(
                {"configurable": {"thread_id": thread_id}}
            )
            if checkpoint_tuple is None:
                logger.debug("[ContextWindow] No checkpoint for thread %s", thread_id)
                return None

            checkpoint = checkpoint_tuple.checkpoint
            channel_values = getattr(checkpoint, "channel_values", {})
            messages = list(channel_values.get("messages", []))

            if not messages:
                logger.debug("[ContextWindow] Empty messages for thread %s", thread_id)
                return None

            original_tokens = self.estimate_checkpoint_tokens_sync(checkpoint)
            if original_tokens == 0:
                return None

            # Determine how many messages to keep vs summarize
            keep_count = _DEFAULT_KEEP_MESSAGES
            if len(messages) <= keep_count:
                logger.debug(
                    "[ContextWindow] Only %d messages, nothing to summarize",
                    len(messages),
                )
                return None

            # Split messages: summarize old, keep recent
            messages_to_summarize = messages[:-keep_count]
            messages_to_keep = messages[-keep_count:]

            # Build summary prompt with older messages
            # Cap to avoid overflow
            if len(messages_to_summarize) > _MAX_MESSAGES_FOR_SUMMARY_PROMPT:
                messages_to_summarize = messages_to_summarize[-_MAX_MESSAGES_FOR_SUMMARY_PROMPT:]

            # Format messages for prompt
            from langchain_core.messages import get_buffer_string

            messages_text = get_buffer_string(messages_to_summarize)
            prompt = _SUMMARY_PROMPT.format(messages=messages_text)

            # Call LLM to generate summary
            model = self._config.create_chat_model("fast")

            async def _invoke() -> Any:
                return await model.ainvoke([HumanMessage(content=prompt)])

            from soothe_nano.utils.llm.invoke_policy import (
                await_with_llm_call_policy,
                llm_rate_limit_config_from,
            )

            summary_response = await await_with_llm_call_policy(
                _invoke,
                config=llm_rate_limit_config_from(self._config),
                thread_id=thread_id,
            )
            summary_text = getattr(summary_response, "content", "")

            if not summary_text:
                logger.warning(
                    "[ContextWindow] LLM returned empty summary for thread %s",
                    thread_id,
                )
                return None

            # Build compacted messages: summary as AIMessage + recent messages
            summary_message = AIMessage(
                content=f"[Context Summary]\n{summary_text}",
            )
            compacted_messages = [summary_message] + messages_to_keep

            # Update checkpoint in-place
            await self._checkpointer.aupdate(
                {"configurable": {"thread_id": thread_id}},
                {"messages": compacted_messages},
            )

            # Estimate new token count
            new_tokens = await self.estimate_checkpoint_tokens(thread_id)

            # Update LoopState metrics
            state.total_tokens_used = new_tokens
            state.context_percentage_consumed = min(
                1.0,
                new_tokens / self._context_limit(),
            )

            messages_removed = len(messages) - len(compacted_messages)

            logger.info(
                "[ContextWindow] Compacted thread %s: %d → %d tokens (%d messages removed)",
                thread_id,
                original_tokens,
                new_tokens,
                messages_removed,
            )

            return ContextCompactionResult(
                thread_id=thread_id,
                tokens_before=original_tokens,
                tokens_after=new_tokens,
                messages_removed=messages_removed,
                summary_preview=summary_text[:200] if summary_text else None,
            )

        except Exception:
            logger.warning(
                "[ContextWindow] Compaction failed for thread %s",
                thread_id,
                exc_info=True,
            )
            return None

    async def check_and_compact_if_needed(
        self,
        thread_id: str,
        state: LoopState,
    ) -> ContextCompactionResult | None:
        """Full flow: estimate → check → compact if needed.

        Called after execute wave completes.

        Args:
            thread_id: Thread to check.
            state: LoopState to update.

        Returns:
            Compaction result if triggered, None otherwise.
        """
        try:
            estimated = await self.estimate_checkpoint_tokens(thread_id)
            if estimated == 0:
                return None

            if not self.should_compact(estimated):
                logger.debug(
                    "[ContextWindow] Thread %s at %d tokens (< %d threshold), no compaction",
                    thread_id,
                    estimated,
                    int(self._context_limit() * self._threshold_pct()),
                )
                return None

            logger.info(
                "[ContextWindow] Thread %s at %d tokens (>= %d threshold), triggering compaction",
                thread_id,
                estimated,
                int(self._context_limit() * self._threshold_pct()),
            )

            result = await self.compact_checkpoint_inplace(thread_id, state)

            # Check if compaction insufficient (still above threshold)
            if result is not None and self.should_compact(result.tokens_after):
                logger.warning(
                    "[ContextWindow] Compaction insufficient (%d > threshold); "
                    "retrying with aggressive compaction",
                    result.tokens_after,
                )
                # Retry with only keeping 2 messages
                result = await self.compact_checkpoint_inplace(thread_id, state)

            return result

        except Exception:
            logger.warning(
                "[ContextWindow] Compaction check failed for thread %s",
                thread_id,
                exc_info=True,
            )
            return None
