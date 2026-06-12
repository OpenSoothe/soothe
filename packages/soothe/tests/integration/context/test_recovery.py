"""Integration tests for crash recovery (soothe.context.engine)."""

import pytest

from soothe.context.engine import ContextEngine


class TestRecovery:
    @pytest.mark.asyncio
    async def test_recover_resets_active_to_pending(self) -> None:
        engine = ContextEngine()
        g1 = await engine.create_goal("Active goal")
        g1.status = "active"
        g1.assigned_loop_id = "loop-1"
        g2 = await engine.create_goal("Pending goal")

        recovered = await engine.recover()
        assert g1.id in recovered
        assert g2.id not in recovered

        fetched = await engine.get_goal(g1.id)
        assert fetched.status == "pending"
        assert fetched.assigned_loop_id is None

    @pytest.mark.asyncio
    async def test_recover_no_active_goals(self) -> None:
        engine = ContextEngine()
        await engine.create_goal("Just pending")
        recovered = await engine.recover()
        assert recovered == []

    @pytest.mark.asyncio
    async def test_recover_preserves_completed_and_failed(self) -> None:
        engine = ContextEngine()
        g1 = await engine.create_goal("Done")
        g1.status = "completed"
        g2 = await engine.create_goal("Failed")
        g2.status = "failed"
        g3 = await engine.create_goal("Stuck")
        g3.status = "active"

        await engine.recover()
        assert (await engine.get_goal(g1.id)).status == "completed"
        assert (await engine.get_goal(g2.id)).status == "failed"
        assert (await engine.get_goal(g3.id)).status == "pending"
