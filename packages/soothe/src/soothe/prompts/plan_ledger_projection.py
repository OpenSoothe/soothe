"""Project StrangeLoop ledger messages for execute / synthesis / intake.

 : The complete ledger includes all phases. CoreAgent execution sees only
``execute_step`` messages (plan-phase reasoning is not injected into the
CoreAgent thread). Goal-completion synthesis uses the current-goal execute
segment (plus optional compacted prior terminal status). Intake classify may
project the last ``goal_completion`` unit.

When ``PlanPromptLedgerConfig`` limits are all zero/unset, the caller receives
the same message object references as ``state.loop_messages`` (shallow list
copy). When any limit is positive, messages are deep-copied and trimmed
without mutating persisted ledger state.
"""

from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from soothe.sloop.orchestrator.stations import (
    INTAKE_LEDGER_PHASES,
    PHASE_EXECUTE_STEP,
    PHASE_GOAL_COMPLETION,
    PHASE_GOAL_INTERRUPTED,
    PLANNING_LEDGER_PHASES,
)
from soothe.sloop.utils.stream_normalize import extract_text_from_message_content

if TYPE_CHECKING:
    from soothe.config.models import ExecutePromptLedgerConfig, PlanPromptLedgerConfig
    from soothe.sloop.state.checkpoint import StrangeLoopCheckpoint
    from soothe.sloop.state.schemas import AgentDecision, LoopState, StepAction

logger = logging.getLogger(__name__)

ExecuteProjectionMode = Literal["goal_boundary", "mid_goal"]


@dataclass
class ProjectedExecuteStepInput:
    """Result of execute-step graph ledger projection."""

    messages: list[BaseMessage] = field(default_factory=list)
    cross_goal_projected: bool = False
    predecessor_projected: bool = False
    mode: ExecuteProjectionMode = "mid_goal"


_LEDGER_OMITTED_MARKER = "[Earlier ledger content omitted for plan prompt size]\n\n"
_TRUNC_PER_MSG = "\n…[truncated for plan prompt]\n"

# RFC-214: phases that mark a goal segment boundary. ``goal_completion`` is the
# success terminal; ``goal_interrupted`` is the non-success terminal marker
# (cancel/fatal/max-iter) carrying the goal's partial-work digest. Projection
# treats both as segment boundaries so an interrupted goal's ``execute_step``
# rows do not bleed into the next goal's "current segment".
_GOAL_TERMINAL_PHASES: frozenset[str] = frozenset({PHASE_GOAL_COMPLETION, PHASE_GOAL_INTERRUPTED})

# Boundary marker for prior goal completion in planning projections.
# Prevents planner anchoring on prior "Recommended next actions" instead of
# decomposing the current goal independently.
_GOAL_COMPLETION_CONTEXT_BOUNDARY = (
    '<PRIOR_GOAL_CONTEXT role="reference_resolution">\n'
    "The following completed goal provides context for resolving user mentions.\n"
    "DO NOT use the recommended actions below as your plan template.\n"
    "Decompose the current goal independently based on its scope.\n"
)

# Boundary for prior terminal units in goal-completion synthesis.
# The full prior report is kept below; this marker only scopes it as reference
# so the model writes for the CURRENT request without reprinting prior output.
_SYNTHESIS_PRIOR_GOAL_CONTEXT_BOUNDARY = (
    '<PRIOR_GOAL_CONTEXT role="status_reference">\n'
    "Prior goal report below is background context for the CURRENT request.\n"
    "Write the report for the CURRENT request using current-goal evidence.\n"
    "Do not reprint or expand the prior report; at most one short status mention.\n"
)


def projected_ledger_has_goal_completion(projected: list[BaseMessage]) -> bool:
    """True when projected ledger includes a goal_completion AI turn."""
    for msg in projected:
        if getattr(msg, "phase", None) != "goal_completion":
            continue
        if type(msg).__name__.endswith("AIMessage"):
            return True
    return False


def _deep_copy_message(msg: BaseMessage) -> BaseMessage:
    copier = getattr(msg, "model_copy", None)
    if callable(copier):
        return copier(deep=True)
    return copy.deepcopy(msg)


def _message_step_id(msg: BaseMessage) -> str | None:
    """Extract step_id from a message's direct attribute or additional_kwargs."""
    sid = getattr(msg, "step_id", None)
    if isinstance(sid, str) and sid.strip():
        return sid.strip()
    add = getattr(msg, "additional_kwargs", None) or {}
    if isinstance(add, dict):
        v = add.get("step_id")
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def _message_text_len(msg: BaseMessage) -> int:
    return len(extract_text_from_message_content(getattr(msg, "content", "")))


def _set_message_content(msg: BaseMessage, text: str) -> BaseMessage:
    copier = getattr(msg, "model_copy", None)
    if callable(copier):
        return copier(update={"content": text})
    if isinstance(msg, HumanMessage):
        return HumanMessage(content=text)
    if isinstance(msg, AIMessage):
        return AIMessage(content=text)
    return msg


def _cap_single_message_content(msg: BaseMessage, max_chars: int) -> BaseMessage:
    if max_chars <= 0:
        return msg
    text = extract_text_from_message_content(getattr(msg, "content", ""))
    if len(text) <= max_chars:
        return msg
    clipped = text[: max(0, max_chars - len(_TRUNC_PER_MSG))] + _TRUNC_PER_MSG
    return _set_message_content(msg, clipped)


def _goal_report_truncation_marker(dropped: int) -> str:
    """Marker inserted between head and tail of a truncated goal-completion report."""
    return f"\n…[{dropped} chars truncated]…\n"


def _truncate_head_tail(text: str, *, cap: int, marker: str) -> str:
    """Truncate to ``cap`` chars keeping 40% head + 60% tail with a truncation marker.

    The tail is favored (recommendations, file paths, deferred items live near the
    end of a goal-completion report) so the most actionable content survives.
    """
    if cap <= 0 or len(text) <= cap:
        return text
    budget = cap - len(marker)
    if budget <= 0:
        return marker
    head = int(budget * 0.4)
    tail = budget - head
    return f"{text[:head]}{marker}{text[-tail:]}"


def _is_goal_completion_ai(msg: BaseMessage) -> bool:
    """True when ``msg`` is a goal-completion AI turn (the synthesis report body)."""
    if getattr(msg, "phase", None) != "goal_completion":
        return False
    return type(msg).__name__.endswith("AIMessage")


def _cap_goal_completion_message(msg: BaseMessage, max_chars: int) -> BaseMessage:
    """Head+tail truncate a goal-completion report (40% head + 60% tail)."""
    if max_chars <= 0:
        return msg
    text = extract_text_from_message_content(getattr(msg, "content", ""))
    if len(text) <= max_chars:
        return msg
    dropped = len(text) - max_chars
    marker = _goal_report_truncation_marker(dropped)
    clipped = _truncate_head_tail(text, cap=max_chars, marker=marker)
    return _set_message_content(msg, clipped)


def _trim_total_chars_front(
    messages: list[BaseMessage], max_chars: int
) -> tuple[list[BaseMessage], bool]:
    """Drop oldest messages until total extracted text <= max_chars (or one truncated body).

    Returns:
        (trimmed_messages, True) if any leading messages were dropped or body was hard-clipped.
    """
    if max_chars <= 0 or not messages:
        return messages, False

    # Single-pass O(N): precompute per-message lengths, then find the cut index.
    lengths = [_message_text_len(m) for m in messages]
    total = sum(lengths)
    if total <= max_chars:
        return messages, False

    start = 0
    while start < len(messages) - 1 and total > max_chars:
        total -= lengths[start]
        start += 1

    out = list(messages[start:])
    shrunk = start > 0

    # If the single remaining message still exceeds the budget, hard-clip it.
    if len(out) == 1:
        m0 = out[0]
        text = extract_text_from_message_content(getattr(m0, "content", ""))
        if len(text) > max_chars:
            if _is_goal_completion_ai(m0):
                # Head+tail: keep 40% beginning + 60% tail of the report.
                dropped = len(text) - max_chars
                clipped = _truncate_head_tail(
                    text,
                    cap=max_chars,
                    marker=_goal_report_truncation_marker(dropped),
                )
            else:
                marker = "\n…[truncated for plan prompt]\n"
                clipped = text[: max(0, max_chars - len(marker))] + marker
            out[0] = _set_message_content(m0, clipped)
            shrunk = True

    return out, shrunk


def _compact_intent_classify_human_for_projection(msg: BaseMessage) -> BaseMessage:
    """Rewrite ``GOAL:`` to ``GOAL RECAP:`` on projected intent-classify humans (D1)."""
    if getattr(msg, "phase", None) != "intent_classify" or not _is_loop_human_message(msg):
        return msg
    from soothe.sloop.utils.ledger_compaction import compact_planning_human_content

    text = extract_text_from_message_content(getattr(msg, "content", ""))
    compacted = compact_planning_human_content(text)
    if compacted == text:
        return msg
    return _set_message_content(_deep_copy_message(msg), compacted)


def _apply_intent_classify_human_compaction(messages: list[BaseMessage]) -> list[BaseMessage]:
    """Return messages with intent-classify humans compacted for plan prompt projection."""
    if not messages:
        return messages
    out: list[BaseMessage] = []
    changed = False
    for msg in messages:
        compacted = _compact_intent_classify_human_for_projection(msg)
        if compacted is not msg:
            changed = True
        out.append(compacted)
    return out if changed else messages


def project_loop_messages_for_plan(
    loop_messages: list[BaseMessage],
    ledger_cfg: PlanPromptLedgerConfig | None,
) -> list[BaseMessage]:
    """Return ledger messages for plan LLM prompts.

    Args:
        loop_messages: ledger from ``LoopState.loop_messages``.
        ledger_cfg: Optional caps; ``None`` treated as all limits disabled.

    Returns:
        Same references as input when no limits apply (shallow list copy).
        Deep-trimmed copies when any limit is positive.
    """
    if ledger_cfg is None:
        return _apply_intent_classify_human_compaction(list(loop_messages))

    max_msg = int(ledger_cfg.plan_ledger_max_messages)
    max_total = int(ledger_cfg.plan_ledger_max_total_chars)
    max_per = int(ledger_cfg.plan_ledger_max_message_chars)

    if max_msg <= 0 and max_total <= 0 and max_per <= 0:
        return _apply_intent_classify_human_compaction(list(loop_messages))

    copies = [_deep_copy_message(m) for m in loop_messages]
    omitted_prefix = False

    if max_msg > 0 and len(copies) > max_msg:
        dropped = len(copies) - max_msg
        copies = copies[-max_msg:]
        omitted_prefix = dropped > 0
        logger.debug(
            "Plan ledger projection: tail messages=%d (dropped oldest=%d)",
            len(copies),
            dropped,
        )

    if max_per > 0:
        copies = [
            _cap_goal_completion_message(m, max_per)
            if _is_goal_completion_ai(m)
            else _cap_single_message_content(m, max_per)
            for m in copies
        ]

    if max_total > 0:
        copies, shrunk_total = _trim_total_chars_front(copies, max_total)
        omitted_prefix = omitted_prefix or shrunk_total

    if omitted_prefix and copies:
        first = copies[0]
        text = extract_text_from_message_content(getattr(first, "content", ""))
        if not text.startswith(_LEDGER_OMITTED_MARKER.strip()):
            copies[0] = _set_message_content(first, _LEDGER_OMITTED_MARKER + text)

    logger.debug(
        "Plan ledger projection: out_msgs=%d approx_chars=%d caps(msg=%s total=%s per=%s)",
        len(copies),
        sum(_message_text_len(m) for m in copies),
        max_msg or "off",
        max_total or "off",
        max_per or "off",
    )
    return _apply_intent_classify_human_compaction(copies)


def _current_goal_segment_start(loop_messages: list[BaseMessage]) -> int:
    """Return index after the last prior-goal terminal AI row.

    A goal segment boundary is marked by either a ``goal_completion`` (success)
    or ``goal_interrupted`` (cancel/fatal/max-iter) AI row. Both terminate the
    prior goal's segment so its ``execute_step`` rows do not bleed into the
    next goal's current-segment projection.
    """
    for i in range(len(loop_messages) - 1, -1, -1):
        msg = loop_messages[i]
        if getattr(msg, "phase", None) in _GOAL_TERMINAL_PHASES and _is_loop_ai_message(msg):
            return i + 1
    return 0


def _is_loop_human_message(msg: BaseMessage) -> bool:
    name = type(msg).__name__
    return name.endswith("HumanMessage")


def _is_loop_ai_message(msg: BaseMessage) -> bool:
    name = type(msg).__name__
    return name.endswith("AIMessage")


def _compact_goal_completion_unit_for_projection(
    unit: list[BaseMessage],
    *,
    include_boundary: bool = True,
) -> list[BaseMessage]:
    """Rewrite goal_completion human envelopes for downstream prompt projection.

    Args:
        unit: Human/AI pair for a goal_completion ledger phase.
        include_boundary: When True (default), prepend boundary marker
            to prevent planner anchoring. Set False for execute-step Slice A
            where prior actions genuinely help execution grounding.

    Returns:
        Deep-copied unit with rewritten human envelope.
    """
    compact_human = "Prior goal completed. Terminal report follows."
    if include_boundary:
        compact_human = _GOAL_COMPLETION_CONTEXT_BOUNDARY + compact_human
    out: list[BaseMessage] = []
    for msg in unit:
        copy_msg = _deep_copy_message(msg)
        if getattr(copy_msg, "phase", None) == "goal_completion" and _is_loop_human_message(
            copy_msg
        ):
            copy_msg = _set_message_content(copy_msg, compact_human)
        out.append(copy_msg)
    return out


def _compact_goal_interrupted_unit_for_projection(
    unit: list[BaseMessage],
    *,
    include_boundary: bool = False,
) -> list[BaseMessage]:
    """Rewrite goal_interrupted human envelopes for downstream prompt projection.

    Unlike completed goals, interrupted goals' leftover work SHOULD anchor the
    new plan — that is the whole point of carry-forward. So the
    anti-anchoring boundary marker is NOT applied by default; the human envelope
    is rewritten to a short label naming the interrupt cause.

    Args:
        unit: Human/AI pair for a goal_interrupted ledger phase.
        include_boundary: When True, prepend boundary marker (rarely
            wanted for interrupted goals; provided for parity).

    Returns:
        Deep-copied unit with rewritten human envelope.
    """
    compact_human = "Prior goal was interrupted before completion. Partial-work digest follows."
    if include_boundary:
        compact_human = _GOAL_COMPLETION_CONTEXT_BOUNDARY + compact_human
    out: list[BaseMessage] = []
    for msg in unit:
        copy_msg = _deep_copy_message(msg)
        if getattr(copy_msg, "phase", None) == "goal_interrupted" and _is_loop_human_message(
            copy_msg
        ):
            copy_msg = _set_message_content(copy_msg, compact_human)
        out.append(copy_msg)
    return out


def _compact_terminal_unit_for_projection(
    unit: list[BaseMessage],
    *,
    include_boundary: bool = True,
) -> list[BaseMessage]:
    """Dispatch a terminal unit to its phase-specific compaction.

    ``goal_completion`` units use the anti-anchoring boundary by default;
    ``goal_interrupted`` units do not (their leftover work should anchor).
    """
    # Detect the unit's phase from its first human/AI row.
    phase = None
    for msg in unit:
        p = getattr(msg, "phase", None)
        if p in _GOAL_TERMINAL_PHASES:
            phase = p
            break
    if phase == "goal_interrupted":
        return _compact_goal_interrupted_unit_for_projection(
            unit, include_boundary=include_boundary
        )
    return _compact_goal_completion_unit_for_projection(unit, include_boundary=include_boundary)


def project_last_goal_completion_for_intake(
    loop_messages: list[BaseMessage],
    ledger_cfg: PlanPromptLedgerConfig | None,
    *,
    include_boundary: bool = True,
    k: int = 3,
) -> list[BaseMessage]:
    """Project up to ``k`` prior ``goal_completion`` ledger units into intake classify input.

    Uses the same ``goal_completion`` resolution as execute Slice A. The synthesis
    human envelope is rewritten to a short label so the classifier focuses on the
    terminal AI report.

    Args:
        loop_messages: Full ledger loaded from CE persistence.
        ledger_cfg: Optional caps (same knobs as plan prompts).
        include_boundary: When True (default), prepend boundary marker.
            Set False where the classifier needs the prior scope signal.
        k: Maximum number of prior completion units to project.

    Returns:
        Bounded ledger slice injected before the classify human message.
    """
    if not loop_messages:
        return []

    units = collect_goal_completion_units(loop_messages, k=k)
    if not units:
        return []

    flat: list[BaseMessage] = []
    for unit in units:
        flat.extend(
            _compact_goal_completion_unit_for_projection(unit, include_boundary=include_boundary)
        )
    projected = project_loop_messages_for_plan(flat, ledger_cfg)
    logger.debug(
        "Intake goal-completion projection: k=%d units=%d out=%d boundary=%s",
        k,
        len(units),
        len(projected),
        include_boundary,
    )
    return projected


def current_goal_has_execute_ledger(state: LoopState) -> bool:
    """True when the active plan already has execute_step rows in the orchestration ledger."""
    decision = state.current_decision
    if decision is None:
        return False
    plan_step_ids = {s.id for s in decision.steps}
    if not plan_step_ids:
        return False
    for msg in state.loop_messages:
        if getattr(msg, "phase", None) != PHASE_EXECUTE_STEP:
            continue
        sid = _message_step_id(msg)
        if sid and sid in plan_step_ids:
            return True
    return False


def resolve_execute_projection_mode(state: LoopState) -> ExecuteProjectionMode:
    """Return ``goal_boundary`` at first execute slice of a goal, else ``mid_goal``."""
    if state.iteration == 0 and not state.step_results:
        # CE-bound loops record execute_step ledger per wave; step_results stay empty
        # until record_iteration. Treat in-flight plan execution as mid_goal so Slice A
        # does not replay same-goal execute rows as cross-goal completion units.
        if current_goal_has_execute_ledger(state):
            return "mid_goal"
        if state.dependency_completion_ids():
            return "mid_goal"
        return "goal_boundary"
    return "mid_goal"


def _execute_plan_tail_index(loop_messages: list[BaseMessage]) -> int:
    """Index before trailing plan-phase rows for the current goal (exclude from Slice A scan)."""
    idx = len(loop_messages)
    plan_phases = PLANNING_LEDGER_PHASES
    while idx > 0:
        phase = getattr(loop_messages[idx - 1], "phase", None)
        if phase in plan_phases:
            idx -= 1
        else:
            break
    return idx


def _goal_segment_start(loop_messages: list[BaseMessage], unit_start: int) -> int:
    """Return index where the goal segment containing ``unit_start`` began."""
    seg_after_prev_terminal = 0
    for i in range(unit_start - 1, -1, -1):
        msg = loop_messages[i]
        if getattr(msg, "phase", None) in _GOAL_TERMINAL_PHASES and _is_loop_ai_message(msg):
            seg_after_prev_terminal = i + 1
            break
    for i in range(seg_after_prev_terminal, unit_start):
        if getattr(loop_messages[i], "phase", None) in INTAKE_LEDGER_PHASES:
            return i
    return seg_after_prev_terminal


def _find_last_phase_pair_indices(
    loop_messages: list[BaseMessage],
    before_index: int,
    phase: str | frozenset[str],
) -> tuple[int, int] | None:
    """Return ``(human_idx, ai_idx)`` for the last ``phase`` pair ending before ``before_index``.

    ``phase`` may be a single phase string or a frozenset of phases; the AI row
    matches if its ``phase`` is in the set. ``_GOAL_TERMINAL_PHASES`` (both
    ``goal_completion`` and ``goal_interrupted``) is the set used by cross-goal
    projection so interrupted goals' partial-work digests are surfaced alongside
    completions.
    """
    if before_index <= 0:
        return None
    phases = frozenset({phase}) if isinstance(phase, str) else phase
    ai_idx: int | None = None
    for i in range(before_index - 1, -1, -1):
        msg = loop_messages[i]
        if getattr(msg, "phase", None) in phases and _is_loop_ai_message(msg):
            ai_idx = i
            break
    if ai_idx is None:
        return None
    human_idx: int | None = None
    for j in range(ai_idx - 1, -1, -1):
        msg = loop_messages[j]
        if getattr(msg, "phase", None) in phases and _is_loop_human_message(msg):
            human_idx = j
            break
    if human_idx is not None:
        return human_idx, ai_idx
    return ai_idx, ai_idx


def resolve_goal_completion_unit(
    loop_messages: list[BaseMessage],
    before_index: int,
) -> tuple[list[BaseMessage], int] | None:
    """Resolve one prior-goal ``goal_completion`` unit ending before ``before_index``.

    Completion-only: used by intake classify (``project_last_goal_completion_for_intake``)
    which must NOT see interrupted goals' digests. Cross-goal Slice A projection
    uses :func:`resolve_goal_terminal_unit` instead to surface both.
    """
    idxs = _find_last_phase_pair_indices(loop_messages, before_index, "goal_completion")
    if idxs is None:
        return None
    start, end = idxs
    unit = [_deep_copy_message(loop_messages[i]) for i in range(start, end + 1)]
    return unit, start


def resolve_goal_terminal_unit(
    loop_messages: list[BaseMessage],
    before_index: int,
) -> tuple[list[BaseMessage], int] | None:
    """Resolve one prior-goal terminal unit (completion OR interrupted) before ``before_index``.

    Cross-goal Slice A variant: scans both ``goal_completion`` and
    ``goal_interrupted`` so an interrupted goal's partial-work digest is
    surfaced to the next goal's planning projection.
    """
    idxs = _find_last_phase_pair_indices(loop_messages, before_index, _GOAL_TERMINAL_PHASES)
    if idxs is None:
        return None
    start, end = idxs
    unit = [_deep_copy_message(loop_messages[i]) for i in range(start, end + 1)]
    return unit, start


def collect_goal_completion_units(
    loop_messages: list[BaseMessage],
    *,
    k: int,
) -> list[list[BaseMessage]]:
    """Collect up to ``k`` prior-goal ``goal_completion`` units, oldest first.

    Completion-only (contrast with :func:`collect_cross_goal_completion_units`,
    which also includes ``goal_interrupted`` units): used by intake classify,
    which must not see interrupted goals' digests.

    ``k <= 0`` means unlimited (project all prior-goal completion units).
    """
    if not loop_messages:
        return []
    k_eff = k if k > 0 else len(loop_messages)

    units_rev: list[list[BaseMessage]] = []
    cursor = _execute_plan_tail_index(loop_messages)
    while len(units_rev) < k_eff and cursor > 0:
        found = resolve_goal_completion_unit(loop_messages, cursor)
        if found is None:
            break
        unit, start = found
        units_rev.append(unit)
        cursor = _goal_segment_start(loop_messages, start)
    units_rev.reverse()
    return units_rev


def collect_cross_goal_completion_units(
    loop_messages: list[BaseMessage],
    *,
    k: int,
) -> list[list[BaseMessage]]:
    """Collect up to ``k`` prior-goal terminal units, oldest first.

    Now includes ``goal_interrupted`` units so interrupted goals' partial-work
    digests are projected beside completions.

    ``k <= 0`` means unlimited (project all prior-goal terminal units).
    """
    if not loop_messages:
        return []
    k_eff = k if k > 0 else len(loop_messages)

    units_rev: list[list[BaseMessage]] = []
    cursor = _execute_plan_tail_index(loop_messages)
    while len(units_rev) < k_eff and cursor > 0:
        found = resolve_goal_terminal_unit(loop_messages, cursor)
        if found is None:
            break
        unit, start = found
        units_rev.append(unit)
        cursor = _goal_segment_start(loop_messages, start)
    units_rev.reverse()
    return units_rev


def execute_step_ids_subsumed_by_cross_goal_completion(
    loop_messages: list[BaseMessage],
    *,
    k: int,
) -> frozenset[str]:
    """Return execute ``step_id`` values subsumed by projected terminal units.

    When Slice A replays a prior goal's terminal report (completion **or**
    interrupted digest), the ``execute_step`` rows from that same goal segment
    must not appear again in Slice B (including ``ledger_direct`` goals where
    the completion body copies execute text).

    ``k <= 0`` means unlimited (subsume across all prior-goal terminal units).
    """
    if not loop_messages:
        return frozenset()
    k_eff = k if k > 0 else len(loop_messages)

    subsumed: set[str] = set()
    cursor = _execute_plan_tail_index(loop_messages)
    collected = 0
    while collected < k_eff and cursor > 0:
        found = resolve_goal_terminal_unit(loop_messages, cursor)
        if found is None:
            break
        _unit, start = found
        segment_start = _goal_segment_start(loop_messages, start)
        for i in range(segment_start, start):
            msg = loop_messages[i]
            if getattr(msg, "phase", None) != PHASE_EXECUTE_STEP:
                continue
            sid = _message_step_id(msg)
            if sid:
                subsumed.add(sid)
        collected += 1
        cursor = segment_start
    return frozenset(subsumed)


def project_cross_goal_completion_tail(
    loop_messages: list[BaseMessage],
    *,
    k: int,
    ledger_cfg: PlanPromptLedgerConfig | None,
    include_boundary: bool = False,
) -> list[BaseMessage]:
    """Project K prior-goal ``goal_completion`` units for execute Slice A.

    Args:
        loop_messages: Full ledger.
        k: Maximum number of prior goal completion units to project.
        ledger_cfg: Optional caps.
        include_boundary: When False (default for execute), omit boundary marker
            since prior actions genuinely help execution grounding. Set True for
            planner projections where anchoring prevention is needed.

    Returns:
        Bounded ledger slice for Slice A.
    """
    units = collect_cross_goal_completion_units(loop_messages, k=k)
    flat: list[BaseMessage] = []
    for unit in units:
        flat.extend(_compact_terminal_unit_for_projection(unit, include_boundary=include_boundary))
    if not flat:
        return []

    projected = project_loop_messages_for_plan(flat, ledger_cfg)
    logger.debug(
        "Execute Slice A projection: k=%d units=%d out_msgs=%d boundary=%s",
        k,
        len(units),
        len(projected),
        include_boundary,
    )
    return projected


def _execute_prompt_ledger_config(config: Any | None) -> ExecutePromptLedgerConfig:
    from soothe.config.models import ExecutePromptLedgerConfig

    if config is None:
        return ExecutePromptLedgerConfig()
    loop_cfg = getattr(config, "agent", None)
    loop_cfg = getattr(loop_cfg, "loop", None) if loop_cfg is not None else None
    exec_cfg = getattr(loop_cfg, "execute_prompt_ledger", None) if loop_cfg is not None else None
    if exec_cfg is None:
        return ExecutePromptLedgerConfig()
    return exec_cfg


def _plan_prompt_ledger_config(config: Any | None) -> PlanPromptLedgerConfig | None:
    if config is None:
        return None
    loop_cfg = getattr(config, "agent", None)
    loop_cfg = getattr(loop_cfg, "loop", None) if loop_cfg is not None else None
    return getattr(loop_cfg, "plan_prompt_ledger", None) if loop_cfg is not None else None


def _prior_wave_step_ids_in_goal_segment(
    loop_messages: list[BaseMessage],
    decision: AgentDecision,
) -> frozenset[str]:
    """Step ids with execute ledger rows in the current goal but outside the active plan."""
    current_ids = {s.id for s in decision.steps}
    seg_start = _current_goal_segment_start(loop_messages)
    prior: set[str] = set()
    for msg in loop_messages[seg_start:]:
        if getattr(msg, "phase", None) != PHASE_EXECUTE_STEP:
            continue
        sid = _message_step_id(msg)
        if sid and sid not in current_ids:
            prior.add(sid)
    return frozenset(prior)


def project_prior_wave_execute_ledger(
    loop_messages: list[BaseMessage],
    decision: AgentDecision,
    *,
    max_messages: int | None = None,
    exclude_step_ids: frozenset[str] | None = None,
) -> list[BaseMessage]:
    """Replay execute-step ledger rows from prior plan waves in the same goal (Slice B′).

    Used when a replan wave step has no in-plan dependencies but prior waves already
    recorded execute evidence for this goal.
    """
    from soothe.sloop.engine.execute.predecessor_branch_context import (
        DEFAULT_BRANCH_PREDECESSOR_MAX_MESSAGES,
        predecessor_execute_messages_for_branch,
    )

    prior_ids = _prior_wave_step_ids_in_goal_segment(loop_messages, decision)
    if not prior_ids:
        return []
    cap = max_messages if max_messages is not None else DEFAULT_BRANCH_PREDECESSOR_MAX_MESSAGES
    projected = predecessor_execute_messages_for_branch(
        loop_messages,
        prior_ids,
        max_messages=cap,
        exclude_step_ids=exclude_step_ids,
    )
    if projected:
        logger.debug(
            "Execute-step prior-wave projection: prior_steps=%d out_msgs=%d",
            len(prior_ids),
            len(projected),
        )
    return projected


def project_execute_step_graph_input(
    loop_messages: list[BaseMessage],
    *,
    state: LoopState,
    step: StepAction,
    decision: AgentDecision,
    checkpoint: StrangeLoopCheckpoint | None = None,
    soothe_config: Any | None = None,
    checkpoint_message_ids: frozenset[str] | None = None,
) -> ProjectedExecuteStepInput:
    """Assemble Slice A + Slice B ledger messages for execute-step CoreAgent input."""
    exec_cfg = _execute_prompt_ledger_config(soothe_config)
    plan_cfg = _plan_prompt_ledger_config(soothe_config)
    mode = resolve_execute_projection_mode(state)
    out: list[BaseMessage] = []
    cross_goal_projected = False
    excluded_step_ids: frozenset[str] = frozenset()

    if mode == "goal_boundary" and exec_cfg.cross_goal_completion_tail >= 0:
        # Always project prior goal_completion terminal units at the goal boundary
        # so the next goal has complete context (plan approvals, prior completions,
        # interrupted digests). The ``continue_loop`` gate was removed because plan
        # mode goals that end via PLAN_REVIEW (not FINALIZE) still need their
        # goal_completion pairs projected to the next goal regardless of whether
        # the loop was explicitly continued.
        tail_k = exec_cfg.cross_goal_completion_tail
        slice_a = project_cross_goal_completion_tail(
            loop_messages,
            k=tail_k,
            ledger_cfg=plan_cfg,
        )
        if slice_a:
            out.extend(slice_a)
            cross_goal_projected = True
            excluded_step_ids = execute_step_ids_subsumed_by_cross_goal_completion(
                loop_messages,
                k=tail_k,
            )

    predecessor_projected = False
    cap = exec_cfg.predecessor_max_messages
    if cap <= 0:
        cap = None
    if step.dependencies:
        slice_b = project_predecessor_execute_ledger_for_step(
            loop_messages,
            step,
            decision,
            max_messages=cap,
            exclude_step_ids=excluded_step_ids,
        )
        if slice_b:
            out.extend(slice_b)
            predecessor_projected = True
    elif mode == "mid_goal":
        slice_prior_wave = project_prior_wave_execute_ledger(
            loop_messages,
            decision,
            max_messages=cap,
            exclude_step_ids=excluded_step_ids,
        )
        if slice_prior_wave:
            out.extend(slice_prior_wave)
            predecessor_projected = True

    if checkpoint_message_ids:
        from soothe.sloop.utils.ledger_message_dedup import (
            filter_messages_not_in_checkpoint,
        )

        before = len(out)
        out = filter_messages_not_in_checkpoint(out, checkpoint_message_ids)
        if before != len(out):
            logger.debug(
                "Execute-step projection dedup: skipped=%d checkpoint_ids=%d step=%s",
                before - len(out),
                len(checkpoint_message_ids),
                step.id,
            )
            if predecessor_projected and not any(
                getattr(msg, "phase", None) == PHASE_EXECUTE_STEP for msg in out
            ):
                predecessor_projected = False

    logger.debug(
        "Execute-step graph projection: mode=%s cross_goal=%s predecessor=%s out_msgs=%d step=%s",
        mode,
        cross_goal_projected,
        predecessor_projected,
        len(out),
        step.id,
    )
    return ProjectedExecuteStepInput(
        messages=out,
        cross_goal_projected=cross_goal_projected,
        predecessor_projected=predecessor_projected,
        mode=mode,
    )


def project_predecessor_execute_ledger_for_step(
    loop_messages: list[BaseMessage],
    step: StepAction,
    decision: AgentDecision,
    *,
    max_messages: int | None = None,
    exclude_step_ids: frozenset[str] | None = None,
) -> list[BaseMessage]:
    """Project transitive-predecessor execute_step ledger rows for branched CoreAgent input.

    Branched step threads (``{main_thread_id}__{hex5}``) start with empty checkpoints.
    Dependent steps receive predecessor Human/AI pairs from the orchestration ledger
    instead of an inline ``PRIOR STEP EVIDENCE`` block in the current envelope.

    Args:
        loop_messages: ledger from ``LoopState.loop_messages``.
        step: Step about to execute on an isolated branch thread.
        decision: Current scoped plan decision (for transitive dependency closure).
        max_messages: Cap on copied ledger rows; ``None`` uses the branch default.
        exclude_step_ids: Step ids to exclude (execute rows subsumed by Slice A goal_completion).

    Returns:
        Deep-copied predecessor execute_step messages in ledger order.
    """
    from soothe.sloop.engine.execute.predecessor_branch_context import (
        DEFAULT_BRANCH_PREDECESSOR_MAX_MESSAGES,
    )
    from soothe.sloop.engine.execute.step_predecessor_context import (
        predecessor_messages_for_step,
    )

    cap = max_messages if max_messages is not None else DEFAULT_BRANCH_PREDECESSOR_MAX_MESSAGES
    projected = predecessor_messages_for_step(
        loop_messages,
        step,
        decision,
        max_messages=cap,
        exclude_step_ids=exclude_step_ids,
    )
    logger.debug(
        "Execute-step predecessor projection: step=%s deps=%d out_msgs=%d",
        step.id,
        len(step.dependencies or []),
        len(projected),
    )
    return projected


def project_loop_messages_for_core_agent(
    loop_messages: list[BaseMessage],
) -> list[BaseMessage]:
    """Return ledger messages for CoreAgent thread.

    Filters to only execute_step phase messages. Historical plan-spine ledger
    turns are not injected into the CoreAgent thread.

    Args:
        loop_messages: complete ledger from ``LoopState.loop_messages``.

    Returns:
        Filtered list with only execute_step Human/AI message pairs.
    """
    from soothe.sloop.utils.messages import LoopAIMessage, LoopHumanMessage

    out: list[BaseMessage] = []
    for msg in loop_messages:
        phase = getattr(msg, "phase", None)
        if isinstance(msg, (LoopHumanMessage, LoopAIMessage)):
            if phase == PHASE_EXECUTE_STEP:
                out.append(msg)
        # Also include any non-loop messages (plain HumanMessage/AIMessage from early phases)
        elif isinstance(msg, (HumanMessage, AIMessage)) and phase is None:
            out.append(msg)

    logger.debug(
        "CoreAgent ledger projection: %d execute_step messages (filtered from %d total)",
        len(out),
        len(loop_messages),
    )
    return out


def _compact_terminal_unit_for_synthesis(unit: list[BaseMessage]) -> list[BaseMessage]:
    """Rewrite a prior terminal unit's human envelope for goal-completion synthesis.

    Only the human envelope is replaced with a status-reference boundary; the AI
    terminal report is kept in full so the prior goal's completion report stays
    in the projection. Global ``plan_prompt_ledger`` caps still bound total size.
    """
    phase: str | None = None
    for msg in unit:
        p = getattr(msg, "phase", None)
        if p in _GOAL_TERMINAL_PHASES:
            phase = p
            break
    if phase == "goal_interrupted":
        compact_human = "Prior goal was interrupted. Full report follows."
    else:
        compact_human = "Prior goal completed. Full report follows."
    compact_human = _SYNTHESIS_PRIOR_GOAL_CONTEXT_BOUNDARY + compact_human

    out: list[BaseMessage] = []
    for msg in unit:
        copy_msg = _deep_copy_message(msg)
        if (
            phase is not None
            and getattr(copy_msg, "phase", None) == phase
            and _is_loop_human_message(copy_msg)
        ):
            copy_msg = _set_message_content(copy_msg, compact_human)
        out.append(copy_msg)
    return out


def _project_prior_goal_for_synthesis(
    loop_messages: list[BaseMessage],
    *,
    before_index: int,
    ledger_cfg: PlanPromptLedgerConfig | None,
    k: int,
) -> list[BaseMessage]:
    """Project up to ``k`` compacted prior terminal units for synthesis."""
    units = collect_cross_goal_completion_units(loop_messages, k=k)
    if not units:
        return []
    flat: list[BaseMessage] = []
    for unit in units:
        flat.extend(_compact_terminal_unit_for_synthesis(unit))
    return project_loop_messages_for_plan(flat, ledger_cfg)


def project_loop_messages_for_synthesis(
    loop_messages: list[BaseMessage],
    ledger_cfg: PlanPromptLedgerConfig | None = None,
    *,
    prior_goal_tail: int = 0,
) -> list[BaseMessage]:
    """Return ledger messages for goal-synthesis prompts.

    Unlike plan-assess / plan-generate, synthesis injects only ``execute_step``
    human/AI turns from the **current goal segment** — plan-phase reasoning and
    prior-goal execute rows are excluded. When prior terminals exist on the
    same loop, up to ``prior_goal_tail`` compacted prior completion/interrupted
    units are prepended as brief status reference (not full prior execute evidence).

    Optional ``plan_prompt_ledger`` caps apply to the filtered slice (same
    trimming as plan prompts).

    Args:
        loop_messages: complete ledger from ``LoopState.loop_messages``.
        ledger_cfg: Optional size caps; ``None`` treated as all limits disabled.
        prior_goal_tail: Max prior-goal terminal units to prepend.

    Returns:
        Current-goal execute_step messages (plus optional compact prior status),
        optionally deep-trimmed copies.
    """
    seg_start = _current_goal_segment_start(loop_messages)
    current_segment = loop_messages[seg_start:]
    execute_only = project_loop_messages_for_core_agent(current_segment)

    prior_msgs: list[BaseMessage] = []
    if seg_start > 0:
        prior_msgs = _project_prior_goal_for_synthesis(
            loop_messages,
            before_index=seg_start,
            ledger_cfg=ledger_cfg,
            k=prior_goal_tail,
        )

    combined = prior_msgs + execute_only
    projected = project_loop_messages_for_plan(combined, ledger_cfg)
    logger.debug(
        "Synthesis ledger projection: seg_start=%d prior=%d execute=%d out=%d (from %d total)",
        seg_start,
        len(prior_msgs),
        len(execute_only),
        len(projected),
        len(loop_messages),
    )
    return projected
