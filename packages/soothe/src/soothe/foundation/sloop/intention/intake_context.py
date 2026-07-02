"""Load continuation context for pre-stream intake classification (IG-540)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from langchain_core.messages import BaseMessage

if TYPE_CHECKING:
    from soothe.config import SootheConfig

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class IntakeContext:
    """Continuation context available before StrangeLoop graph entry."""

    loop_messages: list[BaseMessage] = field(default_factory=list)
    context_engine: Any | None = None


async def load_intake_context(
    config: SootheConfig,
    loop_id: str,
    *,
    workspace: str | None = None,
) -> IntakeContext:
    """Load persisted ledger messages and a CE handle for intake classification.

    Best-effort: on any persistence failure returns an empty context so intake
    classification can still run on the raw user query.

    Args:
        config: Soothe configuration.
        loop_id: Loop identifier (conversation thread / client loop id).
        workspace: Optional workspace path for checkpoint scoping.

    Returns:
        ``IntakeContext`` with ledger messages for projection and optional CE.
    """
    loop_id = (loop_id or "").strip()
    if not loop_id:
        return IntakeContext()

    try:
        from soothe.config import SOOTHE_HOME
        from soothe.foundation.context.engine import ContextEngine
        from soothe.foundation.context.persistence.factory import (
            resolve_context_engine_persistence,
        )

        ce_config = config.agent.loop.context_engine
        persistence = resolve_context_engine_persistence(config, loop_id)
        soothe_home = Path(config.home) if hasattr(config, "home") else SOOTHE_HOME
        ce = ContextEngine(
            persistence=persistence,
            projection_config=ce_config.to_projection_config(),
            soothe_home=soothe_home,
            workspace=Path(workspace) if workspace else None,
        )
        await ce.load()
        loop_messages = [msg for msg, _phase in ce.get_ledger_entries()]
        return IntakeContext(loop_messages=loop_messages, context_engine=ce)
    except Exception:
        logger.debug(
            "Intake context load failed for loop %s; classifying without ledger projection",
            loop_id,
            exc_info=True,
        )
        return IntakeContext()


__all__ = ["IntakeContext", "load_intake_context"]
