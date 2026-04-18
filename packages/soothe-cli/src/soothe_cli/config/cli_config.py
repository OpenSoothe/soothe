"""CLI-specific configuration class (IG-174 Phase 3)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from soothe_sdk.client.config import SOOTHE_HOME

# Sole on-disk location for CLI client settings (WebSocket address, progress verbosity, …).
CLI_CONFIG_FILE = Path(SOOTHE_HOME) / "config" / "cli_config.yml"


@dataclass
class CLIConfig:
    """Minimal CLI config for daemon connection.

    Full config available via daemon RPC when needed.
    CLI package can be installed independently without full SootheConfig.
    """

    # WebSocket connection
    daemon_host: str = "127.0.0.1"
    daemon_port: int = 8765

    # CLI behavior — verbosity: progress/event display (quiet … debug).
    verbosity: str = "normal"
    # logging_level: DEBUG/INFO/… for ~/.soothe/logs/soothe-cli.log; None = derive from verbosity.
    logging_level: str | None = None

    output_format: str = "text"

    # Paths
    soothe_home: Path = field(default_factory=lambda: Path.home() / ".soothe")

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

    @classmethod
    def from_config_file(cls, config_path: Path | None = None) -> CLIConfig:
        """Load CLI config from YAML file (minimal subset).

        Reads minimal CLI-relevant settings from config file.
        Full config available via daemon RPC.

        Args:
            config_path: Path to config file. Defaults to ~/.soothe/config/cli_config.yml.

        Returns:
            CLIConfig instance with minimal settings.
        """
        import yaml

        if config_path is None:
            config_path = CLI_CONFIG_FILE

        if not config_path.exists():
            return cls()  # Use defaults

        with open(config_path) as f:
            data = yaml.safe_load(f) or {}

        # Extract minimal CLI-relevant config
        daemon_section = data.get("daemon", {})
        transports = daemon_section.get("transports", {})
        websocket = transports.get("websocket", {})

        raw_level = data.get("logging_level")
        if raw_level is not None and not isinstance(raw_level, str):
            raw_level = None

        return cls(
            daemon_host=websocket.get("host", "127.0.0.1"),
            daemon_port=websocket.get("port", 8765),
            verbosity=data.get("verbosity", "normal"),
            logging_level=raw_level,
            soothe_home=Path(data.get("home", str(Path.home() / ".soothe"))),
        )

    @classmethod
    def from_soothe_config(cls, soothe_config: Any) -> CLIConfig:
        """Create CLIConfig from full SootheConfig (compatibility helper).

        Used during transition period where some code still has SootheConfig.

        Args:
            soothe_config: Full SootheConfig instance.

        Returns:
            CLIConfig with WebSocket settings extracted.
        """
        level_from_full = getattr(soothe_config.logging, "level", None)
        if isinstance(level_from_full, str) and level_from_full.strip():
            logging_level = level_from_full.strip()
        else:
            logging_level = None

        return cls(
            daemon_host=soothe_config.daemon.transports.websocket.host,
            daemon_port=soothe_config.daemon.transports.websocket.port,
            verbosity=soothe_config.logging.verbosity,
            logging_level=logging_level,
            soothe_home=Path(soothe_config.home),
        )

    # Compatibility properties for transition period
    # These allow gradual migration without breaking existing code

    @property
    def daemon(self) -> Any:
        """Compatibility property: return daemon config structure."""
        return type(
            "DaemonConfig",
            (),
            {
                "transports": type(
                    "TransportsConfig",
                    (),
                    {
                        "websocket": type(
                            "WebSocketConfig",
                            (),
                            {"host": self.daemon_host, "port": self.daemon_port},
                        )
                    },
                )()
            },
        )()

    @property
    def logging(self) -> Any:
        """Compatibility property: return logging config structure."""
        return type(
            "LoggingConfig",
            (),
            {"verbosity": self.verbosity, "level": self.logging_level},
        )()

    @property
    def home(self) -> str:
        """Compatibility property: return home path string."""
        return str(self.soothe_home)
