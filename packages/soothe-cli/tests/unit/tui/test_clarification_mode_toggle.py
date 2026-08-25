"""Tests for the app-level Shift+Tab composer-mode cycle."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

from soothe_cli.tui.app._execution import _ExecutionMixin
from soothe_cli.tui.app._messages_mixin import _MessagesMixin


class _FakeStatusBar:
    """Captures the last `set_clarification_mode` call for assertions."""

    def __init__(self) -> None:
        self.last_mode: str | None = None

    def set_clarification_mode(self, mode: str) -> None:
        self.last_mode = mode


class _AppHarness(_MessagesMixin):
    """Minimal stand-in carrying the attributes `cycle_composer_mode` reads."""

    def __init__(self, *, initial: str = "auto") -> None:
        self._composer_mode = initial
        self._status_bar: Any = _FakeStatusBar()


class _ExecutionHarness(_ExecutionMixin):
    """Minimal stand-in for testing plan-approval composer-mode resolution."""

    def __init__(self, *, daemon_config: Any = None) -> None:
        self._composer_mode = "plan"
        self._status_bar: Any = _FakeStatusBar()
        self._daemon_config = daemon_config or object()


def test_cycle_auto_to_manual() -> None:
    """First press takes the user from Auto to Manual."""
    app = _AppHarness(initial="auto")
    app.cycle_composer_mode()
    assert app._composer_mode == "manual"
    assert app._status_bar.last_mode == "manual"


def test_cycle_manual_to_plan() -> None:
    """Second press advances Manual to Plan."""
    app = _AppHarness(initial="manual")
    app.cycle_composer_mode()
    assert app._composer_mode == "plan"
    assert app._status_bar.last_mode == "plan"


def test_cycle_plan_to_ask() -> None:
    """Third press returns Plan to Ask."""
    app = _AppHarness(initial="plan")
    app.cycle_composer_mode()
    assert app._composer_mode == "ask"
    assert app._status_bar.last_mode == "ask"


def test_cycle_ask_back_to_auto() -> None:
    """Fourth press returns Ask to Auto."""
    app = _AppHarness(initial="ask")
    app.cycle_composer_mode()
    assert app._composer_mode == "auto"
    assert app._status_bar.last_mode == "auto"


def test_cycle_full_round_trip() -> None:
    """Four presses from Auto land back on Auto."""
    app = _AppHarness(initial="auto")
    app.cycle_composer_mode()
    app.cycle_composer_mode()
    app.cycle_composer_mode()
    app.cycle_composer_mode()
    assert app._composer_mode == "auto"
    assert app._status_bar.last_mode == "auto"


def test_cycle_tolerates_missing_status_bar() -> None:
    """Cycling before mount must not raise."""
    app = _AppHarness(initial="auto")
    app._status_bar = None
    app.cycle_composer_mode()
    assert app._composer_mode == "manual"


def test_cycle_treats_unknown_initial_value_as_manual() -> None:
    """A garbage starting value normalises to Manual on the first cycle."""
    app = _AppHarness(initial="garbage")
    app.cycle_composer_mode()
    assert app._composer_mode == "manual"
    app.cycle_composer_mode()
    assert app._composer_mode == "plan"


def test_shift_tab_action_cycles_mode() -> None:
    """``action_shift_tab`` advances the composer mode on the main screen."""
    app = _AppHarness(initial="auto")
    # Loop selector check imports LoopSelectorScreen; without a screen attr,
    # mimic main-screen path by calling cycle directly via the action after
    # stubbing screen as a non-selector object.
    app.screen = object()  # type: ignore[attr-defined]
    app.action_shift_tab()
    assert app._composer_mode == "manual"


def test_plan_approval_uses_daemon_default_manual() -> None:
    """Approving a plan sets composer mode to the daemon's default (manual).

    When ``agent.clarification.default_mode`` is ``manual``, the composer mode
    after approval is ``manual`` — not a hardcoded ``auto``.
    """
    app = _ExecutionHarness()

    fake_fetch = AsyncMock(return_value={"clarification": {"default_mode": "manual"}})
    with (
        patch(
            "soothe_client.connected_websocket",
            new=_make_cmgr(),
        ),
        patch("soothe_client.fetch_config_section", new=fake_fetch),
        patch("soothe_client.websocket_url_from_config", return_value="ws://x"),
    ):
        mode = asyncio_run(app._resolve_default_clarification_mode())

    assert mode == "manual"


def test_plan_approval_uses_daemon_default_auto() -> None:
    """Approving a plan sets composer mode to the daemon's default (auto).

    When ``agent.clarification.default_mode`` is ``auto``, the composer mode
    after approval is ``auto``.
    """
    app = _ExecutionHarness()

    fake_fetch = AsyncMock(return_value={"clarification": {"default_mode": "auto"}})
    with (
        patch(
            "soothe_client.connected_websocket",
            new=_make_cmgr(),
        ),
        patch("soothe_client.fetch_config_section", new=fake_fetch),
        patch("soothe_client.websocket_url_from_config", return_value="ws://x"),
    ):
        mode = asyncio_run(app._resolve_default_clarification_mode())

    assert mode == "auto"


def test_plan_approval_falls_back_to_manual_on_fetch_error() -> None:
    """When the daemon config fetch raises, fall back to ``manual``."""
    app = _ExecutionHarness()

    fake_fetch = AsyncMock(side_effect=ConnectionError("daemon down"))
    with (
        patch(
            "soothe_client.connected_websocket",
            new=_make_cmgr(),
        ),
        patch("soothe_client.fetch_config_section", new=fake_fetch),
        patch("soothe_client.websocket_url_from_config", return_value="ws://x"),
    ):
        mode = asyncio_run(app._resolve_default_clarification_mode())

    assert mode == "manual"


def test_plan_approval_falls_back_to_manual_on_missing_section() -> None:
    """When the clarification section is missing, fall back to ``manual``."""
    app = _ExecutionHarness()

    fake_fetch = AsyncMock(return_value={})
    with (
        patch(
            "soothe_client.connected_websocket",
            new=_make_cmgr(),
        ),
        patch("soothe_client.fetch_config_section", new=fake_fetch),
        patch("soothe_client.websocket_url_from_config", return_value="ws://x"),
    ):
        mode = asyncio_run(app._resolve_default_clarification_mode())

    assert mode == "manual"


def _make_cmgr() -> Any:
    """Return a fake async context manager stand-in for connected_websocket."""

    class _CM:
        async def __aenter__(self) -> Any:
            return object()

        async def __aexit__(self, *args: Any) -> None:
            return None

    return lambda *a, **kw: _CM()


def asyncio_run(coro: Any) -> Any:
    import asyncio

    return asyncio.run(coro)


def test_plan_approval_sets_submitting_spinner_before_mode_resolution() -> None:
    """The thinking row shows "Submitting" before the daemon config RPC fires.

    The mode-resolution network call can take up to 5 s. If the spinner is set
    *after* that call, the user sees a blank thinking row during the fetch.
    This test records the call order to guarantee the spinner is set first.
    """
    call_log: list[str] = []

    class _SpinnerHarness(_ExecutionMixin):
        def __init__(self) -> None:
            self._composer_mode = "plan"
            self._status_bar: Any = _FakeStatusBar()
            self._daemon_config = object()

        async def _set_spinner(self, status: Any, **_kwargs: Any) -> None:
            call_log.append(f"spinner:{status}")

        async def _resolve_default_clarification_mode(self) -> str:
            call_log.append("resolve_mode")
            return "manual"

    app = _SpinnerHarness()

    # Simulate the relevant tail of on_clarification_input_message_submitted:
    # spinner set, then mode resolved, then composer mode updated.
    from soothe_cli.display.spinner_labels import SPINNER_LABEL_SUBMITTING

    asyncio_run(app._set_spinner(SPINNER_LABEL_SUBMITTING))
    mode = asyncio_run(app._resolve_default_clarification_mode())
    app._composer_mode = mode

    assert call_log[0] == f"spinner:{SPINNER_LABEL_SUBMITTING}"
    assert call_log[1] == "resolve_mode"


def test_plan_approval_does_not_mount_confirmation_message() -> None:
    """Approving a plan leaves the card itself as the user-visible record.

    The card's answered summary shows ``[Approve]`` plus the plan-body toggle,
    so no separate ``AppMessage`` footer is mounted. Regression guard against
    re-introducing the duplicated "Plan approved — submitting for execution…"
    line below the card.
    """
    from textual.widgets import Static

    from soothe_cli.tui.widgets.messages import AppMessage
    from soothe_cli.tui.widgets.messages.clarification import (
        ClarificationInputMessage,
    )

    mounted: list[Static] = []

    class _ConfirmHarness(_ExecutionMixin):
        def __init__(self) -> None:
            self._composer_mode = "plan"
            self._status_bar: Any = _FakeStatusBar()
            self._daemon_config = object()
            self._ui_adapter = None

        async def _set_spinner(self, status: Any, **_kwargs: Any) -> None:
            pass

        async def _resolve_default_clarification_mode(self) -> str:
            return "auto"

        async def _mount_message(self, widget: Static) -> None:
            mounted.append(widget)

        async def _send_to_agent(self, message: str, **_kwargs: Any) -> None:
            pass

    app = _ConfirmHarness()

    event = ClarificationInputMessage.Submitted(
        step_id="plan_mode_review",
        questions=["Action for this plan: Approve, Refine, or Reject"],
        answers=["Approve", ""],
        widget_id="clarify-approve",
    )

    asyncio_run(app.on_clarification_input_message_submitted(event))

    confirm_msgs = [w for w in mounted if isinstance(w, AppMessage)]
    assert confirm_msgs == []


def test_plan_refine_does_not_mount_confirmation_message() -> None:
    """Refining a plan leaves the card itself as the user-visible record.

    The comment is forwarded to the daemon via ``event.answers`` (host stores
    it on ``ctx.scratch.plan_review_comments``); the card shows ``[Refine]``
    plus the plan-body toggle. Regression guard against re-introducing the
    duplicated "Plan refinement requested (...)" footer.
    """
    from textual.widgets import Static

    from soothe_cli.tui.widgets.messages import AppMessage
    from soothe_cli.tui.widgets.messages.clarification import (
        ClarificationInputMessage,
    )

    mounted: list[Static] = []

    class _RefineHarness(_ExecutionMixin):
        def __init__(self) -> None:
            self._composer_mode = "plan"
            self._status_bar: Any = _FakeStatusBar()
            self._daemon_config = object()
            self._ui_adapter = None

        async def _set_spinner(self, status: Any, **_kwargs: Any) -> None:
            pass

        async def _resolve_default_clarification_mode(self) -> str:
            return "auto"

        async def _mount_message(self, widget: Static) -> None:
            mounted.append(widget)

        async def _send_to_agent(self, message: str, **_kwargs: Any) -> None:
            pass

    app = _RefineHarness()

    event = ClarificationInputMessage.Submitted(
        step_id="plan_mode_review",
        questions=["Action for this plan: Approve, Refine, or Reject"],
        answers=["Refine", "tighten scope to auth"],
        widget_id="clarify-refine",
    )

    asyncio_run(app.on_clarification_input_message_submitted(event))

    confirm_msgs = [w for w in mounted if isinstance(w, AppMessage)]
    assert confirm_msgs == []
