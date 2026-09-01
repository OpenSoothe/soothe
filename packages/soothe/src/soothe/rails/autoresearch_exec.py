"""Native autoresearch rail execution helpers.

The `autoresearch` rail (`builtin_rails/autoresearch.yml`) uses YAML
`do:` recipes for `decompose_parallel` and `spawn_feedback_cycle` and
`brief:` overrides for `review` / `qa_verify`. The generic
`_do_plan_and_implement` fallback, however, spawns code-planning +
code-implementation goals with TDD / worktree discipline — wrong for research
synthesis.

This module supplies research-specific brief builders and a native
`plan_and_implement` dispatch path so the autoresearch rail synthesizes an
adaptive report from gathered evidence instead of writing production code.

Dispatch is rail-id-aware: `RailBuiltinExecutor.invoke` routes to
`AutoresearchExec.plan_and_implement` only when `state.rail_id ==
"autoresearch"`; all other verbs fall through to the generic `_do_*`
handlers or YAML `do:` recipes.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from soothe.rails.builtins_exec import (
    BuiltinResult,
)

if TYPE_CHECKING:
    from soothe.rails.builtins_exec import RailBuiltinExecutor, RailJobState

logger = logging.getLogger(__name__)

AUTORESEARCH_RAIL_ID = "autoresearch"

# Tag vocabulary for autoresearch goal annotations (mirrors YAML ``do:`` recipes).
RESEARCH_TAGS_PLANNING = ["research", "planning", "questions"]
RESEARCH_TAGS_SYNTHESIS = ["research", "synthesis"]
RESEARCH_TAGS_SCOUT = ["research", "scout"]
RESEARCH_TAGS_FEEDBACK = ["feedback", "research"]

# Scope banner discipline for public-web-only research (RFC-630).
RESEARCH_SCOPE_BANNER = (
    "Scope: public-web-only research. Use web search and crawl discovered "
    "URLs. Do not access private/internal systems or local codebase analysis. "
    "Cite a source URL for every factual claim."
)


def research_plan_brief(*, job_id: str) -> str:
    """Synthesis plan goal brief for autoresearch `plan_and_implement`.

    Reviews gathered scout/feedback evidence and produces a concrete report
    outline (sections, key findings per section, source citations). Does not
    write the report itself — that is the synthesis writer goal.
    """
    return (
        f"Research synthesis plan for job {job_id}. Review gathered evidence "
        "(scout findings, feedback gather/verify results) against the research "
        "acceptance contract. Produce a concrete adaptive-report outline: "
        "section list, key findings per section with source citations, and "
        "gaps remaining. Do not write the report prose here; plan only.\n\n"
        f"{RESEARCH_SCOPE_BANNER}\n\n"
        "REQUIRED deliverable: a flat JSON object with a 'sections' list "
        '(each entry: {"title", "key_findings", "source_urls", '
        '"gap": "closed|open"}). independence must be a plain string '
        "describing why sections are disjoint. No nested trees."
    )


def research_synthesis_brief(*, job_id: str) -> str:
    """Synthesis writer goal brief for autoresearch `plan_and_implement`.

    Composes the adaptive report from the synthesis plan and gathered
    evidence. Does not re-gather web sources.
    """
    return (
        f"Research report synthesis for job {job_id}. Compose the adaptive "
        "report from the synthesis plan and gathered evidence. Follow the "
        "plan's section structure; cite source URLs inline for every factual "
        "claim. Mark open gaps explicitly rather than inventing answers. "
        "Do not re-gather web sources here.\n\n"
        f"{RESEARCH_SCOPE_BANNER}"
    )


def research_scout_inform_ids(state: RailJobState, ce: Any) -> list[str]:
    """Collect completed scout/feedback gather goal ids to inform synthesis.

    Includes goals tagged `research` + (`scout` or `gather`) that are
    completed. Mirrors the generic `_do_plan_and_implement` inform pattern
    but filtered for research roles rather than `exploration`.
    """
    out: list[str] = []
    for gid, ann in state.annotations.items():
        tags = set(ann.tags or [])
        if "research" not in tags:
            continue
        if not (tags & {"scout", "gather"}):
            continue
        g = ce._dag.get_goal(gid)
        if g is not None and g.status == "completed":
            out.append(gid)
    return out


class AutoresearchExec:
    """Native autoresearch rail execution helpers.

    Bound to a `RailBuiltinExecutor` instance. Dispatched by
    `invoke()` only when `state.rail_id == AUTORESEARCH_RAIL_ID`.

    All methods are async and return `BuiltinResult` to match the
    `_do_*` contract. They use the executor's CE and annotation APIs so
    state persistence and GoalNode mirroring are identical to generic verbs.
    """

    def __init__(self, executor: RailBuiltinExecutor) -> None:
        self._ex = executor

    async def plan_and_implement(
        self, *, job_id: str, trigger_goal_id: str | None
    ) -> BuiltinResult:
        """Spawn synthesis plan → synthesis writer goals (research variant).

        Unlike the generic `_do_plan_and_implement` (code planning + code
        implementation with TDD/worktree discipline), this spawns:
          1. A synthesis plan goal (reviews evidence, produces report outline)
          2. A synthesis writer goal (composes the adaptive report)

        Neither goal applies maker discipline (TDD, worktrees, systematic
        debugging) — research synthesis is writing, not coding.
        """
        del trigger_goal_id
        state = await self._ex._require(job_id)

        informs = research_scout_inform_ids(state, self._ex._ce)

        plan = await self._ex._ce.create_goal(
            research_plan_brief(job_id=job_id),
            parent_id=job_id,
            depends_on=informs or None,
            source="decomposition",
            priority=70,
            informs=informs or None,
            rail_id=state.rail_id,
        )
        await self._ex.annotate_goal(
            plan.id,
            job_id,
            tags=list(RESEARCH_TAGS_PLANNING),
            role="planner",
            branch_id=job_id,
        )

        synth = await self._ex._ce.create_goal(
            research_synthesis_brief(job_id=job_id),
            parent_id=job_id,
            depends_on=[plan.id],
            source="decomposition",
            priority=75,
            informs=informs or None,
            rail_id=state.rail_id,
        )
        await self._ex.annotate_goal(
            synth.id,
            job_id,
            tags=list(RESEARCH_TAGS_SYNTHESIS),
            role="writer",
            branch_id=job_id,
        )

        logger.info(
            "autoresearch plan_and_implement job=%s plan=%s synth=%s informs=%d",
            job_id[:8],
            plan.id[:8],
            synth.id[:8],
            len(informs),
        )
        return BuiltinResult(
            status="success",
            detail="spawned research synthesis plan+writer",
            created_goal_ids=[plan.id, synth.id],
        )

    async def review(self, *, job_id: str, trigger_goal_id: str | None) -> BuiltinResult:
        """Native review for autoresearch — synthesis draft review.

        Falls back to the generic `_do_review` when the rail YAML provides
        a `brief:` override (it does). This method is only called when
        `invoke()` detects autoresearch and the verb has no `do:` recipe
        — but `review` has a `brief:` override in the YAML, so the generic
        `_do_review` already resolves the correct brief via
        `resolve_verb_brief`. Kept as a hook for future research-specific
        review logic.
        """
        return await self._ex._do_review(job_id=job_id, trigger_goal_id=trigger_goal_id)

    async def qa_verify(self, *, job_id: str, trigger_goal_id: str | None) -> BuiltinResult:
        """Native QA verify for autoresearch — source/claim verification.

        Like `review`, the YAML provides a `brief:` override so the generic
        `_do_qa_verify` resolves the correct brief. Kept as a hook.
        """
        return await self._ex._do_qa_verify(job_id=job_id, trigger_goal_id=trigger_goal_id)


def is_autoresearch_job(state: RailJobState | None) -> bool:
    """True when the bound rail is the autoresearch rail."""
    return state is not None and state.rail_id == AUTORESEARCH_RAIL_ID


def get_autoresearch_exec(executor: RailBuiltinExecutor) -> AutoresearchExec | None:
    """Return an `AutoresearchExec` bound to `executor` (lazy, no state).

    Returns `None` is impossible — the executor always has the required
    CE and annotation APIs. Caller checks `is_autoresearch_job` first.
    """
    return AutoresearchExec(executor)


__all__ = [
    "AUTORESEARCH_RAIL_ID",
    "AutoresearchExec",
    "RESEARCH_SCOPE_BANNER",
    "RESEARCH_TAGS_FEEDBACK",
    "RESEARCH_TAGS_PLANNING",
    "RESEARCH_TAGS_SCOUT",
    "RESEARCH_TAGS_SYNTHESIS",
    "get_autoresearch_exec",
    "is_autoresearch_job",
    "research_plan_brief",
    "research_scout_inform_ids",
    "research_synthesis_brief",
]
