"""Shared link-click handling for Textual widgets."""

from __future__ import annotations

import logging
import threading
import webbrowser
from typing import TYPE_CHECKING

from soothe_cli.display.unicode_security import check_url_safety, strip_dangerous_unicode

if TYPE_CHECKING:
    from textual.events import Click

logger = logging.getLogger(__name__)


def open_style_link(event: Click) -> None:
    """Open the URL from a Rich link style on click, if present."""
    url = event.style.link
    if not url:
        return

    safety = check_url_safety(url)
    if not safety.safe:
        detail = safety.warnings[0] if safety.warnings else "Suspicious URL"
        logger.warning("Blocked suspicious URL: %s (%s)", url, detail)
        try:
            app = getattr(event, "app", None)
            notify = getattr(app, "notify", None)
            if callable(notify):
                safe_url = strip_dangerous_unicode(url)
                notify(
                    f"Blocked suspicious URL: {safe_url}\n{detail}",
                    severity="warning",
                    markup=False,
                )
        except (AttributeError, TypeError):
            logger.debug("Could not send URL-blocked notification", exc_info=True)
        return

    try:
        threading.Thread(
            target=webbrowser.open,
            args=(url,),
            daemon=True,
        ).start()
    except Exception:
        logger.debug("Could not open browser for URL: %s", url, exc_info=True)
        return
    event.stop()
