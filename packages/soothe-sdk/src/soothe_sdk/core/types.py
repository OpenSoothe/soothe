"""Core type definitions for the Soothe SDK.

This module provides canonical type definitions used across the SDK.
Single source of truth for shared types to prevent duplication.
"""

from __future__ import annotations

from typing import Literal

VerbosityLevel = Literal["quiet", "normal", "debug"]
"""User-configured verbosity level for filtering display content."""

__all__ = ["VerbosityLevel"]
