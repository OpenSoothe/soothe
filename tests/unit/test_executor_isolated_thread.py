"""Sequential Act isolated thread + merge (IG-131)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe.cognition.loop_agent.executor import Executor
from soothe.cognition.loop_agent.schemas import LoopState, StepAction
from soothe.config import SootheConfig


def _step(*, subagent: str | None = None) -> StepAction:
    return StepAction(
        description="Do the thing",
        expected_output="ok",
        subagent=subagent,
    )


def test_should_use_isolated_respects_config_and_hints() -> None:
    agent = MagicMock()
    cfg = SootheConfig()
    ex = Executor(agent, config=cfg)
    steps = [_step(subagent=None), _step(subagent=None)]

    # Disabled when sequential_act_isolated_thread is False (default)
    assert ex._should_use_isolated_sequential_thread(steps) is False

    # Enable isolation feature
    cfg.agentic.sequential_act_isolated_thread = True

    # No subagent in steps → no isolation
    assert ex._should_use_isolated_sequential_thread(steps) is False

    # Has subagent in steps → isolation enabled (automatic semantic rule)
    steps2 = [_step(subagent="claude")]
    assert ex._should_use_isolated_sequential_thread(steps2) is True

    # Mixed steps with subagent → isolation enabled
    steps3 = [_step(subagent=None), _step(subagent="claude")]
    assert ex._should_use_isolated_sequential_thread(steps3) is True


@pytest.mark.asyncio
async def test_merge_appends_child_messages_to_parent() -> None:
    agent = MagicMock()
    graph = MagicMock()
    graph.aget_state = AsyncMock(
        return_value=MagicMock(values={"messages": ["m_child_1", "m_child_2"]}),
    )
    graph.aupdate_state = AsyncMock(return_value=None)
    agent.graph = graph

    ex = Executor(agent, config=SootheConfig())
    await ex._merge_isolated_act_into_parent_thread(
        parent_thread_id="parent_tid",
        child_thread_id="child_tid",
    )

    graph.aget_state.assert_awaited_once()
    graph.aupdate_state.assert_awaited_once()
    call = graph.aupdate_state.await_args
    assert call.args[0] == {"configurable": {"thread_id": "parent_tid"}}
    assert call.args[1] == {"messages": ["m_child_1", "m_child_2"]}
