"""Predecessor execute-step ledger slices for parallel branch threads.

When the executor uses a branched LangGraph ``thread_id`` (``{logical}__p{step_id}``), the
checkpoint namespace starts empty. This module selects prior ``execute_step`` Human/AI
ledger rows whose ``step_id`` is in the transitive dependency closure of the current step
so the branch CoreAgent receives dependency context without merging sibling parallel
threads. Design: RFC-214 (unified ledger; parallel branch predecessor replay).
"""

from __future__ import annotations

import copy
import logging
from typing import Any

from langchain_core.messages import BaseMessage

from soothe.core.loop.state.schemas import AgentDecision, StepAction

logger = logging.getLogger(__name__)

DEFAULT_BRANCH_PREDECESSOR_MAX_MESSAGES = 96


def _deep_copy_message(msg: BaseMessage) -> BaseMessage:
    copier = getattr(msg, "model_copy", None)
    if callable(copier):
        return copier(deep=True)
    return copy.deepcopy(msg)


def _message_step_id(msg: Any) -> str | None:
    sid = getattr(msg, "step_id", None)
    if isinstance(sid, str) and sid.strip():
        return sid.strip()
    add = getattr(msg, "additional_kwargs", None) or {}
    if isinstance(add, dict):
        v = add.get("step_id")
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def transitive_dependency_step_ids(step: StepAction, decision: AgentDecision) -> frozenset[str]:
    """Collect dependency step ids reachable backward through in-plan edges.

    Includes every string listed in ``step.dependencies`` (cross-plan refs may appear here)
    and, for each dependency that matches another step in ``decision.steps``, expands
    recursively through that step's dependencies.

    Args:
        step: Step about to run on a parallel branch.
        decision: Current scoped decision (composite step ids).

    Returns:
        Frozen set of predecessor step ids (may be empty).
    """
    by_id: dict[str, StepAction] = {s.id: s for s in decision.steps}
    acc: set[str] = set()
    stack: list[str] = list(step.dependencies or [])
    while stack:
        dep = (stack.pop() or "").strip()
        if not dep or dep in acc:
            continue
        acc.add(dep)
        other = by_id.get(dep)
        if other and other.dependencies:
            for d in other.dependencies:
                ds = (d or "").strip()
                if ds and ds not in acc:
                    stack.append(ds)
    return frozenset(acc)


def predecessor_execute_messages_for_branch(
    loop_messages: list[Any],
    predecessor_step_ids: frozenset[str],
    *,
    max_messages: int = DEFAULT_BRANCH_PREDECESSOR_MAX_MESSAGES,
) -> list[BaseMessage]:
    """Return deep-copied ledger messages for predecessor steps, in ledger order.

    Only messages tagged ``phase == \"execute_step\"`` with a ``step_id`` in
    ``predecessor_step_ids`` are included. Chronological order follows
    ``loop_messages`` iteration (RFC-214 append order).

    Args:
        loop_messages: ``LoopState.loop_messages`` ledger.
        predecessor_step_ids: Step ids whose execute evidence should be replayed.
        max_messages: Hard cap on copied messages (Human+AI rows each count as one).

    Returns:
        Messages to prepend before the current step's execute envelope.
    """
    if not predecessor_step_ids or max_messages <= 0:
        return []

    out: list[BaseMessage] = []
    for msg in loop_messages:
        if getattr(msg, "phase", None) != "execute_step":
            continue
        sid = _message_step_id(msg)
        if sid is None or sid not in predecessor_step_ids:
            continue
        out.append(_deep_copy_message(msg))
        if len(out) >= max_messages:
            logger.debug(
                "[BranchPred] truncated predecessor ledger slice at max_messages=%d",
                max_messages,
            )
            break
    return out
