"""LLM step-completion progress line for TUI display (no ledger write)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

    from soothe.config import SootheConfig

logger = logging.getLogger(__name__)

_STEP_COMPLETION_REPORT_SYSTEM = (
    "You write brief step-completion status lines for the user watching progress.\n"
    "Given the execute-step input and assistant output, respond with exactly one "
    "first-person sentence (I/we) of at most {max_words} words.\n"
    "No preamble, quotes, or bullet points."
)

_CONTENT_CAP = 8000


async def summarize_step_completion_report(
    *,
    human_content: str,
    ai_content: str,
    fast_model: BaseChatModel,
    soothe_config: SootheConfig | None = None,
    goal_trace: Any | None = None,
    max_words: int | None = None,
) -> str | None:
    """Summarize a completed execute step for TUI cognition display.

    Uses only the single-step human/ai pair (no prior steps or goal messages).
    Delegates message assembly to :class:`GraphPromptWrapper` so the system
    prompt lives in one place alongside all other LLM-invoking nodes.

    Args:
        human_content: Compact execute-step human input (ledger-style).
        ai_content: Final assistant output for the step.
        fast_model: Fast router model for the summary call.
        soothe_config: Optional config for rate limits and tracing.
        goal_trace: Optional trace context for observability.
        max_words: Optional prompt word target; defaults to config or 50 when omitted.

    Returns:
        First-person summary text, or None when input is empty or the call fails.
    """
    from soothe_nano.llm import ainvoke_traced

    from soothe.prompts.graph_wrapper import GraphPromptWrapper

    human = (human_content or "").strip()[:_CONTENT_CAP]
    ai = (ai_content or "").strip()[:_CONTENT_CAP]
    if not human and not ai:
        return None

    word_limit = max_words
    if word_limit is None:
        word_limit = (
            soothe_config.agent.loop.step_completion_report_max_words
            if soothe_config is not None
            else 50
        )

    wrapper = GraphPromptWrapper(soothe_config)
    messages = wrapper.build_step_completion_messages(
        human_content=human,
        ai_content=ai,
        max_words=word_limit,
    )

    from soothe.utils.observability.langfuse import execute_step_langfuse_run_display_name

    cfg = getattr(goal_trace, "soothe_config", None) or soothe_config
    tn = (cfg.observability.langfuse.trace_name or "").strip() if cfg is not None else ""

    try:
        response = await ainvoke_traced(
            fast_model,
            messages,
            soothe_config=soothe_config,
            purpose="step_completion_report",
            component="executor.step_completion_report",
            phase="execute_step",
            run_name=execute_step_langfuse_run_display_name(tn or None),
            goal_trace=goal_trace,
        )
        content = getattr(response, "content", response)
        if isinstance(content, list):
            parts: list[str] = []
            for block in content:
                if isinstance(block, dict):
                    text = block.get("text")
                    if isinstance(text, str):
                        parts.append(text)
                elif isinstance(block, str):
                    parts.append(block)
            content = " ".join(parts)
        raw = str(content or "").strip()
    except Exception:
        logger.warning("Step completion report LLM call failed", exc_info=True)
        return None

    return raw or None


__all__ = ["summarize_step_completion_report"]
