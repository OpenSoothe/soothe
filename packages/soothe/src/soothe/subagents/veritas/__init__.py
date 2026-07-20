"""Veritas subagent: intent-grounded clarification auto-answerer (RFC-622)."""

from __future__ import annotations

from importlib import import_module
from typing import Any

# Side-effect: register wire events (must not pull implementation)
from soothe.subagents.veritas import events as _veritas_events  # noqa: F401
from soothe.subagents.veritas.events import (
    SUBAGENT_VERITAS_ANSWERED,
    SUBAGENT_VERITAS_DEFERRED,
    SUBAGENT_VERITAS_REQUESTED,
    VeritasAnsweredEvent,
    VeritasDeferredEvent,
    VeritasRequestedEvent,
)
from soothe.subagents.veritas.schemas import (
    VeritasAnswerSchema,
    build_veritas_response_schema,
)

__all__ = [
    "SUBAGENT_VERITAS_ANSWERED",
    "SUBAGENT_VERITAS_DEFERRED",
    "SUBAGENT_VERITAS_REQUESTED",
    "VeritasAnswerSchema",
    "VeritasAnsweredEvent",
    "VeritasDeferredEvent",
    "VeritasRequestedEvent",
    "answer",
    "build_veritas_response_schema",
]


def __getattr__(name: str) -> Any:
    if name == "answer":
        return import_module("soothe.subagents.veritas.implementation").answer
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
