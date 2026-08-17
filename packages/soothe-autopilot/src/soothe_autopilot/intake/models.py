"""Typed guidance intake for Autopilot (IG-733).

Guidance is advisory text absorbed into ContextEngine; it never spawns goals.
"""

from __future__ import annotations

from typing import Literal

GuidanceSource = Literal["user", "channel", "system"]
GuidanceScope = Literal["job", "goal"]

GUIDANCE_SOURCES: frozenset[str] = frozenset({"user", "channel", "system"})
GUIDANCE_SCOPES: frozenset[str] = frozenset({"job", "goal"})
