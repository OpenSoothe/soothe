"""Re-export relay event constants from `soothe.events.catalog`.

The catalog is the canonical registration site for `soothe.*` events (type
strings + models + `_reg` calls). Re-exported here so emit sites in
`relay.relay` reference them without importing the full catalog.
"""

from __future__ import annotations

from soothe.events.catalog import (
    RELAY_CAPTURED,
    RELAY_DEFERRED,
    RELAY_RECOVERED,
    RELAY_RESUME_COMMAND_BUILT,
    RELAY_STALE_INTERRUPT_SKIPPED,
    RELAY_UNBLOCKED,
)

__all__ = [
    "RELAY_CAPTURED",
    "RELAY_DEFERRED",
    "RELAY_RECOVERED",
    "RELAY_RESUME_COMMAND_BUILT",
    "RELAY_STALE_INTERRUPT_SKIPPED",
    "RELAY_UNBLOCKED",
]
