"""Compatibility re-export (IG-351); implementation in ``events.stream_accumulator``."""

from soothe_cli.shared.events.stream_accumulator import (
    StreamAccumulator,
    StreamingAccumState,
    StreamingTextAccumulator,
)

__all__ = [
    "StreamAccumulator",
    "StreamingAccumState",
    "StreamingTextAccumulator",
]
