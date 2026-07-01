"""Shared DAG utilities for step dependency token expansion (IG-400, IG-537)."""

from __future__ import annotations

from collections.abc import Iterable


def expand_dependency_satisfaction_ids(completed_step_ids: Iterable[str]) -> set[str]:
    """Expand completed step ids with unambiguous local numeric suffix aliases.

    After ``assign_plan_step_ids``, successful steps are keyed by composite ids such as
    ``KFA-01``. Later plans may reference prior work using the model-local token ``01``
    (or ``1``) in ``dependencies``. Runtime completion sets only contained composite ids,
    so ready-step checks would block the entire wave without alias expansion.

    Adds **only** suffix tokens that map to **exactly one** completed composite id
    with the same integer value.

    Args:
        completed_step_ids: Definitive completed ids (typically from StepDAG or LoopState).

    Returns:
        Superset of ``completed_step_ids`` including safe aliases.
    """
    base = set(completed_step_ids)
    if not base:
        return base

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
