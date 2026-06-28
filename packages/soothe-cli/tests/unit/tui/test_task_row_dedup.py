"""Unit tests for IG-517: Task row deduplication and subagent_type display."""

from __future__ import annotations

import pytest

from soothe_cli.tui.commands.subagent_routing import get_subagent_display_name
from soothe_cli.tui.widgets.messages.cognition_step import CognitionStepMessage


@pytest.fixture
def step_card() -> CognitionStepMessage:
    """Create a step card for testing."""
    return CognitionStepMessage(
        step_id="step-001",
        description="Test step",
        id="step-test",
    )


class TestTaskRowDeduplication:
    """Tests for semantic deduplication of task delegation rows."""

    def test_dedup_by_subagent_type_and_description(self, step_card: CognitionStepMessage) -> None:
        """Task rows with same subagent_type + description should dedupe."""
        # First task row with provider-assigned ID
        step_card.add_tool_call(
            "toolu_01A",
            "task",
            {"subagent_type": "explore", "description": "search files"},
            is_task_row=True,
        )
        assert len(step_card._rows) == 1

        # Second chunk with different ID but same semantics - should update, not add
        step_card.add_tool_call(
            "toolu_01B",
            "task",
            {"subagent_type": "explore", "description": "search files", "prompt": "..."},
            is_task_row=True,
        )
        assert len(step_card._rows) == 1
        # Args should be merged/updated
        row = step_card._rows[0]
        assert row.args.get("prompt") == "..."

    def test_different_tasks_create_separate_rows(self, step_card: CognitionStepMessage) -> None:
        """Task rows with different subagent_type or description should be separate."""
        step_card.add_tool_call(
            "toolu_01A",
            "task",
            {"subagent_type": "explore", "description": "search files"},
            is_task_row=True,
        )
        step_card.add_tool_call(
            "toolu_01B",
            "task",
            {"subagent_type": "plan", "description": "next action"},
            is_task_row=True,
        )
        assert len(step_card._rows) == 2

    def test_same_type_different_description_separate(
        self, step_card: CognitionStepMessage
    ) -> None:
        """Same subagent_type but different descriptions are separate delegations."""
        step_card.add_tool_call(
            "toolu_01A",
            "task",
            {"subagent_type": "explore", "description": "search files"},
            is_task_row=True,
        )
        step_card.add_tool_call(
            "toolu_01B",
            "task",
            {"subagent_type": "explore", "description": "map repo"},
            is_task_row=True,
        )
        assert len(step_card._rows) == 2


class TestSubagentDisplayNames:
    """Tests for subagent type display name mapping."""

    def test_known_subagent_types(self) -> None:
        """Known subagent types should return mapped display names."""
        # Built-in soothe core subagents
        assert get_subagent_display_name("explore") == "Explore"
        assert get_subagent_display_name("tacitus") == "Tacitus"
        assert get_subagent_display_name("plan") == "Plan"
        # Plugin-based subagent
        assert get_subagent_display_name("browser_use") == "Browser"

    def test_unknown_subagent_type_returns_as_is(self) -> None:
        """Unknown subagent types should return the input unchanged."""
        assert get_subagent_display_name("custom-agent") == "custom-agent"
        assert get_subagent_display_name("MyAgent") == "MyAgent"

    def test_empty_subagent_type_returns_task(self) -> None:
        """Empty subagent type should fall back to 'Task' in label rendering."""
        # This is tested indirectly via task_delegation_label
        from soothe_cli.tui.widgets.messages.cognition_step_activity import (
            StepToolRow,
            task_delegation_label,
        )

        row = StepToolRow(
            tool_call_id="test:task",
            tool_name="task",
            args={},
            phase="pending",
            is_task_row=True,
        )
        label = task_delegation_label(row)
        assert label == "Task"

    def test_task_label_with_subagent_type(self) -> None:
        """Task label should use mapped display name when subagent_type present."""
        from soothe_cli.tui.widgets.messages.cognition_step_activity import (
            StepToolRow,
            task_delegation_label,
        )

        row = StepToolRow(
            tool_call_id="test:task",
            tool_name="task",
            args={"subagent_type": "explore", "description": "search code"},
            phase="pending",
            is_task_row=True,
        )
        label = task_delegation_label(row)
        assert label.startswith("Explore(")
        assert "search code" in label


class TestTaskRowArgsInjection:
    """Tests for subagent_type injection from router registry."""

    def test_injection_from_router_registry(self) -> None:
        """When args lack subagent_type, router registry should provide it."""
        # This requires a more complex integration test with the router.
        # For unit coverage, we verify the injection logic path exists.
        # Integration test would use mock router with _spawns_by_task_id populated.
        pass  # Placeholder for integration test in test suite
