"""Dependency token expansion for cross-plan step id matching (IG-400, IG-379 alignment)."""

from __future__ import annotations

from collections.abc import Iterable


def expand_dependency_satisfaction_ids(completed_step_ids: Iterable[str]) -> set[str]:
    """Expand completed step ids with unambiguous local numeric suffix aliases.

    After ``assign_plan_step_ids``, successful steps are keyed by composite ids such as
    ``KFA-01``. Later plans may reference prior work using the model-local token ``01``
    (or ``1``) in ``dependencies`` / ``evidence_refs``. Runtime completion sets only
    contained composite ids, so :meth:`~soothe.core.loop.state.schemas.AgentDecision.get_ready_steps`
    would block the entire wave.

    This helper adds **only** suffix tokens that map to **exactly one** completed
    composite id with the same integer value (same disambiguation spirit as IG-379).

    Args:
        completed_step_ids: Definitive completed ids (typically
            ``LoopState.dependency_completion_ids()`` or DAG ``get_completed_step_ids()``).

    Returns:
        Superset of ``completed_step_ids`` including safe aliases (e.g. ``KFA-01`` → ``01``,
        ``1`` when unambiguous).
    """
    base = set(completed_step_ids)
    if not base:
        return base

    # Map int value -> composite ids whose hyphen-suffix parses to that int
    value_to_owners: dict[int, list[str]] = {}
    for sid in base:
        if "-" not in sid:
            continue
        tail = sid.rsplit("-", 1)[-1]
        if not tail.isdigit():
            continue
        value_to_owners.setdefault(int(tail, 10), []).append(sid)

    for owners in value_to_owners.values():
        if len(owners) != 1:
            continue
        own = owners[0]
        tail = own.rsplit("-", 1)[-1]
        base.add(tail)
        base.add(str(int(tail, 10)))
    return base
