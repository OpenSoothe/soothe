"""Hook system for TUI events (stub implementation from deepagents-cli migration).

This module provides hook dispatch functionality for TUI events.
Full implementation should integrate with Soothe's event system.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def dispatch_hook(hook_name: str, payload: dict[str, Any]) -> None:
    """Dispatch a hook event asynchronously.

    Stub implementation - no hooks are currently registered.
    Full implementation should integrate with Soothe's event system.

    Args:
        hook_name: Name of the hook event (e.g., "user.prompt", "session.end").
        payload: Event payload data.
    """
    logger.debug("Hook dispatch (stub): %s with payload %s", hook_name, payload)
