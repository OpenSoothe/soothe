"""Core type definitions for the Soothe SDK.

This module provides canonical type definitions used across the SDK.
Single source of truth for shared types to prevent duplication.
"""

from __future__ import annotations

from typing import Literal

VerbosityLevel = Literal["quiet", "minimal", "normal", "detailed", "debug"]
"""User-configured verbosity level for filtering display content.

Both `minimal` and `normal` are valid verbosity levels that map to VerbosityTier.NORMAL.
This provides flexibility for user preference without changing behavior.
"""

__all__ = ["VerbosityLevel"]
