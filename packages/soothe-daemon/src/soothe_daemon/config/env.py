"""Environment-variable overrides for ``SootheDaemonConfig``."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from soothe_daemon.config.settings import SootheDaemonConfig


def apply_env_overrides(config: SootheDaemonConfig) -> None:
    """Apply environment-variable overrides to a daemon config in place.

    Currently handles ``SOOTHE_DISTRIBUTED=1/true/yes`` -> enable Ray loop
    execution (RFC-221).
    """

    if os.environ.get("SOOTHE_DISTRIBUTED", "").lower() in ("1", "true", "yes"):
        config.distributed.enabled = True


__all__ = ["apply_env_overrides"]
