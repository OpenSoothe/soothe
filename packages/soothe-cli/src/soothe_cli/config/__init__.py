"""CLI configuration package."""

from soothe_cli.config.cli_config import CLI_CONFIG_FILE, CLIConfig
from soothe_cli.config.loader import load_config

__all__ = ["CLI_CONFIG_FILE", "CLIConfig", "load_config"]
