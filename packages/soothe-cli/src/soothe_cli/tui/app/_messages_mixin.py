"""Message widget lifecycle, store management, queue management, interrupt/quit, toggles, editor, and mouse/focus events mixin."""

from __future__ import annotations

import logging
import time
from contextlib import suppress
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from textual.events import Click, Paste, TextSelected
    from textual.widget import Widget
    from textual.widgets import Input, Static
    from textual.worker import Worker

from textual.app import App
from textual.containers import Container, VerticalScroll
from textual.css.query import NoMatches

from soothe_cli.tui.app._module_init import (
    _ITERM_CURSOR_GUIDE_ON,
    DeferredAction,
    _LoopHistoryPayload,
    _write_iterm_escape,
)
from soothe_cli.tui.widgets.file_change_preview import FileChangePreviewWidget
from soothe_cli.tui.widgets.messages import (
    AppMessage,
    AssistantMessage,
    CognitionGoalTreeMessage,
    CognitionReasonMessage,
    CognitionStepMessage,
    DiffMessage,
    ErrorMessage,
    QueuedUserMessage,
    SkillMessage,
    SummarizationMessage,
)

logger = logging.getLogger(__name__)


def _widget_is_hidden(widget: Any) -> bool:
    """Return True when a widget is CSS-hidden or display-none.

    MagicMock-safe: only treats an explicit ``True`` from ``has_class("hidden")``
    or a concrete ``classes`` collection containing ``hidden`` as hidden.
    """
    has_class = getattr(widget, "has_class", None)
    if callable(has_class):
        try:
            if has_class("hidden") is True:
                return True
        except Exception:  # noqa: BLE001
            pass
    classes = getattr(widget, "classes", None)
    if isinstance(classes, (set, list, tuple, frozenset)) and "hidden" in classes:
        return True
    display = getattr(widget, "display", True)
    return display is False or display == "none"


class _MessagesMixin:
    """Message widget lifecycle, store management, queue, interrupt/quit, toggles, editor, and events."""

    def _refresh_queued_goal_tips(self) -> None:
        """Show queue interaction tips on the most recently queued goal only."""
        if not self._queued_widgets:
            return
        tip_index: int | None = None
        if self._pending_messages and self._pending_messages[-1].mode == "normal":
            pending_tail_index = len(self._pending_messages) - 1
            if pending_tail_index < len(self._queued_widgets):
                tip_index = pending_tail_index
        for index, widget in enumerate(self._queued_widgets):
            with suppress(Exception):
                widget.set_show_queue_tips(tip_index is not None and index == tip_index)

    def _has_pending_chat_input(self) -> bool:
        """Return whether chat input has draft content that should be preserved."""
        chat_input = self._chat_input
        return bool(
            chat_input
            and (
                chat_input.value.strip()
                or chat_input.mode != "normal"
                or chat_input._current_suggestions
            )
        )

    def _can_run_queued_goal_now_from_enter(self) -> bool:
        """Return whether Enter should cancel the current goal for queued-head run."""
        if not self._agent_running or not self._pending_messages:
            return False
        if self._has_pending_chat_input():
            return False
        queue_head = self._pending_messages[0]
        return queue_head.mode == "normal"

    def run_queued_goal_now_from_enter(self) -> bool:
        """Cancel the running goal so queued head can start immediately.

        Returns:
            `True` when an interrupt was triggered, otherwise `False`.
        """
        if not self._can_run_queued_goal_now_from_enter():
            return False
        return self._interrupt_running_goal_preserving_queue()

    def _interrupt_running_goal_preserving_queue(self) -> bool:
        """Interrupt current agent turn while keeping queued goals intact."""
        if not (self._agent_running and self._agent_worker):
            return False
        if self._daemon_session is not None:
            self.run_worker(
                self._interrupt_daemon_agent_turn(discard_queue=False),
                exclusive=False,
                group="daemon-interrupt",
            )
        else:
            self.run_worker(
                self._tear_down_interrupt_ui(),
                exclusive=False,
                group="interrupt-ui",
            )
            self._cancel_worker(self._agent_worker, discard_queue=False)
        return True

    async def _load_loop_history(
        self,
        *,
        loop_id: str | None = None,
        preloaded_payload: _LoopHistoryPayload | None = None,
    ) -> None:
        """Load and render message history when resuming a loop.

        When `preloaded_payload` is provided (e.g. after switching loops),
        this reuses that data. Otherwise, it fetches persisted graph state from the
        agent and converts stored messages into lightweight `MessageData`
        objects. The method then bulk-loads into the `MessageStore` and mounts
        only the last `WINDOW_SIZE` widgets to reduce DOM operations on large
        transcripts.

        Args:
            loop_id: Optional loop id.

                Defaults to current.
            preloaded_payload: Optional pre-fetched history payload for the
                loop.
        """
        history_loop_id = loop_id or self._lc_loop_id
        if not history_loop_id:
            logger.debug("Skipping history load: no loop id available")
            return
        if preloaded_payload is None and not self._runtime_backend_ready():
            logger.debug(
                "Skipping history load for %s: no execution backend and no preloaded data",
                history_loop_id,
            )
            return

        async with self._loop_history_load_lock:
            if history_loop_id == self._loop_history_loaded_for:
                logger.debug(
                    "Skipping duplicate history load for loop %s",
                    history_loop_id,
                )
                return

            try:
                await self._clear_messages()

                # Fetch + convert, or reuse preloaded payload on loop switch.
                payload = (
                    preloaded_payload
                    if preloaded_payload is not None
                    else await self._fetch_loop_history_data(history_loop_id)
                )
                if not payload.messages:
                    return

                # Seed loop token total from persisted checkpoint
                if payload.context_tokens > 0:
                    self._seed_loop_token_from_checkpoint(payload.context_tokens)

                # Bulk load into store (sets visible window; replaces prior data).
                _archived, visible = self._message_store.bulk_load(
                    payload.messages,
                    replace=True,
                )

                # Cache container ref (single query)
                try:
                    messages_container = self.query_one("#messages", Container)
                except NoMatches:
                    return

                # Create and mount only visible widgets (max WINDOW_SIZE).
                from soothe_sdk.display.card_binder import sanitize_resume_display_cards

                from soothe_cli.tui.binding import message_to_widget

                visible = self._dedupe_message_data_by_id(visible)
                visible = sanitize_resume_display_cards(visible)
                widgets = [message_to_widget(msg_data) for msg_data in visible]
                if widgets:
                    await messages_container.mount(*widgets)

                # Render assistant markdown progressively to avoid startup stalls
                for widget, msg_data in zip(widgets, visible, strict=False):
                    if isinstance(widget, AssistantMessage) and msg_data.content:
                        self._enqueue_hydrated_assistant_render(widget, msg_data.content)

                # Add footer immediately and resolve link asynchronously
                loop_msg_widget = AppMessage(f"Resumed loop: {history_loop_id}")
                await self._mount_message(loop_msg_widget)
                self._schedule_loop_message_link(
                    loop_msg_widget,
                    prefix="Resumed loop",
                    loop_id=history_loop_id,
                )

                # Scroll once to bottom after history loads
                def scroll_to_end() -> None:
                    with suppress(NoMatches):
                        chat = self.query_one("#chat", VerticalScroll)
                        chat.scroll_end(animate=False, immediate=True)

                self.set_timer(0.1, scroll_to_end)
                self._loop_history_loaded_for = history_loop_id

            except Exception as e:  # Resilient history loading
                logger.exception(
                    "Failed to load conversation history for %s",
                    history_loop_id,
                )
                await self._mount_message(AppMessage(f"Could not load history: {e}"))

    async def _apply_card_wire_frame(self, data: Any) -> bool:
        """Apply one custom-mode ``soothe.card.*`` payload. Returns True if handled."""

        from soothe_sdk.display.transcript_types import MessageType

        from soothe_cli.tui.binding import message_to_widget
        from soothe_cli.tui.card_wire import (
            CARD_CREATED,
            CARD_FINALIZED,
            CARD_UPDATED,
            parse_card_custom_payload,
        )
        from soothe_cli.tui.widgets.messages import CognitionStepMessage

        parsed = parse_card_custom_payload(data)
        if parsed is None:
            return False
        wire_type, card, patch = parsed

        if wire_type == CARD_CREATED and card is not None:
            existing = self._find_existing_card_widget(card)
            if existing is not None:
                self._register_card_widget_with_adapter(existing, card)
                if isinstance(existing, AssistantMessage) and card.content:
                    self._enqueue_hydrated_assistant_render(existing, card.content)
                return True
            # Live turns already mount the user prompt locally; skip duplicate.
            if card.type == MessageType.USER and self._user_prompt_already_mounted(card.content):
                return True
            # Stream path owns live goal_completion; skip ledger duplicate.
            if card.type == MessageType.ASSISTANT and self._assistant_card_already_visible(card):
                return True
            # Live custom handlers mount intent/plan immediately; skip ledger dup.
            if card.type == MessageType.COGNITION_REASON and self._cognition_reason_already_visible(
                card
            ):
                return True
            widget = message_to_widget(card)
            await self._mount_message(widget)
            self._register_card_widget_with_adapter(widget, card)
            if isinstance(widget, AssistantMessage) and card.content:
                self._enqueue_hydrated_assistant_render(widget, card.content)
                if getattr(card, "loop_output_phase", None) == "goal_completion":
                    adapter = getattr(self, "_ui_adapter", None)
                    if adapter is not None:
                        adapter._goal_completion_mounted_this_turn = True
            return True

        if wire_type in {CARD_UPDATED, CARD_FINALIZED}:
            card_id = str(patch.get("id") or data.get("card_id") or "").strip()
            if not card_id:
                return True
            updated = self._message_store.update_message(
                card_id,
                **{k: v for k, v in patch.items() if k != "id" and k != "type"},
            )
            widget = self._resolve_card_widget_for_patch(card_id, patch)
            if widget is None:
                return True
            if not updated and not isinstance(widget, CognitionStepMessage):
                return True
            content = patch.get("content")
            if isinstance(widget, AssistantMessage) and isinstance(content, str):
                self._enqueue_hydrated_assistant_render(widget, content)
            if isinstance(widget, CognitionStepMessage):
                phase = patch.get("step_progress_phase")
                if phase == "running":
                    widget.set_running()
                elif phase in ("success", "error") and patch.get("step_success") is not None:
                    widget.set_complete(
                        bool(patch.get("step_success")),
                        int(patch.get("step_duration_ms") or 0),
                        int(patch.get("step_tool_call_count") or 0),
                        str(patch.get("step_summary") or ""),
                    )
                    # Drop from live routing registry once the card is terminal.
                    adapter = getattr(self, "_ui_adapter", None)
                    if adapter is not None:
                        step_id = str(
                            patch.get("step_progress_id") or getattr(widget, "_step_id", "") or ""
                        ).strip()
                        if step_id:
                            adapter._current_step_messages.pop(step_id, None)
                desc = patch.get("step_progress_description")
                if isinstance(desc, str) and desc.strip():
                    widget.set_description(desc)
            return True

        return True

    def _find_existing_card_widget(self, card: Any) -> Any | None:
        """Return an already-mounted widget for ``card``, if any."""
        from soothe_sdk.display.transcript_types import MessageType

        if getattr(card, "id", None):
            try:
                return self.query_one(f"#{card.id}")
            except Exception:
                pass
        if getattr(card, "type", None) == MessageType.STEP_PROGRESS:
            step_id = str(getattr(card, "step_progress_id", "") or "").strip()
            adapter = getattr(self, "_ui_adapter", None)
            if adapter is not None and step_id:
                return getattr(adapter, "_current_step_messages", {}).get(step_id)
        return None

    def _resolve_card_widget_for_patch(self, card_id: str, patch: dict[str, Any]) -> Any | None:
        """Resolve a mounted widget for an update/finalize patch."""
        try:
            return self.query_one(f"#{card_id}")
        except Exception:
            pass
        step_id = str(patch.get("step_progress_id") or "").strip()
        adapter = getattr(self, "_ui_adapter", None)
        if adapter is not None and step_id:
            return getattr(adapter, "_current_step_messages", {}).get(step_id)
        return None

    def _user_prompt_already_mounted(self, content: str) -> bool:
        """True when a local user widget already shows this prompt text."""
        from soothe_sdk.display.transcript_types import MessageType

        text = str(content or "").strip()
        if not text:
            return False
        for msg in reversed(self._message_store.get_all_messages()):
            if getattr(msg, "type", None) == MessageType.USER:
                return str(getattr(msg, "content", "") or "").strip() == text
        return False

    def _assistant_card_already_visible(self, card: Any) -> bool:
        """True when stream already mounted this assistant body (avoid double report)."""
        from soothe_sdk.display.transcript_types import MessageType

        adapter = getattr(self, "_ui_adapter", None)
        if adapter is not None and getattr(adapter, "_goal_completion_mounted_this_turn", False):
            return True
        text = str(getattr(card, "content", "") or "").strip()
        if not text:
            return False
        for msg in reversed(self._message_store.get_all_messages()):
            if getattr(msg, "type", None) != MessageType.ASSISTANT:
                continue
            existing = str(getattr(msg, "content", "") or "").strip()
            if not existing:
                continue
            if existing == text or text.startswith(existing) or existing.startswith(text):
                return True
            # Only inspect the latest assistant card.
            break
        return False

    def _cognition_reason_already_visible(self, card: Any) -> bool:
        """True when a live intent/plan cognition card already shows this text."""
        from soothe_sdk.display.transcript_types import MessageType

        strategy = str(getattr(card, "cognition_plan_strategy", "") or "").strip()
        assessment = str(getattr(card, "cognition_plan_assessment", "") or "").strip()
        if not strategy and not assessment:
            return False
        for msg in reversed(self._message_store.get_all_messages()):
            if getattr(msg, "type", None) != MessageType.COGNITION_REASON:
                continue
            existing_strategy = str(getattr(msg, "cognition_plan_strategy", "") or "").strip()
            existing_assessment = str(getattr(msg, "cognition_plan_assessment", "") or "").strip()
            if strategy and strategy == existing_strategy:
                return True
            if assessment and assessment == existing_assessment:
                return True
            break
        return False

    def _register_card_widget_with_adapter(self, widget: Any, card: Any) -> None:
        """Wire card-mounted step widgets into the live tool-routing registry.

        Completed step cards are not re-registered: late display-card mounts
        would otherwise leave stale entries that the stream-end safety net
        mistakes for in-flight work.
        """
        from soothe_sdk.display.transcript_types import MessageType

        from soothe_cli.tui.widgets.messages import CognitionStepMessage

        adapter = getattr(self, "_ui_adapter", None)
        if adapter is None or not isinstance(widget, CognitionStepMessage):
            return
        status = str(getattr(widget, "_status", "") or "")
        if status in ("success", "error"):
            return
        step_id = ""
        if getattr(card, "type", None) == MessageType.STEP_PROGRESS:
            step_id = str(getattr(card, "step_progress_id", "") or "").strip()
        if not step_id:
            step_id = str(getattr(widget, "_step_id", "") or "").strip()
        if not step_id:
            return
        adapter._current_step_messages[step_id] = widget

    @staticmethod
    def _dedupe_message_data_by_id(messages: list[Any]) -> list[Any]:
        """Return messages in order, keeping the last entry per ``MessageData.id``."""
        seen: set[str] = set()
        deduped_reversed: list[Any] = []
        for msg in reversed(messages):
            msg_id = getattr(msg, "id", None)
            if not isinstance(msg_id, str) or not msg_id:
                deduped_reversed.append(msg)
                continue
            if msg_id in seen:
                continue
            seen.add(msg_id)
            deduped_reversed.append(msg)
        deduped_reversed.reverse()
        return deduped_reversed

    async def _mount_message(
        self,
        widget: Static
        | AssistantMessage
        | SkillMessage
        | CognitionStepMessage
        | CognitionReasonMessage
        | CognitionGoalTreeMessage
        | FileChangePreviewWidget
        | DiffMessage
        | SummarizationMessage
        | ErrorMessage
        | AppMessage,
    ) -> None:
        """Mount a message widget to the messages area.

        This method also stores the message data and handles pruning
        when the widget count exceeds the maximum.

        If the ``#messages`` container is not present (e.g. the screen has
        been torn down during an interruption), the call is silently skipped
        to avoid cascading `NoMatches` errors.

        Args:
            widget: The message widget to mount
        """
        try:
            messages = self.query_one("#messages", Container)
        except NoMatches:
            return

        # During shutdown (e.g. Ctrl+D mid-stream) the container may still
        # be in the DOM tree but already detached, so mount() would raise
        # MountError. Bail out silently — the app is exiting anyway.
        if not messages.is_attached:
            return

        # Store message data for virtualization
        from soothe_cli.tui.binding import message_from_widget

        message_data = message_from_widget(widget)
        # Ensure the widget's DOM id matches the store id so that
        # features like click-to-show-timestamp can look it up.
        if not widget.id:
            widget.id = message_data.id
        self._message_store.append(message_data)

        # Queued-message widgets must always stay at the bottom so they
        # remain visually anchored below the current agent response.
        if isinstance(widget, QueuedUserMessage):
            await messages.mount(widget)
        else:
            await self._mount_before_queued(messages, widget)

        # Prune old widgets if window exceeded
        await self._prune_old_messages()

        # Keep the transcript pinned to the latest message. Do NOT call
        # scroll_visible() on #bottom-app-container / ChatInput — that scrolls
        # the Screen and clips the thinking row above the docked input chrome.
        try:
            self.query_one("#chat", VerticalScroll).anchor()
        except NoMatches:
            pass

        from soothe_cli.tui.widgets.messages.clarification import ClarificationInputMessage

        if isinstance(widget, ClarificationInputMessage):
            self.focus_primary_input()

    async def _prune_old_messages(self) -> None:
        """Prune oldest message widgets if we exceed the window size.

        This removes widgets from the DOM but keeps data in MessageStore
        for potential re-hydration when scrolling up.
        """
        if not self._message_store.window_exceeded():
            return

        try:
            messages_container = self.query_one("#messages", Container)
        except NoMatches:
            logger.debug("Skipping pruning: #messages container not found")
            return

        to_prune = self._message_store.get_messages_to_prune()
        if not to_prune:
            return

        pruned_ids: list[str] = []
        for msg_data in to_prune:
            try:
                widget = messages_container.query_one(f"#{msg_data.id}")
                # Capture measured row height before pruning so hydration can
                # restore scroll position with less jump.
                widget_height = getattr(getattr(widget, "size", None), "height", 0)
                if isinstance(widget_height, int) and widget_height > 0:
                    self._message_store.update_message(
                        msg_data.id,
                        height_hint=widget_height,
                    )
                await widget.remove()
                pruned_ids.append(msg_data.id)
            except NoMatches:
                # Widget not found -- do NOT mark as pruned to avoid
                # desyncing the store from the actual DOM state
                logger.debug(
                    "Widget %s not found during pruning, skipping",
                    msg_data.id,
                )

        if pruned_ids:
            self._message_store.mark_pruned(pruned_ids)

    def _set_active_message(self, message_id: str | None) -> None:
        """Set the active streaming message (won't be pruned).

        Args:
            message_id: The ID of the active message, or None to clear.
        """
        self._message_store.set_active_message(message_id)

    def _sync_message_content(self, message_id: str, content: str) -> None:
        """Sync final message content back to the store after streaming.

        Called when streaming finishes so the store holds the full text
        instead of the empty string captured at mount time.

        Args:
            message_id: The ID of the message to update.
            content: The final content after streaming.
        """
        self._message_store.update_message(
            message_id,
            content=content,
            is_streaming=False,
        )

    async def _clear_messages(self) -> None:
        """Clear the messages area, message store, and live plan/turn UI.

        The plan panel is backed by adapter state outside ``#messages``, so a
        transcript wipe must also drop the live goal tree or /clear leaves a
        stale Orchestrate panel.
        """
        self._loop_history_loaded_for = None
        # Clear the message store first
        self._message_store.clear()
        self._deferred_assistant_renders.clear()
        self._assistant_render_drain_scheduled = False
        try:
            messages = self.query_one("#messages", Container)
            await messages.remove_children()
        except NoMatches:
            logger.warning(
                "Messages container (#messages) not found during clear; UI may be out of sync with message store"
            )

        adapter = getattr(self, "_ui_adapter", None)
        if adapter is not None:
            adapter.clear_live_session_ui()

        overlay = self._get_plan_quick_view_overlay()
        if overlay is not None:
            overlay.refresh_content()

        await self._set_spinner(None)

    def _pop_last_queued_entry(self) -> Any | None:
        """Pop the latest queued message and paired widget, if available."""
        if not self._pending_messages:
            return None
        msg = self._pending_messages.pop()
        if self._queued_widgets:
            widget = self._queued_widgets.pop()
            widget.remove()
            self._refresh_queued_goal_tips()
        else:
            logger.warning(
                "Queued-widget deque empty while pending-messages was not; widget/message tracking may be out of sync"
            )
        return msg

    def _restore_last_queued_goal_to_input(self) -> bool:
        """Restore the latest queued goal into an empty chat input for editing."""
        msg = self._pop_last_queued_entry()
        if msg is None:
            return False

        if not self._chat_input:
            logger.warning(
                "Chat input unavailable during queue pop; message text cannot be restored: %s",
                msg.text[:60],
            )
            return False

        if self._has_pending_chat_input():
            logger.warning(
                "Queue restore requested while input has draft content; skipping restore"
            )
            return False
        self._chat_input.value = msg.text
        self.notify("Queued goal moved to input", timeout=2)
        return True

    def _discard_queue(self) -> None:
        """Clear pending messages, deferred actions, and queued widgets."""
        self._pending_messages.clear()
        for w in self._queued_widgets:
            w.remove()
        self._queued_widgets.clear()
        self._deferred_actions.clear()

    def _cancel_last_queued_message(self) -> bool:
        """Cancel the most recently queued goal without restoring it to input."""
        msg = self._pop_last_queued_entry()
        if msg is None:
            return False
        self.notify(f"Cancelled queued goal: {msg.text[:60]}", timeout=2)
        return True

    def edit_queued_goal_from_up(self) -> bool:
        """Move the latest queued goal back to input for editing."""
        if not self._pending_messages:
            return False
        if self._has_pending_chat_input():
            return False
        queue_tail = self._pending_messages[-1]
        if queue_tail.mode != "normal":
            return False
        return self._restore_last_queued_goal_to_input()

    def _defer_action(self, action: DeferredAction) -> None:
        """Queue a deferred action, replacing any existing action of the same kind.

        Last-write-wins: if the user selects a model twice while busy, only the
        final selection runs.

        Args:
            action: The deferred action to queue.
        """
        self._deferred_actions = [a for a in self._deferred_actions if a.kind != action.kind]
        self._deferred_actions.append(action)

    async def _maybe_drain_deferred(self) -> None:
        """Drain deferred actions unless a server connection is still in progress."""
        if not self._connecting:
            await self._drain_deferred_actions()

    async def _drain_deferred_actions(self) -> None:
        """Execute deferred actions queued while busy (e.g. model or loop switch)."""
        while self._deferred_actions:
            action = self._deferred_actions.pop(0)
            try:
                await action.execute()
            except Exception:
                logger.exception(
                    "Failed to execute deferred action %r (callable=%r)",
                    action.kind,
                    action.execute,
                )
                label = action.kind.replace("_", " ")
                with suppress(Exception):
                    await self._mount_message(
                        ErrorMessage(
                            f"Deferred {label} failed unexpectedly. You may need to retry the operation."
                        )
                    )

    _INTERRUPT_UI_MESSAGE = "Stream cancelled"

    async def _tear_down_interrupt_ui(self, message: str | None = None) -> None:
        """Immediately stop in-flight step/goal UI when the user interrupts a turn.

        Daemon cancel and worker teardown can take several seconds; without an
        eager UI pass the thinking spinner stays live after interrupt.
        """
        label = message or self._INTERRUPT_UI_MESSAGE
        adapter = getattr(self, "_ui_adapter", None)
        if adapter is not None:
            if adapter._tool_to_step or adapter._tool_display_by_call_id:
                adapter.finalize_pending_tools_with_error(label)
            if adapter._current_step_messages or adapter._goal_tree_message is not None:
                adapter.finalize_pending_steps_with_error(label)
        await self._set_spinner(None)

    def _cancel_worker(self, worker: Worker[None] | None, *, discard_queue: bool = True) -> None:
        """Cancel an active worker, optionally discarding the pending message queue.

        Args:
            worker: The worker to cancel.
            discard_queue: When ``True`` (default), clear queued messages and
                deferred actions. Set ``False`` on user interrupt (Ctrl+C)
                so a queued goal starts after the running one is cancelled.
        """
        if discard_queue:
            self._discard_queue()
        if worker is not None:
            worker.cancel()

    async def _interrupt_daemon_agent_turn(self, *, discard_queue: bool = True) -> None:
        """Stop in-flight UI and request daemon-side cancel.

        UI teardown runs first so Ctrl+C does not leave the thinking spinner
        active while the daemon winds down (which can take several seconds on
        long execute steps).

        Args:
            discard_queue: When ``False``, preserve queued user goals so they
                run after the cancelled turn finishes cleanup. In this mode,
                the local worker is left running when daemon cancel succeeds.
        """
        await self._tear_down_interrupt_ui()
        session = self._daemon_session
        worker = self._agent_worker
        cancel_sent = False
        if session is not None:
            try:
                await session.cancel_remote_query()
                cancel_sent = True
            except Exception:
                logger.warning("Failed to send cancel to daemon", exc_info=True)
        # For Enter-triggered queued-goal handoff (discard_queue=False), avoid
        # force-cancelling the local worker after /cancel is accepted.
        # Let the active stream finish naturally so queue-drain ordering stays
        # stable and the loop subscription is not torn down mid-handoff.
        if worker is not None and (discard_queue or not cancel_sent):
            self._cancel_worker(worker, discard_queue=discard_queue)

    def action_copy_selection(self) -> None:
        """Copy the current text selection to the system clipboard (Ctrl+Y)."""
        from soothe_cli.tui.widgets.clipboard import copy_selection_to_clipboard

        copy_selection_to_clipboard(self, notify_if_empty=True)

    def action_quit_or_interrupt(self) -> None:
        """Handle Ctrl+C - clear input or interrupt running work.

        Priority order when task is running (agent/shell):
        1. If input has pending text, clear it (first Ctrl+C)
        2. If input is empty, interrupt the running task

        When idle, Ctrl+C never exits the TUI. Type `exit`, `quit`, or `/quit` to exit.

        Note: Copying selected text is bound to Ctrl+Y (`action_copy_selection`)
        so Ctrl+C is reserved for interrupt behavior.
        """
        # Check if input has pending content (text, mode, or completion)
        has_pending_input = self._has_pending_chat_input()

        # If shell command is running: clear input first, then kill shell
        if self._shell_running and self._shell_worker:
            if has_pending_input:
                self._chat_input.clear_input()
                return
            self._cancel_worker(self._shell_worker, discard_queue=False)
            return

        # If agent is running: clear input first, then interrupt
        if self._agent_running and self._agent_worker:
            if has_pending_input:
                self._chat_input.clear_input()
                return
            self._interrupt_running_goal_preserving_queue()
            return

        # Idle path: clear any pending draft, but never quit via keyboard shortcut.
        if self._chat_input:
            self._chat_input.clear_input()
        self.notify("Type exit, quit, or /quit to exit the TUI", timeout=2, markup=False)

    def _get_plan_quick_view_overlay(self) -> Any:
        """Return the cached plan panel, querying the widget tree on first use."""
        overlay = getattr(self, "_plan_quick_view_overlay", None)
        if overlay is not None:
            return overlay
        with suppress(Exception):
            from soothe_cli.tui.widgets.plan_quick_view_overlay import PlanQuickViewOverlay

            overlay = self.query_one("#plan-quick-view-overlay", PlanQuickViewOverlay)
            self._plan_quick_view_overlay = overlay
        return overlay

    def action_dismiss_ui(self) -> None:
        """Handle Escape — dismiss overlays and optionally cancel queued goals.

        Priority order:
        1. If modal screen is active, dismiss it
        2. If plan panel is open, collapse it
        3. If input is idle and queue has a normal goal, cancel queued tail
        4. If completion popup is open, dismiss it
        5. If input is in command/shell mode, exit to normal mode
        """
        # If a modal screen is active, let it cancel itself (so it can
        # restore state, e.g. the theme selector reverts the previewed theme).
        # Fall back to a plain dismiss for modals without action_cancel.
        if self.screen.is_modal:
            cancel = getattr(self.screen, "action_cancel", None)
            if cancel is not None:
                cancel()
            else:
                self.screen.dismiss(None)
            return

        overlay = self._get_plan_quick_view_overlay()
        if overlay is not None and overlay.is_expanded:
            overlay.collapse(forget_preference=True)
            return

        # Close completion popup or exit slash/shell command mode
        if self._chat_input:
            # When queue has pending goals and input is idle, Esc cancels the
            # latest queued normal goal (without interrupting current work).
            if not self._has_pending_chat_input():
                queue_tail = self._pending_messages[-1] if self._pending_messages else None
                if queue_tail is not None and queue_tail.mode == "normal":
                    if self._cancel_last_queued_message():
                        return
            if self._chat_input.dismiss_completion():
                return
            if self._chat_input.exit_mode():
                return

    def action_quit_app(self) -> None:
        """Handle Ctrl+D by hinting explicit exit words or slash quit."""
        self.notify("Type exit, quit, or /quit to exit the TUI", timeout=2, markup=False)

    async def _detach_then_exit(self) -> None:
        """Detach from daemon, then exit the app."""
        if self._detaching:
            return
        self._detaching = True
        try:
            if self._daemon_session is not None:
                from soothe_cli.runtime.transport.session import TUI_EXIT_HANDSHAKE_TIMEOUT_S

                try:
                    await self._daemon_session.detach()
                except ConnectionError:
                    logger.debug("Daemon connection closed before detach during exit")
                await self._daemon_session.close(
                    handshake_timeout=TUI_EXIT_HANDSHAKE_TIMEOUT_S,
                )
            self.exit()
        finally:
            self._detaching = False

    def _detach_or_exit(self) -> None:
        """Gracefully detach from the daemon when connected, then exit."""
        if self._daemon_session is None:
            self.exit()
            return
        self._prepare_shutdown()
        self.notify("Detaching from daemon...", severity="info")
        self.run_worker(self._detach_then_exit(), exclusive=False, group="daemon-detach")

    def _prepare_shutdown(self) -> None:
        """One-shot pre-exit cleanup: flag workers, merge stats, cancel tasks."""
        if self._shutdown_prepared:
            return
        self._shutdown_prepared = True
        # Set before cancelling workers so interrupt cleanup can skip slow RPC.
        self._exit = True

        inflight = self._inflight_turn_stats
        if inflight is not None:
            self._inflight_turn_stats = None
            if not inflight.wall_time_seconds:
                inflight.wall_time_seconds = time.monotonic() - self._inflight_turn_start
            self._session_stats.merge(inflight)

        self._discard_queue()

        if self._shell_running and self._shell_worker:
            self._shell_worker.cancel()
        if self._agent_running and self._agent_worker:
            self._agent_worker.cancel()

    def exit(
        self,
        result: Any = None,  # noqa: ANN401  # Dynamic LangGraph stream result type
        return_code: int = 0,
        message: Any = None,  # noqa: ANN401  # Dynamic LangGraph message type
    ) -> None:
        """Exit the app, restoring iTerm2 cursor guide if applicable.

        Overrides parent to restore iTerm2's cursor guide before Textual's
        cleanup. The atexit handler serves as a fallback for abnormal
        termination.

        Args:
            result: Return value passed to the app runner.
            return_code: Exit code (non-zero for errors).
            message: Optional message to display on exit.
        """
        self._prepare_shutdown()
        _write_iterm_escape(_ITERM_CURSOR_GUIDE_ON)
        App.exit(self, result=result, return_code=return_code, message=message)

    def action_shift_tab(self) -> None:
        """Shift+Tab: navigate loop selector when active, otherwise flip relay mode.

        - In the LoopSelectorScreen, defer to its filter navigation.
        - On the main screen, toggle the clarification relay mode
          (Auto ↔ Manual) so users can switch between the veritas
          auto-answerer and human-in-the-loop relay at any point (RFC-622).
        """
        from soothe_cli.tui.widgets.loop_selector import LoopSelectorScreen

        if isinstance(self.screen, LoopSelectorScreen):
            self.screen.action_focus_previous_filter()
            return
        self.toggle_clarification_mode()

    def toggle_clarification_mode(self) -> None:
        """Flip clarification mode between Auto and Manual and refresh the badge.

        The new mode is held on the app (``self._clarification_mode``) and
        attached to every subsequent ``send_turn`` via the
        ``clarification_mode`` field of the daemon's ``loop_input`` payload
        (RFC-622). The status-bar badge updates immediately; no toast is
        emitted because the badge itself is the visual feedback.
        """
        current = getattr(self, "_clarification_mode", "auto")
        new_mode = "manual" if current == "auto" else "auto"
        self._clarification_mode = new_mode
        if self._status_bar is not None:
            self._status_bar.set_clarification_mode(new_mode)

    def action_toggle_tool_output(self) -> None:
        """Toggle expand/collapse of the most recent skill or tool card."""
        # Try skill messages first (most recent collapsible content)
        with suppress(NoMatches):
            skill_messages = list(self.query(SkillMessage))
            for skill_msg in reversed(skill_messages):
                if skill_msg._stripped_body.strip():
                    skill_msg.toggle_body()
                    return

    def _active_clarification_inputs(self) -> list[Input]:
        """Return enabled clarification answer fields awaiting user input."""
        adapter = getattr(self, "_ui_adapter", None)
        if adapter is None:
            return []
        by_step = getattr(adapter, "_clarification_input_by_step", None) or {}
        inputs: list[Input] = []
        for message in by_step.values():
            if getattr(message, "_submitted", False):
                continue
            for inp in getattr(message, "_inputs", []):
                if inp.disabled:
                    continue
                if _widget_is_hidden(inp):
                    continue
                inputs.append(inp)
        return inputs

    def _active_plan_review_action_focus(self) -> Widget | None:
        """Prefer the Approve button when a planner-review card has no comments yet."""
        adapter = getattr(self, "_ui_adapter", None)
        if adapter is None:
            return None
        by_step = getattr(adapter, "_clarification_input_by_step", None) or {}
        for message in by_step.values():
            if getattr(message, "_submitted", False):
                continue
            # String compare — avoid MagicMock truthiness on property access in tests.
            if getattr(message, "_origin_node", None) != "planner_subagent_review":
                continue
            buttons = getattr(message, "_action_buttons", None) or {}
            if not isinstance(buttons, dict):
                continue
            approve = buttons.get("approve")
            if approve is not None and not getattr(approve, "disabled", False):
                return approve
        return None

    def _non_chat_focusable_inputs(self) -> list[Input]:
        """Return enabled, focusable ``Input`` widgets other than the chat prompt."""
        from textual.widgets import Input

        return [
            widget
            for widget in self.screen.query(Input)
            if widget.can_focus and not widget.disabled and not _widget_is_hidden(widget)
        ]

    def _primary_text_input(self) -> Widget | None:
        """Return the single input that should receive typing focus, if unambiguous.

        When an inline clarification card is active, its answer field takes
        precedence over the bottom chat prompt. Planner-subagent review with no
        comments field yet focuses the Approve action. On modal screens, a lone
        filter box is focused automatically.
        """
        clar_inputs = self._active_clarification_inputs()
        if clar_inputs:
            return clar_inputs[0]

        plan_action = self._active_plan_review_action_focus()
        if plan_action is not None:
            return plan_action

        non_chat = self._non_chat_focusable_inputs()
        if len(non_chat) == 1:
            return non_chat[0]

        return None

    def _schedule_widget_focus(self, widget: Widget) -> None:
        """Focus ``widget`` after layout settles, winning races with chat refocus."""

        def _focus() -> None:
            try:
                self.set_focus(widget)
            except Exception:  # noqa: BLE001
                try:
                    widget.focus()
                except Exception:  # noqa: BLE001
                    logger.debug("Failed to focus primary input widget", exc_info=True)

        self.call_after_refresh(_focus)
        with suppress(Exception):
            self.set_timer(0.05, _focus)

    def focus_primary_input(self) -> None:
        """Focus the user's primary text input when it is unambiguous."""
        target = self._primary_text_input()
        if target is not None:
            self._schedule_widget_focus(target)
            return
        if self._chat_input and not self.screen.is_modal:
            self._chat_input.focus_input()

    def _is_input_focused(self) -> bool:
        """Check if a primary text input widget currently has focus.

        Returns:
            True if chat input or an inline clarification field has focus.
        """
        focused = self.focused
        if focused is None:
            return False

        clar_inputs = self._active_clarification_inputs()
        if clar_inputs:
            for inp in clar_inputs:
                if focused is inp or focused in inp.walk_children(with_self=True):
                    return True

        if not self._chat_input:
            return False
        # Check if focused widget is the text area inside chat input
        return focused.id == "chat-input" or focused in self._chat_input.walk_children()

    async def action_open_editor(self) -> None:
        """Open the current prompt text in an external editor ($VISUAL/$EDITOR)."""
        from soothe_cli.tui.widgets.editor import open_in_editor

        chat_input = self._chat_input
        if not chat_input or not chat_input._text_area:
            return

        current_text = chat_input._text_area.text or ""

        edited: str | None = None
        try:
            with self.suspend():
                edited = open_in_editor(current_text)
        except Exception:
            logger.warning("External editor failed", exc_info=True)
            self.notify(
                "External editor failed. Check $VISUAL/$EDITOR.",
                severity="error",
                timeout=5,
            )
            chat_input.focus_input()
            return

        if edited is not None:
            chat_input._text_area.text = edited
            lines = edited.split("\n")
            chat_input._text_area.move_cursor((len(lines) - 1, len(lines[-1])))
        chat_input.focus_input()

    def on_paste(self, event: Paste) -> None:
        """Route unfocused paste events to chat input for drag/drop reliability."""
        if not self._chat_input:
            return
        if self._is_input_focused():
            return
        if self._chat_input.handle_external_paste(event.text):
            event.prevent_default()
            event.stop()

    def on_app_focus(self) -> None:
        """Restore primary input focus when the terminal regains OS focus.

        When the user opens a link via `webbrowser.open`, OS focus shifts to
        the browser. On returning to the terminal, Textual fires `AppFocus`
        (requires a terminal that supports FocusIn events). Re-focusing the
        primary input keeps it ready for typing — but only when no other
        focusable widget (e.g., a step card control) currently owns focus, so
        the user does not lose an in-progress answer to a tab-out and back.
        """
        if self.screen.is_modal:
            return
        focused = self.focused
        primary = self._primary_text_input()
        if primary is not None:
            if focused is primary or focused in primary.walk_children(with_self=True):
                return
            self.focus_primary_input()
            return
        if not self._chat_input:
            return
        if focused is not None and not self._is_input_focused():
            return
        self._chat_input.focus_input()

    def on_click(self, _event: Click) -> None:
        """Focus the chat input when the click landed on non-focusable chrome.

        Original intent: clicking the dead transcript area should drop the
        caret back in the prompt. But this handler bubbles for *every* click,
        so an unconditional refocus also steals focus from inline focusable
        widgets (e.g., the ClarificationInputMessage answer field) on the same
        click that Textual just used to focus them. Skip the refocus whenever
        the click landed on a focusable widget — Textual's default focus
        handling already does the right thing there.
        """
        if not self._chat_input:
            return
        # Preserve an active text selection (focus would clear highlight for copy).
        from soothe_cli.tui.widgets.clipboard import screen_has_text_selection

        if screen_has_text_selection(self.screen):
            return
        if self._click_landed_on_focusable(_event):
            return
        self.call_after_refresh(self.focus_primary_input)

    def _click_landed_on_focusable(self, event: Click) -> bool:
        """Return True if the click target (or any ancestor) is focusable.

        Walks up from `event.widget` toward the screen. Stops at the screen
        so non-focusable container chrome (Containers, Statics) does not
        suppress the dead-area refocus behavior.
        """
        widget = getattr(event, "widget", None)
        if widget is None:
            return False
        node: Any = widget
        screen = self.screen
        while node is not None and node is not screen:
            try:
                if getattr(node, "can_focus", False):
                    return True
            except Exception:  # noqa: BLE001
                pass
            node = getattr(node, "parent", None)
        return False

    def on_text_selected(self, _event: TextSelected) -> None:
        """Copy selected transcript text on mouse release.

        Must run synchronously here: ``TextSelected`` is posted before the
        synthesized ``Click``, but ``call_after_refresh`` would run after card
        collapse handlers clear the selection.
        """
        from soothe_cli.tui.widgets.clipboard import (
            copy_selection_to_clipboard,
            screen_has_text_selection,
        )

        if not screen_has_text_selection(self.screen):
            return
        copy_selection_to_clipboard(self)

    # =========================================================================
    # Model Switching
    # =========================================================================
