"""DEPRECATED: This package has been split into three independent packages.

The monolithic `soothe` package has been replaced by:

- **soothe-sdk** (v0.2.0): Shared SDK - WebSocket client, protocol, types
- **soothe-cli** (v0.1.0): CLI client - WebSocket-only communication
- **soothe-daemon** (v0.3.0): Daemon server - Agent runtime

Installation:
    pip install soothe-cli soothe-daemon[all]

Usage:
    # Start daemon
    soothe-daemon start

    # Use CLI
    soothe -p "your query"

Migration Guide:
    See MIGRATION.md or docs/migration-guide-v0.3.md

Architecture Documentation:
    See docs/cli-daemon-architecture.md

This package is DEPRECATED and will receive no further updates.
Please migrate to the new packages immediately.

Version: 0.2.13 (final deprecated release)
"""

__version__ = "0.2.13"
__deprecated__ = True

__all__ = []