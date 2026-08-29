"""App entry points and slash-command URL constants.

`run_textual_app` and `run_textual_tui` are the public async and sync entry
points for launching the Textual TUI. `_COMMAND_URLS` maps slash-commands
that just open a browser to their target URLs.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

from soothe_cli._version import CHANGELOG_URL, DOCS_URL
from soothe_cli.tui.app._terminal import init_terminal_integration
from soothe_cli.tui.app._types import AppResult

_COMMAND_URLS: dict[str, str] = {
    "/changelog": CHANGELOG_URL,
    "/docs": DOCS_URL,
    "/feedback": "https://github.com/mirasoth/soothe/issues/new/choose",
}
"""Slash-command to URL mapping for commands that just open a browser."""


async def run_textual_app(
    *,
    daemon_config: Any,  # noqa: ANN401
    assistant_id: str | None = None,
    cwd: str | Path | None = None,
    resume_loop_id: str | None = None,
    initial_prompt: str | None = None,
    initial_skill: str | None = None,
    mcp_server_info: list[dict[str, Any]] | None = None,
    profile_override: dict[str, Any] | None = None,
) -> AppResult:
    """Run the Textual TUI (daemon execution only)."""
    from soothe_cli.tui.app._app import SootheApp  # deferred to avoid circular import

    # Disable iTerm2 cursor guide before Textual takes over the terminal.
    # Previously this was an import-time side effect; now explicit.
    init_terminal_integration()

    app = SootheApp(
        daemon_config=daemon_config,
        assistant_id=assistant_id,
        cwd=cwd,
        resume_loop_id=resume_loop_id,
        initial_prompt=initial_prompt,
        initial_skill=initial_skill,
        mcp_server_info=mcp_server_info,
        profile_override=profile_override,
    )
    try:
        await app.run_async()
    finally:
        if app._daemon_session is not None:
            from soothe_cli.runtime.transport.session import TUI_EXIT_HANDSHAKE_TIMEOUT_S

            await app._daemon_session.close(handshake_timeout=TUI_EXIT_HANDSHAKE_TIMEOUT_S)

    return AppResult(
        return_code=app.return_code or 0,
        loop_id=app._lc_loop_id,
        session_stats=app._session_stats,
        update_available=app._update_available,
    )


def run_textual_tui(
    config: Any,  # noqa: ANN401
    resume_loop_id: str | None = None,
    initial_prompt: str | None = None,
) -> AppResult:
    """Launch the Textual TUI with optional loop attachment and initial prompt.

    Args:
    config: Soothe configuration used for daemon-backed startup.
    resume_loop_id: Loop id to attach to when starting the TUI
    initial_prompt: Auto-submit prompt on launch
    """

    # Caller cwd is forwarded as the loop workspace hint.
    # Daemon workspace is ephemeral TEMP unless SOOTHE_WORKSPACE env set.
    cwd = os.getcwd()

    return asyncio.run(
        run_textual_app(
            resume_loop_id=resume_loop_id,
            initial_prompt=initial_prompt,
            daemon_config=config,
            cwd=cwd,
        )
    )
