"""Resume picker topic labels (TUI /resume)."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from soothe.config import SootheConfig

logger = logging.getLogger(__name__)

_TOPIC_MAX_WORDS = 10


def enforce_topic_word_limit(text: str, *, max_words: int = _TOPIC_MAX_WORDS) -> str:
    """Trim topic text to at most ``max_words`` words."""
    words = " ".join(text.split()).split()
    if not words:
        return ""
    return " ".join(words[:max_words])


def derive_resume_topic(
    *,
    pass1_reasoning: str | None,
    goal_text: str | None,
) -> str | None:
    """Build resume-picker topic from Pass 1 reasoning or original user goal.

    Args:
        pass1_reasoning: ``reasoning`` field from the first goal's Pass 1 intake result.
        goal_text: Verbatim user submission when Pass 1 reasoning is empty.

    Returns:
        Abbreviated topic label (<=10 words), or ``None`` when both sources are empty.
    """
    source = (pass1_reasoning or "").strip() or (goal_text or "").strip()
    if not source:
        return None
    normalized = " ".join(source.strip().strip("\"'`").split())
    topic = enforce_topic_word_limit(normalized)
    return topic or None


async def persist_resume_topic_if_needed(
    *,
    config: SootheConfig,
    loop_id: str,
    pass1_reasoning: str | None = None,
    goal_text: str | None = None,
) -> None:
    """Derive and store the first-goal resume topic once."""
    from soothe.sloop.checkpoints.manager import (
        StrangeLoopCheckpointPersistenceManager,
    )

    topic = derive_resume_topic(pass1_reasoning=pass1_reasoning, goal_text=goal_text)
    if not topic:
        logger.debug("Resume topic skipped for loop %s (empty sources)", loop_id)
        return

    manager = await StrangeLoopCheckpointPersistenceManager.for_shared_checkpoint_pool(config)
    try:
        stored = await manager.set_resume_topic_once(loop_id, topic)
    finally:
        await manager.close()

    if stored:
        logger.info("Stored resume topic for loop %s: %s", loop_id, topic)


def schedule_resume_topic_persistence(
    *,
    config: SootheConfig,
    loop_id: str,
    pass1_reasoning: str | None,
    goal_text: str | None,
    is_first_loop_goal: bool,
) -> None:
    """Fire-and-forget resume topic persistence at first-goal intake."""
    if not is_first_loop_goal:
        return
    if not (pass1_reasoning or "").strip() and not (goal_text or "").strip():
        return

    async def _run() -> None:
        try:
            await persist_resume_topic_if_needed(
                config=config,
                loop_id=loop_id,
                pass1_reasoning=pass1_reasoning,
                goal_text=goal_text,
            )
        except Exception:
            logger.warning(
                "Background resume topic persistence failed for loop %s",
                loop_id,
                exc_info=True,
            )

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.debug("No running event loop; skipping resume topic for %s", loop_id)
        return
    loop.create_task(_run(), name=f"resume-topic-{loop_id[:12]}")
