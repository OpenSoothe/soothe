"""Golden wire trace for IG-556 stream termination ordering (coalescer path)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from soothe_daemon.query.stream_delivery import (
    STRANGE_LOOP_COMPLETED,
    StreamDeliveryCoalescer,
)

_GOLDEN = Path(__file__).with_name("golden") / "ig556_minimal_turn_wire_trace.json"


def _gc_chunk(content: str) -> tuple[tuple[()], str, tuple]:
    return (
        (),
        "messages",
        (
            {
                "type": "AIMessageChunk",
                "content": content,
                "phase": "goal_completion",
            },
            {},
        ),
    )


def _normalize_wire_trace(
    tuples: list[tuple[tuple[str, ...], str, Any]],
) -> list[dict[str, Any]]:
    """Reduce stream tuples to kind/type/scope fields for golden comparison."""
    trace: list[dict[str, Any]] = []
    for _ns, mode, data in tuples:
        if mode == "messages":
            body: dict[str, Any] | None = None
            if isinstance(data, (tuple, list)) and data:
                first = data[0]
                body = first if isinstance(first, dict) else None
            elif isinstance(data, dict):
                body = data
            if body is None:
                continue
            trace.append(
                {
                    "kind": "messages",
                    "phase": body.get("phase"),
                    "chunk_position": body.get("chunk_position"),
                    "stream_terminal": body.get("stream_terminal"),
                }
            )
            continue
        if mode == "custom" and isinstance(data, dict):
            entry: dict[str, Any] = {
                "kind": "custom",
                "type": data.get("type"),
            }
            if "scope" in data:
                entry["scope"] = data.get("scope")
            trace.append(entry)
    return trace


def test_minimal_turn_wire_trace_matches_golden() -> None:
    """Terminal content → stream.end scopes → strange_loop.completed (coalescer)."""
    coalescer = StreamDeliveryCoalescer("batch")
    coalescer.ingest(*_gc_chunk("synthesis tail"))
    tuples = coalescer.ingest(
        (),
        "custom",
        {"type": STRANGE_LOOP_COMPLETED, "status": "done"},
    )
    trace = _normalize_wire_trace(tuples)
    expected = json.loads(_GOLDEN.read_text(encoding="utf-8"))
    assert trace == expected
