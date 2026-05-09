"""Thread history conversion, loading, and daemon event consumption mixin."""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from contextlib import suppress
from datetime import UTC
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from datetime import datetime

    from langchain_core.runnables import RunnableConfig
    from textual.content import Content

from textual.content import Content

from soothe_cli.shared.tools.tool_card_payload import extract_tool_result_card_payload
from soothe_cli.tui.app._module_init import _ThreadHistoryPayload
from soothe_cli.tui.message_display_filter import (
    extract_ai_text_for_display,
    extract_message_tool_calls,
    extract_user_text_for_display,
    normalize_stream_message,
)
from soothe_cli.tui.widgets.message_store import (
    MessageData,
    MessageType,
    ToolStatus,
)
from soothe_cli.tui.widgets.messages import (
    AppMessage,
    AssistantMessage,
    ToolCallMessage,
    UserMessage,
)

logger = logging.getLogger(__name__)


class _HistoryMixin:
    """Thread history conversion, loading, and daemon event consumption."""

    @staticmethod
    def _convert_messages_to_data(messages: list[Any]) -> list[MessageData]:
        """Convert LangChain messages into lightweight `MessageData` objects.

        This is a pure function with zero DOM operations. Tool call matching
        happens here: `ToolMessage` results are matched by `tool_call_id` and
        stored directly on the corresponding `MessageData`.

        Args:
            messages: LangChain message objects from a thread checkpoint.

        Returns:
            Ordered list of `MessageData` ready for `MessageStore.bulk_load`.
        """
        from langchain_core.messages import AIMessage, ToolMessage

        from soothe_cli.shared.tools.message_processing import (
            extract_tool_args_dict,
            normalize_tool_calls_list,
        )

        result: list[MessageData] = []
        # Maps tool_call_id -> index into result list
        pending_tool_indices: dict[str, int] = {}

        for msg in messages:
            msg = normalize_stream_message(msg)
            user_text = extract_user_text_for_display(msg)
            if user_text is not None:
                # Detect skill invocations persisted via additional_kwargs
                skill_meta = (msg.additional_kwargs or {}).get("__skill")
                if isinstance(skill_meta, dict) and skill_meta.get("name"):
                    result.append(
                        MessageData(
                            type=MessageType.SKILL,
                            content="",
                            skill_name=skill_meta["name"],
                            skill_description=str(skill_meta.get("description", "")),
                            skill_source=str(skill_meta.get("source", "")),
                            skill_args=str(skill_meta.get("args", "")),
                            skill_body=user_text,
                        )
                    )
                else:
                    result.append(MessageData(type=MessageType.USER, content=user_text))

            elif isinstance(msg, AIMessage):
                text = extract_ai_text_for_display(msg)
                if text:
                    result.append(MessageData(type=MessageType.ASSISTANT, content=text))

                # Track tool calls for later matching
                for tc in normalize_tool_calls_list(getattr(msg, "tool_calls", [])):
                    tc_id = tc.get("id")
                    name = tc.get("name", "unknown")
                    args = extract_tool_args_dict(tc)
                    data = MessageData(
                        type=MessageType.TOOL,
                        content="",
                        tool_name=name,
                        tool_args=args,
                        tool_status=ToolStatus.PENDING,
                    )
                    result.append(data)
                    if tc_id:
                        pending_tool_indices[tc_id] = len(result) - 1
                    else:
                        data.tool_status = ToolStatus.REJECTED

            elif isinstance(msg, ToolMessage):
                tc_id = getattr(msg, "tool_call_id", None)
                if tc_id and tc_id in pending_tool_indices:
                    idx = pending_tool_indices.pop(tc_id)
                    data = result[idx]
                    payload = extract_tool_result_card_payload(msg)
                    if payload is not None:
                        data.tool_status = (
                            ToolStatus.ERROR if payload.is_error else ToolStatus.SUCCESS
                        )
                        data.tool_output = payload.output_display
                    else:
                        status = getattr(msg, "status", "success")
                        content = msg.content if isinstance(msg.content, str) else str(msg.content)
                        if status == "success":
                            data.tool_status = ToolStatus.SUCCESS
                        else:
                            data.tool_status = ToolStatus.ERROR
                        data.tool_output = content
                else:
                    logger.debug(
                        "ToolMessage with tool_call_id=%r could not be matched to a pending tool call",
                        tc_id,
                    )

            else:
                logger.debug(
                    "Skipping unsupported message type %s during history conversion",
                    type(msg).__name__,
                )

        # Mark unmatched tool calls as rejected
        for idx in pending_tool_indices.values():
            result[idx].tool_status = ToolStatus.REJECTED

        return result

    async def _get_thread_state_values(self, thread_id: str) -> dict[str, Any]:
        """Fetch thread state values, with remote checkpointer fallback.

        In server mode the LangGraph dev server can report an empty thread state
        after a restart even when checkpoints exist on disk. When that happens,
        read the latest checkpoint directly so resumed threads can still load
        history and display correctly.

        Args:
            thread_id: Thread ID to fetch from checkpoint storage.

        Returns:
            Thread state values keyed by channel name. Returns an empty dict
                when no checkpointed values are available.
        """
        if self._daemon_session is not None:
            config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
            snapshot = await self._daemon_session.aget_state(config)
            values = dict(snapshot.values)
            recovered = await self._recover_missing_checkpoint_messages(
                thread_id=thread_id,
                values=values,
            )
            if recovered:
                values["messages"] = recovered
            return values

        if not self._agent:
            return {}

        config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
        state = await self._agent.aget_state(config)

        values: dict[str, Any] = {}
        if state and state.values:
            values = dict(state.values)

        messages = values.get("messages")
        if isinstance(messages, list) and messages:
            return values
        if not self._remote_agent():
            return values

        logger.debug(
            "Remote state empty for thread %s; falling back to local checkpointer",
            thread_id,
        )
        fallback_values = await self._read_channel_values_from_checkpointer(thread_id)
        fallback_messages = fallback_values.get("messages")
        if isinstance(fallback_messages, list) and fallback_messages:
            values["messages"] = fallback_messages
        if values.get("_summarization_event") is None and "_summarization_event" in fallback_values:
            values["_summarization_event"] = fallback_values["_summarization_event"]
        if values.get("_context_tokens") is None and "_context_tokens" in fallback_values:
            values["_context_tokens"] = fallback_values["_context_tokens"]
        return values

    async def _recover_missing_checkpoint_messages(
        self,
        *,
        thread_id: str,
        values: dict[str, Any],
    ) -> list[Any] | None:
        """Recover missing checkpoint messages from persisted thread conversation rows.

        Args:
            thread_id: Thread ID being resumed.
            values: Current checkpoint values from `thread_state`.

        Returns:
            Recovered LangChain message objects, or `None` when recovery is not possible.
        """
        if self._daemon_session is None:
            return None
        existing = values.get("messages")
        if isinstance(existing, list) and existing:
            return None

        rows = await self._daemon_session.fetch_conversation_log(
            thread_id,
            limit=10000,
            include_events=True,
        )
        recovered_messages = self._conversation_rows_to_langchain_messages(rows)
        if not recovered_messages:
            return None

        try:
            from langchain_core.messages.base import messages_to_dict

            config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
            await self._daemon_session.aupdate_state(
                config,
                {"messages": messages_to_dict(recovered_messages)},
                timeout=10.0,
            )
            logger.info(
                "Recovered %d checkpoint messages from thread log for %s",
                len(recovered_messages),
                thread_id,
            )
        except Exception:
            logger.warning(
                "Failed to persist recovered checkpoint messages for %s",
                thread_id,
                exc_info=True,
            )
        return recovered_messages

    @staticmethod
    def _conversation_rows_to_langchain_messages(rows: list[dict[str, Any]]) -> list[Any]:
        """Convert persisted conversation rows to LangChain message objects."""
        from langchain_core.messages import AIMessage, HumanMessage

        messages: list[Any] = []
        for row in rows:
            if str(row.get("kind") or "").strip() != "conversation":
                continue
            metadata = row.get("metadata")
            metadata_dict = metadata if isinstance(metadata, dict) else {}
            role = str(row.get("role") or metadata_dict.get("role") or "").strip().lower()
            content = str(row.get("content") or metadata_dict.get("text") or "").strip()
            if not content:
                continue
            if role == "user":
                messages.append(HumanMessage(content=content))
            elif role == "assistant":
                messages.append(AIMessage(content=content))
        return messages

    async def _fetch_thread_activity_events(self, thread_id: str) -> list[dict[str, Any]]:
        """Read ThreadLogger JSONL events for thread history recovery via daemon RPC.

        Args:
            thread_id: Thread ID to read events from.

        Returns:
            List of event records (tool_call, tool_result, custom events) from ThreadLogger.
        """
        if self._daemon_session is None:
            logger.debug("No daemon session - cannot read ThreadLogger events")
            return []

        try:
            messages = await self._daemon_session.fetch_conversation_log(
                thread_id,
                limit=10000,
                include_events=True,
            )
            # Filter for event types (tool calls, tool results, events).
            # The daemon API returns ThreadMessage objects with `kind` field.
            return [m for m in messages if m.get("kind") in ("event", "tool_call", "tool_result")]
        except Exception:
            logger.debug(
                "Failed to read ThreadLogger events for thread %s", thread_id, exc_info=True
            )
            return []

    @staticmethod
    def _parse_thread_event_timestamp(timestamp: Any) -> datetime | None:
        """Parse an event timestamp into a UTC-aware datetime.

        Args:
            timestamp: Event timestamp value from ThreadLogger.

        Returns:
            Parsed UTC-aware datetime, or `None` when parsing fails.
        """
        from datetime import datetime

        if not isinstance(timestamp, str) or not timestamp:
            return None
        try:
            parsed = datetime.fromisoformat(timestamp)
        except (ValueError, TypeError):
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)

    def _convert_event_to_message_data(self, event: dict[str, Any]) -> MessageData | None:
        """Convert one persisted thread-event row to MessageData.

        Args:
            event: Persisted `thread_messages` row with optional metadata payload.

        Returns:
            MessageData when a displayable card can be built, else `None`.
        """
        from ast import literal_eval

        kind = str(event.get("kind") or "").strip()
        metadata_raw = event.get("metadata")
        metadata = metadata_raw if isinstance(metadata_raw, dict) else {}
        parsed_ts = self._parse_thread_event_timestamp(event.get("timestamp"))

        event_timestamp = parsed_ts.timestamp() if parsed_ts is not None else time.time()

        if kind == "tool_call":
            tool_name = str(event.get("tool_name") or metadata.get("tool_name") or "unknown")
            args_preview = str(
                event.get("args_preview")
                or metadata.get("args_preview")
                or event.get("content")
                or ""
            ).strip()
            parsed_args: dict[str, Any] | None = None
            if args_preview:
                with suppress(ValueError, SyntaxError):
                    parsed = literal_eval(args_preview)
                    if isinstance(parsed, dict):
                        parsed_args = parsed
            return MessageData(
                type=MessageType.TOOL,
                content="",
                tool_name=tool_name,
                tool_args=parsed_args,
                tool_status=ToolStatus.RUNNING,
                timestamp=event_timestamp,
            )

        if kind == "tool_result":
            tool_name = str(event.get("tool_name") or metadata.get("tool_name") or "unknown")
            content = str(event.get("content") or metadata.get("content") or "")
            return MessageData(
                type=MessageType.TOOL,
                content="",
                tool_name=tool_name,
                tool_status=ToolStatus.SUCCESS,
                tool_output=content,
                timestamp=event_timestamp,
            )

        if kind == "event":
            event_data = event.get("data")
            if not isinstance(event_data, dict):
                nested_data = metadata.get("data")
                if isinstance(nested_data, dict):
                    event_data = nested_data
                else:
                    return None

            if isinstance(event_data, dict):
                event_type = str(event_data.get("type") or "").strip()
                summary = str(event_data.get("summary") or "").strip()
                if event_type == "soothe.cognition.agent_loop.reasoned":
                    plan_action_raw = str(event_data.get("plan_action") or "new").strip()
                    plan_action = plan_action_raw if plan_action_raw in {"keep", "new"} else "new"
                    return MessageData(
                        type=MessageType.COGNITION_PLAN,
                        content="",
                        timestamp=event_timestamp,
                        cognition_plan_next_action=str(event_data.get("next_action") or ""),
                        cognition_plan_status=str(event_data.get("status") or ""),
                        cognition_plan_iteration=int(event_data.get("iteration") or 0),
                        cognition_plan_action=plan_action,
                        cognition_plan_assessment=str(event_data.get("assessment_reasoning") or ""),
                        cognition_plan_strategy=str(event_data.get("plan_reasoning") or ""),
                    )
                if event_type == "soothe.cognition.agent_loop.started":
                    goal_snapshot = {
                        "goal": str(event_data.get("goal") or "").strip(),
                        "max_iterations": int(event_data.get("max_iterations") or 0),
                        "steps": [],
                        "footer_visible": False,
                        "footer_text": "",
                    }
                    return MessageData(
                        type=MessageType.COGNITION_GOAL_TREE,
                        content="",
                        timestamp=event_timestamp,
                        cognition_goal_snapshot_json=json.dumps(goal_snapshot),
                    )
                if event_type == "soothe.cognition.agent_loop.step.started":
                    step_id = str(event_data.get("step_id") or "").strip()
                    if not step_id:
                        return None
                    return MessageData(
                        type=MessageType.STEP_PROGRESS,
                        content="",
                        timestamp=event_timestamp,
                        step_progress_id=step_id,
                        step_progress_description=str(event_data.get("description") or "(step)"),
                        step_progress_phase="running",
                    )
                if event_type == "soothe.cognition.agent_loop.step.completed":
                    step_id = str(event_data.get("step_id") or "").strip()
                    if not step_id:
                        return None
                    success = bool(event_data.get("success", True))
                    summary_text = str(
                        event_data.get("summary") or event_data.get("output_preview") or ""
                    ).strip()
                    if not summary_text:
                        summary_text = "Done" if success else "Failed"
                    return MessageData(
                        type=MessageType.STEP_PROGRESS,
                        content="",
                        timestamp=event_timestamp,
                        step_progress_id=step_id,
                        step_progress_description=str(event_data.get("description") or "(step)"),
                        step_progress_phase="success" if success else "error",
                        step_success=success,
                        step_duration_ms=int(event_data.get("duration_ms") or 0),
                        step_tool_call_count=int(event_data.get("tool_call_count") or 0),
                        step_summary=summary_text,
                    )
                if summary:
                    content = summary
                elif event_type:
                    content = f"Event: {event_type}"
                else:
                    return None
            return MessageData(
                type=MessageType.APP,
                content=content,
                timestamp=event_timestamp,
            )

        return None

    def _convert_thread_events_to_data(self, events: list[dict[str, Any]]) -> list[MessageData]:
        """Convert persisted thread event rows into stable TUI cards.

        This fallback is used only when checkpoint messages are unavailable.
        """
        from datetime import datetime

        data: list[MessageData] = []
        pending_tool_indices: dict[str, list[int]] = {}

        sorted_events = sorted(
            events,
            key=lambda event: (
                self._parse_thread_event_timestamp(event.get("timestamp"))
                or datetime.min.replace(tzinfo=UTC)
            ),
        )
        for event in sorted_events:
            kind = str(event.get("kind") or "").strip()
            msg_data = self._convert_event_to_message_data(event)
            if msg_data is None:
                continue

            if kind == "tool_call" and msg_data.type == MessageType.TOOL and msg_data.tool_name:
                pending_tool_indices.setdefault(msg_data.tool_name, []).append(len(data))
                data.append(msg_data)
                continue

            if kind == "tool_result" and msg_data.type == MessageType.TOOL and msg_data.tool_name:
                tool_name = msg_data.tool_name
                pending = pending_tool_indices.get(tool_name, [])
                if pending:
                    call_idx = pending.pop(0)
                    data[call_idx].tool_status = ToolStatus.SUCCESS
                    data[call_idx].tool_output = msg_data.tool_output
                else:
                    data.append(msg_data)
                continue

            data.append(msg_data)

        return data

    def _merge_history_sources(
        self,
        checkpoint_messages: list[Any],
        thread_logger_events: list[dict[str, Any]],
    ) -> list[tuple[str, Any]]:
        """Merge checkpoint messages and ThreadLogger events chronologically.

        Args:
            checkpoint_messages: LangChain message objects from checkpoint.
            thread_logger_events: ThreadLogger event records.

        Returns:
            List of (source_type, data) tuples sorted by timestamp:
                source_type: "message" or "event"
                data: LangChain message or MessageData
        """
        from datetime import datetime

        timeline: list[tuple[datetime, str, Any]] = []
        min_timestamp = datetime.min.replace(tzinfo=UTC)

        # Extract timestamps from checkpoint messages
        for msg in checkpoint_messages:
            # LangChain messages don't have explicit timestamps in checkpoint
            # Use message sequence as proxy (they're already ordered)
            # We'll place them relative to events based on tool call matching
            timeline.append((min_timestamp, "message", msg))

        # Add ThreadLogger events with explicit timestamps
        for event in thread_logger_events:
            ts = self._parse_thread_event_timestamp(event.get("timestamp")) or min_timestamp

            # Convert event to MessageData
            msg_data = self._convert_event_to_message_data(event)
            if msg_data:
                timeline.append((ts, "event", msg_data))

        # Sort by timestamp (messages without timestamps get datetime.min)
        # This interleaves events chronologically with messages
        timeline.sort(key=lambda x: x[0])

        # Return as (source_type, data) list
        return [(item[1], item[2]) for item in timeline]

    def _convert_combined_to_data(self, combined: list[tuple[str, Any]]) -> list[MessageData]:
        """Convert merged timeline to MessageData widgets.

        Args:
            combined: List of (source_type, data) from merge.

        Returns:
            List of MessageData widgets for UI rendering.
        """
        data: list[MessageData] = []
        pending_checkpoint_messages: list[Any] = []

        def flush_checkpoint_messages() -> None:
            if not pending_checkpoint_messages:
                return
            data.extend(self._convert_messages_to_data(pending_checkpoint_messages))
            pending_checkpoint_messages.clear()

        for source_type, item in combined:
            if source_type == "message":
                pending_checkpoint_messages.append(item)
                continue

            flush_checkpoint_messages()
            if source_type == "event" and isinstance(item, MessageData):
                data.append(item)

        flush_checkpoint_messages()
        return data

    async def _fetch_thread_history_data(self, thread_id: str) -> _ThreadHistoryPayload:
        """Fetch and convert complete thread history (checkpoint + ThreadLogger).

        Enhanced to read from both checkpoint messages and ThreadLogger events
        to reconstruct full visual history including tool calls, activities, and events.

        Args:
            thread_id: Thread ID to fetch from checkpoint and ThreadLogger storage.

        Returns:
            Payload containing converted message data and the persisted
            context-token count.
        """
        # 1. Read checkpoint messages (existing)
        state_values = await self._get_thread_state_values(thread_id)
        raw_tokens = state_values.get("_context_tokens")
        context_tokens = raw_tokens if isinstance(raw_tokens, int) and raw_tokens >= 0 else 0
        messages = state_values.get("messages", [])

        # 2. Primary source: checkpoint messages -> canonical TUI cards
        if messages and isinstance(messages[0], dict):
            from soothe_sdk.langchain_wire import messages_from_wire_dicts

            messages = messages_from_wire_dicts(messages)
        if messages:
            data = await asyncio.to_thread(self._convert_messages_to_data, messages)
            return _ThreadHistoryPayload(data, context_tokens)

        # 3. Fallback source: ThreadLogger events when checkpoints are unavailable.
        events = await self._fetch_thread_activity_events(thread_id)
        if not events:
            return _ThreadHistoryPayload([], context_tokens)

        data = await asyncio.to_thread(self._convert_thread_events_to_data, events)

        return _ThreadHistoryPayload(data, context_tokens)

    @staticmethod
    async def _read_channel_values_from_checkpointer(thread_id: str) -> dict[str, Any]:
        """Read checkpoint channel values directly from the SQLite checkpointer.

        Args:
            thread_id: Thread ID to look up.

        Returns:
            Channel values from the latest checkpoint, or an empty dict on
                failure.
        """
        try:
            from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

            from soothe_cli.tui.sessions import get_db_path

            db_path = str(get_db_path())
            config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
            async with AsyncSqliteSaver.from_conn_string(db_path) as saver:
                tup = await saver.aget_tuple(config)
                if tup and tup.checkpoint:
                    channel_values = tup.checkpoint.get("channel_values", {})
                    if isinstance(channel_values, dict):
                        return dict(channel_values)
        except (ImportError, OSError) as exc:
            logger.warning(
                "Failed to read checkpointer directly for %s: %s",
                thread_id,
                exc,
            )
        except Exception:
            logger.warning(
                "Unexpected error reading checkpointer for %s",
                thread_id,
                exc_info=True,
            )
        return {}

    async def _upgrade_thread_message_link(
        self,
        widget: AppMessage,
        *,
        prefix: str,
        thread_id: str,
    ) -> None:
        """Upgrade a plain thread message to a linked one when URL resolves.

        Args:
            widget: The already-mounted app message.
            prefix: Text prefix before thread ID.
            thread_id: Thread ID to resolve.
        """
        try:
            thread_msg = await self._build_thread_message(prefix, thread_id)
            if not isinstance(thread_msg, Content):
                logger.debug(
                    "Skipping thread link upgrade for %s: URL did not resolve",
                    thread_id,
                )
                return
            if widget.parent is None:
                logger.debug(
                    "Skipping thread link upgrade for %s: widget no longer mounted",
                    thread_id,
                )
                return
            # Keep serialized content in sync with the rendered content.
            widget._content = thread_msg
            widget.update(thread_msg)
        except Exception:
            logger.warning(
                "Failed to upgrade thread message link for %s",
                thread_id,
                exc_info=True,
            )

    def _schedule_thread_message_link(
        self,
        widget: AppMessage,
        *,
        prefix: str,
        thread_id: str,
    ) -> None:
        """Schedule thread URL link resolution and apply updates in the background.

        Args:
            widget: The message widget to update.
            prefix: Text prefix before thread ID.
            thread_id: Thread ID to resolve.
        """
        self.run_worker(
            self._upgrade_thread_message_link(
                widget,
                prefix=prefix,
                thread_id=thread_id,
            ),
            exclusive=False,
        )

    async def _consume_daemon_events_background(self) -> None:
        """Consume events from daemon when subscribed to a running thread.

        IG-228: This background task reads events from the daemon websocket
        when the thread is already running passively (not during an active
        turn). It uses the same event processing pipeline as active queries.
        """
        if not self._daemon_session:
            return

        logger.info("Starting background event consumer for subscribed thread")
        from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage

        from soothe_cli.cli.stream.pipeline import StreamDisplayPipeline
        from soothe_cli.shared.tools.message_processing import extract_tool_args_dict

        progress_pipeline = StreamDisplayPipeline()
        tool_cards: dict[str, ToolCallMessage] = {}
        assistant_cards_by_ns: dict[tuple[Any, ...], AssistantMessage] = {}
        last_user_text_by_ns: dict[tuple[Any, ...], str] = {}
        last_ai_chunk_by_ns: dict[tuple[Any, ...], str] = {}

        try:
            # Use iter_turn_chunks to read events (same as active turn execution)
            chunk_source = self._daemon_session.iter_turn_chunks()
            async for chunk in chunk_source:
                if not isinstance(chunk, tuple) or len(chunk) != 3:
                    logger.debug("Skipping non-3-tuple chunk: %s", type(chunk).__name__)
                    continue

                namespace, mode, data = chunk
                ns_key = tuple(namespace) if namespace else ()

                async def _flush_assistant_ns(key: tuple[Any, ...]) -> None:
                    card = assistant_cards_by_ns.pop(key, None)
                    if card is not None:
                        await card.stop_stream()

                if mode == "status":
                    continue

                if mode == "messages":
                    if not isinstance(data, tuple) or len(data) != 2:
                        continue
                    message, _metadata = data
                    message = normalize_stream_message(message)

                    user_text = extract_user_text_for_display(message)
                    if user_text is not None:
                        # Deduplicate immediate replayed user rows after reconnect/resubscribe.
                        if last_user_text_by_ns.get(ns_key) == user_text:
                            continue
                        await _flush_assistant_ns(ns_key)
                        await self._mount_message(UserMessage(user_text))
                        last_user_text_by_ns[ns_key] = user_text
                        continue

                    if isinstance(message, ToolMessage):
                        call_id = str(getattr(message, "tool_call_id", "") or "").strip()
                        if call_id and call_id in tool_cards:
                            tool_cards[call_id].set_success(
                                str(getattr(message, "content", "") or "")
                            )
                        continue

                    # Render tool calls as cards in background mode too.
                    for raw_call in extract_message_tool_calls(message):
                        call_id = str(
                            raw_call.get("id") or raw_call.get("tool_call_id") or ""
                        ).strip()
                        tool_name = str(raw_call.get("name") or "").strip()
                        if not call_id or not tool_name or call_id in tool_cards:
                            continue
                        tool_msg = ToolCallMessage(
                            tool_name,
                            extract_tool_args_dict(raw_call),
                            tool_call_id=call_id,
                        )
                        tool_msg.set_running()
                        await self._mount_message(tool_msg)
                        tool_cards[call_id] = tool_msg

                    if isinstance(message, (AIMessage, AIMessageChunk)):
                        extracted = extract_ai_text_for_display(message)
                        if extracted:
                            # Deduplicate immediate replayed AI chunks after reconnect/resubscribe.
                            if last_ai_chunk_by_ns.get(ns_key) == extracted:
                                if getattr(message, "chunk_position", None) == "last":
                                    await _flush_assistant_ns(ns_key)
                                continue
                            asst = assistant_cards_by_ns.get(ns_key)
                            if asst is None:
                                asst = AssistantMessage(id=f"asst-{uuid.uuid4().hex[:8]}")
                                await self._mount_message(asst)
                                assistant_cards_by_ns[ns_key] = asst
                            await asst.append_content(extracted)
                            last_ai_chunk_by_ns[ns_key] = extracted

                        if getattr(message, "chunk_position", None) == "last":
                            await _flush_assistant_ns(ns_key)
                            last_ai_chunk_by_ns.pop(ns_key, None)
                        continue
                    continue

                if mode != "updates" or not isinstance(data, dict):
                    continue

                await _flush_assistant_ns(ns_key)
                payloads: list[dict[str, Any]] = []
                if isinstance(data.get("type"), str):
                    payloads.append(data)
                for value in data.values():
                    if isinstance(value, dict) and isinstance(value.get("type"), str):
                        payloads.append(value)

                for event_payload in payloads:
                    event_for_pipeline = dict(event_payload)
                    event_for_pipeline["namespace"] = list(namespace)
                    lines = progress_pipeline.process(event_for_pipeline)
                    for line in lines:
                        rendered = line.format().lstrip("\n").rstrip()
                        if rendered:
                            await self._mount_message(AppMessage(rendered))

        except asyncio.CancelledError:
            logger.info("Background event consumer cancelled")
        except Exception as exc:
            logger.warning("Background event consumer error: %s", exc)
        finally:
            for card in assistant_cards_by_ns.values():
                with suppress(Exception):
                    await card.stop_stream()
            logger.info("Background event consumer stopped")
