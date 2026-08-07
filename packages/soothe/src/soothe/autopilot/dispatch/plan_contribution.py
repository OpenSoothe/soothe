"""Build worker contribution / wire response from a completed PlanResult.

Lives under ``dispatch`` (wire contribution packing), not ``verify``
(judgment). StrangeLoop Plan-Execute-Eval owns goal-done judgment; autopilot
consensus compares goal text to the wire response synthesized here — not
host workspace probes (IG-710 / RFC-204).

Side-effect claims (``GoalEffect``) are emitted by StrangeLoop assess and
copied by the worker — this module does not infer effects from prose or the
filesystem (IG-712).
"""

from __future__ import annotations

from typing import Any


def decision_step_actions(decision: Any | None) -> list[Any]:
    """Return plan step actions from an ``AgentDecision``-like object.

    Prefer ``steps`` (canonical ``AgentDecision`` field). Accept legacy
    ``actions`` only for older fixtures / wire payloads.
    """
    if decision is None:
        return []
    steps = getattr(decision, "steps", None)
    if isinstance(steps, list) and steps:
        return list(steps)
    actions = getattr(decision, "actions", None)
    if isinstance(actions, list) and actions:
        return list(actions)
    return []


def synthesize_sloop_response(
    plan_result: Any | None,
    *,
    prefer_full_output: bool = False,
) -> str:
    """Derive the StrangeLoop response string for the consensus wire field.

    Prefer explicit ``evidence_summary``, then user-visible ``full_output``,
    then completed decision step descriptions. Never uses the goal text.

    When ``prefer_full_output`` is True (IG-724 collect_evidence), prefer
    ``full_output`` over a thin ``evidence_summary`` so proof narratives reach
    consensus.

    The autopilot wire does not clip length here — consensus already takes the
    full Agent Response (IG-690); clipping would bury git/report proof.
    """
    if plan_result is None:
        return ""

    summary = (getattr(plan_result, "evidence_summary", None) or "").strip()
    full_output = (getattr(plan_result, "full_output", None) or "").strip()

    if prefer_full_output:
        if full_output:
            return full_output
        if summary:
            return summary
    else:
        if summary:
            return summary
        if full_output:
            return full_output

    decision = getattr(plan_result, "decision", None)
    actions = decision_step_actions(decision)
    if actions:
        bits: list[str] = []
        for action in actions[:10]:
            if isinstance(action, dict):
                text = str(action.get("description", "") or "").strip()
            else:
                text = str(getattr(action, "description", "") or "").strip()
            if text:
                bits.append(text[:200])
        if bits:
            return "Completed steps: " + "; ".join(bits)

    return ""
