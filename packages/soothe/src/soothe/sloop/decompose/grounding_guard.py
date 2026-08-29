"""Grounding guard for decompose_task proposals (d15f hallucination defense)."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field, model_validator

from soothe.context.decomposition import DecompositionProposal, ProposedSubtask

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

    from soothe.config import SootheConfig
    from soothe.utils.observability.langfuse import GoalLoopTrace

logger = logging.getLogger(__name__)

# Cap the total evidence text fed to the critic / generation prompt.
_EVIDENCE_PROMPT_CAP = 6000

# Internal wall-clock budget for the grounding critic LLM call.  When this
# elapses, the critic fails open (returns ``None`` → proposal is queued
# without grounding verification).  This must be strictly less than the
# ``decompose_task`` per-tool timeout (180 s) so the tool never gets
# killed mid-retry by the outer middleware.
_CRITIC_TIMEOUT_SECONDS = 45.0

# Internal wall-clock budget for the fast-model subtask generation call.
# Must also be < ``decompose_task`` per-tool timeout (180 s).
_GENERATE_TIMEOUT_SECONDS = 60.0


class UngroundedClaim(BaseModel):
    """A proposal claim the critic judges as unsupported by evidence."""

    subtask: int = Field(description="Index of the subtask (0-based) in the proposal")
    claim: str = Field(description="The specific unsupported claim")
    reason: str = Field(description="Why the evidence does not support this claim (concise)")


class GroundingVerdict(BaseModel):
    """Structured verdict from the FAST grounding critic."""

    grounded: bool = Field(
        description="True when every concrete claim is supported by the evidence."
    )
    ungrounded_claims: list[UngroundedClaim] = Field(
        default_factory=list,
        description="Claims NOT supported by the evidence (empty if grounded).",
    )

    @model_validator(mode="before")
    @classmethod
    def _coerce(cls, data: Any) -> Any:
        """Coerce common LLM output mistakes (strings instead of dicts)."""
        if not isinstance(data, dict):
            return data
        claims = data.get("ungrounded_claims")
        if isinstance(claims, list):
            coerced: list[Any] = []
            for c in claims:
                if isinstance(c, str):
                    coerced.append({"subtask": 0, "claim": c, "reason": ""})
                else:
                    coerced.append(c)
            data["ungrounded_claims"] = coerced
        if "grounded" not in data:
            data["grounded"] = not bool(data.get("ungrounded_claims"))
        return data


# ── Fast-model subtask generation ───────────────────────────────────────────


class GeneratedSubtask(BaseModel):
    """A single subtask produced by the FAST model from evidence."""

    description: str = Field(description="Short imperative title for this subtask")
    full_description: str = Field(
        default="",
        description=(
            "Detailed scope: files to touch, functions to modify, concrete "
            "actions. Only reference paths/modules confirmed in the evidence."
        ),
    )
    expected_output: str = Field(
        default="",
        description="What the completed subtask produces or changes.",
    )


class GeneratedSubtaskList(BaseModel):
    """Structured output schema for fast-model subtask generation."""

    subtasks: list[GeneratedSubtask] = Field(
        min_length=1,
        description="Proposed child subtasks grounded in the evidence.",
    )


_GENERATE_PROMPT = """\
You are a task decomposition assistant for an AI coding agent.

The agent is working on a step in a goal-driven loop. Below is the TASK \
description and EVIDENCE — the concatenated outputs of search/inspection \
tool calls the agent gathered in this step thread.

Decompose the TASK into 1-{max_subtasks} child subtasks that can be \
executed in parallel or in dependency order. Each subtask must be:
- Grounded: only reference files, modules, functions, or directories that \
appear in the EVIDENCE. Do not invent paths.
- Self-contained: each subtask should be independently executable.
- Concrete: the full_description must specify what to change and where.

If the task is simple enough to finish in one thread, propose exactly 1 \
subtask that covers the whole task.

TASK:
{task}

EVIDENCE:
{evidence}
"""


def _normalize_generated_subtasks(
    data: dict[str, Any],
) -> list[ProposedSubtask]:
    """Convert GeneratedSubtaskList dicts to ProposedSubtask instances."""
    raw = data.get("subtasks") or data.get("generated_subtasks") or []
    out: list[ProposedSubtask] = []
    for item in raw:
        if isinstance(item, ProposedSubtask):
            out.append(item)
            continue
        if isinstance(item, dict):
            out.append(ProposedSubtask.model_validate(item))
            continue
        out.append(ProposedSubtask.model_validate(item))
    return out


async def generate_subtasks_via_fast_model(
    task: str,
    *,
    evidence_corpus: list[str],
    fast_model: BaseChatModel | None,
    soothe_config: SootheConfig | None = None,
    step_id: str,
    max_subtasks: int = 8,
    goal_trace: GoalLoopTrace | None = None,
) -> list[ProposedSubtask] | None:
    """Generate subtasks from evidence using the FAST model.

    Returns a list of :class:`ProposedSubtask`, or ``None`` on failure \
    (caller should fall back to the main-model-provided subtasks).
    """
    if fast_model is None:
        return None
    evidence = _render_evidence(evidence_corpus)
    if not evidence_corpus:
        return None
    prompt = _GENERATE_PROMPT.format(
        task=task,
        evidence=evidence,
        max_subtasks=max_subtasks,
    )
    try:
        from soothe_nano.llm import ainvoke_structured_traced

        data = await asyncio.wait_for(
            ainvoke_structured_traced(
                fast_model,
                [{"role": "user", "content": prompt}],
                json_schema=GeneratedSubtaskList.model_json_schema(),
                schema_name="GeneratedSubtaskList",
                soothe_config=soothe_config,
                purpose="decompose_generate",
                component="sloop.decompose.grounding_guard",
                phase="execute_step",
                goal_trace=goal_trace,
                methods=("json_schema", "json_mode", "function_calling", None),
                strict=False,
            ),
            timeout=_GENERATE_TIMEOUT_SECONDS,
        )
        return _normalize_generated_subtasks(data)
    except TimeoutError:
        logger.warning(
            "[decompose] subtask generation timed out after %.0fs (step=%s)",
            _GENERATE_TIMEOUT_SECONDS,
            step_id,
        )
        return None
    except Exception:
        logger.warning(
            "[decompose] subtask generation LLM call failed (step=%s)",
            step_id,
            exc_info=True,
        )
        return None


def _render_proposal(proposal: DecompositionProposal) -> str:
    """Render a proposal's subtasks into text for the critic prompt."""
    lines: list[str] = []
    for idx, sub in enumerate(proposal.subtasks):
        parts = [f"### Subtask {idx}"]
        if sub.description:
            parts.append(f"description: {sub.description}")
        if sub.full_description:
            parts.append(f"full_description: {sub.full_description}")
        if sub.expected_output:
            parts.append(f"expected_output: {sub.expected_output}")
        lines.append("\n".join(parts))
    return "\n\n".join(lines)


def _render_evidence(corpus: list[str]) -> str:
    """Concatenate evidence excerpts with an overall cap."""
    chunks: list[str] = []
    total = 0
    for excerpt in corpus:
        if total + len(excerpt) > _EVIDENCE_PROMPT_CAP:
            remaining = _EVIDENCE_PROMPT_CAP - total
            if remaining > 80:
                chunks.append(excerpt[: remaining - 1] + "…")
            break
        chunks.append(excerpt)
        total += len(excerpt)
    return "\n---\n".join(chunks) if chunks else "(no evidence)"


_CRITIC_PROMPT = """\
You are a grounding critic for an AI coding agent's task decomposition.

Below is EVIDENCE — the concatenated outputs of search/inspection tool calls \
the agent gathered in this step thread — and a PROPOSAL — the subtasks the \
agent wants to decompose the current step into.

For each concrete claim in the PROPOSAL — a file/dir path, a module, function, \
or class name, a file count or quantity, or a behavioral assertion (e.g. \
"X is a backward-compat shim", "Y depends on Z") — decide whether the EVIDENCE \
supports it. A claim is supported when the item (or a close variant, e.g. a \
path with a longer prefix/suffix, or the same identifier) appears in the \
evidence. Do NOT require an exact string match; semantic near-match counts.

List ONLY claims that are NOT supported by the evidence — things the agent \
appears to have invented without having observed them. If every concrete claim \
is supported, set grounded=true with an empty ungrounded_claims list.

Do not reject legitimate inferences: if the agent saw "packages/soothe/src/\
soothe/sloop/state/checkpoint.py" in evidence and the proposal cites \
"sloop/state/checkpoint.py", that is supported (the path was observed).

EVIDENCE:
{evidence}

PROPOSAL (parent step {step_id}):
{proposal}
"""


async def check_proposal_grounded(
    proposal: DecompositionProposal,
    *,
    evidence_corpus: list[str],
    fast_model: BaseChatModel | None,
    soothe_config: SootheConfig | None = None,
    step_id: str,
    goal_trace: GoalLoopTrace | None = None,
) -> GroundingVerdict | None:
    """Run the FAST grounding critic on a decompose proposal.

    Returns ``None`` on failure (fail-open: don't block the proposal).
    """
    if fast_model is None:
        # No fast model resolved — fail open (don't block legitimate work).
        return None
    evidence = _render_evidence(evidence_corpus)
    if not evidence_corpus:
        # No evidence text captured; the zero-evidence gate in tool.py
        # should have caught this, but be defensive.
        return None
    proposal_text = _render_proposal(proposal)
    prompt = _CRITIC_PROMPT.format(evidence=evidence, proposal=proposal_text, step_id=step_id)
    try:
        from soothe_nano.llm import ainvoke_structured_traced

        data = await asyncio.wait_for(
            ainvoke_structured_traced(
                fast_model,
                [{"role": "user", "content": prompt}],
                json_schema=GroundingVerdict.model_json_schema(),
                schema_name="GroundingVerdict",
                soothe_config=soothe_config,
                purpose="decompose_grounding_critic",
                component="sloop.decompose.grounding_guard",
                phase="execute_step",
                goal_trace=goal_trace,
                # Prefer json_schema over function_calling: the GroundingVerdict
                # schema has a nested list of objects, which many FAST models
                # fail to emit correctly under function_calling strict mode
                # (observed: every attempt fails validation → repair retry →
                # fallback, wasting 20-40s).  json_schema handles nested
                # structures better and avoids the retry cycle.
                methods=("json_schema", "json_mode", "function_calling", None),
                # strict=False skips post-validation repair retries; we
                # validate via Pydantic below instead.
                strict=False,
            ),
            timeout=_CRITIC_TIMEOUT_SECONDS,
        )
        return GroundingVerdict.model_validate(data)
    except TimeoutError:
        logger.warning(
            "[decompose] grounding critic timed out after %.0fs (step=%s); fail-open",
            _CRITIC_TIMEOUT_SECONDS,
            step_id,
        )
        return None
    except Exception:
        logger.warning(
            "[decompose] grounding critic LLM call failed (step=%s); fail-open",
            step_id,
            exc_info=True,
        )
        return None


def build_ungrounded_claims_guidance(
    verdict: GroundingVerdict,
    *,
    step_id: str,
) -> str:
    """Build the soft-rejection guidance returned to the LLM for ungrounded claims."""
    claims_preview = "; ".join(
        f"subtask[{c.subtask}]: {c.claim}" for c in verdict.ungrounded_claims[:5]
    )
    reasons = "\n".join(
        f'  - subtask[{c.subtask}] "{c.claim}": {c.reason}' for c in verdict.ungrounded_claims
    )
    return (
        f"Decomposition proposal for step {step_id} was NOT queued: it contains "
        f"claims not supported by the evidence you gathered ({claims_preview}"
        f"{'; …' if len(verdict.ungrounded_claims) > 5 else ''}).\n\n"
        f"Unsupported claims:\n{reasons}\n\n"
        f"Re-ground: run ls/glob/grep/read_file to confirm the areas this task "
        f"spans, then re-propose only subtasks whose concrete claims (paths, "
        f"modules, quantities, behavioral assertions) you have actually "
        f"observed in tool outputs. Do not fabricate subtasks for things you "
        f"have not verified."
    )


def build_no_evidence_guidance(*, step_id: str) -> str:
    """Build the soft-rejection guidance returned to the LLM when no evidence was gathered."""
    return (
        f"Decomposition proposal for step {step_id} was NOT queued: no "
        f"evidence-gathering tool (ls/glob/grep/read_file) has run in this "
        f"thread yet. Gather evidence first — run at least one search or "
        f"inspection to confirm the areas this task spans, then call "
        f"decompose_task. Decomposing without evidence produces fabricated "
        f"subtasks."
    )


__all__ = [
    "GeneratedSubtask",
    "GeneratedSubtaskList",
    "GroundingVerdict",
    "UngroundedClaim",
    "build_no_evidence_guidance",
    "build_ungrounded_claims_guidance",
    "check_proposal_grounded",
    "generate_subtasks_via_fast_model",
]
