"""Subagents package: CoreAgent delegates (nano) + veritas (soothe)."""

from __future__ import annotations

from importlib import import_module

# Register nano CoreAgent subagent wire events (no veritas)
import soothe_nano.subagents  # noqa: F401

__all__: list[str] = ["veritas"]


def __getattr__(name: str):
    if name == "veritas":
        return import_module("soothe.subagents.veritas")
    return getattr(import_module("soothe_nano.subagents"), name)
