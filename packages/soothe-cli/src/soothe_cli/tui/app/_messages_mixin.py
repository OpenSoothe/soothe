"""Message widget lifecycle, store management, queue management, interrupt/quit, toggles, editor, and mouse/focus events mixin."""

from __future__ import annotations

import logging
import time
from contextlib import suppress
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from textual.containers import Container
    from textual.events import Click, Paste, TextSelected
    from textual.widgets import Static
    from textual.worker import Worker

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


class _MessagesMixin:
    """Message widget lifecycle, store management, queue, interrupt/quit, toggles, editor, and events."""

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

        try:
            # Fetch + convert, or reuse preloaded payload on loop switch.
            payload = (
                preloaded_payload
                if preloaded_payload is not None
                else await self._fetch_loop_history_data(history_loop_id)
            )
            if not payload.messages:
                return

            # Seed token cache from persisted state
            if payload.context_tokens > 0:
                self._on_tokens_update(payload.context_tokens)

            # 3. Bulk load into store (sets visible window)
            _archived, visible = self._message_store.bulk_load(payload.messages)

            # 5. Cache container ref (single query)
            try:
                messages_container = self.query_one("#messages", Container)
            except NoMatches:
                return

            # 6-7. Create and mount only visible widgets (max WINDOW_SIZE)
            from soothe_cli.tui.binding import message_to_widget

            widgets = [message_to_widget(msg_data) for msg_data in visible]
            if widgets:
                await messages_container.mount(*widgets)

            # 8. Render assistant markdown progressively to avoid startup stalls
            for widget, msg_data in zip(widgets, visible, strict=False):
                if isinstance(widget, AssistantMessage) and msg_data.content:
                    self._enqueue_hydrated_assistant_render(widget, msg_data.content)

            # 9. Add footer immediately and resolve link asynchronously
            loop_msg_widget = AppMessage(f"Resumed loop: {history_loop_id}")
            await self._mount_message(loop_msg_widget)
            self._schedule_loop_message_link(
                loop_msg_widget,
                prefix="Resumed loop",
                loop_id=history_loop_id,
            )

            # 10. Scroll once to bottom after history loads
            def scroll_to_end() -> None:
                with suppress(NoMatches):
                    chat = self.query_one("#chat", VerticalScroll)
                    chat.scroll_end(animate=False, immediate=True)

            self.set_timer(0.1, scroll_to_end)

        except Exception as e:  # Resilient history loading
            logger.exception(
                "Failed to load conversation history for %s",
                history_loop_id,
            )
            await self._mount_message(AppMessage(f"Could not load history: {e}"))

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

        # Scroll to keep input bar visible
        try:
            input_container = self.query_one("#bottom-app-container", Container)
            input_container.scroll_visible()
        except NoMatches:
            pass

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
        """Clear the messages area and message store."""
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

    def _pop_last_queued_message(self) -> None:
        """Remove the most recently queued message (LIFO).

        If the chat input is empty the evicted text is restored there so the
        user can edit and re-submit. Otherwise the message is discarded. The
        toast message distinguishes between the two outcomes.

        Caller must ensure `_pending_messages` is non-empty. A defensive guard
        is included in case of async TOCTOU races.
        """
        if not self._pending_messages:
            return
        msg = self._pending_messages.pop()
        if self._queued_widgets:
            widget = self._queued_widgets.pop()
            widget.remove()
        else:
            logger.warning(
                "Queued-widget deque empty while pending-messages was not; widget/message tracking may be out of sync"
            )

        if not self._chat_input:
            logger.warning(
                "Chat input unavailable during queue pop; message text cannot be restored: %s",
                msg.text[:60],
            )
            self.notify("Queued message discarded", timeout=2)
            return

        if not self._chat_input.value.strip():
            self._chat_input.value = msg.text
            self.notify("Queued message moved to input", timeout=2)
        else:
            self.notify("Queued message discarded (input not empty)", timeout=3)

    def _discard_queue(self) -> None:
        """Clear pending messages, deferred actions, and queued widgets."""
        self._pending_messages.clear()
        for w in self._queued_widgets:
            w.remove()
        self._queued_widgets.clear()
        self._deferred_actions.clear()

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

    def _cancel_worker(self, worker: Worker[None] | None) -> None:
        """Discard the message queue and cancel an active worker.

        Args:
            worker: The worker to cancel.
        """
        self._discard_queue()
        if worker is not None:
            worker.cancel()

    async def _interrupt_daemon_agent_turn(self) -> None:
        """Send daemon ``/cancel``, then cancel the local streaming worker.

        Awaiting cancel first stops the server-side query; cancelling the worker
        alone would only detach the TUI from chunks while the daemon kept running.
        """
        session = self._daemon_session
        worker = self._agent_worker
        if session is not None:
            try:
                await session.cancel_remote_query()
            except Exception:
                logger.warning("Failed to send cancel to daemon", exc_info=True)
        if worker is not None:
            self._cancel_worker(worker)

    def action_copy_selection(self) -> None:
        """Copy the current text selection to the system clipboard (Ctrl+Y)."""
        from soothe_cli.tui.widgets.clipboard import copy_selection_to_clipboard

        copy_selection_to_clipboard(self, notify_if_empty=True)

    def action_quit_or_interrupt(self) -> None:
        """Handle Ctrl+C - interrupt agent or quit on double press.

        Priority order:
        1. If shell command is running, kill it
        2. If agent is running, interrupt it (preserve input)
        3. If double press (quit_pending), quit
        4. Otherwise clear draft input and show quit hint

        Note: Copying selected text is bound to Ctrl+Y (`action_copy_selection`)
        so Ctrl+C is reserved for interrupt/quit only.
        """
        # If shell command is running, cancel the worker
        if self._shell_running and self._shell_worker:
            self._cancel_worker(self._shell_worker)
            self._quit_pending = False
            return

        # If agent is running, interrupt it and discard queued messages
        if self._agent_running and self._agent_worker:
            if self._daemon_session is not None:
                self.run_worker(
                    self._interrupt_daemon_agent_turn(),
                    exclusive=False,
                    group="daemon-interrupt",
                )
            else:
                self._cancel_worker(self._agent_worker)
            self._quit_pending = False
            return

        # Double Ctrl+C to quit
        if self._quit_pending:
            self.exit()
        else:
            self._arm_quit_pending("Ctrl+C")

    def _arm_quit_pending(self, shortcut: str) -> None:
        """Set the pending-quit flag, clear draft input, and show a matching hint.

        Args:
            shortcut: The key chord to show in the quit hint.
        """
        if self._chat_input:
            self._chat_input.clear_input()
        self._quit_pending = True
        quit_timeout = 3
        self.notify(f"Press {shortcut} again to quit", timeout=quit_timeout, markup=False)
        self.set_timer(quit_timeout, lambda: setattr(self, "_quit_pending", False))

    def action_interrupt(self) -> None:
        """Handle escape key.

        Priority order:
        1. If modal screen is active, dismiss it
        2. If completion popup is open, dismiss it
        3. If input is in command/shell mode, exit to normal mode
        4. If shell command is running, kill it
        5. If queued messages exist, pop the last one (LIFO)
        6. If agent is running, interrupt it
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

        # Close completion popup or exit slash/shell command mode
        if self._chat_input:
            if self._chat_input.dismiss_completion():
                return
            if self._chat_input.exit_mode():
                return

        # If shell command is running, cancel the worker
        if self._shell_running and self._shell_worker:
            self._cancel_worker(self._shell_worker)
            return

        # If queued messages exist, pop the last one (LIFO) instead of
        # interrupting the agent.  This lets the user retract queued messages
        # one at a time; once the queue is empty the next ESC will interrupt.
        if self._pending_messages:
            self._pop_last_queued_message()
            return

        # If agent is running, interrupt it and discard queued messages
        if self._agent_running and self._agent_worker:
            if self._daemon_session is not None:
                self.run_worker(
                    self._interrupt_daemon_agent_turn(),
                    exclusive=False,
                    group="daemon-interrupt",
                )
            else:
                self._cancel_worker(self._agent_worker)
            return

    def action_quit_app(self) -> None:
        """Handle quit action (Ctrl+D)."""
        from soothe_cli.tui.widgets.loop_selector import LoopSelectorScreen

        if isinstance(self.screen, LoopSelectorScreen):
            # Loop selector doesn't have delete confirmation - just detach
            self._detach_or_exit()
            return
        self._detach_or_exit()

    async def _detach_then_exit(self) -> None:
        """Detach from daemon, then exit the app."""
        if self._detaching:
            return
        self._detaching = True
        try:
            if self._daemon_session is not None:
                await self._daemon_session.detach()
                await self._daemon_session.close()
            self.exit()
        finally:
            self._detaching = False

    def _detach_or_exit(self) -> None:
        """Exit immediately, or detach first when daemon-backed."""
        if self._daemon_session is None:
            self.exit()
            return
        self.notify("Detaching from daemon...", severity="info")
        self.run_worker(self._detach_then_exit(), exclusive=False, group="daemon-detach")

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
        # Merge in-flight turn stats before any cleanup that might raise.
        # When the agent worker is cancelled (e.g. Ctrl+D during a pending tool
        # call), the worker's finally block will see _inflight_turn_stats is
        # already None and skip the merge.
        inflight = self._inflight_turn_stats
        if inflight is not None:
            self._inflight_turn_stats = None
            if not inflight.wall_time_seconds:
                inflight.wall_time_seconds = time.monotonic() - self._inflight_turn_start
            self._session_stats.merge(inflight)

        # Discard queued messages so _cleanup_agent_task won't try to
        # process them after the event loop is torn down, and cancel
        # active workers so their subprocesses are terminated
        # (SIGTERM → SIGKILL) instead of being orphaned.
        self._discard_queue()

        if self._shell_running and self._shell_worker:
            self._shell_worker.cancel()
        if self._agent_running and self._agent_worker:
            self._agent_worker.cancel()

        _write_iterm_escape(_ITERM_CURSOR_GUIDE_ON)
        super().exit(result=result, return_code=return_code, message=message)

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

    def _is_input_focused(self) -> bool:
        """Check if the chat input (or its text area) has focus.

        Returns:
            True if the input widget has focus, False otherwise.
        """
        if not self._chat_input:
            return False
        focused = self.focused
        if focused is None:
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
        """Restore chat input focus when the terminal regains OS focus.

        When the user opens a link via `webbrowser.open`, OS focus shifts to
        the browser. On returning to the terminal, Textual fires `AppFocus`
        (requires a terminal that supports FocusIn events). Re-focusing the chat
        input here keeps it ready for typing — but only when no other focusable
        widget (e.g., an inline clarification Input) currently owns focus, so
        the user does not lose an in-progress answer to a tab-out and back.
        """
        if not self._chat_input:
            return
        if self.screen.is_modal:
            return
        focused = self.focused
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
        self.call_after_refresh(self._chat_input.focus_input)

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
    # SOOTHE: Slash command actions

    def action_detach(self) -> None:
        """Exit TUI but leave daemon running."""
        self._detach_or_exit()
