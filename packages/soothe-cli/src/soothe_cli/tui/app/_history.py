"""Conversation history loading, daemon event consumption, and thin binder delegation.

Pure event → card binding logic lives in ``soothe_sdk.display.card_binder``
(RFC-413). The static methods on ``_HistoryMixin`` are kept as thin
wrappers so the existing ``SootheApp._convert_messages_to_data(...)`` API
(used by tests and other mixins) continues to work.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from contextlib import suppress
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from datetime import datetime

from soothe_sdk.display import card_binder as _binder
from soothe_sdk.display.text_extract import (
    extract_ai_text_for_display,
    extract_user_text_for_display,
    normalize_stream_message,
)
from soothe_sdk.display.transcript_types import MessageData
from soothe_sdk.ux.loop_stream import is_stream_terminal
from textual.content import Content

from soothe_cli.tui.app._module_init import _LoopHistoryPayload
from soothe_cli.tui.widgets.messages import (
    AppMessage,
    AssistantMessage,
    UserMessage,
)

logger = logging.getLogger(__name__)


class _HistoryMixin:
    """History conversion, loading, and daemon WebSocket event consumption."""

    # ------------------------------------------------------------------
    # Binder delegation (RFC-413).
    # Pure logic lives in `soothe_sdk.display.card_binder`; these wrappers
    # preserve the existing SootheApp API so tests and callers stay unchanged.
    # ------------------------------------------------------------------

    @staticmethod
    def _is_loop_internal_checkpoint_message(msg: Any) -> bool:
        """Delegate to ``soothe_sdk.display.card_binder.is_loop_internal_checkpoint_message``."""
        return _binder.is_loop_internal_checkpoint_message(msg)

    @staticmethod
    def _merge_visible_messages_with_cognition_cards(
        visible: list[MessageData],
        cognition: list[MessageData],
    ) -> list[MessageData]:
        """Delegate to ``soothe_sdk.display.card_binder.merge_visible_messages_with_cognition_cards``."""
        return _binder.merge_visible_messages_with_cognition_cards(visible, cognition)

    @staticmethod
    def _convert_messages_to_data(
        messages: list[Any],
        *,
        cognition_card_replay: list[MessageData] | None = None,
    ) -> list[MessageData]:
        """Delegate to ``soothe_sdk.display.card_binder.convert_messages_to_data``."""
        return _binder.convert_messages_to_data(
            messages,
            cognition_card_replay=cognition_card_replay,
        )

    @staticmethod
    def _conversation_rows_to_langchain_messages(rows: list[dict[str, Any]]) -> list[Any]:
        """Delegate to ``soothe_sdk.display.card_binder.conversation_rows_to_langchain_messages``."""
        return _binder.conversation_rows_to_langchain_messages(rows)

    @staticmethod
    def _parse_loop_event_timestamp(timestamp: Any) -> datetime | None:
        """Delegate to ``soothe_sdk.display.card_binder.parse_loop_event_timestamp``."""
        return _binder.parse_loop_event_timestamp(timestamp)

    @staticmethod
    def _convert_event_to_message_data(event: dict[str, Any]) -> MessageData | None:
        """Delegate to ``soothe_sdk.display.card_binder.convert_event_to_message_data``."""
        return _binder.convert_event_to_message_data(event)

    @staticmethod
    def _collect_cognition_card_replay(events: list[dict[str, Any]]) -> list[MessageData]:
        """Delegate to ``soothe_sdk.display.card_binder.collect_cognition_card_replay``."""
        return _binder.collect_cognition_card_replay(events)

    @staticmethod
    def _merge_step_progress(prior: MessageData, later: MessageData) -> MessageData:
        """Delegate to ``soothe_sdk.display.card_binder.merge_step_progress``."""
        return _binder.merge_step_progress(prior, later)

    def _convert_loop_events_to_data(self, events: list[dict[str, Any]]) -> list[MessageData]:
        """Delegate to ``soothe_sdk.display.card_binder.convert_loop_events_to_data``."""
        return _binder.convert_loop_events_to_data(events)

    def _merge_history_sources(
        self,
        checkpoint_messages: list[Any],
        activity_events: list[dict[str, Any]],
    ) -> list[tuple[str, Any]]:
        """Delegate to ``soothe_sdk.display.card_binder.merge_history_sources``."""
        return _binder.merge_history_sources(checkpoint_messages, activity_events)

    def _convert_combined_to_data(self, combined: list[tuple[str, Any]]) -> list[MessageData]:
        """Delegate to ``soothe_sdk.display.card_binder.convert_combined_to_data``."""
        return _binder.convert_combined_to_data(combined)

    # ------------------------------------------------------------------
    # I/O: resume reads from the daemon's bound card ledger (RFC-413).
    # Legacy checkpoint + activity-log readers were removed when RFC-411
    # was superseded — the daemon now owns derivation and exposes a single
    # ``loop_cards_fetch`` RPC.
    # ------------------------------------------------------------------

    async def _fetch_loop_history_data(self, loop_id: str) -> _LoopHistoryPayload:
        """Fetch conversation history from goal snapshots + live card tail.

        RFC-631: prefers ``loop_history_fetch``; falls back to ``loop_cards_fetch``.

        Args:
            loop_id: Loop id.

        Returns:
            Payload containing converted message data and the persisted
            context-token count.
        """
        if self._daemon_session is None:
            return _LoopHistoryPayload([], 0)

        from soothe_sdk.display.card_ledger import card_from_wire_dict, card_to_wire_dict
        from soothe_sdk.display.snapshot_types import GoalDisplaySnapshot

        context_tokens = 0
        goal_dicts: tuple[dict[str, Any], ...] = ()
        wire_cards: list[dict[str, Any]] = []

        fetch_history = getattr(self._daemon_session, "fetch_loop_history", None)
        if callable(fetch_history):
            try:
                response = await fetch_history(loop_id)
            except Exception:
                logger.warning("loop_history_fetch failed for %s", loop_id, exc_info=True)
                response = None
            if response is not None and getattr(response, "success", False):
                context_tokens = int(getattr(response, "context_tokens", 0) or 0)
                goals_raw = getattr(response, "goals", []) or []
                goal_dicts = tuple(g for g in goals_raw if isinstance(g, dict))
                for goal_raw in goal_dicts:
                    goal = GoalDisplaySnapshot.from_wire_dict(goal_raw)
                    wire_cards.extend(card_to_wire_dict(card) for card in goal.display_cards)
                for card in getattr(response, "live_cards", []) or []:
                    if isinstance(card, dict):
                        wire_cards.append(card)

        if not wire_cards:
            try:
                response = await self._daemon_session.fetch_loop_cards(loop_id)
            except Exception:
                logger.warning("loop_cards_fetch failed for %s", loop_id, exc_info=True)
                return _LoopHistoryPayload([], 0)

            if not getattr(response, "success", False):
                return _LoopHistoryPayload([], 0)

            wire_cards = list(getattr(response, "cards", []) or [])
            context_tokens = int(getattr(response, "context_tokens", 0) or 0)

        if not wire_cards:
            return _LoopHistoryPayload([], context_tokens, goal_dicts)

        try:
            data = [card_from_wire_dict(c) for c in wire_cards]
        except Exception:
            logger.warning(
                "Failed to deserialize loop history payload for %s",
                loop_id,
                exc_info=True,
            )
            return _LoopHistoryPayload([], context_tokens, goal_dicts)

        from soothe_sdk.display.card_binder import (
            merge_consecutive_assistant_cards,
            sanitize_resume_display_cards,
        )

        data = sanitize_resume_display_cards(merge_consecutive_assistant_cards(data))

        return _LoopHistoryPayload(data, context_tokens, goal_dicts)

    async def _show_goal_history(self) -> None:
        """Render structured goal history from RFC-631 snapshots."""
        loop_id = self._lc_loop_id or (self._session_state.loop_id if self._session_state else None)
        if not loop_id:
            await self._mount_message(AppMessage("No active loop."))
            return

        payload = await self._fetch_loop_history_data(loop_id)
        goals = payload.goals
        if not goals:
            await self._mount_message(AppMessage("No completed goals recorded yet."))
            return

        lines: list[str] = []
        for index, goal_raw in enumerate(goals, start=1):
            if not isinstance(goal_raw, dict):
                continue
            goal_text = str(goal_raw.get("goal_text") or "").strip() or f"Goal {index}"
            status = str(goal_raw.get("status") or "completed")
            card_count = int(goal_raw.get("card_count") or 0)
            completion = str(goal_raw.get("goal_completion") or "").strip()
            if len(completion) > 120:
                completion = completion[:117] + "..."
            lines.append(f"Goal {index} [{status}] — {goal_text}")
            lines.append(f"  cards: {card_count}")
            if completion:
                lines.append(f"  completion: {completion}")
            lines.append("")

        await self._mount_message(AppMessage("\n".join(lines).rstrip()))

    async def _upgrade_loop_message_link(
        self,
        widget: AppMessage,
        *,
        prefix: str,
        loop_id: str,
    ) -> None:
        """Upgrade a plain status message to a linked one when URL resolves.

        Args:
            widget: The already-mounted app message.
            prefix: Text prefix before the loop id.
            loop_id: Loop id.
        """
        try:
            loop_msg = await self._build_loop_status_line(prefix, loop_id)
            if not isinstance(loop_msg, Content):
                logger.debug(
                    "Skipping loop link upgrade for %s: URL did not resolve",
                    loop_id,
                )
                return
            if widget.parent is None:
                logger.debug(
                    "Skipping loop link upgrade for %s: widget no longer mounted",
                    loop_id,
                )
                return
            # Keep serialized content in sync with the rendered content.
            widget._content = loop_msg
            widget.update(loop_msg)
        except Exception:
            logger.warning(
                "Failed to upgrade loop message link for %s",
                loop_id,
                exc_info=True,
            )

    def _schedule_loop_message_link(
        self,
        widget: AppMessage,
        *,
        prefix: str,
        loop_id: str,
    ) -> None:
        """Schedule loop URL link resolution and apply updates in the background.

        Args:
            widget: The message widget to update.
            prefix: Text prefix before the loop id.
            loop_id: Loop id.
        """
        self.run_worker(
            self._upgrade_loop_message_link(
                widget,
                prefix=prefix,
                loop_id=loop_id,
            ),
            exclusive=False,
        )

    async def _consume_daemon_events_background(self) -> None:
        """Consume daemon websocket events for an already-running loop subscription.

        IG-228: Reads passively when the loop is running without an active local turn,
        using the same processing pipeline as streaming queries.
        """
        if not self._daemon_session:
            return

        logger.info("Starting background event consumer for subscribed loop")
        from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
        from soothe_sdk.ux.loop_stream import LOOP_ASSISTANT_OUTPUT_PHASES, assistant_output_phase

        assistant_cards_by_ns: dict[tuple[Any, ...], AssistantMessage] = {}
        last_user_text_by_ns: dict[tuple[Any, ...], str] = {}
        last_ai_chunk_by_ns: dict[tuple[Any, ...], str] = {}

        try:
            # Use iter_turn_chunks to read events (same as active turn execution)
            chunk_source = self._daemon_session.iter_turn_chunks()
            async for chunk in chunk_source:
                if not isinstance(chunk, (list, tuple)) or len(chunk) != 3:
                    logger.debug("Skipping invalid stream chunk: %s", type(chunk).__name__)
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
                    if not isinstance(data, (list, tuple)) or len(data) != 2:
                        continue
                    message, _metadata = data
                    message = normalize_stream_message(message)

                    if self._is_loop_internal_checkpoint_message(message):
                        continue

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
                        continue

                    if isinstance(message, (AIMessage, AIMessageChunk)):
                        phase = assistant_output_phase(message)
                        if phase is not None and phase not in LOOP_ASSISTANT_OUTPUT_PHASES:
                            continue
                        extracted = extract_ai_text_for_display(message)
                        is_terminal = is_stream_terminal(message)
                        if extracted:
                            # Deduplicate immediate replayed AI chunks after reconnect/resubscribe.
                            if last_ai_chunk_by_ns.get(ns_key) == extracted:
                                if is_terminal:
                                    asst = assistant_cards_by_ns.get(ns_key)
                                    if asst is not None:
                                        await asst.stop_stream()
                                continue
                            asst = assistant_cards_by_ns.get(ns_key)
                            if asst is None:
                                asst = AssistantMessage(id=f"asst-{uuid.uuid4().hex[:8]}")
                                await self._mount_message(asst)
                                assistant_cards_by_ns[ns_key] = asst
                            await asst.append_content(extracted)
                            last_ai_chunk_by_ns[ns_key] = extracted

                        if is_terminal:
                            asst = assistant_cards_by_ns.get(ns_key)
                            if asst is not None:
                                await asst.stop_stream()
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

        except asyncio.CancelledError:
            logger.info("Background event consumer cancelled")
        except ConnectionError as exc:
            logger.warning("Background event consumer lost daemon connection: %s", exc)
            if self._daemon_session is not None:
                try:
                    await self._daemon_session.ensure_connected()
                    logger.info("Daemon session reconnected after background consumer disconnect")
                except Exception:
                    logger.debug(
                        "Background consumer reconnect failed",
                        exc_info=True,
                    )
        except Exception as exc:
            logger.warning("Background event consumer error: %s", exc)
        finally:
            for card in assistant_cards_by_ns.values():
                with suppress(Exception):
                    await card.stop_stream()
            self._bg_event_worker = None
            # If an agent turn was active (e.g. the loop completed while the
            # background consumer was reading), perform the same cleanup that
            # _run_agent_task's finally block would: re-enable input, clear
            # spinner, drain deferred actions, and process queued messages.
            if self._agent_running:
                with suppress(Exception):
                    await self._cleanup_agent_task()
            logger.info("Background event consumer stopped")
