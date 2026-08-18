"""Plugin-side event registration.

Event registration now lives in :mod:`soothe_sdk.core.registry`, which owns
the canonical ``EventRegistry`` / ``EventMeta`` / ``EventPriority`` trio and
the shared ``REGISTRY`` singleton. This module re-exports ``register_event``
so plugin authors can keep the ``from soothe_sdk.plugin import register_event``
import path.
"""

from __future__ import annotations

from soothe_sdk.core.registry import register_event

__all__ = ["register_event"]
