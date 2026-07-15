"""Decouple daemon stream ingestion from chunk processing and UI application.

Canonical implementation lives in ``soothe_client.appkit.turn`` (RFC-629 Layer 1).
This module re-exports the public API for CLI import stability.
"""

from __future__ import annotations

from soothe_client.appkit.turn import (
    _DEFAULT_BATCH_DELAY_MS,
    _DEFAULT_BATCH_SIZE,
    _DEFAULT_INBOUND_MAXSIZE,
    _DEFAULT_OUTBOUND_MAXSIZE,
    PRIORITY_CRITICAL,
    PRIORITY_HIGH,
    PRIORITY_LOW,
    PRIORITY_NORMAL,
    TurnApplyBatcher,
    TurnEventPipeline,
    run_turn_pipeline,
)

__all__ = [
    "PRIORITY_CRITICAL",
    "PRIORITY_HIGH",
    "PRIORITY_LOW",
    "PRIORITY_NORMAL",
    "TurnApplyBatcher",
    "TurnEventPipeline",
    "run_turn_pipeline",
    "_DEFAULT_BATCH_SIZE",
    "_DEFAULT_BATCH_DELAY_MS",
    "_DEFAULT_INBOUND_MAXSIZE",
    "_DEFAULT_OUTBOUND_MAXSIZE",
]
