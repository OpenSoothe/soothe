"""CLI-specific configuration class (IG-174 Phase 3)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from soothe_sdk.paths import SOOTHE_HOME


@dataclass
class CLIConfig:
    """Minimal CLI config for daemon connection.

    Full config available via daemon RPC when needed.
    CLI package can be installed independently without full SootheConfig.

    Values are supplied via global CLI flags on the root ``soothe`` command.
    """

    # WebSocket connection
    daemon_host: str = "127.0.0.1"
    daemon_port: int = 8765

    # logging_level: DEBUG/INFO/… for ~/.soothe/logs/cli.log; None = default INFO.
    logging_level: str | None = None

    # TUI rendering options
    render_markdown: bool = True
    """Render assistant messages as Markdown in TUI (default True)."""

    markdown_theme: str = "match-app"
    """Markdown appearance preset (``match-app``, ``langchain``, ``standard``, …)."""

    # Plan panel visibility preference
    plan_panel_default_visible: bool = True
    """Auto-show the in-flow plan panel when a goal plan is active. Ctrl+t toggles."""

    # Output streaming overrides (RFC-614)
    output_streaming_enabled: bool | None = None
    """Override daemon streaming enabled setting."""

    output_streaming_mode: str | None = None
    """Override daemon streaming mode: 'streaming' or 'batch'."""

    # RFC-622: clarification relay mode
    clarification_mode: str | None = None
    """'manual' (relay to human) or 'auto' (veritas auto-answer). None = auto-detect from TTY."""

    # Resume behavior: when the launcher finds an active loop on startup,
    # auto-resume it (True) or prompt the user (False, default).
    auto_resume: bool = False
    """Auto-resume active loops on CLI startup without prompting (default: prompt)."""

    # Paths
    soothe_home: Path = field(default_factory=lambda: Path(SOOTHE_HOME))

    def websocket_url(self) -> str:
        """Construct WebSocket URL for daemon connection."""
        return f"ws://{self.daemon_host}:{self.daemon_port}"
