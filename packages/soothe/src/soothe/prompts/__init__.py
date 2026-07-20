"""Soothe prompts: L2 user_message + CoreAgent templates from nano."""

from __future__ import annotations

from typing import Any

from soothe.prompts.user_message import *  # noqa: F403

__all__ = [n for n in globals() if not n.startswith("_")]


def __getattr__(name: str) -> Any:
    from importlib import import_module

    return getattr(import_module("soothe_nano.prompts"), name)
