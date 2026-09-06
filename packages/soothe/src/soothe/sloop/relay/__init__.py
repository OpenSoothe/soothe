"""LoopRelay — single typed bridge between StrangeLoop and CoreAgent graphs.

Public surface: `LoopRelay` and the dataclasses it returns as outcomes. The
orchestrator (`relay.relay`) is imported lazily via `__getattr__` so importing
a light submodule (`relay.router`, `relay.outbox`, `relay.snapshot`) does not
trigger the full dependency chain (`relay.channel` →
`clarification.protocol`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from soothe.sloop.relay.errors import (
        RelayCaptureError,
        RelayConcurrentResumeError,
        RelayError,
        RelayResumeMismatchError,
        RelayStaleInterruptError,
    )
    from soothe.sloop.relay.relay import (
        CaptureOutcome,
        LoopRelay,
        RelaySnapshot,
        RouteDecision,
    )

__all__ = [
    "CaptureOutcome",
    "LoopRelay",
    "RelayCaptureError",
    "RelayConcurrentResumeError",
    "RelayError",
    "RelayResumeMismatchError",
    "RelaySnapshot",
    "RelayStaleInterruptError",
    "RouteDecision",
]


def __getattr__(name: str) -> Any:
    if name in {"LoopRelay", "CaptureOutcome", "RouteDecision", "RelaySnapshot"}:
        from soothe.sloop.relay import relay as _relay_mod

        return getattr(_relay_mod, name)
    if name in {
        "RelayError",
        "RelayStaleInterruptError",
        "RelayConcurrentResumeError",
        "RelayResumeMismatchError",
        "RelayCaptureError",
    }:
        from soothe.sloop.relay import errors as _errors_mod

        return getattr(_errors_mod, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
