"""DEPRECATED: Use soothe.safety.filesystem instead.

This module is kept for backward compatibility only.
"""

import warnings

warnings.warn(
    "soothe.core.filesystem is deprecated, use soothe.safety instead",
    DeprecationWarning,
    stacklevel=2,
)

from soothe.safety.filesystem import FrameworkFilesystem

__all__ = ["FrameworkFilesystem"]