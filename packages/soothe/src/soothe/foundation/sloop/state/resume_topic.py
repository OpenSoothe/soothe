"""Resume picker topic labels for completed loops (TUI /resume)."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from soothe.foundation.sloop.utils.stream_normalize import extract_text_from_message_content

if TYPE_CHECKING:
    from soothe.config import SootheConfig

logger = logging.getLogger(__name__)

_TOPIC_MAX_WORDS = 8
_LEDGER_ABBREV_MAX_CHARS = 512
_PER_LINE_MAX_CHARS = 96
_inflight_loop_ids: set[str] = set()

_TOPIC_PROMPT = """Summarize this agent loop transcript as a short resume topic label.
Reply with ONLY the topic text: at most {max_words} words, no quotes or punctuation-only answer.
{language_instruction}

Transcript:
{transcript}
"""


def _resume_topic_language_instruction(response_language: object | None) -> str:
    from soothe.foundation.sloop.intention.models import (
        ResponseLanguage,
        normalize_response_language,
    )

    resolved = normalize_response_language(response_language)
    if resolved is None or resolved == ResponseLanguage.OTHER:
        return "Prefer the same natural language as the user's goal when obvious."
    display = {
        ResponseLanguage.EN: "English",
        ResponseLanguage.ZH: "Chinese",
        ResponseLanguage.JA: "Japanese",
        ResponseLanguage.KO: "Korean",
    }.get(resolved, resolved.value)
    return f"Write the topic label in {display} ({resolved.value})."


def _topic_is_set(value: str | None) -> bool:
    return bool(str(value or "").strip())


async def _load_existing_resume_topic(config: SootheConfig, loop_id: str) -> str | None:
    from soothe.foundation.sloop.state.persistence.manager import (
        StrangeLoopCheckpointPersistenceManager,
    )

    manager = await StrangeLoopCheckpointPersistenceManager.for_shared_checkpoint_pool(config)
    try:
        metadata = await manager.get_loop_metadata(loop_id)
    finally:
        await manager.close()
    if not metadata:
        return None
    stored = metadata.get("resume_topic")
    return str(stored).strip() if _topic_is_set(stored) else None


def _message_role(msg: BaseMessage) -> str:
    if isinstance(msg, HumanMessage):
        return "U"
    if isinstance(msg, AIMessage):
        return "A"
    msg_type = getattr(msg, "type", None)
    if msg_type == "human":
        return "U"
    if msg_type == "ai":
        return "A"
    return "?"


def _clip_line(text: str, max_chars: int) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= max_chars:
        return collapsed
    if max_chars <= 1:
        return collapsed[:max_chars]
    return collapsed[: max_chars - 1] + "…"


def abbreviate_ledger_for_topic(
    messages: list[Any],
    *,
    max_chars: int = _LEDGER_ABBREV_MAX_CHARS,
) -> str:
    """Compact ledger text for resume-topic LLM input.

    Args:
        messages: Loop ledger messages (``LoopHumanMessage`` / ``LoopAIMessage`` or LC types).
        max_chars: Maximum total characters for the abbreviated transcript.

    Returns:
        Abbreviated single-line-per-turn transcript capped at ``max_chars``.
    """
    if max_chars <= 0 or not messages:
        return ""

    lines: list[str] = []
    for msg in messages:
        if not isinstance(msg, BaseMessage):
            continue
        text = extract_text_from_message_content(getattr(msg, "content", "")).strip()
        if not text:
            continue
        phase = getattr(msg, "phase", None)
        phase_tag = f"[{phase}] " if isinstance(phase, str) and phase else ""
        lines.append(f"{_message_role(msg)}: {phase_tag}{_clip_line(text, _PER_LINE_MAX_CHARS)}")

    if not lines:
        return ""

    joined = "\n".join(lines)
    if len(joined) <= max_chars:
        return joined

    # Keep the most recent turns when over budget.
    kept: list[str] = []
    total = 0
    for line in reversed(lines):
        extra = len(line) + (1 if kept else 0)
        if total + extra > max_chars:
            break
        kept.insert(0, line)
        total += extra
    if not kept:
        return joined[-max_chars:]
    return "\n".join(kept)


def enforce_topic_word_limit(text: str, *, max_words: int = _TOPIC_MAX_WORDS) -> str:
    """Trim topic text to at most ``max_words`` words."""
    words = " ".join(text.split()).split()
    if not words:
        return ""
    return " ".join(words[:max_words])


def normalize_topic_response(raw: str) -> str:
    """Normalize LLM topic output to a short plain label."""
    text = " ".join(str(raw or "").strip().strip("\"'`").split())
    return enforce_topic_word_limit(text)


async def generate_resume_topic_from_ledger(
    config: SootheConfig,
    ledger_messages: list[Any],
    *,
    fast_llm: Any | None = None,
    response_language: object | None = None,
) -> str | None:
    """Generate a resume topic label from abbreviated ledger text.

    Args:
        config: Soothe configuration (for fast model + rate limits).
        ledger_messages: Loop ledger messages after goal completion.
        fast_llm: Optional pre-created fast model instance.

    Returns:
        Topic string (<=8 words) or ``None`` when generation fails.
    """
    transcript = abbreviate_ledger_for_topic(ledger_messages)
    if not transcript:
        return None

    model = fast_llm
    if model is None:
        try:
            model = config.create_chat_model("fast")
        except Exception:
            logger.debug("Resume topic: fast model unavailable", exc_info=True)
            return None

    prompt = _TOPIC_PROMPT.format(
        max_words=_TOPIC_MAX_WORDS,
        language_instruction=_resume_topic_language_instruction(response_language),
        transcript=transcript,
    )

    async def _invoke() -> Any:
        return await model.ainvoke([HumanMessage(content=prompt)])

    try:
        from soothe.utils.llm.invoke_policy import (
            await_with_llm_call_policy,
            llm_rate_limit_config_from,
        )

        response = await await_with_llm_call_policy(
            _invoke,
            config=llm_rate_limit_config_from(config),
            thread_id=None,
        )
    except Exception:
        logger.warning("Resume topic LLM call failed", exc_info=True)
        return None

    content = extract_text_from_message_content(getattr(response, "content", ""))
    topic = normalize_topic_response(content)
    return topic or None


async def persist_resume_topic_once(
    *,
    config: SootheConfig,
    loop_id: str,
    topic: str,
) -> bool:
    """Persist generated resume topic when none is stored yet."""
    from soothe.foundation.sloop.state.persistence.manager import (
        StrangeLoopCheckpointPersistenceManager,
    )

    manager = await StrangeLoopCheckpointPersistenceManager.for_shared_checkpoint_pool(config)
    try:
        return await manager.set_resume_topic_once(loop_id, topic.strip())
    finally:
        await manager.close()


async def generate_and_persist_resume_topic(
    *,
    config: SootheConfig,
    loop_id: str,
    ledger_messages: list[Any],
    fast_llm: Any | None = None,
    response_language: object | None = None,
) -> None:
    """Background task: summarize ledger and store resume topic once."""
    if await _load_existing_resume_topic(config, loop_id):
        logger.debug("Resume topic already stored for loop %s; skipping generation", loop_id)
        return

    topic = await generate_resume_topic_from_ledger(
        config,
        ledger_messages,
        fast_llm=fast_llm,
        response_language=response_language,
    )
    if not topic:
        logger.debug("Resume topic generation skipped for loop %s (empty result)", loop_id)
        return

    if await _load_existing_resume_topic(config, loop_id):
        logger.debug(
            "Resume topic appeared while generating for loop %s; skipping persist",
            loop_id,
        )
        return

    stored = await persist_resume_topic_once(config=config, loop_id=loop_id, topic=topic)
    if stored:
        logger.info("Stored resume topic for loop %s: %s", loop_id, topic)
    else:
        logger.debug("Resume topic already stored for loop %s; persist skipped", loop_id)


def schedule_resume_topic_generation(
    *,
    config: SootheConfig,
    loop_id: str,
    ledger_messages: list[Any],
    goals_completed: int,
    fast_llm: Any | None = None,
    existing_resume_topic: str | None = None,
    response_language: object | None = None,
) -> None:
    """Fire-and-forget resume topic generation after the first goal completes."""
    if goals_completed != 1:
        return
    if not ledger_messages:
        return
    if _topic_is_set(existing_resume_topic):
        return
    if loop_id in _inflight_loop_ids:
        return
    _inflight_loop_ids.add(loop_id)

    async def _run() -> None:
        try:
            await generate_and_persist_resume_topic(
                config=config,
                loop_id=loop_id,
                ledger_messages=list(ledger_messages),
                fast_llm=fast_llm,
                response_language=response_language,
            )
        except Exception:
            logger.warning(
                "Background resume topic generation failed for loop %s",
                loop_id,
                exc_info=True,
            )
        finally:
            _inflight_loop_ids.discard(loop_id)

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.debug("No running event loop; skipping resume topic generation for %s", loop_id)
        return
    loop.create_task(_run(), name=f"resume-topic-{loop_id[:12]}")
