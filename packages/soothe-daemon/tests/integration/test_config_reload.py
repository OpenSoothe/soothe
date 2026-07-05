"""Integration tests for config hot-reload functionality.

Tests the ConfigWatcher's ability to:
1. Trigger reload callbacks on file modification
2. Handle SIGHUP signals for manual reload
3. Debounce rapid file saves
4. Gracefully handle invalid YAML

Note: These tests require the optional `watchdog` package for file system
watching. Tests that require file watching will be skipped if watchdog
is not installed. Core reload functionality (reload_now, error handling)
is tested regardless of watchdog availability.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from pathlib import Path

import pytest
from soothe.config.reload import ConfigReloadEvent, ConfigWatcher

# Default debounce interval for tests
TEST_DEBOUNCE_SECONDS = 0.3

# Check if watchdog is available for file watching tests
try:
    from watchdog.observers import Observer  # noqa: F401

    _WATCHDOG_AVAILABLE = True
except ImportError:
    _WATCHDOG_AVAILABLE = False


skip_if_no_watchdog = pytest.mark.skipif(
    not _WATCHDOG_AVAILABLE,
    reason="watchdog package not installed (pip install watchdog)",
)


@dataclass
class MockConfig:
    """Simple mock config class for testing reload behavior."""

    value: str = "initial"
    version: int = 1


class ReloadTracker:
    """Tracks reload callback invocations.

    Uses a class method as callback to avoid WeakSet garbage collection
    issues with bound methods.
    """

    def __init__(self) -> None:
        self.events: list[ConfigReloadEvent] = []
        self.call_count: int = 0
        self.lock: threading.Lock = threading.Lock()
        # Create a callable that captures self but is a regular function
        self.callback = self._record

    def _record(self, event: ConfigReloadEvent) -> None:
        """Record a reload event (internal callback)."""
        with self.lock:
            self.events.append(event)
            self.call_count += 1

    def get_events(self) -> list[ConfigReloadEvent]:
        """Get a copy of recorded events."""
        with self.lock:
            return list(self.events)

    def get_count(self) -> int:
        """Get the number of recorded events."""
        with self.lock:
            return self.call_count

    def reset(self) -> None:
        """Reset the tracker."""
        with self.lock:
            self.events.clear()
            self.call_count = 0


@pytest.fixture
def temp_config_file(tmp_path: Path) -> Path:
    """Create a temporary YAML config file."""
    config_file = tmp_path / "config.yml"
    config_file.write_text(
        "# Test config\nagent:\n  name: test-agent\nvalue: initial\n",
        encoding="utf-8",
    )
    return config_file


@pytest.fixture
def reload_tracker() -> ReloadTracker:
    """Create a fresh reload tracker."""
    return ReloadTracker()


@pytest.fixture
def config_watcher(reload_tracker: ReloadTracker) -> ConfigWatcher:
    """Create a ConfigWatcher with short debounce for testing."""
    return ConfigWatcher(debounce_seconds=TEST_DEBOUNCE_SECONDS)


class TestConfigWatcherFileModification:
    """Tests for file modification triggered reload."""

    @skip_if_no_watchdog
    def test_file_modification_triggers_reload_callback_with_new_config(
        self,
        tmp_path: Path,
        reload_tracker: ReloadTracker,
    ) -> None:
        """File modification triggers reload callback with new config."""
        # Create a config file
        config_file = tmp_path / "config.yml"
        config_file.write_text("value: initial\nversion: 1\n", encoding="utf-8")

        def loader() -> MockConfig:
            """Load config from file."""
            content = config_file.read_text(encoding="utf-8")
            lines = content.strip().split("\n")
            data = {}
            for line in lines:
                if ":" in line:
                    key, val = line.split(":", 1)
                    data[key.strip()] = val.strip()
            return MockConfig(
                value=data.get("value", "unknown"),
                version=int(data.get("version", 0)),
            )

        # Create watcher and register config
        # Use reload_tracker.callback (stored as attribute) to avoid WeakSet GC
        watcher = ConfigWatcher(debounce_seconds=TEST_DEBOUNCE_SECONDS)
        watcher.watch_config(
            path=config_file,
            config_type="agent",
            loader=loader,
            callback=reload_tracker.callback,
        )

        # Start watching
        watcher.start()

        try:
            # Wait for initial load
            time.sleep(0.3)

            # Verify initial load
            assert reload_tracker.get_count() >= 1
            initial_event = reload_tracker.get_events()[0]
            assert initial_event.config_type == "agent"
            assert initial_event.error is None
            assert initial_event.new_config.value == "initial"
            assert initial_event.new_config.version == 1

            # Reset tracker
            reload_tracker.reset()

            # Modify the file
            config_file.write_text("value: updated\nversion: 2\n", encoding="utf-8")

            # Wait for debounced reload
            time.sleep(TEST_DEBOUNCE_SECONDS + 0.5)

            # Verify reload was triggered with new config
            assert reload_tracker.get_count() >= 1
            reload_event = reload_tracker.get_events()[-1]
            assert reload_event.config_type == "agent"
            assert reload_event.error is None
            assert reload_event.new_config.value == "updated"
            assert reload_event.new_config.version == 2
            # old_config should have the previous value
            assert reload_event.old_config.value == "initial"
            assert reload_event.old_config.version == 1

        finally:
            watcher.stop()

    @skip_if_no_watchdog
    def test_multiple_callbacks_all_invoked_on_reload(
        self,
        tmp_path: Path,
    ) -> None:
        """Multiple registered callbacks are all invoked on reload."""
        config_file = tmp_path / "config.yml"
        config_file.write_text("value: initial\n", encoding="utf-8")

        tracker1 = ReloadTracker()
        tracker2 = ReloadTracker()

        def loader() -> MockConfig:
            return MockConfig(value=config_file.read_text(encoding="utf-8").split(":")[1].strip())

        watcher = ConfigWatcher(debounce_seconds=TEST_DEBOUNCE_SECONDS)
        watcher.watch_config(
            path=config_file,
            config_type="agent",
            loader=loader,
            callback=tracker1.callback,
        )
        # Add second callback for same file
        watcher.watch_config(
            path=config_file,
            config_type="agent",
            loader=loader,
            callback=tracker2.callback,
        )

        watcher.start()

        try:
            time.sleep(0.3)  # Initial load

            # Modify file
            config_file.write_text("value: updated\n", encoding="utf-8")

            time.sleep(TEST_DEBOUNCE_SECONDS + 0.5)

            # Both trackers should have been called
            assert tracker1.get_count() >= 1
            assert tracker2.get_count() >= 1

        finally:
            watcher.stop()


class TestConfigWatcherSIGHUP:
    """Tests for SIGHUP signal-triggered reload."""

    def test_sighup_triggers_reload(
        self,
        tmp_path: Path,
        reload_tracker: ReloadTracker,
    ) -> None:
        """SIGHUP signal triggers config reload via reload_now()."""
        config_file = tmp_path / "config.yml"
        config_file.write_text("value: initial\nversion: 1\n", encoding="utf-8")

        def loader() -> MockConfig:
            content = config_file.read_text(encoding="utf-8")
            lines = content.strip().split("\n")
            data = {}
            for line in lines:
                if ":" in line:
                    key, val = line.split(":", 1)
                    data[key.strip()] = val.strip()
            return MockConfig(
                value=data.get("value", "unknown"),
                version=int(data.get("version", 0)),
            )

        watcher = ConfigWatcher(debounce_seconds=TEST_DEBOUNCE_SECONDS)
        watcher.watch_config(
            path=config_file,
            config_type="agent",
            loader=loader,
            callback=reload_tracker.callback,
        )

        watcher.start()

        try:
            # Wait for initial load
            time.sleep(0.2)
            initial_count = reload_tracker.get_count()
            assert initial_count >= 1

            # Modify file but don't wait for file watcher debounce
            config_file.write_text("value: sighup_updated\nversion: 2\n", encoding="utf-8")

            # Small delay to ensure file is written
            time.sleep(0.1)

            # Reset tracker to see reload_now-specific reload
            reload_tracker.reset()

            # Use reload_now() to simulate SIGHUP-triggered reload
            # This is more reliable than sending actual signals in tests
            watcher.reload_now()

            time.sleep(0.2)

            # Verify reload was triggered
            assert reload_tracker.get_count() >= 1
            event = reload_tracker.get_events()[-1]
            assert event.new_config.value == "sighup_updated"
            assert event.new_config.version == 2

        finally:
            watcher.stop()

    def test_sighup_handler_installed_and_removed(
        self,
        tmp_path: Path,
    ) -> None:
        """SIGHUP handler is properly installed on start and removed on stop."""
        config_file = tmp_path / "config.yml"
        config_file.write_text("value: test\n", encoding="utf-8")

        watcher = ConfigWatcher(debounce_seconds=TEST_DEBOUNCE_SECONDS)
        watcher.watch_config(
            path=config_file,
            config_type="agent",
            loader=lambda: MockConfig(value="test"),
        )

        # Check initial state
        assert not watcher._sighup_handler_installed

        watcher.start()

        try:
            # After start, SIGHUP handler should be installed (on Unix)
            assert watcher._sighup_handler_installed

        finally:
            watcher.stop()

        # After stop, handler should be restored
        assert not watcher._sighup_handler_installed


class TestConfigWatcherDebounce:
    """Tests for debounce behavior on rapid file saves."""

    @skip_if_no_watchdog
    def test_rapid_file_saves_are_debounced(
        self,
        tmp_path: Path,
        reload_tracker: ReloadTracker,
    ) -> None:
        """Rapid consecutive file saves only trigger one callback (debounced)."""
        config_file = tmp_path / "config.yml"
        config_file.write_text("value: initial\nversion: 0\n", encoding="utf-8")

        def loader() -> MockConfig:
            content = config_file.read_text(encoding="utf-8")
            lines = content.strip().split("\n")
            data = {}
            for line in lines:
                if ":" in line:
                    key, val = line.split(":", 1)
                    data[key.strip()] = val.strip()
            return MockConfig(
                value=data.get("value", "unknown"),
                version=int(data.get("version", 0)),
            )

        # Use longer debounce to make test more reliable
        debounce_time = 0.5
        watcher = ConfigWatcher(debounce_seconds=debounce_time)
        watcher.watch_config(
            path=config_file,
            config_type="agent",
            loader=loader,
            callback=reload_tracker.callback,
        )

        watcher.start()

        try:
            # Wait for initial load
            time.sleep(0.3)
            reload_tracker.reset()

            # Rapidly modify file multiple times within debounce window
            for i in range(5):
                config_file.write_text(f"value: rapid_{i}\nversion: {i + 1}\n", encoding="utf-8")
                time.sleep(0.05)  # 50ms between saves, well under debounce

            # Wait for debounce to complete
            time.sleep(debounce_time + 0.5)

            # Should only have one reload (debounced)
            # Note: Some platforms may have timing issues, so we allow for 1-2 calls
            assert reload_tracker.get_count() <= 2, (
                f"Expected at most 2 reloads (debounced), got {reload_tracker.get_count()}"
            )

            # The final config should have the last written values
            final_event = reload_tracker.get_events()[-1]
            assert final_event.new_config.version == 5  # Last version written

        finally:
            watcher.stop()

    @skip_if_no_watchdog
    def test_separate_file_saves_after_debounce_trigger_separate_reloads(
        self,
        tmp_path: Path,
        reload_tracker: ReloadTracker,
    ) -> None:
        """File saves spaced beyond debounce interval trigger separate reloads."""
        config_file = tmp_path / "config.yml"
        config_file.write_text("value: initial\nversion: 0\n", encoding="utf-8")

        def loader() -> MockConfig:
            content = config_file.read_text(encoding="utf-8")
            lines = content.strip().split("\n")
            data = {}
            for line in lines:
                if ":" in line:
                    key, val = line.split(":", 1)
                    data[key.strip()] = val.strip()
            return MockConfig(
                value=data.get("value", "unknown"),
                version=int(data.get("version", 0)),
            )

        debounce_time = 0.3
        watcher = ConfigWatcher(debounce_seconds=debounce_time)
        watcher.watch_config(
            path=config_file,
            config_type="agent",
            loader=loader,
            callback=reload_tracker.callback,
        )

        watcher.start()

        try:
            # Wait for initial load
            time.sleep(0.2)
            reload_tracker.reset()

            # First modification
            config_file.write_text("value: first\nversion: 1\n", encoding="utf-8")
            time.sleep(debounce_time + 0.3)

            # Second modification (after debounce)
            config_file.write_text("value: second\nversion: 2\n", encoding="utf-8")
            time.sleep(debounce_time + 0.3)

            # Should have two reloads
            assert reload_tracker.get_count() >= 2, (
                f"Expected at least 2 reloads, got {reload_tracker.get_count()}"
            )

        finally:
            watcher.stop()


class TestConfigWatcherInvalidYAML:
    """Tests for handling invalid YAML files."""

    def test_invalid_yaml_does_not_crash_watcher(
        self,
        tmp_path: Path,
        reload_tracker: ReloadTracker,
    ) -> None:
        """Invalid YAML does not crash the watcher; error is reported in event."""
        config_file = tmp_path / "config.yml"
        config_file.write_text("value: valid\nversion: 1\n", encoding="utf-8")

        def loader() -> MockConfig:
            content = config_file.read_text(encoding="utf-8")
            # Simulate YAML parsing that could fail
            if "invalid" in content.lower() or "]]]" in content:
                raise ValueError("Invalid YAML: parsing error")
            lines = content.strip().split("\n")
            data = {}
            for line in lines:
                if ":" in line:
                    key, val = line.split(":", 1)
                    data[key.strip()] = val.strip()
            return MockConfig(
                value=data.get("value", "unknown"),
                version=int(data.get("version", 0)),
            )

        watcher = ConfigWatcher(debounce_seconds=TEST_DEBOUNCE_SECONDS)
        watcher.watch_config(
            path=config_file,
            config_type="agent",
            loader=loader,
            callback=reload_tracker.callback,
        )

        watcher.start()

        try:
            # Wait for initial load
            time.sleep(0.2)
            assert reload_tracker.get_count() >= 1
            initial_event = reload_tracker.get_events()[0]
            assert initial_event.error is None

            # Reset tracker
            reload_tracker.reset()

            # Write invalid content and trigger reload_now
            config_file.write_text("]]]\ninvalid yaml content: [[[", encoding="utf-8")

            # Trigger reload directly
            watcher.reload_now()

            # Watcher should not crash, and error should be reported
            assert reload_tracker.get_count() >= 1
            error_event = reload_tracker.get_events()[-1]
            assert error_event.error is not None
            assert isinstance(error_event.error, ValueError)

            # Watcher should still be running
            assert watcher.is_running

            # Writing valid content should work again
            reload_tracker.reset()
            config_file.write_text("value: recovered\nversion: 2\n", encoding="utf-8")

            watcher.reload_now()

            assert reload_tracker.get_count() >= 1
            recovered_event = reload_tracker.get_events()[-1]
            assert recovered_event.error is None
            assert recovered_event.new_config.value == "recovered"

        finally:
            watcher.stop()

    def test_loader_exception_in_callback_does_not_crash_watcher(
        self,
        tmp_path: Path,
    ) -> None:
        """Exception in reload callback does not crash the watcher."""
        config_file = tmp_path / "config.yml"
        config_file.write_text("value: initial\n", encoding="utf-8")

        callback_error_raised = threading.Event()

        # Store callback as a standalone function to avoid WeakSet GC
        def make_bad_callback() -> callable:
            def bad_callback(event: ConfigReloadEvent) -> None:
                """Callback that raises an exception."""
                callback_error_raised.set()
                raise RuntimeError("Callback error!")

            return bad_callback

        bad_callback = make_bad_callback()

        def loader() -> MockConfig:
            return MockConfig(value=config_file.read_text(encoding="utf-8").split(":")[1].strip())

        watcher = ConfigWatcher(debounce_seconds=TEST_DEBOUNCE_SECONDS)
        watcher.watch_config(
            path=config_file,
            config_type="agent",
            loader=loader,
            callback=bad_callback,
        )

        watcher.start()

        try:
            # Wait for initial load (callback will error)
            time.sleep(0.2)

            # Callback was invoked despite error
            assert callback_error_raised.is_set()

            # Watcher should still be running
            assert watcher.is_running

            # Modify file to trigger another reload via reload_now
            callback_error_raised.clear()
            config_file.write_text("value: updated\n", encoding="utf-8")

            watcher.reload_now()
            time.sleep(0.1)

            # Callback was called again
            assert callback_error_raised.is_set()
            assert watcher.is_running

        finally:
            watcher.stop()

    def test_missing_config_file_handled_gracefully(
        self,
        tmp_path: Path,
        reload_tracker: ReloadTracker,
    ) -> None:
        """Missing config file is handled gracefully during reload."""
        config_file = tmp_path / "config.yml"
        config_file.write_text("value: initial\n", encoding="utf-8")

        def loader() -> MockConfig:
            if not config_file.exists():
                raise FileNotFoundError(f"Config file not found: {config_file}")
            return MockConfig(value=config_file.read_text(encoding="utf-8").split(":")[1].strip())

        watcher = ConfigWatcher(debounce_seconds=TEST_DEBOUNCE_SECONDS)
        watcher.watch_config(
            path=config_file,
            config_type="agent",
            loader=loader,
            callback=reload_tracker.callback,
        )

        watcher.start()

        try:
            # Wait for initial load
            time.sleep(0.2)
            initial_count = reload_tracker.get_count()
            assert initial_count >= 1

            # Delete the config file
            config_file.unlink()
            reload_tracker.reset()

            # Trigger reload manually (since file watching won't detect deletion on all platforms)
            watcher.reload_now(config_file)

            time.sleep(0.2)

            # Error should be recorded
            assert reload_tracker.get_count() >= 1
            error_event = reload_tracker.get_events()[-1]
            assert error_event.error is not None
            assert isinstance(error_event.error, FileNotFoundError)

            # Watcher still running
            assert watcher.is_running

        finally:
            watcher.stop()


class TestConfigWatcherLifecycle:
    """Tests for watcher lifecycle management."""

    def test_start_stop_idempotent(self, tmp_path: Path) -> None:
        """Start and stop can be called multiple times safely."""
        config_file = tmp_path / "config.yml"
        config_file.write_text("value: test\n", encoding="utf-8")

        watcher = ConfigWatcher(debounce_seconds=TEST_DEBOUNCE_SECONDS)
        watcher.watch_config(
            path=config_file,
            config_type="agent",
            loader=lambda: MockConfig(value="test"),
        )

        # Multiple starts should be idempotent
        watcher.start()
        assert watcher.is_running
        watcher.start()  # Second call
        assert watcher.is_running

        # Multiple stops should be idempotent
        watcher.stop()
        assert not watcher.is_running
        watcher.stop()  # Second call
        assert not watcher.is_running

    def test_get_current_config(self, tmp_path: Path) -> None:
        """get_current_config returns the loaded config."""
        config_file = tmp_path / "config.yml"
        config_file.write_text("value: test_value\n", encoding="utf-8")

        watcher = ConfigWatcher(debounce_seconds=TEST_DEBOUNCE_SECONDS)
        watcher.watch_config(
            path=config_file,
            config_type="agent",
            loader=lambda: MockConfig(value="loaded_value"),
        )

        # Before start, no config
        assert watcher.get_current_config("agent") is None

        watcher.start()

        try:
            time.sleep(0.2)

            # After start, config should be loaded
            config = watcher.get_current_config("agent")
            assert config is not None
            assert config.value == "loaded_value"

            # Non-existent type returns None
            assert watcher.get_current_config("nonexistent") is None

        finally:
            watcher.stop()

    def test_unwatch_config(self, tmp_path: Path, reload_tracker: ReloadTracker) -> None:
        """unwatch_config stops watching a file."""
        config_file = tmp_path / "config.yml"
        config_file.write_text("value: initial\n", encoding="utf-8")

        watcher = ConfigWatcher(debounce_seconds=TEST_DEBOUNCE_SECONDS)
        watcher.watch_config(
            path=config_file,
            config_type="agent",
            loader=lambda: MockConfig(value="test"),
            callback=reload_tracker.callback,
        )

        watcher.start()

        try:
            time.sleep(0.2)
            initial_count = reload_tracker.get_count()
            assert initial_count >= 1

            # Unwatch the config
            watcher.unwatch_config(config_file)

            # Reset tracker and modify the file
            reload_tracker.reset()
            config_file.write_text("value: modified\n", encoding="utf-8")

            # Trigger reload - but since we unwatched, nothing should happen
            watcher.reload_now()

            # Should not trigger callback since we unwatched
            assert reload_tracker.get_count() == 0

        finally:
            watcher.stop()


class TestConfigWatcherValidation:
    """Tests for config validation before reload."""

    def test_validator_prevents_swap_on_failure(
        self,
        tmp_path: Path,
        reload_tracker: ReloadTracker,
    ) -> None:
        """Validation failure prevents config swap and emits error event."""
        config_file = tmp_path / "config.yml"
        config_file.write_text("value: initial\nversion: 1\n", encoding="utf-8")

        def loader() -> MockConfig:
            content = config_file.read_text(encoding="utf-8")
            lines = content.strip().split("\n")
            data = {}
            for line in lines:
                if ":" in line:
                    key, val = line.split(":", 1)
                    data[key.strip()] = val.strip()
            return MockConfig(
                value=data.get("value", "unknown"),
                version=int(data.get("version", 0)),
            )

        # Validator that rejects configs with version > 10
        def validator(config: MockConfig) -> bool:
            if config.version > 10:
                raise ValueError(f"Version {config.version} exceeds maximum 10")
            return True

        watcher = ConfigWatcher(debounce_seconds=TEST_DEBOUNCE_SECONDS)
        watcher.watch_config(
            path=config_file,
            config_type="agent",
            loader=loader,
            callback=reload_tracker.callback,
            validator=validator,
        )

        watcher.start()

        try:
            time.sleep(0.2)
            initial_count = reload_tracker.get_count()
            assert initial_count >= 1
            initial_event = reload_tracker.get_events()[0]
            assert initial_event.error is None
            assert initial_event.new_config.version == 1

            # Store the initial config reference
            initial_config = watcher.get_current_config("agent")
            assert initial_config is not None
            assert initial_config.version == 1

            # Reset tracker
            reload_tracker.reset()

            # Modify file to have invalid version (exceeds limit)
            config_file.write_text("value: invalid\nversion: 99\n", encoding="utf-8")

            # Trigger reload
            watcher.reload_now()

            time.sleep(0.2)

            # Reload should have been called
            assert reload_tracker.get_count() >= 1
            reload_event = reload_tracker.get_events()[-1]

            # Event should have error (validation failed)
            assert reload_event.error is not None
            assert "Version 99" in str(reload_event.error)

            # new_config should be None (swap skipped)
            assert reload_event.new_config is None

            # Current config should still be the initial one (swap skipped)
            current_config = watcher.get_current_config("agent")
            assert current_config is not None
            assert current_config.version == 1
            assert current_config.value == "initial"

        finally:
            watcher.stop()

    def test_validator_returns_false_prevents_swap(
        self,
        tmp_path: Path,
        reload_tracker: ReloadTracker,
    ) -> None:
        """Validator returning False prevents config swap."""
        config_file = tmp_path / "config.yml"
        config_file.write_text("value: valid\nversion: 1\n", encoding="utf-8")

        def loader() -> MockConfig:
            content = config_file.read_text(encoding="utf-8")
            lines = content.strip().split("\n")
            data = {}
            for line in lines:
                if ":" in line:
                    key, val = line.split(":", 1)
                    data[key.strip()] = val.strip()
            return MockConfig(
                value=data.get("value", "unknown"),
                version=int(data.get("version", 0)),
            )

        # Validator that returns False for 'invalid' value
        def validator(config: MockConfig) -> bool:
            return config.value != "invalid"

        watcher = ConfigWatcher(debounce_seconds=TEST_DEBOUNCE_SECONDS)
        watcher.watch_config(
            path=config_file,
            config_type="agent",
            loader=loader,
            callback=reload_tracker.callback,
            validator=validator,
        )

        watcher.start()

        try:
            time.sleep(0.2)

            # Reset tracker
            reload_tracker.reset()

            # Modify file to have invalid value
            config_file.write_text("value: invalid\nversion: 2\n", encoding="utf-8")

            watcher.reload_now()
            time.sleep(0.2)

            # Should have error event
            assert reload_tracker.get_count() >= 1
            event = reload_tracker.get_events()[-1]
            assert event.error is not None
            assert "False" in str(event.error) or "validation" in str(event.error).lower()
            assert event.new_config is None

        finally:
            watcher.stop()

    def test_validator_passes_allows_swap(
        self,
        tmp_path: Path,
        reload_tracker: ReloadTracker,
    ) -> None:
        """Validation passing allows config swap to proceed."""
        config_file = tmp_path / "config.yml"
        config_file.write_text("value: initial\nversion: 1\n", encoding="utf-8")

        def loader() -> MockConfig:
            content = config_file.read_text(encoding="utf-8")
            lines = content.strip().split("\n")
            data = {}
            for line in lines:
                if ":" in line:
                    key, val = line.split(":", 1)
                    data[key.strip()] = val.strip()
            return MockConfig(
                value=data.get("value", "unknown"),
                version=int(data.get("version", 0)),
            )

        # Validator that always passes
        def validator(config: MockConfig) -> bool:
            return True

        watcher = ConfigWatcher(debounce_seconds=TEST_DEBOUNCE_SECONDS)
        watcher.watch_config(
            path=config_file,
            config_type="agent",
            loader=loader,
            callback=reload_tracker.callback,
            validator=validator,
        )

        watcher.start()

        try:
            time.sleep(0.2)
            initial_count = reload_tracker.get_count()
            assert initial_count >= 1

            # Reset tracker
            reload_tracker.reset()

            # Modify file with valid values
            config_file.write_text("value: valid_updated\nversion: 5\n", encoding="utf-8")

            watcher.reload_now()
            time.sleep(0.2)

            # Should have successful reload
            assert reload_tracker.get_count() >= 1
            event = reload_tracker.get_events()[-1]
            assert event.error is None
            assert event.new_config is not None
            assert event.new_config.value == "valid_updated"
            assert event.new_config.version == 5

            # Current config should be updated
            current = watcher.get_current_config("agent")
            assert current is not None
            assert current.value == "valid_updated"
            assert current.version == 5

        finally:
            watcher.stop()

    def test_no_validator_allows_swap(
        self,
        tmp_path: Path,
        reload_tracker: ReloadTracker,
    ) -> None:
        """Without validator, config swap proceeds normally."""
        config_file = tmp_path / "config.yml"
        config_file.write_text("value: initial\nversion: 1\n", encoding="utf-8")

        def loader() -> MockConfig:
            content = config_file.read_text(encoding="utf-8")
            lines = content.strip().split("\n")
            data = {}
            for line in lines:
                if ":" in line:
                    key, val = line.split(":", 1)
                    data[key.strip()] = val.strip()
            return MockConfig(
                value=data.get("value", "unknown"),
                version=int(data.get("version", 0)),
            )

        watcher = ConfigWatcher(debounce_seconds=TEST_DEBOUNCE_SECONDS)
        # No validator passed
        watcher.watch_config(
            path=config_file,
            config_type="agent",
            loader=loader,
            callback=reload_tracker.callback,
        )

        watcher.start()

        try:
            time.sleep(0.2)

            # Reset tracker
            reload_tracker.reset()

            # Modify file - any values allowed
            config_file.write_text("value: any_value\nversion: 999\n", encoding="utf-8")

            watcher.reload_now()
            time.sleep(0.2)

            # Should have successful reload (no validation)
            assert reload_tracker.get_count() >= 1
            event = reload_tracker.get_events()[-1]
            assert event.error is None
            assert event.new_config.version == 999

        finally:
            watcher.stop()

    def test_loader_failure_before_validator(
        self,
        tmp_path: Path,
        reload_tracker: ReloadTracker,
    ) -> None:
        """Loader failure is caught before validator runs."""
        config_file = tmp_path / "config.yml"
        config_file.write_text("value: initial\n", encoding="utf-8")

        call_order: list[str] = []

        def loader() -> MockConfig:
            call_order.append("loader")
            # Simulate loader failure
            raise RuntimeError("Loader failed")

        def validator(config: MockConfig) -> bool:
            call_order.append("validator")
            return True

        watcher = ConfigWatcher(debounce_seconds=TEST_DEBOUNCE_SECONDS)
        watcher.watch_config(
            path=config_file,
            config_type="agent",
            loader=loader,
            callback=reload_tracker.callback,
            validator=validator,
        )

        watcher.start()

        try:
            time.sleep(0.2)

            # Reset tracker
            reload_tracker.reset()

            watcher.reload_now()
            time.sleep(0.2)

            # Should have error from loader
            assert reload_tracker.get_count() >= 1
            event = reload_tracker.get_events()[-1]
            assert event.error is not None
            assert "Loader failed" in str(event.error)

            # Validator should not have been called (loader failed first)
            assert "validator" not in call_order

        finally:
            watcher.stop()


class TestConfigWatcherAuditLog:
    """Tests for reload audit logging."""

    def test_audit_log_records_successful_reload(
        self,
        tmp_path: Path,
        reload_tracker: ReloadTracker,
    ) -> None:
        """Successful reload is recorded in audit log with hashes."""
        config_file = tmp_path / "config.yml"
        config_file.write_text("value: initial\nversion: 1\n", encoding="utf-8")

        def loader() -> MockConfig:
            content = config_file.read_text(encoding="utf-8")
            lines = content.strip().split("\n")
            data = {}
            for line in lines:
                if ":" in line:
                    key, val = line.split(":", 1)
                    data[key.strip()] = val.strip()
            return MockConfig(
                value=data.get("value", "unknown"),
                version=int(data.get("version", 0)),
            )

        watcher = ConfigWatcher(debounce_seconds=TEST_DEBOUNCE_SECONDS)
        watcher.watch_config(
            path=config_file,
            config_type="agent",
            loader=loader,
            callback=reload_tracker.callback,
        )

        watcher.start()

        try:
            time.sleep(0.2)

            # Initial load should create an audit entry
            history = watcher.get_reload_history()
            assert len(history) >= 1

            initial_entry = history[0]
            assert initial_entry.config_type == "agent"
            assert initial_entry.success is True
            assert initial_entry.error is None
            # Hashes should be present (old may be empty on first load)
            assert initial_entry.new_config_hash != ""

            # Modify and reload
            reload_tracker.reset()
            config_file.write_text("value: updated\nversion: 2\n", encoding="utf-8")
            watcher.reload_now()
            time.sleep(0.2)

            # Should have two entries now
            history = watcher.get_reload_history()
            assert len(history) >= 2

            # Most recent first
            latest = history[0]
            assert latest.config_type == "agent"
            assert latest.success is True
            assert latest.old_config_hash != ""
            assert latest.new_config_hash != ""
            # Hashes should differ (config changed)
            assert latest.old_config_hash != latest.new_config_hash

        finally:
            watcher.stop()

    def test_audit_log_records_failed_reload(
        self,
        tmp_path: Path,
        reload_tracker: ReloadTracker,
    ) -> None:
        """Failed reload is recorded in audit log with error."""
        config_file = tmp_path / "config.yml"
        config_file.write_text("value: initial\nversion: 1\n", encoding="utf-8")

        def loader() -> MockConfig:
            content = config_file.read_text(encoding="utf-8")
            if "invalid" in content:
                raise ValueError("Invalid config content")
            lines = content.strip().split("\n")
            data = {}
            for line in lines:
                if ":" in line:
                    key, val = line.split(":", 1)
                    data[key.strip()] = val.strip()
            return MockConfig(
                value=data.get("value", "unknown"),
                version=int(data.get("version", 0)),
            )

        watcher = ConfigWatcher(debounce_seconds=TEST_DEBOUNCE_SECONDS)
        watcher.watch_config(
            path=config_file,
            config_type="agent",
            loader=loader,
            callback=reload_tracker.callback,
        )

        watcher.start()

        try:
            time.sleep(0.2)

            # Write invalid content and trigger reload
            config_file.write_text("value: invalid\n", encoding="utf-8")
            reload_tracker.reset()
            watcher.reload_now()
            time.sleep(0.2)

            # Check audit log for failed entry
            history = watcher.get_reload_history()
            assert len(history) >= 1

            failed_entry = history[0]
            assert failed_entry.success is False
            assert failed_entry.error is not None
            assert "Invalid config content" in failed_entry.error

        finally:
            watcher.stop()

    def test_audit_log_limits_entries(
        self,
        tmp_path: Path,
        reload_tracker: ReloadTracker,
    ) -> None:
        """Audit log respects max_entries limit."""
        config_file = tmp_path / "config.yml"

        def loader() -> MockConfig:
            content = config_file.read_text(encoding="utf-8")
            version = 0
            for line in content.strip().split("\n"):
                if line.startswith("version:"):
                    version = int(line.split(":")[1].strip())
            return MockConfig(value="test", version=version)

        # Create watcher with small audit limit
        watcher = ConfigWatcher(
            debounce_seconds=TEST_DEBOUNCE_SECONDS,
            max_audit_entries=10,  # Small limit for testing
        )
        watcher.watch_config(
            path=config_file,
            config_type="agent",
            loader=loader,
            callback=reload_tracker.callback,
        )

        watcher.start()

        try:
            # Do more reloads than the limit
            for i in range(20):
                config_file.write_text(f"version: {i}\n", encoding="utf-8")
                watcher.reload_now()
                time.sleep(0.05)

            # Should be capped at limit
            history = watcher.get_reload_history()
            assert len(history) <= 10

        finally:
            watcher.stop()

    def test_audit_log_history_order(
        self,
        tmp_path: Path,
        reload_tracker: ReloadTracker,
    ) -> None:
        """Audit log returns history in most-recent-first order."""
        config_file = tmp_path / "config.yml"

        def loader() -> MockConfig:
            content = config_file.read_text(encoding="utf-8")
            version = 0
            for line in content.strip().split("\n"):
                if line.startswith("version:"):
                    version = int(line.split(":")[1].strip())
            return MockConfig(value="test", version=version)

        watcher = ConfigWatcher(debounce_seconds=TEST_DEBOUNCE_SECONDS)
        watcher.watch_config(
            path=config_file,
            config_type="agent",
            loader=loader,
            callback=reload_tracker.callback,
        )

        watcher.start()

        try:
            # Do multiple reloads with different versions
            versions_loaded: list[int] = []
            for i in range(5):
                config_file.write_text(f"version: {i + 10}\n", encoding="utf-8")
                watcher.reload_now()
                time.sleep(0.1)
                versions_loaded.append(i + 10)

            # Get history
            history = watcher.get_reload_history()
            assert len(history) >= 5

            # Most recent first - so versions should be descending
            # Note: we can't check version directly from audit entry,
            # but we can check timestamps are descending
            timestamps = [entry.timestamp for entry in history[:5]]
            # Timestamps should be in descending order (most recent first)
            assert timestamps == sorted(timestamps, reverse=True)

        finally:
            watcher.stop()

    def test_audit_log_disabled_when_max_entries_zero(
        self,
        tmp_path: Path,
        reload_tracker: ReloadTracker,
    ) -> None:
        """Audit logging disabled when max_audit_entries=0."""
        config_file = tmp_path / "config.yml"
        config_file.write_text("value: test\n", encoding="utf-8")

        watcher = ConfigWatcher(
            debounce_seconds=TEST_DEBOUNCE_SECONDS,
            max_audit_entries=0,  # Disabled
        )
        watcher.watch_config(
            path=config_file,
            config_type="agent",
            loader=lambda: MockConfig(value="test"),
            callback=reload_tracker.callback,
        )

        watcher.start()

        try:
            time.sleep(0.2)

            # Audit log should be None
            assert watcher.audit_log is None

            # get_reload_history should return empty list
            history = watcher.get_reload_history()
            assert history == []

        finally:
            watcher.stop()

    def test_audit_entry_included_in_reload_event(
        self,
        tmp_path: Path,
        reload_tracker: ReloadTracker,
    ) -> None:
        """ConfigReloadEvent includes audit_entry with reload details."""
        config_file = tmp_path / "config.yml"
        config_file.write_text("value: initial\nversion: 1\n", encoding="utf-8")

        def loader() -> MockConfig:
            content = config_file.read_text(encoding="utf-8")
            lines = content.strip().split("\n")
            data = {}
            for line in lines:
                if ":" in line:
                    key, val = line.split(":", 1)
                    data[key.strip()] = val.strip()
            return MockConfig(
                value=data.get("value", "unknown"),
                version=int(data.get("version", 0)),
            )

        watcher = ConfigWatcher(debounce_seconds=TEST_DEBOUNCE_SECONDS)
        watcher.watch_config(
            path=config_file,
            config_type="agent",
            loader=loader,
            callback=reload_tracker.callback,
        )

        watcher.start()

        try:
            time.sleep(0.2)
            reload_tracker.reset()

            # Trigger reload
            config_file.write_text("value: updated\nversion: 2\n", encoding="utf-8")
            watcher.reload_now()
            time.sleep(0.2)

            # Check that event has audit_entry
            events = reload_tracker.get_events()
            assert len(events) >= 1

            event = events[-1]
            assert event.audit_entry is not None
            assert event.audit_entry.config_type == "agent"
            assert event.audit_entry.success is True
            assert event.audit_entry.old_config_hash != ""
            assert event.audit_entry.new_config_hash != ""
            assert event.audit_entry.timestamp != ""

        finally:
            watcher.stop()
