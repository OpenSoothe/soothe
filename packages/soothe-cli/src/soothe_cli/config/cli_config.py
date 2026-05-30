"""CLI-specific configuration class (IG-174 Phase 3)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from soothe_sdk.client.config import SOOTHE_HOME


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

    # Output streaming overrides (RFC-614)
    output_streaming_enabled: bool | None = None
    """Override daemon streaming enabled setting."""

    output_streaming_mode: str | None = None
    """Override daemon streaming mode: 'streaming' or 'batch'."""

    # Paths
    soothe_home: Path = field(default_factory=lambda: Path(SOOTHE_HOME))

    # Daemon config cache (fetched via RPC)
    _daemon_config_cache: dict[str, Any] = field(default_factory=dict)

    def websocket_url(self) -> str:
        """Construct WebSocket URL for daemon connection."""
        return f"ws://{self.daemon_host}:{self.daemon_port}"

    async def fetch_daemon_config(self, section: str = "all") -> dict[str, Any]:
        """Fetch daemon config section via WebSocket RPC.

        Args:
            section: Config section name (e.g., "providers", "defaults", "all").

        Returns:
            Wire-safe config section dict.
        """
        from soothe_sdk.client import WebSocketClient, fetch_config_section

        client = WebSocketClient(url=self.websocket_url())
        await client.connect()

        try:
            config_section = await fetch_config_section(client, section, timeout=5.0)
            self._daemon_config_cache[section] = config_section
            return config_section
        finally:
            await client.close()

    def get_cached_config(self, section: str) -> dict[str, Any]:
        """Get cached daemon config section.

        Args:
            section: Config section name.

        Returns:
            Cached config section dict, or empty dict if not cached.
        """
        return self._daemon_config_cache.get(section, {})
