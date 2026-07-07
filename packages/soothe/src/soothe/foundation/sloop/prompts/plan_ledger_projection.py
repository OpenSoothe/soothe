"""Project StrangeLoop ledger messages for plan-assess / plan-generate (IG-380, RFC-214).

RFC-214: The complete ledger includes all phases (plan_assess, plan_generate,
execute_step). Plan-assess, plan-generate, and continuation-assess prompts omit prior
``plan_assess`` pairs from projected ledger; generate receives assess status
via the inline ``ASSESSMENT`` task envelope instead. CoreAgent execution sees only execute_step
messages (plan-phase reasoning not injected into CoreAgent thread).

When ``PlanPromptLedgerConfig`` limits are all zero/unset behavior, the caller
receives the same message object references as ``state.loop_messages`` (shallow
list copy). When any limit is positive, messages are deep-copied and trimmed
without mutating persisted ledger state.
"""

from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from soothe.foundation.sloop.utils.stream_normalize import extract_text_from_message_content

if TYPE_CHECKING:
    from soothe.config.models import ExecutePromptLedgerConfig, PlanPromptLedgerConfig
    from soothe.foundation.sloop.state.checkpoint import StrangeLoopCheckpoint
    from soothe.foundation.sloop.state.schemas import AgentDecision, LoopState, StepAction

logger = logging.getLogger(__name__)

PlannerProjectionMode = Literal["new_goal", "mid_goal"]
ExecuteProjectionMode = Literal["goal_boundary", "mid_goal"]


@dataclass
class ProjectedExecuteStepInput:
    """Result of execute-step graph ledger projection (IG-542)."""

    messages: list[BaseMessage] = field(default_factory=list)
    cross_goal_projected: bool = False
    predecessor_projected: bool = False
    mode: ExecuteProjectionMode = "mid_goal"


_LEDGER_OMITTED_MARKER = "[Earlier ledger content omitted for plan prompt size]\n\n"
_TRUNC_PER_MSG = "\n…[truncated for plan prompt]\n"
_NEW_GOAL_LEDGER_PHASES = frozenset({"intent_classify", "plan_generate", "goal_completion"})
_PLANNER_PROJECTED_EXCLUDED_PHASES = frozenset({"plan_assess"})
_MID_GOAL_CURRENT_PHASES = frozenset({"intent_classify", "plan_generate", "execute_step"})

# IG-555: Boundary marker for prior goal completion in planning projections.
# Prevents planner anchoring on prior "Recommended next actions" instead of
# decomposing the current goal independently.
_GOAL_COMPLETION_CONTEXT_BOUNDARY = (
    '<PRIOR_GOAL_CONTEXT role="reference_resolution">\n'
    "The following completed goal provides context for resolving user mentions.\n"
    "DO NOT use the recommended actions below as your plan template.\n"
    "Decompose the current goal independently based on its scope.\n"
)


def resolve_planner_projection_mode(state: LoopState) -> PlannerProjectionMode:
    """Return ``new_goal`` at iter=0 before any execution, else ``mid_goal``."""
    if state.iteration == 0 and not state.step_results:
        return "new_goal"
    return "mid_goal"


def filter_loop_messages_for_planner_mode(
    loop_messages: list[BaseMessage],
    mode: PlannerProjectionMode,
) -> list[BaseMessage]:
    """Phase-filter ledger messages before tail/cap projection."""
    if mode == "mid_goal":
        return list(loop_messages)
    out: list[BaseMessage] = []
    for msg in loop_messages:
        phase = getattr(msg, "phase", None)
        if phase in _NEW_GOAL_LEDGER_PHASES:
            out.append(msg)
    return out


def filter_ledger_phases(
    loop_messages: list[BaseMessage],
    exclude_phases: frozenset[str],
) -> list[BaseMessage]:
    """Drop ledger rows whose ``phase`` is in ``exclude_phases``."""
    if not exclude_phases:
        return list(loop_messages)
    return [msg for msg in loop_messages if getattr(msg, "phase", None) not in exclude_phases]


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


def _extract_step_ids_from_messages(messages: list[BaseMessage]) -> frozenset[str]:
    """Extract all unique step_id values from a list of messages."""
    step_ids: set[str] = set()
    for msg in messages:
        sid = _message_step_id(msg)
        if sid:
            step_ids.add(sid)
    return frozenset(step_ids)


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


def _trim_total_chars_front(
    messages: list[BaseMessage], max_chars: int
) -> tuple[list[BaseMessage], bool]:
    """Drop oldest messages until total extracted text <= max_chars (or one truncated body).

    Returns:
        (trimmed_messages, True) if any leading messages were dropped or body was hard-clipped.
    """
    if max_chars <= 0 or not messages:
        return messages, False

    def total_len(ms: list[BaseMessage]) -> int:
        return sum(_message_text_len(m) for m in ms)

    out = list(messages)
    shrunk = False
    while out and total_len(out) > max_chars:
        if len(out) == 1:
            m0 = out[0]
            text = extract_text_from_message_content(getattr(m0, "content", ""))
            if len(text) <= max_chars:
                break
            marker = "\n…[truncated for plan prompt]\n"
            clipped = text[: max(0, max_chars - len(marker))] + marker
            out[0] = _set_message_content(m0, clipped)
            shrunk = True
            break
        out.pop(0)
        shrunk = True
    return out, shrunk


def _compact_intent_classify_human_for_projection(msg: BaseMessage) -> BaseMessage:
    """Rewrite ``GOAL:`` to ``GOAL RECAP:`` on projected intent-classify humans (D1)."""
    if getattr(msg, "phase", None) != "intent_classify" or not _is_loop_human_message(msg):
        return msg
    from soothe.foundation.sloop.cognition.ledger_compaction import compact_planning_human_content

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
    """Return ledger messages for plan LLM prompts (IG-380).

    Args:
        loop_messages: RFC-214 ledger from ``LoopState.loop_messages``.
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
        copies = [_cap_single_message_content(m, max_per) for m in copies]

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
    """Return index after the last prior-goal ``goal_completion`` AI row."""
    for i in range(len(loop_messages) - 1, -1, -1):
        msg = loop_messages[i]
        if getattr(msg, "phase", None) == "goal_completion" and _is_loop_ai_message(msg):
            return i + 1
    return 0


def _project_planner_ledger_mid_goal_isolated(
    loop_messages: list[BaseMessage],
    *,
    ledger_cfg: PlanPromptLedgerConfig | None,
    soothe_config: Any | None,
    exclude_phases: frozenset[str],
) -> list[BaseMessage]:
    """Mid-goal planner projection: Slice A prior goals + current-goal segment only.

    IG-555: Slice A includes boundary marker to prevent planner anchoring.
    """
    exec_cfg = _execute_prompt_ledger_config(soothe_config)
    slice_a = project_cross_goal_completion_tail(
        loop_messages,
        k=exec_cfg.cross_goal_completion_tail,
        ledger_cfg=ledger_cfg,
        include_boundary=True,  # IG-555: prevent planner anchoring
    )
    seg_start = _current_goal_segment_start(loop_messages)
    current_segment = [
        _deep_copy_message(m)
        for m in loop_messages[seg_start:]
        if getattr(m, "phase", None) in _MID_GOAL_CURRENT_PHASES
    ]
    combined = [*slice_a, *current_segment]
    filtered = filter_ledger_phases(combined, exclude_phases)
    projected = project_loop_messages_for_plan(filtered, ledger_cfg)
    logger.debug(
        "Planner mid_goal projection: slice_a=%d current=%d out=%d seg_start=%d",
        len(slice_a),
        len(current_segment),
        len(projected),
        seg_start,
    )
    return projected


def project_planner_ledger(
    loop_messages: list[BaseMessage],
    mode: PlannerProjectionMode,
    ledger_cfg: PlanPromptLedgerConfig | None,
    *,
    exclude_phases: frozenset[str] | None = None,
    soothe_config: Any | None = None,
) -> list[BaseMessage]:
    """Project CE ledger for planner prompts with ``new_goal`` / ``mid_goal`` phase filter (IG-538).

    Args:
        loop_messages: Full RFC-214 ledger from ``LoopState.loop_messages``.
        mode: ``new_goal`` excludes ``execute_step`` by default; ``mid_goal`` uses Slice A
            (prior ``goal_completion`` units) plus the current goal segment only.
        ledger_cfg: Optional tail/char caps (IG-380).
        exclude_phases: Extra phase tags to omit in addition to ``plan_assess``.
        soothe_config: Optional SootheConfig for execute Slice A ``cross_goal_completion_tail``.

    Returns:
        Filtered then capped message list for plan LLM prompts.
    """
    phases_to_exclude = _PLANNER_PROJECTED_EXCLUDED_PHASES | (exclude_phases or frozenset())
    if mode == "mid_goal":
        return _project_planner_ledger_mid_goal_isolated(
            loop_messages,
            ledger_cfg=ledger_cfg,
            soothe_config=soothe_config,
            exclude_phases=phases_to_exclude,
        )

    filtered = filter_loop_messages_for_planner_mode(loop_messages, mode)
    filtered = filter_ledger_phases(filtered, phases_to_exclude)
    filtered = _compact_goal_completion_units_in_messages(filtered, include_boundary=True)
    projected = project_loop_messages_for_plan(filtered, ledger_cfg)
    logger.debug(
        "Planner ledger projection: mode=%s in=%d filtered=%d out=%d exclude=%s boundary=%s",
        mode,
        len(loop_messages),
        len(filtered),
        len(projected),
        sorted(phases_to_exclude),
        True,
    )
    return projected


_EXECUTE_AI_STRIP_PREFIXES = (
    "GOAL:",
    "INSTRUCTIONS:",
    "WORKSPACE:",
    "<INSTRUCTIONS",
    "<WORKSPACE",
)


def _is_execute_ai_message(msg: BaseMessage) -> bool:
    return getattr(msg, "phase", None) == "execute_step" and _is_loop_ai_message(msg)


def _compact_execute_ai_for_assess(msg: BaseMessage, max_chars: int) -> BaseMessage:
    """Keep outcome prose; strip planning boilerplate from execute AI rows."""
    text = extract_text_from_message_content(getattr(msg, "content", ""))
    lines: list[str] = []
    skip_block = False
    for line in text.splitlines():
        stripped = line.strip()
        if any(stripped.startswith(prefix) for prefix in _EXECUTE_AI_STRIP_PREFIXES):
            skip_block = True
            continue
        if skip_block:
            if not stripped:
                skip_block = False
            continue
        lines.append(line)
    compacted = "\n".join(lines).strip() or text.strip()
    if max_chars > 0 and len(compacted) > max_chars:
        compacted = compacted[-max_chars:]
    return _set_message_content(_deep_copy_message(msg), compacted)


def _apply_head_tail_message_cap(
    messages: list[BaseMessage],
    max_msg: int,
    *,
    keep_head_tail: bool,
) -> list[BaseMessage]:
    """Keep first-wave and recent execute AI rows when tail-truncating."""
    if max_msg <= 0 or len(messages) <= max_msg:
        return messages
    if not keep_head_tail:
        return messages[-max_msg:]
    head = max(1, max_msg // 4)
    tail = max_msg - head
    if head + tail >= len(messages):
        return messages
    return [*messages[:head], *messages[-tail:]]


def _collect_assess_execute_ai(
    loop_messages: list[BaseMessage],
    mode: PlannerProjectionMode,
) -> list[BaseMessage]:
    """Collect current-goal execute AI rows for assess projection."""
    if mode == "new_goal":
        has_execute = any(_is_execute_ai_message(m) for m in loop_messages)
        if not has_execute:
            return []
        seg_start = 0
    else:
        seg_start = _current_goal_segment_start(loop_messages)
    return [m for m in loop_messages[seg_start:] if _is_execute_ai_message(m)]


def _assess_prompt_ledger_config(soothe_config: Any | None) -> Any | None:
    from soothe.config.models import PlanAssessPromptConfig

    if soothe_config is None:
        return PlanAssessPromptConfig()
    loop_cfg = getattr(soothe_config, "agent", None)
    loop_cfg = getattr(loop_cfg, "loop", None) if loop_cfg is not None else None
    assess_cfg = getattr(loop_cfg, "plan_assess_prompt", None) if loop_cfg is not None else None
    if assess_cfg is None:
        return PlanAssessPromptConfig()
    return assess_cfg


def _assess_effective_ledger_cfg(
    assess_cfg: Any,
    shared_cfg: PlanPromptLedgerConfig | None,
) -> PlanPromptLedgerConfig | None:
    from soothe.config.models import PlanPromptLedgerConfig

    max_msg = int(getattr(assess_cfg, "ledger_max_messages", 24))
    max_total = int(shared_cfg.plan_ledger_max_total_chars) if shared_cfg is not None else 0
    max_per = int(shared_cfg.plan_ledger_max_message_chars) if shared_cfg is not None else 0
    if max_msg <= 0 and max_total <= 0 and max_per <= 0:
        return None
    return PlanPromptLedgerConfig(
        plan_ledger_max_messages=max_msg,
        plan_ledger_max_total_chars=max_total,
        plan_ledger_max_message_chars=max_per,
    )


def project_planner_ledger_for_assess(
    loop_messages: list[BaseMessage],
    mode: PlannerProjectionMode,
    ledger_cfg: PlanPromptLedgerConfig | None,
    *,
    soothe_config: Any | None = None,
) -> list[BaseMessage]:
    """Assess-only ledger projection: current-goal execute AI rows only (IG-557)."""
    assess_cfg = _assess_prompt_ledger_config(soothe_config)

    execute_ai = _collect_assess_execute_ai(loop_messages, mode)
    max_per = int(getattr(assess_cfg, "execute_ai_max_chars", 400))
    compacted = [_compact_execute_ai_for_assess(m, max_per) for m in execute_ai]
    max_msg = int(getattr(assess_cfg, "ledger_max_messages", 24))
    trimmed = _apply_head_tail_message_cap(
        compacted,
        max_msg,
        keep_head_tail=bool(getattr(assess_cfg, "keep_head_tail_execute_ai", True)),
    )
    effective_cfg = _assess_effective_ledger_cfg(assess_cfg, ledger_cfg)
    projected = project_loop_messages_for_plan(trimmed, effective_cfg)
    logger.debug(
        "Assess ledger projection: mode=%s execute_ai=%d out=%d",
        mode,
        len(execute_ai),
        len(projected),
    )
    return projected


def project_continuation_assess_ledger(
    loop_messages: list[BaseMessage],
    ledger_cfg: PlanPromptLedgerConfig | None,
) -> list[BaseMessage]:
    """Lean ledger for continuation-assess: last goal_completion unit only (mirrors intake).

    IG-555: Includes boundary marker to prevent anchoring on prior recommendations.
    """
    return project_last_goal_completion_for_intake(loop_messages, ledger_cfg, include_boundary=True)


def _is_loop_human_message(msg: BaseMessage) -> bool:
    name = type(msg).__name__
    return name.endswith("HumanMessage")


def _is_loop_ai_message(msg: BaseMessage) -> bool:
    name = type(msg).__name__
    return name.endswith("AIMessage")


def _extract_last_phase_pair(
    loop_messages: list[BaseMessage],
    phase: str,
) -> list[BaseMessage]:
    """Return the last human+AI pair for ``phase``, or the trailing AI alone."""
    last_ai_idx: int | None = None
    for i in range(len(loop_messages) - 1, -1, -1):
        msg = loop_messages[i]
        if getattr(msg, "phase", None) == phase and _is_loop_ai_message(msg):
            last_ai_idx = i
            break
    if last_ai_idx is None:
        return []
    last_human_idx: int | None = None
    for j in range(last_ai_idx - 1, -1, -1):
        msg = loop_messages[j]
        if getattr(msg, "phase", None) == phase and _is_loop_human_message(msg):
            last_human_idx = j
            break
    if last_human_idx is not None:
        return list(loop_messages[last_human_idx : last_ai_idx + 1])
    return [loop_messages[last_ai_idx]]


def _compact_goal_completion_units_in_messages(
    messages: list[BaseMessage],
    *,
    include_boundary: bool,
) -> list[BaseMessage]:
    """Rewrite ``goal_completion`` pairs in a flat ledger slice for planner prompts."""
    out: list[BaseMessage] = []
    i = 0
    while i < len(messages):
        msg = messages[i]
        phase = getattr(msg, "phase", None)
        if (
            phase == "goal_completion"
            and _is_loop_human_message(msg)
            and i + 1 < len(messages)
            and getattr(messages[i + 1], "phase", None) == "goal_completion"
            and _is_loop_ai_message(messages[i + 1])
        ):
            out.extend(
                _compact_goal_completion_unit_for_projection(
                    [msg, messages[i + 1]],
                    include_boundary=include_boundary,
                )
            )
            i += 2
            continue
        out.append(_deep_copy_message(msg))
        i += 1
    return out


def _compact_goal_completion_unit_for_projection(
    unit: list[BaseMessage],
    *,
    include_boundary: bool = True,
) -> list[BaseMessage]:
    """Rewrite goal_completion human envelopes for downstream prompt projection.

    Args:
        unit: Human/AI pair for a goal_completion ledger phase.
        include_boundary: When True (default), prepend IG-555 boundary marker
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


def project_last_goal_completion_for_intake(
    loop_messages: list[BaseMessage],
    ledger_cfg: PlanPromptLedgerConfig | None,
    *,
    include_boundary: bool = True,
) -> list[BaseMessage]:
    """Project the last ``goal_completion`` ledger unit into intake classify input (IG-540).

    Uses the same ``goal_completion`` resolution as execute Slice A. The synthesis
    human envelope is rewritten to a short label so the classifier focuses on the
    terminal AI report.

    Args:
        loop_messages: Full RFC-214 ledger loaded from CE persistence.
        ledger_cfg: Optional caps (same knobs as plan prompts).
        include_boundary: When True (default), prepend IG-555 boundary marker.
            Set False for intake Pass 2 where classifier needs prior scope signal.

    Returns:
        Bounded ledger slice injected before the classify human message.
    """
    if not loop_messages:
        return []

    found = resolve_goal_completion_unit(loop_messages, len(loop_messages))
    if found is not None:
        unit, _ = found
        projected = project_loop_messages_for_plan(
            _compact_goal_completion_unit_for_projection(unit, include_boundary=include_boundary),
            ledger_cfg,
        )
        logger.debug(
            "Intake goal-completion projection: in=%d out=%d boundary=%s",
            len(unit),
            len(projected),
            include_boundary,
        )
        return projected

    return []


def _current_goal_has_execute_ledger(state: LoopState) -> bool:
    """True when the active plan already has execute_step rows in the orchestration ledger."""
    decision = state.current_decision
    if decision is None:
        return False
    plan_step_ids = {s.id for s in decision.steps}
    if not plan_step_ids:
        return False
    for msg in state.loop_messages:
        if getattr(msg, "phase", None) != "execute_step":
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
        if _current_goal_has_execute_ledger(state):
            return "mid_goal"
        if state.dependency_completion_ids():
            return "mid_goal"
        return "goal_boundary"
    return "mid_goal"


def _execute_plan_tail_index(loop_messages: list[BaseMessage]) -> int:
    """Index before trailing plan-phase rows for the current goal (exclude from Slice A scan)."""
    idx = len(loop_messages)
    plan_phases = frozenset({"plan_assess", "plan_generate", "intent_classify", "continuation"})
    while idx > 0:
        phase = getattr(loop_messages[idx - 1], "phase", None)
        if phase in plan_phases:
            idx -= 1
        else:
            break
    return idx


def _goal_segment_start(loop_messages: list[BaseMessage], unit_start: int) -> int:
    """Return index where the goal segment containing ``unit_start`` began."""
    seg_after_prev_gc = 0
    for i in range(unit_start - 1, -1, -1):
        msg = loop_messages[i]
        if getattr(msg, "phase", None) == "goal_completion" and _is_loop_ai_message(msg):
            seg_after_prev_gc = i + 1
            break
    for i in range(seg_after_prev_gc, unit_start):
        if getattr(loop_messages[i], "phase", None) == "intent_classify":
            return i
    return seg_after_prev_gc


def _find_last_phase_pair_indices(
    loop_messages: list[BaseMessage],
    before_index: int,
    phase: str,
) -> tuple[int, int] | None:
    """Return ``(human_idx, ai_idx)`` for the last ``phase`` pair ending before ``before_index``."""
    if before_index <= 0:
        return None
    ai_idx: int | None = None
    for i in range(before_index - 1, -1, -1):
        msg = loop_messages[i]
        if getattr(msg, "phase", None) == phase and _is_loop_ai_message(msg):
            ai_idx = i
            break
    if ai_idx is None:
        return None
    human_idx: int | None = None
    for j in range(ai_idx - 1, -1, -1):
        msg = loop_messages[j]
        if getattr(msg, "phase", None) == phase and _is_loop_human_message(msg):
            human_idx = j
            break
    if human_idx is not None:
        return human_idx, ai_idx
    return ai_idx, ai_idx


def resolve_goal_completion_unit(
    loop_messages: list[BaseMessage],
    before_index: int,
) -> tuple[list[BaseMessage], int] | None:
    """Resolve one prior-goal ``goal_completion`` unit ending before ``before_index``."""
    idxs = _find_last_phase_pair_indices(loop_messages, before_index, "goal_completion")
    if idxs is None:
        return None
    start, end = idxs
    unit = [_deep_copy_message(loop_messages[i]) for i in range(start, end + 1)]
    return unit, start


def collect_cross_goal_completion_units(
    loop_messages: list[BaseMessage],
    *,
    k: int,
) -> list[list[BaseMessage]]:
    """Collect up to ``k`` prior-goal completion units, oldest first."""
    if k <= 0 or not loop_messages:
        return []

    units_rev: list[list[BaseMessage]] = []
    cursor = _execute_plan_tail_index(loop_messages)
    while len(units_rev) < k and cursor > 0:
        found = resolve_goal_completion_unit(loop_messages, cursor)
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
    """Return execute ``step_id`` values subsumed by projected ``goal_completion`` units.

    When Slice A replays a prior goal's terminal ``goal_completion`` report, the
    ``execute_step`` rows from that same goal segment must not appear again in Slice B
    (including ``ledger_direct`` goals where the completion body copies execute text).
    """
    if k <= 0 or not loop_messages:
        return frozenset()

    subsumed: set[str] = set()
    cursor = _execute_plan_tail_index(loop_messages)
    collected = 0
    while collected < k and cursor > 0:
        found = resolve_goal_completion_unit(loop_messages, cursor)
        if found is None:
            break
        _unit, start = found
        segment_start = _goal_segment_start(loop_messages, start)
        for i in range(segment_start, start):
            msg = loop_messages[i]
            if getattr(msg, "phase", None) != "execute_step":
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
    """Project K prior-goal ``goal_completion`` units for execute Slice A (IG-542).

    Args:
        loop_messages: Full RFC-214 ledger.
        k: Maximum number of prior goal completion units to project.
        ledger_cfg: Optional caps.
        include_boundary: When False (default for execute), omit IG-555 boundary marker
            since prior actions genuinely help execution grounding. Set True for
            planner projections where anchoring prevention is needed.

    Returns:
        Bounded ledger slice for Slice A.
    """
    units = collect_cross_goal_completion_units(loop_messages, k=k)
    flat: list[BaseMessage] = []
    for unit in units:
        flat.extend(
            _compact_goal_completion_unit_for_projection(unit, include_boundary=include_boundary)
        )
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


def project_execute_step_graph_input(
    loop_messages: list[BaseMessage],
    *,
    state: LoopState,
    step: StepAction,
    decision: AgentDecision,
    checkpoint: StrangeLoopCheckpoint | None = None,
    soothe_config: Any | None = None,
) -> ProjectedExecuteStepInput:
    """Assemble Slice A + Slice B ledger messages for execute-step CoreAgent input."""
    exec_cfg = _execute_prompt_ledger_config(soothe_config)
    plan_cfg = _plan_prompt_ledger_config(soothe_config)
    mode = resolve_execute_projection_mode(state)
    out: list[BaseMessage] = []
    cross_goal_projected = False
    excluded_step_ids: frozenset[str] = frozenset()

    if mode == "goal_boundary" and exec_cfg.cross_goal_completion_tail > 0:
        if getattr(state, "continue_loop", False):
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
    if step.dependencies:
        cap = exec_cfg.predecessor_max_messages
        if cap <= 0:
            cap = None
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

    Branched step threads (``{logical}__step_{step_id}``) start with empty checkpoints.
    Dependent steps receive predecessor Human/AI pairs from the orchestration ledger
    instead of an inline ``PRIOR STEP EVIDENCE`` block in the current envelope.

    Args:
        loop_messages: RFC-214 ledger from ``LoopState.loop_messages``.
        step: Step about to execute on an isolated branch thread.
        decision: Current scoped plan decision (for transitive dependency closure).
        max_messages: Cap on copied ledger rows; ``None`` uses the branch default.
        exclude_step_ids: Step ids to exclude (execute rows subsumed by Slice A goal_completion).

    Returns:
        Deep-copied predecessor execute_step messages in ledger order.
    """
    from soothe.foundation.sloop.engine.predecessor_branch_context import (
        DEFAULT_BRANCH_PREDECESSOR_MAX_MESSAGES,
    )
    from soothe.foundation.sloop.engine.step_predecessor_context import (
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
    """Return ledger messages for CoreAgent thread (RFC-214).

    Filters to only execute_step phase messages. Plan-phase messages
    (plan_assess, plan_generate) are NOT injected into CoreAgent thread,
    keeping CoreAgent's history focused on tool execution.

    Args:
        loop_messages: RFC-214 complete ledger from ``LoopState.loop_messages``.

    Returns:
        Filtered list with only execute_step Human/AI message pairs.
    """
    from soothe.foundation.sloop.utils.messages import LoopAIMessage, LoopHumanMessage

    out: list[BaseMessage] = []
    for msg in loop_messages:
        phase = getattr(msg, "phase", None)
        if isinstance(msg, (LoopHumanMessage, LoopAIMessage)):
            if phase == "execute_step":
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


def project_loop_messages_for_synthesis(
    loop_messages: list[BaseMessage],
    ledger_cfg: PlanPromptLedgerConfig | None = None,
) -> list[BaseMessage]:
    """Return execute_step ledger messages for goal-synthesis prompts (RFC-214).

    Unlike plan-assess / plan-generate, synthesis injects only ``execute_step``
    human/AI turns — plan-phase reasoning is excluded. Optional ``plan_prompt_ledger``
    caps apply to the filtered slice (same trimming as plan prompts).

    Args:
        loop_messages: RFC-214 complete ledger from ``LoopState.loop_messages``.
        ledger_cfg: Optional size caps; ``None`` treated as all limits disabled.

    Returns:
        Filtered execute_step messages, optionally deep-trimmed copies.
    """
    execute_only = project_loop_messages_for_core_agent(loop_messages)
    projected = project_loop_messages_for_plan(execute_only, ledger_cfg)
    logger.debug(
        "Synthesis ledger projection: %d execute_step messages (filtered from %d total)",
        len(projected),
        len(loop_messages),
    )
    return projected
