"""User-visible cron messages."""

from __future__ import annotations

AUTOPILOT_REQUIRED_FOR_CRON = (
    "Autopilot is disabled. Set agent.autopilot.enabled to true in config "
    "and restart the daemon (soothed restart) before scheduling cron jobs."
)
"""Message shown when cron submission requires a running autopilot scheduler."""
