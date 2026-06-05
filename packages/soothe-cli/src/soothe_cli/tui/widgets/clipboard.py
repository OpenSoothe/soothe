"""Clipboard utilities for Soothe."""

from __future__ import annotations

import base64
import logging
import os
import pathlib
import shutil
import subprocess
import sys
from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING

from soothe_cli.tui.config import get_glyphs
from soothe_cli.tui.preview_limits import CLIPBOARD_TOAST_PREVIEW_CHARS

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from textual.app import App
    from textual.widget import Widget


def _copy_osc52(text: str) -> None:
    """Copy text using OSC 52 escape sequence (works over SSH/tmux)."""
    encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
    osc52_seq = f"\033]52;c;{encoded}\a"
    if os.environ.get("TMUX"):
        osc52_seq = f"\033Ptmux;\033{osc52_seq}\033\\"

    with pathlib.Path("/dev/tty").open("w", encoding="utf-8") as tty:
        tty.write(osc52_seq)
        tty.flush()


def _copy_native(text: str) -> None:
    """Copy text using native OS clipboard command (pbcopy/xclip/xsel)."""
    if sys.platform == "darwin":
        cmd = ["pbcopy"]
    elif shutil.which("xclip"):
        cmd = ["xclip", "-selection", "clipboard"]
    elif shutil.which("xsel"):
        cmd = ["xsel", "--clipboard", "--input"]
    elif shutil.which("wl-copy"):
        cmd = ["wl-copy"]
    else:
        raise RuntimeError("No native clipboard command found")

    proc = subprocess.run(
        cmd,
        input=text.encode("utf-8"),
        capture_output=True,
        timeout=5,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"{cmd[0]} failed: {proc.stderr.decode()}")


def _shorten_preview(texts: list[str]) -> str:
    """Shorten text for notification preview.

    Returns:
        Shortened preview text suitable for notification display.
    """
    glyphs = get_glyphs()
    dense_text = glyphs.newline.join(texts).replace("\n", glyphs.newline)
    if len(dense_text) > CLIPBOARD_TOAST_PREVIEW_CHARS:
        return f"{dense_text[: CLIPBOARD_TOAST_PREVIEW_CHARS - 1]}{glyphs.ellipsis}"
    return dense_text


def _get_selected_text(widget: Widget) -> str | None:
    """Return selected text from a widget, if available."""
    if not hasattr(widget, "text_selection") or not widget.text_selection:
        return None

    selection = widget.text_selection
    if selection.end is None:
        return None

    try:
        result = widget.get_selection(selection)
    except (AttributeError, TypeError, ValueError, IndexError) as e:
        logger.debug(
            "Failed to get selection from widget %s: %s",
            type(widget).__name__,
            e,
            exc_info=True,
        )
        return None

    if not result:
        return None

    selected_text, _ = result
    text = selected_text.strip()
    return text or None


def _prefer_tty_osc52() -> bool:
    """Return True when clipboard should use tmux-wrapped OSC 52 on /dev/tty.

    Textual's ``copy_to_clipboard`` emits unwrapped OSC 52 via the driver and
    never raises, so it would block the tmux-aware path if tried first.
    """
    return bool(os.environ.get("TMUX") or os.environ.get("SSH_CONNECTION"))


def _clipboard_copy_methods(app: App) -> list[Callable[[str], None]]:
    """Return clipboard backends in priority order for the current environment."""
    methods: list[Callable[[str], None]] = []

    try:
        import pyperclip

        methods.append(pyperclip.copy)
    except ImportError:
        pass

    # Native OS clipboard (pbcopy on macOS, xclip/xsel on Linux) — most
    # reliable for local sessions where OSC 52 may not be supported.
    methods.append(_copy_native)

    if _prefer_tty_osc52():
        methods.append(_copy_osc52)
    else:
        methods.append(app.copy_to_clipboard)
        methods.append(_copy_osc52)

    return methods


def _copy_texts_to_clipboard(app: App, selected_texts: list[str]) -> None:
    """Copy selected text(s) via available clipboard methods."""
    if not selected_texts:
        return

    combined_text = "\n".join(selected_texts)
    copy_methods = _clipboard_copy_methods(app)

    for copy_fn in copy_methods:
        try:
            copy_fn(combined_text)
            # Use markup=False to prevent copied text from being parsed as Rich markup
            app.notify(
                f'"{_shorten_preview(selected_texts)}" copied',
                severity="information",
                timeout=2,
                markup=False,
            )
        except (OSError, RuntimeError, TypeError) as e:
            logger.debug(
                "Clipboard copy method %s failed: %s",
                getattr(copy_fn, "__name__", repr(copy_fn)),
                e,
                exc_info=True,
            )
            continue
        else:
            return

    # If all methods fail, still notify but warn
    app.notify(
        "Failed to copy - no clipboard method available",
        severity="warning",
        timeout=3,
    )


def screen_has_text_selection(screen: object | None) -> bool:
    """Return True when the screen still has an active text selection.

      Prefer this over ``screen.get_selected_text()`` for click guards: animated
    widgets can hold stale line offsets that make extraction raise ``IndexError``.
    """
    if screen is None:
        return False
    selections = getattr(screen, "selections", None)
    return bool(selections)


def _selected_text_from_screen(app: App) -> str | None:
    """Return selected text via Textual's screen-level selection API."""
    screen = app.screen
    if screen is None:
        return None
    try:
        selected = screen.get_selected_text()
    except (AttributeError, TypeError, ValueError, IndexError) as exc:
        logger.debug("screen.get_selected_text failed: %s", exc, exc_info=True)
        return None
    if not selected:
        return None
    text = selected.strip()
    return text or None


def clear_widget_text_selection(widget: Widget) -> None:
    """Drop a widget's selection entry when its rendered line count may have changed."""
    screen = widget.screen
    if screen is None:
        return
    selections = getattr(screen, "selections", None)
    if not selections or widget not in selections:
        return
    updated = dict(selections)
    updated.pop(widget, None)
    screen.selections = updated


def _collect_selected_texts(
    app: App,
    *,
    candidate_widgets: Iterable[Widget] | None = None,
) -> list[str]:
    """Gather non-empty selected text fragments from the screen or widgets."""
    screen_text = _selected_text_from_screen(app)
    if screen_text:
        return [screen_text]

    selected_texts: list[str] = []
    seen_ids: set[int] = set()

    def _append_from_widget(widget: Widget | None) -> None:
        if widget is None:
            return
        marker = id(widget)
        if marker in seen_ids:
            return
        seen_ids.add(marker)
        selected = _get_selected_text(widget)
        if selected:
            selected_texts.append(selected)

    if candidate_widgets is not None:
        for widget in candidate_widgets:
            _append_from_widget(widget)
        if selected_texts:
            return selected_texts

    for widget in app.query("*"):
        _append_from_widget(widget)
    return selected_texts


def copy_selection_to_clipboard(
    app: App,
    *,
    candidate_widgets: Iterable[Widget] | None = None,
    notify_if_empty: bool = False,
) -> bool:
    """Copy selected text from the TUI to the system clipboard.

    Args:
        app: The running Textual app.
        candidate_widgets: Optional widgets to inspect before a full DOM scan.
        notify_if_empty: When True, show a hint if nothing is selected.

    Returns:
        True when text was copied, False otherwise.
    """
    selected_texts = _collect_selected_texts(app, candidate_widgets=candidate_widgets)
    if not selected_texts:
        if notify_if_empty:
            app.notify("No text selected", severity="warning", timeout=2, markup=False)
        return False
    _copy_texts_to_clipboard(app, selected_texts)
    return True
