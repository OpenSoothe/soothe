"""Shared utilities for worker runners (subprocess pool, thread pool, Ray actors).

Functions extracted from local_runner.py for reuse across runner implementations.
"""

from __future__ import annotations

import json
import logging
from dataclasses import replace
from typing import TYPE_CHECKING

from soothe.foundation.loop.intention import IntentHint

if TYPE_CHECKING:
    from soothe.config.settings import SootheConfig
    from soothe.protocols.runner import LoopRunRequest

logger = logging.getLogger(__name__)


def spawn_safe_config(config: SootheConfig | None) -> SootheConfig:
    """Return a copy of ``config`` safe for ``multiprocessing`` spawn pickling.

    The daemon may have populated runtime caches (chat models, embeddings,
    vector stores) that hold unpickleable synchronization primitives. The
    subprocess only needs declarative settings and rebuilds caches locally.

    Args:
        config: Loaded daemon config, or ``None`` (tests / callers without config)
            to use declarative defaults only.
    """
    from soothe.config.settings import SootheConfig

    base = config if config is not None else SootheConfig()
    return SootheConfig.model_validate(base.model_dump(mode="json"))


def spawn_safe_request(request: LoopRunRequest) -> LoopRunRequest:
    """Ensure ``model_params`` contains only JSON-round-trippable values."""
    if not request.model_params:
        return request
    safe_params = json.loads(json.dumps(request.model_params, default=str))
    return replace(request, model_params=safe_params)


def parse_intent_hint(intent_hint: str | None) -> IntentHint | None:
    """Parse intent_hint string to IntentHint enum.

    Args:
        intent_hint: String intent hint value.

    Returns:
        IntentHint enum or None if invalid/empty.
    """
    if not intent_hint:
        return None
    normalized = intent_hint.strip().lower()
    try:
        return IntentHint(normalized)
    except ValueError:
        logger.warning("Invalid intent_hint value: %s", intent_hint)
        return None


__all__ = ["spawn_safe_config", "spawn_safe_request", "parse_intent_hint"]
