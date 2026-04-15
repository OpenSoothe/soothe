"""AutopilotConfig and SootheConfig integration."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from soothe.config.models import AutopilotConfig
from soothe.config.settings import SootheConfig


class TestAutopilotConfigDefaults:
    """Unit tests for AutopilotConfig default values per Autopilot."""

    def test_max_iterations_default(self) -> None:
        config = AutopilotConfig()
        assert config.max_iterations == 50

    def test_max_send_backs_default(self) -> None:
        config = AutopilotConfig()
        assert config.max_send_backs == 3

    def test_max_parallel_goals_default(self) -> None:
        config = AutopilotConfig()
        assert config.max_parallel_goals == 3

    def test_dreaming_enabled_default(self) -> None:
        config = AutopilotConfig()
        assert config.dreaming_enabled is True

    def test_dreaming_consolidation_interval_default(self) -> None:
        config = AutopilotConfig()
        assert config.dreaming_consolidation_interval == 300

    def test_dreaming_health_check_interval_default(self) -> None:
        config = AutopilotConfig()
        assert config.dreaming_health_check_interval == 60

    def test_checkpoint_interval_default(self) -> None:
        config = AutopilotConfig()
        assert config.checkpoint_interval == 10

    def test_scheduler_enabled_default(self) -> None:
        config = AutopilotConfig()
        assert config.scheduler_enabled is True

    def test_max_scheduled_tasks_default(self) -> None:
        config = AutopilotConfig()
        assert config.max_scheduled_tasks == 100

    def test_webhooks_defaults_to_empty_dict(self) -> None:
        config = AutopilotConfig()
        assert config.webhooks == {}
        assert isinstance(config.webhooks, dict)


class TestAutopilotConfigValidation:
    """Unit tests for AutopilotConfig field validation (ge/le constraints)."""

    def test_max_iterations_min(self) -> None:
        config = AutopilotConfig(max_iterations=1)
        assert config.max_iterations == 1

    def test_max_iterations_max(self) -> None:
        config = AutopilotConfig(max_iterations=500)
        assert config.max_iterations == 500

    def test_max_iterations_below_min(self) -> None:
        with pytest.raises(ValidationError):
            AutopilotConfig(max_iterations=0)

    def test_max_iterations_above_max(self) -> None:
        with pytest.raises(ValidationError):
            AutopilotConfig(max_iterations=501)

    def test_max_send_backs_min(self) -> None:
        config = AutopilotConfig(max_send_backs=1)
        assert config.max_send_backs == 1

    def test_max_send_backs_max(self) -> None:
        config = AutopilotConfig(max_send_backs=10)
        assert config.max_send_backs == 10

    def test_max_send_backs_below_min(self) -> None:
        with pytest.raises(ValidationError):
            AutopilotConfig(max_send_backs=0)

    def test_max_parallel_goals_min(self) -> None:
        config = AutopilotConfig(max_parallel_goals=1)
        assert config.max_parallel_goals == 1

    def test_max_parallel_goals_max(self) -> None:
        config = AutopilotConfig(max_parallel_goals=10)
        assert config.max_parallel_goals == 10

    def test_max_scheduled_tasks_min(self) -> None:
        config = AutopilotConfig(max_scheduled_tasks=1)
        assert config.max_scheduled_tasks == 1

    def test_max_scheduled_tasks_max(self) -> None:
        config = AutopilotConfig(max_scheduled_tasks=1000)
        assert config.max_scheduled_tasks == 1000

    def test_max_scheduled_tasks_above_max(self) -> None:
        with pytest.raises(ValidationError):
            AutopilotConfig(max_scheduled_tasks=1001)

    def test_checkpoint_interval_min(self) -> None:
        config = AutopilotConfig(checkpoint_interval=1)
        assert config.checkpoint_interval == 1

    def test_checkpoint_interval_max(self) -> None:
        config = AutopilotConfig(checkpoint_interval=100)
        assert config.checkpoint_interval == 100

    def test_dreaming_consolidation_interval_min(self) -> None:
        config = AutopilotConfig(dreaming_consolidation_interval=10)
        assert config.dreaming_consolidation_interval == 10

    def test_dreaming_consolidation_interval_below_min(self) -> None:
        with pytest.raises(ValidationError):
            AutopilotConfig(dreaming_consolidation_interval=5)

    def test_dreaming_health_check_interval_min(self) -> None:
        config = AutopilotConfig(dreaming_health_check_interval=5)
        assert config.dreaming_health_check_interval == 5

    def test_dreaming_health_check_interval_below_min(self) -> None:
        with pytest.raises(ValidationError):
            AutopilotConfig(dreaming_health_check_interval=1)


class TestSootheConfigAutopilot:
    """Unit tests for SootheConfig autopilot field."""

    def test_autopilot_field_exists_with_default(self) -> None:
        config = SootheConfig()
        assert config.autopilot is not None
        assert isinstance(config.autopilot, AutopilotConfig)

    def test_autopilot_uses_defaults(self) -> None:
        config = SootheConfig()
        assert config.autopilot.max_iterations == 50
        assert config.autopilot.max_send_backs == 3
        assert config.autopilot.max_scheduled_tasks == 100
        assert config.autopilot.dreaming_enabled is True

    def test_autopilot_webhooks_empty_by_default(self) -> None:
        config = SootheConfig()
        assert config.autopilot.webhooks == {}

    def test_yaml_override_autopilot_values(self, tmp_path: Path) -> None:
        yaml_content = """
router:
  default: "openai:gpt-4o-mini"
providers: []
autopilot:
  max_iterations: 200
  max_send_backs: 5
  max_parallel_goals: 2
  dreaming_enabled: false
  dreaming_consolidation_interval: 600
  max_scheduled_tasks: 50
  webhooks:
    on_goal_completed: "https://example.com/hook"
    on_goal_failed: "https://example.com/fail-hook"
"""
        config_file = tmp_path / "config.yml"
        config_file.write_text(yaml_content)

        config = SootheConfig.from_yaml_file(str(config_file))
        assert config.autopilot.max_iterations == 200
        assert config.autopilot.max_send_backs == 5
        assert config.autopilot.max_parallel_goals == 2
        assert config.autopilot.dreaming_enabled is False
        assert config.autopilot.dreaming_consolidation_interval == 600
        assert config.autopilot.max_scheduled_tasks == 50
        assert config.autopilot.webhooks.get("on_goal_completed") == "https://example.com/hook"
        assert config.autopilot.webhooks.get("on_goal_failed") == "https://example.com/fail-hook"

    def test_yaml_partial_override(self, tmp_path: Path) -> None:
        """Only override some fields; rest should use defaults."""
        yaml_content = """
router:
  default: "openai:gpt-4o-mini"
providers: []
autopilot:
  max_iterations: 100
"""
        config_file = tmp_path / "config.yml"
        config_file.write_text(yaml_content)

        config = SootheConfig.from_yaml_file(str(config_file))
        assert config.autopilot.max_iterations == 100
        # Unchanged fields keep defaults
        assert config.autopilot.max_send_backs == 3
        assert config.autopilot.dreaming_enabled is True
        assert config.autopilot.max_scheduled_tasks == 100
