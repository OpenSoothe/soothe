"""Tacitus effort levels — scale research depth and question breadth."""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from .protocol import TacitusConfig, TacitusEffortLevel

_EFFORT_PATTERN = re.compile(
    r"(?:^|\b)effort\s*[:=]\s*(normal|high|xhigh)\b",
    re.IGNORECASE,
)


class TacitusEffortProfile(BaseModel):
    """Hard caps and loop limits for one effort level."""

    effort: TacitusEffortLevel
    max_sub_questions: int = Field(ge=1, le=20)
    max_initial_queries: int = Field(ge=1, le=20)
    max_follow_up_queries: int = Field(ge=0, le=10)
    max_loops: int = Field(ge=1, le=10)
    max_sources_per_query: int = Field(ge=1, le=10)

    @property
    def analyze_question_hint(self) -> str:
        return f"Identify {self.max_sub_questions} or fewer key sub-questions."

    @property
    def generate_queries_hint(self) -> str:
        return f"Generate at most {self.max_initial_queries} targeted search queries."

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


_PROFILES: dict[TacitusEffortLevel, TacitusEffortProfile] = {
    "normal": TacitusEffortProfile(
        effort="normal",
        max_sub_questions=3,
        max_initial_queries=4,
        max_follow_up_queries=1,
        max_loops=2,
        max_sources_per_query=2,
    ),
    "high": TacitusEffortProfile(
        effort="high",
        max_sub_questions=5,
        max_initial_queries=6,
        max_follow_up_queries=2,
        max_loops=3,
        max_sources_per_query=3,
    ),
    "xhigh": TacitusEffortProfile(
        effort="xhigh",
        max_sub_questions=8,
        max_initial_queries=10,
        max_follow_up_queries=3,
        max_loops=5,
        max_sources_per_query=4,
    ),
}


def profile_for_effort(effort: TacitusEffortLevel) -> TacitusEffortProfile:
    """Return the profile for a validated effort level."""
    return _PROFILES[effort]


def parse_effort_from_text(text: str) -> TacitusEffortLevel | None:
    """Parse ``effort: high`` or ``effort=xhigh`` from topic or task description."""
    if not text:
        return None
    match = _EFFORT_PATTERN.search(text.strip())
    if not match:
        return None
    level = match.group(1).lower()
    if level in _PROFILES:
        return level  # type: ignore[return-value]
    return None


def normalize_effort(raw: str | None) -> TacitusEffortLevel:
    """Coerce config/context value to a valid effort level."""
    key = (raw or "normal").strip().lower()
    if key in _PROFILES:
        return key  # type: ignore[return-value]
    return "normal"


def resolve_effort(
    config: TacitusConfig,
    *,
    topic: str = "",
    context_effort: str | None = None,
    context_max_loops: int | None = None,
) -> tuple[TacitusEffortLevel, TacitusEffortProfile]:
    """Resolve effort and profile; apply explicit max_loops override when set."""
    effort: TacitusEffortLevel = "normal"
    if parsed := parse_effort_from_text(topic):
        effort = parsed
    elif context_effort:
        effort = normalize_effort(context_effort)
    else:
        effort = normalize_effort(getattr(config, "effort", "normal"))

    profile = profile_for_effort(effort)
    if context_max_loops is not None and context_max_loops != profile.max_loops:
        profile = profile.model_copy(update={"max_loops": context_max_loops})
    return effort, profile


__all__ = [
    "TacitusEffortLevel",
    "TacitusEffortProfile",
    "normalize_effort",
    "parse_effort_from_text",
    "profile_for_effort",
    "resolve_effort",
]
