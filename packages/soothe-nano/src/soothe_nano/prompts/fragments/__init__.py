"""Prefetched static CoreAgent prompt fragments for cache optimization (IG-183).

This module loads static XML fragments at import time to maximize prompt cache hit rate.
All fragments are read once and cached as module constants.

Host loop plan/classifier fragments live under ``soothe.prompts``.
"""

from pathlib import Path

_FRAGMENTS_DIR = Path(__file__).parent


def _read(relative: str, *, strip: bool = False) -> str:
    text = _FRAGMENTS_DIR.joinpath(relative).read_text(encoding="utf-8")
    return text.strip() if strip else text


# Byte-for-byte preserved from previous Python literals — do not ``.strip()``
# on system prompt bodies (whitespace is part of the composed template).
DEFAULT_SYSTEM_PROMPT_BODY_FRAGMENT = _read("system/prompts/default_system_body.xml")
ASSISTANT_IDENTITY_FRAGMENT = _read("system/prompts/assistant_identity.xml", strip=True)
SIMPLE_SYSTEM_PROMPT_FRAGMENT = _read("system/prompts/simple_system.xml")
MEDIUM_SYSTEM_PROMPT_FRAGMENT = _read("system/prompts/medium_system.xml")


__all__ = [
    "ASSISTANT_IDENTITY_FRAGMENT",
    "DEFAULT_SYSTEM_PROMPT_BODY_FRAGMENT",
    "MEDIUM_SYSTEM_PROMPT_FRAGMENT",
    "SIMPLE_SYSTEM_PROMPT_FRAGMENT",
]
