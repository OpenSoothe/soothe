"""Routing for structural keep from gather_evidence (IG-671)."""

from __future__ import annotations

from soothe.sloop.orchestrator.routing import route_after_evidence_gather
from soothe.sloop.orchestrator.stations import COMMIT_PLAN, GENERATE_PLAN


def test_route_keep_plan_to_commit() -> None:
    assert route_after_evidence_gather({"evidence_gather_route": "keep_plan"}) == COMMIT_PLAN


def test_route_fresh_loop_still_generate() -> None:
    assert (
        route_after_evidence_gather({"evidence_gather_route": "plan_generate_skip_assess"})
        == GENERATE_PLAN
    )
