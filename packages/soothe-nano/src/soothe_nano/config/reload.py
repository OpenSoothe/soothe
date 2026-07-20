"""Config hot-reload support for Soothe.

Provides file system watching and signal-based config reload capabilities.
"""

from __future__ import annotations

import hashlib
import json
import logging
import signal
import threading
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from weakref import WeakSet

from soothe_nano.config.env import SOOTHE_HOME

_logger = logging.getLogger(__name__)

# Default paths for config files
DEFAULT_CONFIG_PATH = Path(SOOTHE_HOME) / "config" / "config.yml"
DEFAULT_DAEMON_CONFIG_PATH = Path(SOOTHE_HOME) / "config" / "daemon.yml"

# Default debounce interval in seconds
DEFAULT_DEBOUNCE_SECONDS = 1.0

# Default max audit entries
DEFAULT_MAX_AUDIT_ENTRIES = 100


def _compute_config_hash(config: Any) -> str:
    """Compute a hash of a config object for audit logging.

    Args:
        config: Config object (Pydantic model, dict, or other serializable).

    Returns:
        SHA256 hash string of the config.
    """
    if config is None:
        return "null"
    try:
        if hasattr(config, "model_dump"):
            data = config.model_dump(mode="json")
        elif isinstance(config, dict):
            data = config
        else:
            data = str(config)
        json_str = json.dumps(data, sort_keys=True, default=str)
        return hashlib.sha256(json_str.encode()).hexdigest()[:16]
    except Exception:
        return "error"


@dataclass
class ReloadAuditEntry:
    """Audit entry for a single reload attempt.

    Attributes:
        timestamp: ISO format timestamp when reload occurred.
        config_type: Type of config ('agent' or 'daemon').
        config_path: Path to the config file.
        old_config_hash: Hash of previous config (or 'null' if first load).
        new_config_hash: Hash of new config (or 'error' if load failed).
        success: Whether reload succeeded.
        error: Error message if reload failed, None otherwise.
    """

    timestamp: str
    config_type: str
    config_path: str
    old_config_hash: str
    new_config_hash: str
    success: bool
    error: str | None = None


class ReloadAuditLog:
    """Thread-safe audit log for config reload history.

    Stores the last N reload attempts in memory for debugging and monitoring.

    Attributes:
        max_entries: Maximum number of entries to retain.
    """

    def __init__(self, max_entries: int = DEFAULT_MAX_AUDIT_ENTRIES) -> None:
        """Initialize the audit log.

        Args:
            max_entries: Maximum number of entries to retain (default 100).
        """
        self._max_entries = max_entries
        self._entries: deque[ReloadAuditEntry] = deque(maxlen=max_entries)
        self._lock = threading.Lock()

    def record(
        self,
        config_type: str,
        config_path: Path | str,
        old_config: Any,
        new_config: Any,
        error: Exception | None = None,
    ) -> ReloadAuditEntry:
        """Record a reload attempt.

        Args:
            config_type: Type of config ('agent' or 'daemon').
            config_path: Path to the config file.
            old_config: Previous config instance (may be None).
            new_config: New config instance (may be None on error).
            error: Exception if reload failed, None otherwise.

        Returns:
            The created audit entry.
        """
        entry = ReloadAuditEntry(
            timestamp=datetime.now(UTC).isoformat(),
            config_type=config_type,
            config_path=str(config_path),
            old_config_hash=_compute_config_hash(old_config),
            new_config_hash=_compute_config_hash(new_config),
            success=error is None,
            error=str(error) if error else None,
        )
        with self._lock:
            self._entries.append(entry)
        _logger.debug(
            "Recorded reload audit: type=%s success=%s old=%s new=%s",
            config_type,
            entry.success,
            entry.old_config_hash,
            entry.new_config_hash,
        )
        return entry

    def get_history(self, limit: int | None = None) -> list[ReloadAuditEntry]:
        """Get reload history, most recent first.

        Args:
            limit: Maximum entries to return (None for all).

        Returns:
            List of audit entries, most recent first.
        """
        with self._lock:
            entries = list(self._entries)
        # Return most recent first
        entries.reverse()
        if limit is not None:
            entries = entries[:limit]
        return entries

    def clear(self) -> None:
        """Clear all audit entries."""
        with self._lock:
            self._entries.clear()

    @property
    def count(self) -> int:
        """Number of entries in the log."""
        with self._lock:
            return len(self._entries)


@dataclass
class ConfigReloadEvent:
    """Event emitted when a config file is reloaded.

    Attributes:
        config_type: Type of config that was reloaded ('agent' or 'daemon').
        config_path: Path to the config file that changed.
        old_config: Previous config instance (may be None on first load).
        new_config: New config instance.
        error: Exception if reload failed, None otherwise.
        audit_entry: Audit entry with reload details (hashes, timestamp, etc.).
    """

    config_type: str
    config_path: Path
    old_config: Any
    new_config: Any
    error: Exception | None = None
    audit_entry: ReloadAuditEntry | None = None


# Type alias for reload callbacks
ConfigReloadCallback = Callable[[ConfigReloadEvent], None]


@dataclass
class WatchedConfig:
    """Internal tracking for a watched config file.

    Attributes:
        path: Path to the config file.
        config_type: Type identifier ('agent' or 'daemon').
        loader: Callable that loads and returns the config.
        callbacks: Set of callbacks to invoke on reload.
        last_modified: Last modification timestamp seen.
        validator: Optional callable to validate the loaded config before swap.
    """

    path: Path
    config_type: str
    loader: Callable[[], Any]
    callbacks: WeakSet[ConfigReloadCallback] = field(default_factory=WeakSet)
    last_modified: float = 0.0
    current_config: Any = None
    validator: Callable[[Any], bool] | None = None


class ConfigWatcher:
    """Watches config files for changes and triggers debounced reload callbacks.

    Supports:
    - File system watching via watchdog for YAML files
    - Debounced reload callbacks (prevents rapid-fire reloads)
    - SIGHUP signal handler for manual reload triggers
    - Graceful shutdown via threading.Event
    - Audit logging of all reload attempts

    Example:
        ```python
        from soothe_nano.config.reload import ConfigWatcher, DEFAULT_CONFIG_PATH
        from soothe_nano.config import SootheConfig


        def on_reload(event):
            if event.error:
                print(f"Reload failed: {event.error}")
            else:
                print(f"Reloaded {event.config_type} config")


        watcher = ConfigWatcher()

        # Watch agent config
        watcher.watch_config(
            path=DEFAULT_CONFIG_PATH,
            config_type="agent",
            loader=lambda: SootheConfig.from_yaml_file(str(DEFAULT_CONFIG_PATH)),
            callback=on_reload,
        )

        # Start watching (non-blocking)
        watcher.start()

        # ... later ...
        watcher.stop()
        ```
    """

    def __init__(
        self,
        debounce_seconds: float = DEFAULT_DEBOUNCE_SECONDS,
        max_audit_entries: int = DEFAULT_MAX_AUDIT_ENTRIES,
    ) -> None:
        """Initialize the config watcher.

        Args:
            debounce_seconds: Minimum seconds between reloads for the same file.
                Prevents rapid-fire reloads when files are modified multiple times
                in quick succession (e.g., editor saves).
            max_audit_entries: Maximum number of audit entries to retain
                (default 100). Set to 0 to disable audit logging.
        """
        self._debounce_seconds = debounce_seconds
        self._max_audit_entries = max_audit_entries
        self._audit_log = (
            ReloadAuditLog(max_entries=max_audit_entries) if max_audit_entries > 0 else None
        )
        self._watched: dict[Path, WatchedConfig] = {}
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._debounce_timers: dict[Path, threading.Timer] = {}
        self._observer: Any | None = None  # watchdog.observer.Observer
        self._sighup_handler_installed = False
        self._original_sighup_handler: Any = None
        self._thread: threading.Thread | None = None
        self._started = False

    @property
    def is_running(self) -> bool:
        """Check if the watcher is currently running."""
        return self._started and not self._stop_event.is_set()

    def watch_config(
        self,
        path: Path | str,
        config_type: str,
        loader: Callable[[], Any],
        callback: ConfigReloadCallback | None = None,
        validator: Callable[[Any], bool] | None = None,
    ) -> None:
        """Register a config file to watch.

        Args:
            path: Path to the config file (e.g., config.yml or daemon.yml).
            config_type: Type identifier for the config ('agent' or 'daemon').
            loader: Callable that loads and returns the config instance.
                Called on initial load and subsequent reloads.
            callback: Optional callback to invoke when config is reloaded.
                Callbacks are stored as weak references and will be removed
                when the callback object is garbage collected.
            validator: Optional callable to validate the loaded config before swap.
                Should return True if config is valid, False otherwise.
                If validation fails, the config swap is skipped and an error
                is logged with the callback receiving an error event.
        """
        path = Path(path).expanduser().resolve()
        with self._lock:
            if path in self._watched:
                watched = self._watched[path]
                if callback is not None:
                    watched.callbacks.add(callback)
                _logger.debug("Added callback for existing watch: %s", path)
                return

            watched = WatchedConfig(
                path=path,
                config_type=config_type,
                loader=loader,
                validator=validator,
            )
            if callback is not None:
                watched.callbacks.add(callback)
            self._watched[path] = watched

            # Track initial modification time
            if path.exists():
                watched.last_modified = path.stat().st_mtime

            _logger.info("Watching config file: %s (type=%s)", path, config_type)

    def unwatch_config(self, path: Path | str) -> None:
        """Stop watching a config file.

        Args:
            path: Path to the config file to stop watching.
        """
        path = Path(path).expanduser().resolve()
        with self._lock:
            if path in self._watched:
                del self._watched[path]
                # Cancel any pending debounce timer
                if path in self._debounce_timers:
                    self._debounce_timers[path].cancel()
                    del self._debounce_timers[path]
                _logger.info("Stopped watching config file: %s", path)

    def start(self) -> None:
        """Start watching for config changes.

        This method is non-blocking. It starts a background thread for file
        system watching and installs a SIGHUP handler for manual reload triggers.

        Safe to call multiple times; subsequent calls are no-ops.
        """
        with self._lock:
            if self._started:
                _logger.debug("ConfigWatcher already started")
                return

            self._stop_event.clear()
            self._started = True

        # Initial load of all watched configs
        self._load_all_configs()

        # Start file system observer
        self._start_observer()

        # Install SIGHUP handler
        self._install_sighup_handler()

        _logger.info("ConfigWatcher started (debounce=%.1fs)", self._debounce_seconds)

    def stop(self) -> None:
        """Stop watching for config changes.

        Stops the file system observer, cancels pending timers, removes the
        SIGHUP handler, and waits for the observer thread to finish.

        Safe to call multiple times; subsequent calls are no-ops.
        """
        with self._lock:
            if not self._started:
                return

            self._stop_event.set()
            self._started = False

        # Stop the file system observer
        self._stop_observer()

        # Remove SIGHUP handler
        self._uninstall_sighup_handler()

        # Cancel all pending debounce timers
        for timer in list(self._debounce_timers.values()):
            timer.cancel()
        self._debounce_timers.clear()

        _logger.info("ConfigWatcher stopped")

    def reload_now(self, path: Path | str | None = None) -> None:
        """Immediately reload config(s), bypassing debounce.

        Args:
            path: Specific config path to reload, or None to reload all.
        """
        if path is not None:
            path = Path(path).expanduser().resolve()
            with self._lock:
                if path in self._watched:
                    self._reload_config(path)
        else:
            self._load_all_configs()

    def get_current_config(self, config_type: str) -> Any | None:
        """Get the current config instance for a given type.

        Args:
            config_type: Type identifier ('agent' or 'daemon').

        Returns:
            Current config instance, or None if not loaded yet.
        """
        with self._lock:
            for watched in self._watched.values():
                if watched.config_type == config_type:
                    return watched.current_config
        return None

    def get_reload_history(self, limit: int | None = None) -> list[ReloadAuditEntry]:
        """Get reload history from the audit log.

        Args:
            limit: Maximum entries to return (None for all).

        Returns:
            List of audit entries, most recent first.
            Returns empty list if audit logging is disabled.
        """
        if self._audit_log is None:
            return []
        return self._audit_log.get_history(limit=limit)

    @property
    def audit_log(self) -> ReloadAuditLog | None:
        """Get the audit log instance (None if disabled)."""
        return self._audit_log

    # -----------------------------------------------------------------------
    # Private methods
    # -----------------------------------------------------------------------

    def _load_all_configs(self) -> None:
        """Load all watched configs initially."""
        with self._lock:
            for path in list(self._watched.keys()):
                self._reload_config(path)

    def _reload_config(self, path: Path) -> None:
        """Reload a single config file and invoke callbacks.

        If a validator is configured for the watched config, it will be called
        with the loaded config. If validation fails, the config swap is skipped
        and an error is logged.
        """
        with self._lock:
            watched = self._watched.get(path)
            if watched is None:
                return

            old_config = watched.current_config
            error: Exception | None = None
            new_config: Any = None

            try:
                new_config = watched.loader()

                # Run validator before swapping if configured
                if watched.validator is not None:
                    try:
                        is_valid = watched.validator(new_config)
                        if not is_valid:
                            raise ValueError("Config validation returned False")
                    except Exception as validation_error:
                        error = validation_error
                        _logger.error(
                            "Validation failed for %s config from %s: %s",
                            watched.config_type,
                            path,
                            validation_error,
                        )
                        # Skip swap on validation failure
                        new_config = None

                # Only swap if validation passed (or no validator)
                if error is None:
                    watched.current_config = new_config
                    watched.last_modified = path.stat().st_mtime if path.exists() else 0.0
                    _logger.info(
                        "Reloaded %s config from %s",
                        watched.config_type,
                        path,
                    )
            except Exception as e:
                error = e
                _logger.exception(
                    "Failed to reload %s config from %s: %s",
                    watched.config_type,
                    path,
                    e,
                )

            # Record audit entry
            audit_entry = None
            if self._audit_log is not None:
                audit_entry = self._audit_log.record(
                    config_type=watched.config_type,
                    config_path=path,
                    old_config=old_config,
                    new_config=new_config,
                    error=error,
                )

            event = ConfigReloadEvent(
                config_type=watched.config_type,
                config_path=path,
                old_config=old_config,
                new_config=new_config,
                error=error,
                audit_entry=audit_entry,
            )

            # Invoke callbacks (copy to avoid modification during iteration)
            callbacks = list(watched.callbacks)
            for callback in callbacks:
                try:
                    callback(event)
                except Exception:
                    _logger.exception(
                        "Error in config reload callback for %s",
                        watched.config_type,
                    )

    def _on_file_modified(self, path: Path) -> None:
        """Handle file modification event from watchdog."""
        with self._lock:
            watched = self._watched.get(path)
            if watched is None:
                return

            # Check if file actually changed (mtime comparison)
            try:
                current_mtime = path.stat().st_mtime
                if current_mtime <= watched.last_modified:
                    return  # No actual change
            except OSError:
                return  # File might have been deleted

            # Cancel any existing debounce timer
            if path in self._debounce_timers:
                self._debounce_timers[path].cancel()

            # Schedule debounced reload
            timer = threading.Timer(
                self._debounce_seconds,
                self._debounced_reload,
                args=(path,),
            )
            self._debounce_timers[path] = timer
            timer.daemon = True
            timer.start()

            _logger.debug(
                "Scheduled debounced reload for %s in %.1fs",
                path,
                self._debounce_seconds,
            )

    def _debounced_reload(self, path: Path) -> None:
        """Execute debounced reload."""
        if self._stop_event.is_set():
            return

        with self._lock:
            if path in self._debounce_timers:
                del self._debounce_timers[path]

        self._reload_config(path)

    def _start_observer(self) -> None:
        """Start the watchdog file system observer."""
        try:
            from watchdog.events import FileSystemEvent, FileSystemEventHandler
            from watchdog.observers import Observer
        except ImportError:
            _logger.warning(
                "watchdog not installed; file system watching disabled. "
                "Install with: pip install watchdog"
            )
            return

        class ConfigFileHandler(FileSystemEventHandler):
            """Handler for file system events on config files."""

            def __init__(self, watcher: ConfigWatcher):
                self._watcher = watcher
                self._watched_paths: set[Path] = set()

            def add_path(self, path: Path) -> None:
                self._watched_paths.add(path)

            def on_modified(self, event: FileSystemEvent) -> None:
                if event.is_directory:
                    return
                path = Path(event.src_path).resolve()
                if path in self._watched_paths:
                    self._watcher._on_file_modified(path)

            def on_created(self, event: FileSystemEvent) -> None:
                # Handle file creation (e.g., after editor atomic save)
                if event.is_directory:
                    return
                path = Path(event.src_path).resolve()
                if path in self._watched_paths:
                    self._watcher._on_file_modified(path)

        handler = ConfigFileHandler(self)

        with self._lock:
            # Group watched files by parent directory
            dirs_to_watch: dict[Path, set[Path]] = {}
            for path in self._watched:
                parent = path.parent
                if parent not in dirs_to_watch:
                    dirs_to_watch[parent] = set()
                dirs_to_watch[parent].add(path)
                handler.add_path(path)

        self._observer = Observer()
        for dir_path, files in dirs_to_watch.items():
            if dir_path.exists():
                self._observer.schedule(handler, str(dir_path), recursive=False)
                _logger.debug("Watching directory: %s (for %d files)", dir_path, len(files))

        self._observer.daemon = True
        self._observer.start()
        _logger.debug("Watchdog observer started")

    def _stop_observer(self) -> None:
        """Stop the watchdog file system observer."""
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=5.0)
            self._observer = None
            _logger.debug("Watchdog observer stopped")

    def _install_sighup_handler(self) -> None:
        """Install SIGHUP handler for manual reload trigger."""
        if self._sighup_handler_installed:
            return

        def handle_sighup(_signum: int, frame: Any) -> None:
            _logger.info("Received SIGHUP, triggering config reload")
            self.reload_now()

        try:
            self._original_sighup_handler = signal.getsignal(signal.SIGHUP)
            signal.signal(signal.SIGHUP, handle_sighup)
            self._sighup_handler_installed = True
            _logger.debug("SIGHUP handler installed")
        except (ValueError, OSError) as e:
            # SIGHUP not available on this platform (e.g., Windows)
            _logger.debug("Could not install SIGHUP handler: %s", e)

    def _uninstall_sighup_handler(self) -> None:
        """Remove SIGHUP handler."""
        if not self._sighup_handler_installed:
            return

        try:
            if self._original_sighup_handler is not None:
                signal.signal(signal.SIGHUP, self._original_sighup_handler)
            self._sighup_handler_installed = False
            self._original_sighup_handler = None
            _logger.debug("SIGHUP handler removed")
        except (ValueError, OSError):
            pass  # Ignore errors during cleanup

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Context manager exit - stops the watcher."""
        self.stop()


# ---------------------------------------------------------------------------
# Convenience functions for standalone config watching
# ---------------------------------------------------------------------------

# Global singleton watcher for standalone usage
_global_watcher: ConfigWatcher | None = None
_global_watcher_lock = threading.Lock()


def start_config_watcher(
    agent_config_path: Path | str | None = None,
    daemon_config_path: Path | str | None = None,
    callback: ConfigReloadCallback | None = None,
    debounce_seconds: float = DEFAULT_DEBOUNCE_SECONDS,
) -> ConfigWatcher:
    """Start a global config watcher for agent and daemon config files.

    This is a convenience function for standalone usage (e.g., in scripts
    or non-daemon applications). For daemon integration, use
    `SootheDaemon.enable_config_reload()` instead.

    Args:
        agent_config_path: Path to agent config.yml (defaults to ~/.soothe/config/config.yml).
        daemon_config_path: Path to daemon.yml (defaults to ~/.soothe/config/daemon.yml).
        callback: Optional callback to invoke when either config is reloaded.
        debounce_seconds: Minimum seconds between reloads for the same file.

    Returns:
        The started ConfigWatcher instance.

    Raises:
        RuntimeError: If a watcher is already running.
    """
    global _global_watcher

    with _global_watcher_lock:
        if _global_watcher is not None and _global_watcher.is_running:
            raise RuntimeError("Config watcher already running; call stop_config_watcher() first")

        agent_path = Path(agent_config_path or DEFAULT_CONFIG_PATH)
        daemon_path = Path(daemon_config_path or DEFAULT_DAEMON_CONFIG_PATH)

        _global_watcher = ConfigWatcher(debounce_seconds=debounce_seconds)

        # Watch agent config if file exists
        if agent_path.exists():
            _global_watcher.watch_config(
                path=agent_path,
                config_type="agent",
                loader=lambda: _load_agent_config(agent_path),
                callback=callback,
            )

        # Watch daemon config if file exists
        if daemon_path.exists():
            _global_watcher.watch_config(
                path=daemon_path,
                config_type="daemon",
                loader=lambda: _load_daemon_config(daemon_path),
                callback=callback,
            )

        _global_watcher.start()
        _logger.info("Global config watcher started")
        return _global_watcher


def stop_config_watcher() -> None:
    """Stop the global config watcher if running.

    Safe to call multiple times; subsequent calls are no-ops.
    """
    global _global_watcher

    with _global_watcher_lock:
        if _global_watcher is None:
            return

        _global_watcher.stop()
        _global_watcher = None
        _logger.info("Global config watcher stopped")


def get_config_watcher() -> ConfigWatcher | None:
    """Get the current global config watcher instance.

    Returns:
        The ConfigWatcher instance if running, or None.
    """
    with _global_watcher_lock:
        return _global_watcher


def _load_agent_config(path: Path) -> Any:
    """Load agent config from YAML file with env expansion."""
    from soothe_nano.config.settings import SootheConfig

    return SootheConfig.from_yaml_file(str(path))


def _load_daemon_config(path: Path) -> Any:
    """Load daemon config from YAML file."""
    # Import locally to avoid circular dependency
    import importlib

    module = importlib.import_module("soothe_daemon.config.settings")
    daemon_config_cls = getattr(module, "SootheDaemonConfig")
    return daemon_config_cls.from_yaml_file(str(path))


# ---------------------------------------------------------------------------
# __all__ export list
# ---------------------------------------------------------------------------

__all__ = [
    "DEFAULT_CONFIG_PATH",
    "DEFAULT_DAEMON_CONFIG_PATH",
    "DEFAULT_DEBOUNCE_SECONDS",
    "ConfigReloadEvent",
    "ConfigReloadCallback",
    "WatchedConfig",
    "ConfigWatcher",
    "start_config_watcher",
    "stop_config_watcher",
    "get_config_watcher",
]
