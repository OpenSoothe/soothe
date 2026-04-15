"""Soothe daemon entry point - daemon server management.

DEPRECATED: This file is deprecated and will be removed in a future version.
Use 'soothe.cli.daemon_main:app' entry point directly via 'soothe-daemon' command.
"""

from soothe.cli.daemon_main import app

# Re-export for backward compatibility during transition
__all__ = ["app"]
