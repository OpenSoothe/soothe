"""Unit tests for Rail Exec ``do:`` recipes (IG-717 / RFC-231 M3)."""

from __future__ import annotations

from pathlib import Path

import pytest
from soothe.context import ContextEngine
from soothe.rails import LoopRailCatalog, RailCatalogError, load_rail_file
from soothe.rails.builtins_exec import RailBuiltinExecutor, RailJobState


@pytest.mark.asyncio
async def test_recipe_do_spawns_chained_goals(tmp_path: Path) -> None:
    ce = ContextEngine()
    root = await ce.create_goal("Job", workspace=str(tmp_path), priority=70)
    ex = RailBuiltinExecutor(ce, jobs_root=tmp_path)
    await ex.bind_job(
        RailJobState(
            job_id=root.id,
            rail_id="custom",
            rail_version="1.0",
            verb_overrides={
                "spawn_feedback_cycle": {
                    "do": [
                        {"gate": {"unless": "acceptance_met", "max": "feedback_rounds"}},
                        {"bump": "feedback_round"},
                        {
                            "spawn_goal": {
                                "id": "diagnose",
                                "role": "diagnoser",
                                "tags": ["feedback", "diagnose", "feedback-{feedback_round}"],
                                "brief": "Diagnose round {feedback_round} for job {job_id}.",
                                "depends": ["trigger"],
                                "priority": 82,
                            }
                        },
                        {
                            "spawn_goal": {
                                "id": "optimize",
                                "role": "maker",
                                "tags": ["feedback", "optimize"],
                                "brief": "Optimize after diagnose.",
                                "depends": ["diagnose"],
                                "priority": 78,
                            }
                        },
                    ]
                }
            },
        )
    )
    prior = await ce.create_goal("QA", parent_id=root.id, source="decomposition")
    await ce.complete_goal(prior.id)

    result = await ex.invoke("spawn_feedback_cycle", job_id=root.id, trigger_goal_id=prior.id)
    assert result.status == "success"
    assert len(result.created_goal_ids) == 2
    state = await ex.job_state(root.id)
    assert state is not None
    assert state.feedback_round == 1

    d = await ce.get_goal(result.created_goal_ids[0])
    o = await ce.get_goal(result.created_goal_ids[1])
    assert d is not None and o is not None
    assert "Diagnose round 1" in d.description
    assert prior.id in (d.depends_on or [])
    assert d.id in (o.depends_on or [])
    assert "feedback-1" in (state.annotations[d.id].tags or [])


@pytest.mark.asyncio
async def test_recipe_gate_skips_when_acceptance_met(tmp_path: Path) -> None:
    ce = ContextEngine()
    root = await ce.create_goal("Job", workspace=str(tmp_path), priority=70)
    ex = RailBuiltinExecutor(ce, jobs_root=tmp_path)
    await ex.bind_job(
        RailJobState(
            job_id=root.id,
            rail_id="custom",
            rail_version="1.0",
            acceptance_met=True,
            verb_overrides={
                "spawn_feedback_cycle": {
                    "do": [
                        {"gate": {"unless": "acceptance_met"}},
                        {
                            "spawn_goal": {
                                "brief": "Should not spawn",
                                "tags": ["feedback"],
                            }
                        },
                    ]
                }
            },
        )
    )
    result = await ex.invoke("spawn_feedback_cycle", job_id=root.id)
    assert result.status == "skipped"
    assert "acceptance" in result.detail.lower()
    assert result.created_goal_ids == []


@pytest.mark.asyncio
async def test_builtin_plan_milestones_via_do_recipe(tmp_path: Path) -> None:
    ce = ContextEngine()
    root = await ce.create_goal("Build", workspace=str(tmp_path), priority=70)
    ex = RailBuiltinExecutor(ce, jobs_root=tmp_path)
    rail = LoopRailCatalog().resolve("greenfield-system")
    await ex.bind_job(
        RailJobState(
            job_id=root.id,
            rail_id=rail.id,
            rail_version=rail.version,
            verb_overrides=dict(rail.verbs),
            require_plan=True,
        )
    )
    result = await ex.invoke("plan_milestones", job_id=root.id)
    assert result.status == "success"
    assert len(result.created_goal_ids) == 1
    arch = await ce.get_goal(result.created_goal_ids[0])
    assert arch is not None
    assert "ownership" in arch.description.lower()
    refreshed = await ce.get_goal(root.id)
    assert refreshed is not None
    assert arch.id in (refreshed.depends_on or [])


def test_load_rail_do_recipe_ok(tmp_path: Path) -> None:
    path = tmp_path / "recipe.yml"
    path.write_text(
        """
id: recipe
version: "1.0"
summary: Multi-step do.
applies_when: test
verbs:
  review:
    do:
      - spawn_goal:
          brief: Review job {job_id}.
          tags: [review]
          role: checker
flow:
  - event: job_start
    then: review
""".strip()
        + "\n",
        encoding="utf-8",
    )
    rail = load_rail_file(path)
    assert rail.verbs["review"]["do"][0]["spawn_goal"]["role"] == "checker"


def test_load_rail_do_requires_spawn_brief(tmp_path: Path) -> None:
    path = tmp_path / "nobrief.yml"
    path.write_text(
        """
id: nobrief
version: "1.0"
summary: Missing brief.
applies_when: x
verbs:
  review:
    do:
      - spawn_goal:
          tags: [review]
flow:
  - event: job_start
    then: review
""".strip()
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(RailCatalogError, match="brief"):
        load_rail_file(path)
