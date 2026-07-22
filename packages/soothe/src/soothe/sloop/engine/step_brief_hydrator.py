"""Between-wave LLM hydration for dependent step execution briefs."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field
from soothe_nano.utils.llm.structured import invoke_structured_chat_typed

from soothe.sloop.engine.step_predecessor_context import template_hydrate_step_brief

if TYPE_CHECKING:
    from soothe.config import SootheConfig
    from soothe.sloop.state.schemas import StepAction

logger = logging.getLogger(__name__)


class StepBriefHydration(BaseModel):
    """Structured output for between-wave step brief hydration."""

    full_description: str = Field(
        ...,
        description=(
            "Standalone execution brief (50-120 words) referencing concrete "
            "findings from prior step evidence; no rediscovery commands."
        ),
    )


class StepBriefHydrator:
    """Expand vague dependent-step briefs using predecessor evidence."""

    def __init__(self, model: Any, config: SootheConfig | None = None) -> None:
        self._model = model
        self._config = config

    async def hydrate(
        self,
        step: StepAction,
        *,
        predecessor_evidence: str,
        goal: str,
    ) -> str:
        """Return a hydrated ``full_description`` for ``step``."""
        fallback = template_hydrate_step_brief(
            step,
            predecessor_evidence,
        )
        if self._model is None or not predecessor_evidence.strip():
            return fallback

        prompt = (
            "Write a standalone execution brief for an AI coding agent.\n\n"
            f"Overall goal:\n{goal.strip() or '(unspecified)'}\n\n"
            f"Step milestone (TUI label):\n{step.description.strip()}\n\n"
            f"Prior step evidence:\n{predecessor_evidence.strip()}\n\n"
            "Rules:\n"
            "- 50-120 words, imperative tone\n"
            "- Reference concrete failures, paths, and identifiers from prior evidence\n"
            "- Do NOT instruct re-running discovery/diagnostic commands already in prior evidence\n"
            "- For diagnose→fix chains: fix listed items first; verify only after edits\n"
        )
        try:
            result = await invoke_structured_chat_typed(
                self._model,
                [{"role": "user", "content": prompt}],
                StepBriefHydration,
            )
            hydrated = (result.full_description or "").strip()
            if hydrated and len(hydrated.split()) >= 8:
                return hydrated
        except Exception:
            logger.debug("[StepBriefHydrator] LLM hydration failed; using template", exc_info=True)
        return fallback


__all__ = ["StepBriefHydration", "StepBriefHydrator"]
