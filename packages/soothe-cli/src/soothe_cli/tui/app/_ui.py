"""UI interaction mixin: status bar, tokens, scroll hydration, spinner, approval, ask_user, interrupt/quit."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from contextlib import suppress
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from textual.containers import Container
    from textual.widget import Widget
    from textual.widgets._scrollbar import ScrollUp

    from soothe_cli.tui._ask_user_types import AskUserWidgetResult, Question
    from soothe_cli.tui.widgets.approval import ApprovalMenu
    from soothe_cli.tui.widgets.ask_user import AskUserMenu

from textual.app import ScreenStackError
from textual.containers import Container, VerticalScroll
from textual.css.query import NoMatches
from textual.widgets import Static

from soothe_cli.tui._session_stats import SpinnerStatus
from soothe_cli.tui.app._module_init import _DEFERRED_APPROVAL_TIMEOUT_SECONDS
from soothe_cli.tui.widgets.loading import LoadingWidget
from soothe_cli.tui.widgets.messages import AppMessage, AssistantMessage

logger = logging.getLogger(__name__)
_monotonic = time.monotonic


class _UIMixin:
    """UI interaction: status, tokens, hydration, spinner, approval, ask_user, quit/interrupt."""

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
            self.call_later(self._hydrate_messages_above)

    async def _hydrate_messages_above(self) -> None:
        """Hydrate older messages when user scrolls near the top.

        This recreates widgets for archived messages and inserts them
        at the top of the messages container.
        """
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
        hydrated_widgets: list[tuple] = []  # (widget, msg_data)
        for msg_data in to_hydrate:
            try:
                widget = msg_data.to_widget()
                hydrated_widgets.append((widget, msg_data))
            except Exception:
                logger.warning(
                    "Failed to create widget for message %s",
                    msg_data.id,
                    exc_info=True,
                )

        for widget, msg_data in reversed(hydrated_widgets):
            try:
                if first_child:
                    await messages_container.mount(widget, before=first_child)
                else:
                    await messages_container.mount(widget)
                first_child = widget
                hydrated_count += 1
                # Render Markdown content for hydrated assistant messages
                if isinstance(widget, AssistantMessage) and msg_data.content:
                    await widget.set_content(msg_data.content)
            except Exception:
                logger.warning(
                    "Failed to mount hydrated widget %s",
                    widget.id,
                    exc_info=True,
                )

        # Only update store for the number we actually mounted
        if hydrated_count > 0:
            self._message_store.mark_hydrated(hydrated_count)

        # Adjust scroll position to maintain the user's view.
        # Widget heights aren't known until after layout, so we use a
        # heuristic. A more accurate approach would measure actual heights
        # via call_after_refresh.
        estimated_height_per_message = 5  # terminal rows, rough estimate
        added_height = hydrated_count * estimated_height_per_message
        chat.scroll_y = old_scroll_y + added_height

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

    async def _request_approval(
        self,
        action_requests: Any,  # noqa: ANN401  # ActionRequest uses dynamic typing
        assistant_id: str | None,
    ) -> asyncio.Future:
        """Request user approval inline in the messages area.

        Mounts ApprovalMenu in the messages area (inline with chat).
        ChatInput stays visible - user can still see it.

        If another approval is already pending, queue this one.

        Auto-approves shell commands that are in the configured allow-list.

        Args:
            action_requests: List of action request dicts to approve
            assistant_id: The assistant ID for display purposes

        Returns:
            A Future that resolves to the user's decision.
        """
        from soothe_cli.tui.config import (
            SHELL_TOOL_NAMES,
            is_shell_command_allowed,
            settings,
        )

        loop = asyncio.get_running_loop()
        result_future: asyncio.Future = loop.create_future()

        # Check if ALL actions in the batch are auto-approvable shell commands
        if settings.shell_allow_list and action_requests:
            all_auto_approved = True
            approved_commands = []

            for req in action_requests:
                if req.get("name") in SHELL_TOOL_NAMES:
                    command = req.get("args", {}).get("command", "")
                    if is_shell_command_allowed(command, settings.shell_allow_list):
                        approved_commands.append(command)
                    else:
                        all_auto_approved = False
                        break
                else:
                    # Non-shell commands need normal approval
                    all_auto_approved = False
                    break

            if all_auto_approved and approved_commands:
                # Auto-approve all commands in the batch
                result_future.set_result({"type": "approve"})

                # Mount system messages showing the auto-approvals
                try:
                    messages = self.query_one("#messages", Container)
                    for command in approved_commands:
                        auto_msg = AppMessage(
                            f"✓ Auto-approved shell command (allow-list): {command}"
                        )
                        await self._mount_before_queued(messages, auto_msg)
                    with suppress(NoMatches, ScreenStackError):
                        self.query_one("#chat", VerticalScroll).anchor()
                except Exception:  # noqa: S110, BLE001  # Resilient auto-message display
                    pass  # Don't fail if we can't show the message

                return result_future

        # If there's already a pending approval, wait for it to complete first
        if self._pending_approval_widget is not None:
            while self._pending_approval_widget is not None:  # noqa: ASYNC110  # Simple polling is sufficient here
                await asyncio.sleep(0.1)

        # Create menu with unique ID to avoid conflicts
        from soothe_cli.tui.widgets.approval import ApprovalMenu

        unique_id = f"approval-menu-{uuid.uuid4().hex[:8]}"
        menu = ApprovalMenu(action_requests, assistant_id, id=unique_id)
        menu.set_future(result_future)

        self._pending_approval_widget = menu

        if self._is_user_typing():
            # Show a placeholder until the user stops typing, then swap in the
            # real ApprovalMenu.  This prevents accidental key presses (e.g.
            # 'y', 'n') from triggering approval decisions mid-sentence.
            placeholder = Static(
                "Waiting for typing to finish...",
                classes="approval-placeholder",
            )
            self._approval_placeholder = placeholder
            try:
                messages = self.query_one("#messages", Container)
                await self._mount_before_queued(messages, placeholder)
                self.call_after_refresh(placeholder.scroll_visible)
            except Exception:
                logger.exception("Failed to mount approval placeholder")
                # Placeholder failed — fall back to showing the menu directly
                # so the future is always resolvable.
                self._approval_placeholder = None
                await self._mount_approval_widget(menu, result_future)
                return result_future

            self.run_worker(
                self._deferred_show_approval(placeholder, menu, result_future),
                exclusive=False,
            )
        else:
            await self._mount_approval_widget(menu, result_future)

        return result_future

    async def _mount_approval_widget(
        self,
        menu: ApprovalMenu,
        result_future: asyncio.Future[dict[str, str]],
    ) -> None:
        """Mount the approval menu widget inline in the messages area.

        If mounting fails, clears `_pending_approval_widget` and propagates
        the exception via `result_future`.

        Args:
            menu: The `ApprovalMenu` instance to mount.
            result_future: The future to resolve/reject for the caller.
        """
        try:
            messages = self.query_one("#messages", Container)
            await self._mount_before_queued(messages, menu)
            self.call_after_refresh(menu.scroll_visible)
            self.call_after_refresh(menu.focus)
        except Exception as e:
            logger.exception(
                "Failed to mount approval menu (id=%s) in messages container",
                menu.id,
            )
            self._pending_approval_widget = None
            if not result_future.done():
                result_future.set_exception(e)

    async def _deferred_show_approval(
        self,
        placeholder: Static,
        menu: ApprovalMenu,
        result_future: asyncio.Future[dict[str, str]],
    ) -> None:
        """Wait until the user is idle, then swap the placeholder for the real menu.

        Exits early if the placeholder has already been detached (e.g. the
        approval was cancelled while waiting).  In that case the future is
        cancelled so the caller is not left hanging.

        Args:
            placeholder: The temporary placeholder widget currently mounted.
            menu: The `ApprovalMenu` to show once the user stops typing.
            result_future: The future backing this approval flow.
        """
        deadline = _monotonic() + _DEFERRED_APPROVAL_TIMEOUT_SECONDS
        while self._is_user_typing():  # Simple polling
            if _monotonic() > deadline:
                logger.warning("Timed out waiting for user to stop typing; showing approval now")
                break
            await asyncio.sleep(0.2)

        # Guard: if the placeholder was already removed (e.g. agent cancelled
        # the approval while we were waiting), clean up and cancel the future.
        if not placeholder.is_attached:
            logger.warning(
                "Approval placeholder detached before menu shown (id=%s)",
                menu.id,
            )
            self._approval_placeholder = None
            self._pending_approval_widget = None
            if not result_future.done():
                result_future.cancel()
            return

        self._approval_placeholder = None
        try:
            await placeholder.remove()
        except Exception:
            logger.warning(
                "Failed to remove approval placeholder during swap",
                exc_info=True,
            )
        await self._mount_approval_widget(menu, result_future)

    def _on_auto_approve_enabled(self) -> None:
        """Handle auto-approve being enabled via the HITL approval menu.

        Called when the user selects "Auto-approve all" from an approval
        dialog. Syncs the auto-approve state across the app flag, status
        bar indicator, and session state so subsequent tool calls skip
        the approval prompt.
        """
        self._auto_approve = True
        if self._status_bar:
            self._status_bar.set_auto_approve(enabled=True)
        if self._session_state:
            self._session_state.auto_approve = True

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
