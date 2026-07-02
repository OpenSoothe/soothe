"""Predecessor execute-step ledger slices for parallel branch threads.

When the executor uses a branched LangGraph ``thread_id`` (``{logical}__step_{step_id}``), the
checkpoint namespace starts empty. This module provides helpers for:

- **Transitive dependency closure** (``transitive_dependency_step_ids``): used by
  ``predecessor_messages_for_step()`` / ``project_predecessor_execute_ledger_for_step()``
  for same-goal dependent steps.
- **Legacy ledger replay** (``prior_loop_execute_messages()``): retained for tests and
  tooling; loop-continuation bootstrap now grounds via ``PRIOR GOAL COMPLETION`` in the
  execute envelope (``continuation_context``) instead of replaying prior execute rows.

Same-goal DAG dependent steps ground predecessors via projected execute-step ledger rows
(RFC-214 §3.1); the current-step envelope carries only the task and hints.
"""

from __future__ import annotations

import copy
import logging
from typing import Any

from langchain_core.messages import BaseMessage

from soothe.foundation.sloop.state.schemas import AgentDecision, StepAction

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


def prior_loop_execute_messages(
    loop_messages: list[Any],
    *,
    max_messages: int = DEFAULT_BRANCH_PREDECESSOR_MAX_MESSAGES,
) -> list[BaseMessage]:
    """Return deep-copied ``execute_step`` ledger rows for loop-continuation bootstrap.

    Used by the executor when a bootstrap step (no dependencies) runs as the first
    step of a continuation goal. Unlike ``predecessor_execute_messages_for_branch``,
    this does not filter by step_id — it replays ALL prior execute_step rows
    from ``LoopState.loop_messages`` (synced from CE ledger for multi-goal context),
    so the agent sees the prior goal's conversation as context.

    Args:
        loop_messages: ``LoopState.loop_messages`` ledger (synced from CE or seeded from prior goal).
        max_messages: Hard cap on copied messages.

    Returns:
        Messages to prepend before the bootstrap step's execute envelope, in ledger order.
    """
    unlimited = max_messages <= 0

    out: list[BaseMessage] = []
    for msg in loop_messages:
        if getattr(msg, "phase", None) != "execute_step":
            continue
        out.append(_deep_copy_message(msg))
        if (not unlimited) and len(out) >= max_messages:
            logger.debug(
                "[LoopContinuation] truncated prior ledger slice at max_messages=%d",
                max_messages,
            )
            break
    return out


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
    if not predecessor_step_ids:
        return []
    unlimited = max_messages <= 0

    out: list[BaseMessage] = []
    for msg in loop_messages:
        if getattr(msg, "phase", None) != "execute_step":
            continue
        sid = _message_step_id(msg)
        if sid is None or sid not in predecessor_step_ids:
            continue
        out.append(_deep_copy_message(msg))
        if (not unlimited) and len(out) >= max_messages:
            logger.debug(
                "[BranchPred] truncated predecessor ledger slice at max_messages=%d",
                max_messages,
            )
            break
    return out
