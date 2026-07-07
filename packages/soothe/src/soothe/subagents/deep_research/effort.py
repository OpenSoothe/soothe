"""Effort levels for deep_research — normal and thorough."""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from .protocol import DeepResearchConfig, DeepResearchEffortLevel

_EFFORT_PATTERN = re.compile(
    r"(?:^|\b)effort\s*[:=]\s*(normal|thorough)\b",
    re.IGNORECASE,
)


class DeepResearchEffortProfile(BaseModel):
    """Hard caps for one effort level."""

    effort: DeepResearchEffortLevel
    max_sub_questions: int = Field(ge=1, le=20)
    max_initial_queries: int = Field(ge=1, le=20)
    max_follow_up_queries: int = Field(ge=0, le=10)
    max_loops: int = Field(ge=1, le=10)
    crawl_top_n: int = Field(ge=1, le=10)

    @property
    def plan_hint(self) -> str:
        return (
            f"Identify at most {self.max_sub_questions} sub-questions and "
            f"at most {self.max_initial_queries} search queries."
        )

    @property
    def reflect_follow_up_hint(self) -> str:
        if self.max_follow_up_queries == 0:
            return (
                "If not sufficient, set is_sufficient to true; do not generate follow-up queries."
            )
        return (
            f"If not sufficient, generate at most {self.max_follow_up_queries} "
            "follow-up queries targeting the gaps."
        )


_PROFILES: dict[DeepResearchEffortLevel, DeepResearchEffortProfile] = {
    "normal": DeepResearchEffortProfile(
        effort="normal",
        max_sub_questions=3,
        max_initial_queries=4,
        max_follow_up_queries=1,
        max_loops=2,
        crawl_top_n=3,
    ),
    "thorough": DeepResearchEffortProfile(
        effort="thorough",
        max_sub_questions=5,
        max_initial_queries=8,
        max_follow_up_queries=2,
        max_loops=4,
        crawl_top_n=5,
    ),
}


def profile_for_effort(effort: DeepResearchEffortLevel) -> DeepResearchEffortProfile:
    """Return the profile for a validated effort level."""
    return _PROFILES[effort]


def normalize_effort(raw: str | None) -> DeepResearchEffortLevel:
    """Coerce config/context value to a valid effort level."""
    key = (raw or "normal").strip().lower()
    if key == "thorough":
        return "thorough"
    return "normal"


def parse_effort_from_text(text: str) -> DeepResearchEffortLevel | None:
    """Parse ``effort: thorough`` from topic text."""
    if not text:
        return None
    match = _EFFORT_PATTERN.search(text.strip())
    if not match:
        return None
    return normalize_effort(match.group(1))


def resolve_effort(
    config: DeepResearchConfig,
    *,
    topic: str = "",
    context_effort: str | None = None,
    context_max_loops: int | None = None,
) -> tuple[DeepResearchEffortLevel, DeepResearchEffortProfile]:
    """Resolve effort and profile."""
    effort: DeepResearchEffortLevel = "normal"
    if parsed := parse_effort_from_text(topic):
        effort = parsed
    elif context_effort:
        effort = normalize_effort(context_effort)
    else:
        effort = normalize_effort(getattr(config, "effort", "normal"))

    profile = _PROFILES[effort]
    if context_max_loops is not None and context_max_loops != profile.max_loops:
        profile = profile.model_copy(update={"max_loops": context_max_loops})
    return effort, profile
