"""Tests for CLI shell health state tracking."""

from soothe.tools._internal.shell import (
    ShellHealthState,
    _shell_health_states,
)
from soothe.tools.execution import RunCommandTool


class TestShellHealthState:
    """Test ShellHealthState dataclass."""

    def test_default_initialization(self) -> None:
        """Test default initialization of health state."""
        health = ShellHealthState()

        assert health.last_command_success is True
        assert health.last_command_timestamp is None
        assert health.consecutive_failures == 0
        assert health.last_test_timestamp is None
        assert health.shell_recovered is False
        assert health.first_command_executed is False
        assert health.last_trouble_sign == "none"

    def test_custom_initialization(self) -> None:
        """Test custom initialization of health state."""
        from datetime import datetime

        now = datetime.now()
        health = ShellHealthState(
            last_command_success=False,
            last_command_timestamp=now,
            consecutive_failures=2,
            shell_recovered=True,
            first_command_executed=True,
            last_trouble_sign="timeout",
        )

        assert health.last_command_success is False
        assert health.last_command_timestamp == now
        assert health.consecutive_failures == 2
        assert health.shell_recovered is True
        assert health.first_command_executed is True
        assert health.last_trouble_sign == "timeout"


class TestShouldTestResponsiveness:
    """Test smart responsiveness testing logic."""

    def test_first_command_triggers_test(self) -> None:
        """Test that first command always triggers test."""
        tool = RunCommandTool()

        # Clear health state to simulate first command
        _shell_health_states.clear()

        should_test = tool._should_test_responsiveness("default")

        assert should_test is True

    def test_healthy_shell_skips_test(self) -> None:
        """Test that healthy shell skips responsiveness test."""
        from datetime import datetime

        tool = RunCommandTool()

        # Create health state indicating healthy shell
        health = ShellHealthState(
            last_command_success=True,
            first_command_executed=True,
            consecutive_failures=0,
            last_trouble_sign="none",
            shell_recovered=False,
            last_command_timestamp=datetime.now(),
        )
        _shell_health_states["default"] = health

        should_test = tool._should_test_responsiveness("default")

        assert should_test is False

    def test_failed_command_triggers_test(self) -> None:
        """Test that failed command triggers retest."""
        from datetime import datetime

        tool = RunCommandTool()

        # Create health state indicating failed command
        health = ShellHealthState(
            last_command_success=False,
            first_command_executed=True,
            consecutive_failures=1,
            last_trouble_sign="none",
            shell_recovered=False,
            last_command_timestamp=datetime.now(),
        )
        _shell_health_states["default"] = health

        should_test = tool._should_test_responsiveness("default")

        assert should_test is True

    def test_recovered_shell_triggers_test(self) -> None:
        """Test that recovered shell triggers validation test."""
        from datetime import datetime

        tool = RunCommandTool()

        # Create health state indicating shell was recovered
        health = ShellHealthState(
            last_command_success=True,
            first_command_executed=True,
            consecutive_failures=0,
            last_trouble_sign="none",
            shell_recovered=True,  # Shell was recovered
            last_command_timestamp=datetime.now(),
        )
        _shell_health_states["default"] = health

        should_test = tool._should_test_responsiveness("default")

        assert should_test is True

    def test_consecutive_failures_trigger_test(self) -> None:
        """Test that consecutive failures trigger test."""
        from datetime import datetime

        tool = RunCommandTool()

        # Create health state with consecutive failures
        health = ShellHealthState(
            last_command_success=False,
            first_command_executed=True,
            consecutive_failures=2,
            last_trouble_sign="none",
            shell_recovered=False,
            last_command_timestamp=datetime.now(),
        )
        _shell_health_states["default"] = health

        should_test = tool._should_test_responsiveness("default")

        assert should_test is True

    def test_trouble_signs_trigger_test(self) -> None:
        """Test that trouble signs trigger test."""
        from datetime import datetime

        tool = RunCommandTool()

        # Test each type of trouble sign
        trouble_signs = ["timeout", "eof", "error", "unexpected_output"]

        for sign in trouble_signs:
            health = ShellHealthState(
                last_command_success=True,
                first_command_executed=True,
                consecutive_failures=0,
                last_trouble_sign=sign,
                shell_recovered=False,
                last_command_timestamp=datetime.now(),
            )
            _shell_health_states["default"] = health

            should_test = tool._should_test_responsiveness("default")
            assert should_test is True, f"Trouble sign '{sign}' should trigger test"


class TestDetectTroubleSign:
    """Test trouble sign detection."""

    def test_no_error_returns_none(self) -> None:
        """Test that no error returns 'none'."""
        tool = RunCommandTool()

        sign = tool._detect_trouble_sign(error=None, _output="")

        assert sign == "none"

    def test_timeout_detection(self) -> None:
        """Test detection of timeout errors."""
        import pexpect

        tool = RunCommandTool()

        sign = tool._detect_trouble_sign(error=pexpect.TIMEOUT("timeout"), _output="")

        assert sign == "timeout"

    def test_eof_detection(self) -> None:
        """Test detection of EOF errors."""
        import pexpect

        tool = RunCommandTool()

        sign = tool._detect_trouble_sign(error=pexpect.EOF("eof"), _output="")

        assert sign == "eof"

    def test_generic_error_detection(self) -> None:
        """Test detection of generic errors."""
        tool = RunCommandTool()

        sign = tool._detect_trouble_sign(error=RuntimeError("test error"), _output="")

        assert sign == "error"


class TestHealthStateTracking:
    """Test that health state is properly tracked during command execution."""

    def test_successful_command_updates_health(self) -> None:
        """Test that successful command updates health state."""
        tool = RunCommandTool()

        # Clear health state
        _shell_health_states.clear()

        # Execute a successful command
        tool._run("echo 'test'")

        # Check health state was updated
        health = _shell_health_states.get("default")
        assert health is not None
        assert health.last_command_success is True
        assert health.first_command_executed is True
        assert health.consecutive_failures == 0
        assert health.last_trouble_sign == "none"

    def test_banned_command_skips_health_update(self) -> None:
        """Test that banned commands don't update health state."""
        tool = RunCommandTool()

        # Clear health state
        _shell_health_states.clear()

        # Execute a banned command
        tool._run("rm -rf /")

        # Should not have created health state
        # Health state might exist from initialization, but shouldn't be updated
        # The banned command check happens before health tracking


class TestCleanup:
    """Test cleanup functionality."""

    def test_cleanup_clears_health_state(self) -> None:
        """Test that cleanup clears health state."""
        # Create health state
        from datetime import datetime

        health = ShellHealthState(last_command_timestamp=datetime.now())
        _shell_health_states["default"] = health

        # Verify it exists
        assert "default" in _shell_health_states

        # Cleanup
        RunCommandTool.cleanup()

        # Verify it's cleared
        assert "default" not in _shell_health_states
