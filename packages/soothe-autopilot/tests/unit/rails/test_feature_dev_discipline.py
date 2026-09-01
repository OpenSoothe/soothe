"""IG-737: feature-dev scout / plan / implement brief discipline."""

from __future__ import annotations

import pytest
from soothe.context.engine import ContextEngine
from soothe.rails.builtins_exec import RailBuiltinExecutor, RailJobState


@pytest.mark.asyncio
async def test_decompose_and_plan_implement_discipline_briefs() -> None:
    ce = ContextEngine()
    root = await ce.create_goal("Ship feature X", priority=70)
    ex = RailBuiltinExecutor(ce)
    await ex.bind_job(
        RailJobState(
            job_id=root.id,
            rail_id="feature-dev",
            rail_version="1.4",
        )
    )

    dec = await ex.invoke("decompose_parallel", job_id=root.id, trigger_goal_id=None)
    assert dec.status == "success"
    assert dec.created_goal_ids
    for gid in dec.created_goal_ids:
        g = await ce.get_goal(gid)
        assert g is not None
        assert "Systematic debugging" in g.description

    for gid in dec.created_goal_ids:
        await ce.complete_goal(gid)

    pi = await ex.invoke("plan_and_implement", job_id=root.id, trigger_goal_id=None)
    assert pi.status == "success"
    assert len(pi.created_goal_ids) == 2
    plan_g = await ce.get_goal(pi.created_goal_ids[0])
    impl_g = await ce.get_goal(pi.created_goal_ids[1])
    assert plan_g is not None
    assert impl_g is not None
    assert "Parallel dispatch:" in plan_g.description
    assert 'invoke_skill("using-git-worktrees")' in impl_g.description
    assert "NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST" in impl_g.description
