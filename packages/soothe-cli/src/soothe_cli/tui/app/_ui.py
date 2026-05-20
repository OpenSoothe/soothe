"""UI interaction mixin: status bar, tokens, scroll hydration, spinner, ask_user, interrupt/quit."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from textual.containers import Container
    from textual.widget import Widget
    from textual.widgets._scrollbar import ScrollUp

    from soothe_cli.tui._ask_user_types import AskUserWidgetResult, Question
    from soothe_cli.tui.widgets.ask_user import AskUserMenu

from textual.containers import Container, VerticalScroll
from textual.css.query import NoMatches

from soothe_cli.runtime.state.session_stats import SpinnerStatus
from soothe_cli.tui.widgets.loading import LoadingWidget
from soothe_cli.tui.widgets.messages import AssistantMessage

logger = logging.getLogger(__name__)
_monotonic = time.monotonic

_HYDRATION_CHECK_INTERVAL_SECONDS = 0.08
"""Minimum interval between scroll-triggered hydration checks."""


class _UIMixin:
    """UI interaction: status, tokens, hydration, spinner, ask_user, quit/interrupt."""

    def on_scroll_up(self, _event: ScrollUp) -> None:
        """Handle scroll up to check if we need to hydrate older messages."""
        self._check_hydration_needed()

    def _update_status(self, message: str) -> None:
        """Update the status bar with a message."""
        if self._status_bar:
            self._status_bar.set_status_message(message)

    def _update_tokens(self, count: int, *, approximate: bool = False) -> None:
        """Update the token count in the status bar.

        Low-level helper — only touches the UI.  Callers that also need to
        update the local cache should use `_on_tokens_update` instead.

        Args:
            count: Total context token count.
            approximate: Append "+" to signal a stale/interrupted count.
        """
        if self._status_bar:
            self._status_bar.set_tokens(count, approximate=approximate)

    def _on_tokens_update(self, count: int, *, approximate: bool = False) -> None:
        """Update the local cache *and* the status bar.

        This is the callback wired to the adapter's `_on_tokens_update`.

        Args:
            count: Total context token count to cache and display.
            approximate: Append "+" to signal a stale/interrupted count.
        """
        self._context_tokens = count
        self._tokens_approximate = approximate
        self._update_tokens(count, approximate=approximate)

    def _show_tokens(self, *, approximate: bool = False) -> None:
        """Restore the status bar to the cached token value.

        Args:
            approximate: Append "+" to signal a stale/interrupted count.

                This flag is sticky until `_on_tokens_update` receives a fresh
                count from the model.
        """
        self._tokens_approximate = self._tokens_approximate or approximate
        self._update_tokens(
            self._context_tokens,
            approximate=self._tokens_approximate,
        )

    def _hide_tokens(self) -> None:
        """Hide the token display during streaming."""
        if self._status_bar:
            self._status_bar.hide_tokens()

    def _check_hydration_needed(self) -> None:
        """Check if we need to hydrate messages from the store.

        Called when user scrolls up near the top of visible messages.
        """
        if self._hydrate_in_progress or self._hydrate_scheduled:
            return
        now = _monotonic()
        if (now - self._last_hydration_check_mono) < _HYDRATION_CHECK_INTERVAL_SECONDS:
            return
        self._last_hydration_check_mono = now
        if not self._message_store.has_messages_above:
            return

        try:
            chat = self.query_one("#chat", VerticalScroll)
        except NoMatches:
            logger.debug("Skipping hydration check: #chat container not found")
            return

        scroll_y = chat.scroll_y
        viewport_height = chat.size.height

        if self._message_store.should_hydrate_above(scroll_y, viewport_height):
            self._hydrate_scheduled = True
            self.call_later(self._hydrate_messages_above)

    async def _hydrate_messages_above(self) -> None:
        """Hydrate older messages when user scrolls near the top.

        This recreates widgets for archived messages and inserts them
        at the top of the messages container.
        """
        self._hydrate_scheduled = False
        if self._hydrate_in_progress:
            return
        self._hydrate_in_progress = True
        try:
            if not self._message_store.has_messages_above:
                return

            try:
                chat = self.query_one("#chat", VerticalScroll)
            except NoMatches:
                logger.debug("Skipping hydration: #chat not found")
                return

            try:
                messages_container = self.query_one("#messages", Container)
            except NoMatches:
                logger.debug("Skipping hydration: #messages not found")
                return

            to_hydrate = self._message_store.get_messages_to_hydrate()
            if not to_hydrate:
                return

            old_scroll_y = chat.scroll_y
            first_child = messages_container.children[0] if messages_container.children else None

            # Build widgets in chronological order, then mount in reverse so
            # each is inserted before the previous first_child, resulting in
            # correct chronological order in the DOM.
            hydrated_count = 0
            hydrated_widgets: list[tuple[Widget, Any]] = []  # (widget, msg_data)
            for msg_data in to_hydrate:
                try:
                    from soothe_cli.tui.binding import message_to_widget

                    widget = message_to_widget(msg_data)
                    hydrated_widgets.append((widget, msg_data))
                except Exception:
                    logger.warning(
                        "Failed to create widget for message %s",
                        msg_data.id,
                        exc_info=True,
                    )

            assistant_render_tasks: list[Any] = []
            mounted_messages: list[Any] = []
            for widget, msg_data in reversed(hydrated_widgets):
                try:
                    if first_child:
                        await messages_container.mount(widget, before=first_child)
                    else:
                        await messages_container.mount(widget)
                    first_child = widget
                    hydrated_count += 1
                    mounted_messages.append(msg_data)
                    # Render plain text for hydrated assistant messages
                    if isinstance(widget, AssistantMessage) and msg_data.content:
                        assistant_render_tasks.append(widget.set_content(msg_data.content))
                except Exception:
                    logger.warning(
                        "Failed to mount hydrated widget %s",
                        widget.id,
                        exc_info=True,
                    )

            if assistant_render_tasks:
                rendered = await asyncio.gather(*assistant_render_tasks, return_exceptions=True)
                for error in rendered:
                    if isinstance(error, Exception):
                        logger.warning(
                            "Failed to render hydrated assistant message",
                            exc_info=True,
                        )

            # Only update store for the number we actually mounted
            if hydrated_count > 0:
                self._message_store.mark_hydrated(hydrated_count)

            # Adjust scroll position to maintain the user's view.
            # Prefer cached measured heights (captured when pruning), and
            # fall back to a conservative estimate when unavailable.
            estimated_height_per_message = 5  # terminal rows, fallback estimate
            added_height = sum(
                int(msg_data.height_hint or estimated_height_per_message)
                for msg_data in mounted_messages
            )
            chat.scroll_y = old_scroll_y + added_height

            # If the user is still near the top and we still have history above,
            # schedule one more hydration pass (debounced by flags).
            if self._message_store.should_hydrate_above(chat.scroll_y, chat.size.height):
                self._hydrate_scheduled = True
                self.call_later(self._hydrate_messages_above)
        finally:
            self._hydrate_in_progress = False

    async def _mount_before_queued(self, container: Container, widget: Widget) -> None:
        """Mount a widget in the messages container, before any queued widgets.

        Queued-message widgets must stay at the bottom of the container so
        they remain visually anchored below the current agent response.
        This helper inserts `widget` just before the first queued widget,
        or appends at the end when the queue is empty.

        Args:
            container: The `#messages` container to mount into.
            widget: The widget to mount.
        """
        if not container.is_attached:
            return
        first_queued = self._queued_widgets[0] if self._queued_widgets else None
        if first_queued is not None and first_queued.parent is container:
            try:
                await container.mount(widget, before=first_queued)
            except Exception:
                logger.warning(
                    "Stale queued-widget reference; appending at end",
                    exc_info=True,
                )
            else:
                return
        await container.mount(widget)

    def _is_spinner_at_correct_position(self, container: Container) -> bool:
        """Check whether the loading spinner is already correctly positioned.

        The spinner should be immediately before the first queued widget, or
        at the very end of the container when the queue is empty.

        Args:
            container: The `#messages` container.

        Returns:
            `True` if the spinner is already in the correct position.
        """
        children = list(container.children)
        if not children or self._loading_widget not in children:
            return False

        if self._queued_widgets:
            first_queued = self._queued_widgets[0]
            if first_queued not in children:
                return False
            return children.index(self._loading_widget) == (children.index(first_queued) - 1)

        return children[-1] == self._loading_widget

    async def _set_spinner(self, status: SpinnerStatus) -> None:
        """Show, update, or hide the loading spinner.

        Args:
            status: The spinner status to display, or `None` to hide.
        """
        if status is None:
            # Hide
            if self._loading_widget:
                await self._loading_widget.remove()
                self._loading_widget = None
            return

        thinking_status = self.query_one("#thinking-status", Container)

        if self._loading_widget is None:
            # Create new
            turn_mono = self._inflight_turn_start if self._agent_running else None
            self._loading_widget = LoadingWidget(status, turn_start_mono=turn_mono)
            await thinking_status.mount(self._loading_widget)
        else:
            if self._agent_running:
                self._loading_widget.set_turn_start_mono(self._inflight_turn_start)
            # Update existing
            self._loading_widget.set_status(status)
        # NOTE: Don't call anchor() here - it would re-anchor and drag user back
        # to bottom if they've scrolled away during streaming

    async def _remove_ask_user_widget(  # noqa: PLR6301  # Shared helper used by ask_user event handlers
        self,
        widget: AskUserMenu,
        *,
        context: str,
    ) -> None:
        """Remove an ask_user widget without surfacing cleanup races.

        Args:
            widget: Ask-user widget instance to remove.
            context: Short context string for diagnostics.
        """
        try:
            await widget.remove()
        except Exception:
            logger.debug(
                "Failed to remove ask-user widget during %s",
                context,
                exc_info=True,
            )

    async def _request_ask_user(
        self,
        questions: list[Question],
    ) -> asyncio.Future[AskUserWidgetResult]:
        """Display the ask_user widget and return a Future with user response.

        Args:
            questions: List of question dicts, each with `question`, `type`,
                and optional `choices` and `required` keys.

        Returns:
            A Future that resolves to a dict with `'type'` (`'answered'` or
                `'cancelled'`) and, when answered, an `'answers'` list.
        """
        loop = asyncio.get_running_loop()
        result_future: asyncio.Future[AskUserWidgetResult] = loop.create_future()

        if self._pending_ask_user_widget is not None:
            deadline = _monotonic() + 30
            while self._pending_ask_user_widget is not None:
                if _monotonic() > deadline:
                    logger.error(
                        "Timed out waiting for previous ask-user widget to clear. Forcefully cleaning up."
                    )
                    old_widget = self._pending_ask_user_widget
                    if old_widget is not None:
                        old_widget.action_cancel()
                        self._pending_ask_user_widget = None
                        await self._remove_ask_user_widget(
                            old_widget,
                            context="ask-user timeout cleanup",
                        )
                    break
                await asyncio.sleep(0.1)

        from soothe_cli.tui.widgets.ask_user import AskUserMenu

        unique_id = f"ask-user-menu-{uuid.uuid4().hex[:8]}"
        menu = AskUserMenu(questions, id=unique_id)
        menu.set_future(result_future)

        self._pending_ask_user_widget = menu

        try:
            messages = self.query_one("#messages", Container)
            await self._mount_before_queued(messages, menu)
            self.call_after_refresh(menu.scroll_visible)
            self.call_after_refresh(menu.focus_active)
        except Exception as e:
            logger.exception(
                "Failed to mount ask-user menu (id=%s)",
                unique_id,
            )
            self._pending_ask_user_widget = None
            if not result_future.done():
                result_future.set_exception(e)

        return result_future

    async def on_ask_user_menu_answered(
        self,
        event: Any,  # noqa: ARG002, ANN401
    ) -> None:
        """Handle ask_user menu answers - remove widget and refocus input."""
        if self._pending_ask_user_widget:
            widget = self._pending_ask_user_widget
            self._pending_ask_user_widget = None
            await self._remove_ask_user_widget(widget, context="ask-user answered")

        if self._chat_input:
            self.call_after_refresh(self._chat_input.focus_input)

    async def on_ask_user_menu_cancelled(
        self,
        event: Any,  # noqa: ARG002, ANN401
    ) -> None:
        """Handle ask_user menu cancellation - remove widget and refocus input."""
        if self._pending_ask_user_widget:
            widget = self._pending_ask_user_widget
            self._pending_ask_user_widget = None
            await self._remove_ask_user_widget(widget, context="ask-user cancelled")
        if self._chat_input:
            self.call_after_refresh(self._chat_input.focus_input)
