"""Grounding guard for decompose_task proposals (d15f hallucination defense).

Two runtime layers that reject decompose proposals issued without evidence:

- ``check_proposal_grounded``: an LLM-driven critic (FAST model) that judges
  whether the concrete claims in a proposal (paths, modules, functions,
  quantities, behavioral assertions) are supported by the evidence the agent
  actually gathered in the step thread. Replaces the old rigid
  filesystem-path existence check so it works in sandboxes with no real
  project paths and catches hallucinations beyond paths.
- ``current_evidence_calls`` (in :mod:`runtime`): a decompose_task issued
  with zero prior evidence-gathering tool calls in the thread is rejected
  without invoking the model (cheap short-circuit).

Together they prevent the d15f failure: a complex root step called
``decompose_task`` as its first action (no grounding) and fabricated
``client/swift/``, ``client/kotlin/`` subtasks that did not exist.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from soothe.context.decomposition import DecompositionProposal

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

    from soothe.config import SootheConfig
    from soothe.utils.observability.langfuse import GoalLoopTrace

logger = logging.getLogger(__name__)

# Cap the total evidence text fed to the critic prompt (bounds cost/latency).
_EVIDENCE_PROMPT_CAP = 6000


class UngroundedClaim(BaseModel):
    """A proposal claim the critic judges as unsupported by evidence."""

    subtask: int = Field(description="Index of the subtask (0-based) in the proposal")
    claim: str = Field(description="The specific unsupported claim")
    reason: str = Field(description="Why the evidence does not support this claim (concise)")


class GroundingVerdict(BaseModel):
    """Structured verdict from the FAST grounding critic."""

    grounded: bool = Field(
        description=(
            "True when every concrete claim in the proposal is supported by "
            "the evidence (paths, modules, functions, quantities, behavioral "
            "assertions appear or are close-variant in the evidence)."
        )
    )
    ungrounded_claims: list[UngroundedClaim] = Field(
        default_factory=list,
        description="Claims NOT supported by the evidence (empty if grounded)",
    )


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

    Returns a :class:`GroundingVerdict`, or ``None`` on failure (fail-open: \
    the caller should not block the proposal when the critic itself errors).
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

        data = await ainvoke_structured_traced(
            fast_model,
            [{"role": "user", "content": prompt}],
            json_schema=GroundingVerdict.model_json_schema(),
            schema_name="GroundingVerdict",
            soothe_config=soothe_config,
            purpose="decompose_grounding_critic",
            component="sloop.decompose.grounding_guard",
            phase="execute_step",
            goal_trace=goal_trace,
        )
        return GroundingVerdict.model_validate(data)
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
    "GroundingVerdict",
    "UngroundedClaim",
    "build_no_evidence_guidance",
    "build_ungrounded_claims_guidance",
    "check_proposal_grounded",
]
