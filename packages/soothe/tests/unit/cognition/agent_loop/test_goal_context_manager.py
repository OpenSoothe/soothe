"""Unit tests for GoalContextManager (RFC-609)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock

import pytest

from soothe.cognition.agent_loop.checkpoint import (
    AgentLoopCheckpoint,
    GoalExecutionRecord,
    ThreadHealthMetrics,
)
from soothe.cognition.agent_loop.goal_context_manager import GoalContextManager
from soothe.config.models import GoalContextConfig


@pytest.fixture
def mock_state_manager():
    """Create mock AgentLoopStateManager."""
    return Mock()


@pytest.fixture
def default_config():
    """Create default GoalContextConfig."""
    return GoalContextConfig()


@pytest.fixture
def goal_context_manager(mock_state_manager, default_config):
    """Create GoalContextManager with mocked state manager."""
    return GoalContextManager(mock_state_manager, default_config)


@pytest.mark.asyncio
async def test_get_plan_context_empty_history(goal_context_manager, mock_state_manager):
    """Plan context returns [] when no checkpoint."""
    mock_state_manager.load = AsyncMock(return_value=None)

    result = await goal_context_manager.get_plan_context(limit=10)

    assert result == []


@pytest.mark.asyncio
async def test_get_plan_context_no_goals(goal_context_manager, mock_state_manager):
    """Plan context returns [] when goal_history is empty."""
    checkpoint = AgentLoopCheckpoint(
        loop_id="test_loop",
        thread_ids=["thread_A"],
        current_thread_id="thread_A",
        status="ready_for_next_goal",
        goal_history=[],
        current_goal_index=-1,
        thread_health_metrics=ThreadHealthMetrics(
            thread_id="thread_A", last_updated=datetime.now(UTC)
        ),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    mock_state_manager.load = AsyncMock(return_value=checkpoint)

    result = await goal_context_manager.get_plan_context(limit=10)

    assert result == []


@pytest.mark.asyncio
async def test_get_plan_context_filters_same_thread(goal_context_manager, mock_state_manager):
    """Plan context only includes goals from current thread."""
    checkpoint = AgentLoopCheckpoint(
        loop_id="test_loop",
        thread_ids=["thread_A", "thread_B"],
        current_thread_id="thread_A",
        status="ready_for_next_goal",
        goal_history=[
            GoalExecutionRecord(
                goal_id="goal_1",
                goal_text="analyze performance",
                thread_id="thread_A",
                iteration=3,
                max_iterations=10,
                status="completed",
                reason_history=[],
                act_history=[],
                final_report="Found bottleneck in db.py",
                started_at=datetime.now(UTC),
            ),
            GoalExecutionRecord(
                goal_id="goal_2",
                goal_text="optimize queries",
                thread_id="thread_B",  # Different thread
                iteration=2,
                max_iterations=10,
                status="completed",
                reason_history=[],
                act_history=[],
                final_report="Improved performance",
                started_at=datetime.now(UTC),
            ),
        ],
        current_goal_index=-1,
        thread_health_metrics=ThreadHealthMetrics(
            thread_id="thread_A", last_updated=datetime.now(UTC)
        ),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    mock_state_manager.load = AsyncMock(return_value=checkpoint)

    result = await goal_context_manager.get_plan_context(limit=10)

    assert len(result) == 1  # Only thread_A goal
    assert "thread_A" in result[0]
    assert "analyze performance" in result[0]


@pytest.mark.asyncio
async def test_get_plan_context_filters_completed_only(goal_context_manager, mock_state_manager):
    """Plan context only includes completed goals."""
    checkpoint = AgentLoopCheckpoint(
        loop_id="test_loop",
        thread_ids=["thread_A"],
        current_thread_id="thread_A",
        status="ready_for_next_goal",
        goal_history=[
            GoalExecutionRecord(
                goal_id="goal_1",
                goal_text="completed task",
                thread_id="thread_A",
                iteration=3,
                max_iterations=10,
                status="completed",
                reason_history=[],
                act_history=[],
                final_report="Done",
                started_at=datetime.now(UTC),
            ),
            GoalExecutionRecord(
                goal_id="goal_2",
                goal_text="running task",
                thread_id="thread_A",
                iteration=1,
                max_iterations=10,
                status="running",  # Not completed
                reason_history=[],
                act_history=[],
                final_report="",
                started_at=datetime.now(UTC),
            ),
        ],
        current_goal_index=-1,
        thread_health_metrics=ThreadHealthMetrics(
            thread_id="thread_A", last_updated=datetime.now(UTC)
        ),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    mock_state_manager.load = AsyncMock(return_value=checkpoint)

    result = await goal_context_manager.get_plan_context(limit=10)

    assert len(result) == 1  # Only completed goal
    assert "completed task" in result[0]


@pytest.mark.asyncio
async def test_get_plan_context_respects_limit(goal_context_manager, mock_state_manager):
    """Plan context respects limit parameter."""
    checkpoint = AgentLoopCheckpoint(
        loop_id="test_loop",
        thread_ids=["thread_A"],
        current_thread_id="thread_A",
        status="ready_for_next_goal",
        goal_history=[
            GoalExecutionRecord(
                goal_id=f"goal_{i}",
                goal_text=f"task {i}",
                thread_id="thread_A",
                iteration=3,
                max_iterations=10,
                status="completed",
                reason_history=[],
                act_history=[],
                final_report=f"Result {i}",
                started_at=datetime.now(UTC),
            )
            for i in range(15)
        ],
        current_goal_index=-1,
        thread_health_metrics=ThreadHealthMetrics(
            thread_id="thread_A", last_updated=datetime.now(UTC)
        ),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    mock_state_manager.load = AsyncMock(return_value=checkpoint)

    result = await goal_context_manager.get_plan_context(limit=5)

    assert len(result) == 5


@pytest.mark.asyncio
async def test_get_plan_context_config_disabled(mock_state_manager):
    """Plan context returns [] when config.enabled=False."""
    config = GoalContextConfig(enabled=False)
    manager = GoalContextManager(mock_state_manager, config)

    checkpoint = AgentLoopCheckpoint(
        loop_id="test_loop",
        thread_ids=["thread_A"],
        current_thread_id="thread_A",
        status="ready_for_next_goal",
        goal_history=[
            GoalExecutionRecord(
                goal_id="goal_1",
                goal_text="task",
                thread_id="thread_A",
                iteration=3,
                max_iterations=10,
                status="completed",
                reason_history=[],
                act_history=[],
                final_report="Done",
                started_at=datetime.now(UTC),
            )
        ],
        current_goal_index=-1,
        thread_health_metrics=ThreadHealthMetrics(
            thread_id="thread_A", last_updated=datetime.now(UTC)
        ),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    mock_state_manager.load = AsyncMock(return_value=checkpoint)

    result = await manager.get_plan_context()

    assert result == []


@pytest.mark.asyncio
async def test_get_execute_briefing_returns_none_without_flag(
    goal_context_manager, mock_state_manager
):
    """Execute briefing returns None when thread_switch_pending=False."""
    checkpoint = AgentLoopCheckpoint(
        loop_id="test_loop",
        thread_ids=["thread_A"],
        current_thread_id="thread_A",
        status="ready_for_next_goal",
        thread_switch_pending=False,  # Flag is False
        goal_history=[],
        current_goal_index=-1,
        thread_health_metrics=ThreadHealthMetrics(
            thread_id="thread_A", last_updated=datetime.now(UTC)
        ),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    mock_state_manager.load = AsyncMock(return_value=checkpoint)

    result = await goal_context_manager.get_execute_briefing()

    assert result is None


@pytest.mark.asyncio
async def test_get_execute_briefing_clears_flag(goal_context_manager, mock_state_manager):
    """Execute briefing clears thread_switch_pending flag."""
    checkpoint = AgentLoopCheckpoint(
        loop_id="test_loop",
        thread_ids=["thread_A", "thread_B"],
        current_thread_id="thread_B",
        status="ready_for_next_goal",
        thread_switch_pending=True,  # Flag is True
        goal_history=[
            GoalExecutionRecord(
                goal_id="goal_1",
                goal_text="task",
                thread_id="thread_A",
                iteration=3,
                max_iterations=10,
                status="completed",
                reason_history=[],
                act_history=[],
                final_report="Done",
                started_at=datetime.now(UTC),
            )
        ],
        current_goal_index=-1,
        thread_health_metrics=ThreadHealthMetrics(
            thread_id="thread_B", last_updated=datetime.now(UTC)
        ),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    mock_state_manager.load = AsyncMock(return_value=checkpoint)
    mock_state_manager.save = AsyncMock()

    result = await goal_context_manager.get_execute_briefing()

    assert result is not None
    # Verify save was called with flag cleared
    saved_checkpoint = mock_state_manager.save.call_args[0][0]
    assert not saved_checkpoint.thread_switch_pending


@pytest.mark.asyncio
async def test_get_execute_briefing_cross_thread(goal_context_manager, mock_state_manager):
    """Execute briefing includes goals from all threads."""
    checkpoint = AgentLoopCheckpoint(
        loop_id="test_loop",
        thread_ids=["thread_A", "thread_B"],
        current_thread_id="thread_B",
        status="ready_for_next_goal",
        thread_switch_pending=True,
        goal_history=[
            GoalExecutionRecord(
                goal_id="goal_1",
                goal_text="task A",
                thread_id="thread_A",
                iteration=3,
                max_iterations=10,
                status="completed",
                reason_history=[],
                act_history=[],
                final_report="Result A",
                started_at=datetime.now(UTC),
            ),
            GoalExecutionRecord(
                goal_id="goal_2",
                goal_text="task B",
                thread_id="thread_B",
                iteration=2,
                max_iterations=10,
                status="completed",
                reason_history=[],
                act_history=[],
                final_report="Result B",
                started_at=datetime.now(UTC),
            ),
        ],
        current_goal_index=-1,
        thread_health_metrics=ThreadHealthMetrics(
            thread_id="thread_B", last_updated=datetime.now(UTC)
        ),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    mock_state_manager.load = AsyncMock(return_value=checkpoint)
    mock_state_manager.save = AsyncMock()

    result = await goal_context_manager.get_execute_briefing()

    assert result is not None
    assert "thread_A" in result
    assert "thread_B" in result
    assert "task A" in result
    assert "task B" in result


@pytest.mark.asyncio
async def test_get_execute_briefing_no_completed_goals(goal_context_manager, mock_state_manager):
    """Execute briefing returns None when no completed goals."""
    checkpoint = AgentLoopCheckpoint(
        loop_id="test_loop",
        thread_ids=["thread_A"],
        current_thread_id="thread_A",
        status="ready_for_next_goal",
        thread_switch_pending=True,
        goal_history=[
            GoalExecutionRecord(
                goal_id="goal_1",
                goal_text="running task",
                thread_id="thread_A",
                iteration=1,
                max_iterations=10,
                status="running",  # Not completed
                reason_history=[],
                act_history=[],
                final_report="",
                started_at=datetime.now(UTC),
            )
        ],
        current_goal_index=-1,
        thread_health_metrics=ThreadHealthMetrics(
            thread_id="thread_A", last_updated=datetime.now(UTC)
        ),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    mock_state_manager.load = AsyncMock(return_value=checkpoint)
    mock_state_manager.save = AsyncMock()

    result = await goal_context_manager.get_execute_briefing()

    assert result is None


@pytest.mark.asyncio
async def test_get_execute_briefing_config_disabled(mock_state_manager):
    """Execute briefing returns None when config.enabled=False."""
    config = GoalContextConfig(enabled=False)
    manager = GoalContextManager(mock_state_manager, config)

    checkpoint = AgentLoopCheckpoint(
        loop_id="test_loop",
        thread_ids=["thread_A"],
        current_thread_id="thread_A",
        status="ready_for_next_goal",
        thread_switch_pending=True,
        goal_history=[
            GoalExecutionRecord(
                goal_id="goal_1",
                goal_text="task",
                thread_id="thread_A",
                iteration=3,
                max_iterations=10,
                status="completed",
                reason_history=[],
                act_history=[],
                final_report="Done",
                started_at=datetime.now(UTC),
            )
        ],
        current_goal_index=-1,
        thread_health_metrics=ThreadHealthMetrics(
            thread_id="thread_A", last_updated=datetime.now(UTC)
        ),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    mock_state_manager.load = AsyncMock(return_value=checkpoint)

    result = await manager.get_execute_briefing()

    assert result is None


def test_extract_key_findings_bullet_points(goal_context_manager):
    """Key findings extraction extracts bullet points."""
    report = """
Analysis completed:
- Found bottleneck in database queries
- Identified memory leak in worker process
- Detected race condition in async handler
"""

    result = goal_context_manager._extract_key_findings(report)

    assert "bottleneck" in result
    assert "memory leak" in result
    assert "race condition" in result


def test_extract_key_findings_numbered_items(goal_context_manager):
    """Key findings extraction extracts numbered items."""
    report = """
Findings:
1. Database N+1 query problem
2. Missing cache layer
3. Unbatched API calls
"""

    result = goal_context_manager._extract_key_findings(report)

    assert "N+1 query" in result
    assert "Missing cache" in result
    assert "Unbatched API" in result


def test_extract_key_findings_fallback(goal_context_manager):
    """Key findings extraction fallback truncates long reports."""
    report = "This is a long report without bullet points or numbered items. " * 10

    result = goal_context_manager._extract_key_findings(report)

    assert len(result) <= 153  # 150 chars + "..."
    assert result.endswith("...")


def test_extract_key_findings_empty_report(goal_context_manager):
    """Key findings extraction returns 'No findings' for empty report."""
    result = goal_context_manager._extract_key_findings("")

    assert result == "No findings"


def test_extract_critical_files(goal_context_manager):
    """Critical files extraction finds file paths."""
    report = """
Changes made:
- Fixed query in user_service.py:142
- Added cache layer to api_client.py
- Updated config_manager.py:89
"""

    result = goal_context_manager._extract_critical_files(report)

    assert "user_service.py" in result
    assert "api_client.py" in result
    assert "config_manager.py" in result


def test_extract_critical_files_no_matches(goal_context_manager):
    """Critical files extraction returns 'None identified' when no matches."""
    report = "This is a report without file paths."

    result = goal_context_manager._extract_critical_files(report)

    assert result == "None identified"


def test_extract_critical_files_empty_report(goal_context_manager):
    """Critical files extraction returns 'None identified' for empty report."""
    result = goal_context_manager._extract_critical_files("")

    assert result == "None identified"


def test_extract_result_summary_explicit_marker(goal_context_manager):
    """Result summary extraction finds explicit markers."""
    report = """
Analysis completed.
Result: Performance improved by 67%
"""

    result = goal_context_manager._extract_result_summary(report)

    assert "Performance improved by 67%" in result


def test_extract_result_summary_outcome_marker(goal_context_manager):
    """Result summary extraction finds Outcome marker."""
    report = """
Task finished.
Outcome: 3 bottlenecks fixed
"""

    result = goal_context_manager._extract_result_summary(report)

    assert "3 bottlenecks fixed" in result


def test_extract_result_summary_fallback(goal_context_manager):
    """Result summary extraction fallback uses last line."""
    report = """
Analysis:
- Found issues
- Fixed problems
All tests passing now
"""

    result = goal_context_manager._extract_result_summary(report)

    assert "All tests passing" in result


def test_extract_result_summary_empty_report(goal_context_manager):
    """Result summary extraction returns 'Completed' for empty report."""
    result = goal_context_manager._extract_result_summary("")

    assert result == "Completed"


def test_format_execute_briefing_structure(goal_context_manager):
    """Execute briefing format has correct structure."""
    goals = [
        GoalExecutionRecord(
            goal_id="goal_1",
            goal_text="analyze performance",
            thread_id="thread_A",
            iteration=3,
            max_iterations=10,
            status="completed",
            reason_history=[],
            act_history=[],
            final_report="Found bottleneck in db.py",
            started_at=datetime.now(UTC),
        )
    ]

    result = goal_context_manager._format_execute_briefing(goals, "thread_B")

    assert "## Previous Goal Context (Thread Switch Recovery)" in result
    assert "**Goal 1**" in result
    assert "thread_A" in result
    assert "**Current thread**: thread_B" in result
    assert "**Instruction**:" in result
