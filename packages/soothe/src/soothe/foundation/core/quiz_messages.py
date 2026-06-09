"""System message content for quiz-path LLM calls."""

from __future__ import annotations

from pathlib import Path

_FRAGMENTS_DIR = Path(__file__).resolve().parent.parent / "loop" / "prompts" / "fragments"


def _read_fragment(relative: str) -> str:
    return _FRAGMENTS_DIR.joinpath(relative).read_text(encoding="utf-8").strip()


def build_quiz_system_message(assistant_name: str) -> str:
    """Build the system message for quiz fast-path LLM invocations.

    Used by intent classification (piggybacked ``quiz_response``) and by the
    runner quiz fallback. Quiz calls do not go through ``SystemPromptMiddleware``,
    so identity must be set here explicitly.

    Args:
        assistant_name: Configured assistant display name (e.g. ``Soothe``).

    Returns:
        System prompt text including assistant identity and quiz response rules.
    """
    identity_template = _read_fragment("system/prompts/simple_system.xml")
    guide = _read_fragment("system/response_guides/quiz_response.xml")
    identity = identity_template.format(assistant_name=assistant_name).strip()
    return (
        f"{identity}\n\n"
        f"{guide}\n\n"
        "When the user asks who you are, identify yourself using your assistant name above. "
        "Do not claim to be Claude, ChatGPT, Gemini, or another vendor or base model."
    )
