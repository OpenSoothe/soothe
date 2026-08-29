"""iTerm2 terminal integration: cursor guide escape sequences and lifecycle.

The cursor guide (highlight cursor line) causes visual artifacts when Textual
takes over the terminal in alternate screen mode. We disable it before the app
launches and restore on exit. Both atexit and exit() override are used for
defense-in-depth: atexit catches abnormal termination (SIGTERM, unhandled
exceptions), while exit() ensures restoration before Textual's cleanup.

Unlike the previous catch-all module, this module performs **no** side effects
at import time. Call `init_terminal_integration()` explicitly before starting
the Textual app.
"""

from __future__ import annotations

import os

# Detection: check env vars AND that stderr is a TTY (avoids false positives
# when env vars are inherited but running in non-TTY context like CI)
_IS_ITERM = (
    (
        os.environ.get("LC_TERMINAL", "") == "iTerm2"
        or os.environ.get("TERM_PROGRAM", "") == "iTerm.app"
    )
    and hasattr(os, "isatty")
    and os.isatty(2)
)

# iTerm2 cursor guide escape sequences (OSC 1337)
# Format: OSC 1337 ; HighlightCursorLine=<yes|no> ST
# Where OSC = ESC ] (0x1b 0x5d) and ST = ESC \ (0x1b 0x5c)
_ITERM_CURSOR_GUIDE_OFF = "\x1b]1337;HighlightCursorLine=no\x1b\\"
_ITERM_CURSOR_GUIDE_ON = "\x1b]1337;HighlightCursorLine=yes\x1b\\"


def _write_iterm_escape(sequence: str) -> None:
    """Write an iTerm2 escape sequence to stderr.

    Silently fails if the terminal is unavailable (redirected, closed, broken
    pipe). This is a cosmetic feature, so failures should never crash the app.
    """
    if not _IS_ITERM:
        return
    try:
        import sys

        if sys.__stderr__ is not None:
            sys.__stderr__.write(sequence)
            sys.__stderr__.flush()
    except OSError:
        # Terminal may be unavailable (redirected, closed, broken pipe)
        pass


def _restore_cursor_guide() -> None:
    """Restore iTerm2 cursor guide on exit.

    Registered with atexit to ensure the cursor guide is re-enabled
    when the CLI exits, regardless of how the exit occurs.
    """
    _write_iterm_escape(_ITERM_CURSOR_GUIDE_ON)


def init_terminal_integration() -> None:
    """Disable the iTerm2 cursor guide and register restore-on-exit.

    Call this explicitly before starting the Textual app. This replaces the
    previous import-time side effect so that merely importing the module does
    not write to the terminal.
    """
    _write_iterm_escape(_ITERM_CURSOR_GUIDE_OFF)
    if _IS_ITERM:
        import atexit

        atexit.register(_restore_cursor_guide)
