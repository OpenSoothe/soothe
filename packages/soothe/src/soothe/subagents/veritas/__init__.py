"""Veritas subagent: intent-grounded clarification auto-answerer (RFC-622)."""

from __future__ import annotations

from importlib import import_module
from typing import Any

from soothe.subagents.veritas.schemas import (
    VeritasAnswerSchema,
    build_veritas_response_schema,
)

__all__ = [
    "VeritasAnswerSchema",
    "answer",
    "build_veritas_response_schema",
]


def __getattr__(name: str) -> Any:
    if name == "answer":
        return import_module("soothe.subagents.veritas.implementation").answer
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
