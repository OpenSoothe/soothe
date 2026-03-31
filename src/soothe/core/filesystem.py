"""DEPRECATED: Use soothe.safety.filesystem instead.

This module is kept for backward compatibility only.
"""

import warnings

from soothe.safety.filesystem import FrameworkFilesystem

warnings.warn(
    "soothe.core.filesystem is deprecated, use soothe.safety instead",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["FrameworkFilesystem"]
