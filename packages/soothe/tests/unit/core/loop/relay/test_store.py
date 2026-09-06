"""Unit tests for the unified interrupt relay store (SQLite, in-memory)."""

from __future__ import annotations

from pathlib import Path

import pytest

from soothe.sloop.clarification.origins import ORIGIN_EXECUTE, ORIGIN_TOOL_APPROVAL
from soothe.sloop.clarification.protocol import (
    ClarificationAnswer,
    ClarificationRequest,
    LoopStateView,
)
from soothe.sloop.relay.store import (
    ClarificationRow,
    SqliteClarificationStore,
    encode_answer,
)


def _view(goal_id: str = "g1") -> LoopStateView:
    return LoopStateView(
        goal_id=goal_id,
        goal_description="test goal",
        user_request="do thing",
        iteration=0,
        intent_classification=None,
        plan_summary=None,
        recent_step_outputs=(),
        workspace_summary=None,
        active_skills=(),
        active_mcp_servers=(),
    )


def _request(iid: str = "iid-1", origin: str = ORIGIN_EXECUTE) -> ClarificationRequest:
    return ClarificationRequest(
        questions=("What color?",),
        origin_node=origin,  # type: ignore[arg-type]
        origin_interrupt_id=iid,
        loop_state=_view(),
    )


def _row(
    relay_id: str = "r1",
    goal_id: str = "g1",
    origin: str = ORIGIN_EXECUTE,
    iid: str = "iid-1",
    thread_id: str | None = "thread-1",
) -> ClarificationRow:
    return ClarificationRow.from_handle(
        relay_id=relay_id,
        loop_id="loop-1",
        goal_id=goal_id,
        handle_origin=origin,
        handle_interrupt_id=iid,
        request=_request(iid=iid, origin=origin),
        core_agent_thread_id=thread_id,
        step_id="step-1",
        step_description="test step",
        policy_mode="manual",
        captured_at="2026-01-01T00:00:00+00:00",
    )


@pytest.fixture
async def store() -> SqliteClarificationStore:
    s = SqliteClarificationStore("loop-1", db_path=Path(":memory:"))
    yield s  # type: ignore[misc]
    await s.close()


class TestInsertAndGet:
    async def test_insert_then_get(self, store: SqliteClarificationStore) -> None:
        row = _row()
        await store.insert(row)
        fetched = await store.get("r1")
        assert fetched is not None
        assert fetched.relay_id == "r1"
        assert fetched.status == "captured"
        assert fetched.origin == ORIGIN_EXECUTE
        assert fetched.core_agent_thread_id == "thread-1"
        assert fetched.policy_mode == "manual"
        assert fetched.retry_count == 0

    async def test_get_missing_returns_none(self, store: SqliteClarificationStore) -> None:
        assert await store.get("nonexistent") is None

    async def test_decode_request(self, store: SqliteClarificationStore) -> None:
        row = _row()
        await store.insert(row)
        fetched = await store.get("r1")
        assert fetched is not None
        req = fetched.decode_request()
        assert req.origin_node == ORIGIN_EXECUTE
        assert req.origin_interrupt_id == "iid-1"
        assert req.questions == ("What color?",)

    async def test_decode_answer_none_when_not_answered(
        self, store: SqliteClarificationStore
    ) -> None:
        row = _row()
        await store.insert(row)
        fetched = await store.get("r1")
        assert fetched is not None
        assert fetched.decode_answer() is None


class TestUpdate:
    async def test_update_status(self, store: SqliteClarificationStore) -> None:
        await store.insert(_row())
        ok = await store.update("r1", status="parked", parked_at="2026-01-01T01:00:00+00:00")
        assert ok is True
        fetched = await store.get("r1")
        assert fetched is not None
        assert fetched.status == "parked"
        assert fetched.parked_at == "2026-01-01T01:00:00+00:00"

    async def test_update_answer(self, store: SqliteClarificationStore) -> None:
        await store.insert(_row())
        answer = ClarificationAnswer(answers=("blue",), source="human")
        ok = await store.update(
            "r1",
            status="answered",
            answer_json=encode_answer(answer),
            answer_source="human",
            answered_at="2026-01-01T02:00:00+00:00",
            idempotency_key="key-1",
        )
        assert ok is True
        fetched = await store.get("r1")
        assert fetched is not None
        assert fetched.status == "answered"
        assert fetched.answer_source == "human"
        assert fetched.idempotency_key == "key-1"
        decoded = fetched.decode_answer()
        assert decoded is not None
        assert decoded.answers == ("blue",)
        assert decoded.source == "human"

    async def test_update_missing_returns_false(self, store: SqliteClarificationStore) -> None:
        ok = await store.update("nonexistent", status="parked")
        assert ok is False

    async def test_update_no_fields_returns_false(self, store: SqliteClarificationStore) -> None:
        await store.insert(_row())
        ok = await store.update("r1")
        assert ok is False

    async def test_update_retry_count(self, store: SqliteClarificationStore) -> None:
        await store.insert(_row())
        await store.update("r1", status="answered", retry_count=3)
        fetched = await store.get("r1")
        assert fetched is not None
        assert fetched.retry_count == 3


class TestListByGoal:
    async def test_list_by_goal_ordered(self, store: SqliteClarificationStore) -> None:
        for i in range(3):
            await store.insert(_row(relay_id=f"r{i}", iid=f"iid-{i}"))
        rows = await store.list_by_goal("g1")
        assert len(rows) == 3
        # Ordered by captured_at ASC
        assert rows[0].relay_id == "r0"
        assert rows[2].relay_id == "r2"

    async def test_list_by_goal_status_filter(self, store: SqliteClarificationStore) -> None:
        await store.insert(_row(relay_id="r0"))
        await store.insert(_row(relay_id="r1"))
        await store.update("r0", status="parked")
        parked = await store.list_by_goal("g1", status="parked")
        assert len(parked) == 1
        assert parked[0].relay_id == "r0"
        captured = await store.list_by_goal("g1", status="captured")
        assert len(captured) == 1
        assert captured[0].relay_id == "r1"

    async def test_list_by_goal_empty(self, store: SqliteClarificationStore) -> None:
        rows = await store.list_by_goal("nonexistent")
        assert rows == []


class TestCountPending:
    async def test_count_zero(self, store: SqliteClarificationStore) -> None:
        assert await store.count_pending_by_goal("g1") == 0

    async def test_count_captured_and_parked(self, store: SqliteClarificationStore) -> None:
        await store.insert(_row(relay_id="r0"))
        await store.insert(_row(relay_id="r1"))
        await store.insert(_row(relay_id="r2"))
        await store.update("r1", status="parked")
        await store.update("r2", status="answered")
        # Only captured + parked count as pending
        assert await store.count_pending_by_goal("g1") == 2

    async def test_count_separate_goals(self, store: SqliteClarificationStore) -> None:
        await store.insert(_row(relay_id="r0", goal_id="g1"))
        await store.insert(_row(relay_id="r1", goal_id="g2"))
        assert await store.count_pending_by_goal("g1") == 1
        assert await store.count_pending_by_goal("g2") == 1


class TestListByLoop:
    async def test_list_by_loop(self, store: SqliteClarificationStore) -> None:
        await store.insert(_row(relay_id="r0"))
        rows = await store.list_by_loop("loop-1")
        assert len(rows) == 1
        assert rows[0].relay_id == "r0"

    async def test_list_by_loop_wrong_loop(self, store: SqliteClarificationStore) -> None:
        await store.insert(_row())
        rows = await store.list_by_loop("wrong-loop")
        assert rows == []


class TestClarificationRowFromHandle:
    def test_from_handle_builds_row(self) -> None:
        row = _row()
        assert row.relay_id == "r1"
        assert row.loop_id == "loop-1"
        assert row.goal_id == "g1"
        assert row.origin == ORIGIN_EXECUTE
        assert row.origin_interrupt_id == "iid-1"
        assert row.status == "captured"
        assert row.core_agent_thread_id == "thread-1"
        assert row.policy_mode == "manual"

    def test_from_handle_no_thread(self) -> None:
        row = ClarificationRow.from_handle(
            relay_id="r1",
            loop_id="loop-1",
            goal_id="g1",
            handle_origin=ORIGIN_TOOL_APPROVAL,
            handle_interrupt_id="iid-1",
            request=_request(origin=ORIGIN_TOOL_APPROVAL),
            core_agent_thread_id=None,
            step_id=None,
            step_description=None,
            policy_mode="auto",
        )
        assert row.core_agent_thread_id is None
        assert row.policy_mode == "auto"
