"""Plugin system exception classes.

This module defines the exception hierarchy for the plugin system,
providing specific error types for each failure phase.
"""


class PluginError(Exception):
    """Base exception for plugin system errors.

    All plugin-related exceptions inherit from this base class,
    allowing callers to catch all plugin errors with a single except clause.

    Attributes:
        message: Human-readable error description.
        plugin_name: Name of the plugin that caused the error (if applicable).
    """

    def __init__(self, message: str, plugin_name: str | None = None) -> None:
        """Initialize plugin error.

        Args:
            message: Human-readable error description.
            plugin_name: Name of the plugin that caused the error.
        """
        self.message = message
        self.plugin_name = plugin_name
        super().__init__(message)

    def __str__(self) -> str:
        """Return string representation of the error."""
        if self.plugin_name:
            return f"[{self.plugin_name}] {self.message}"
        return self.message


class DiscoveryError(PluginError):
    """Error during plugin discovery.

    Raised when a plugin cannot be found or loaded from its source
    (entry point, config declaration, or filesystem).

    Examples:
        - Entry point references non-existent module
        - Config-declared plugin has invalid module path
        - Filesystem plugin directory is malformed
    """


class ValidationError(PluginError):
    """Error during manifest validation.

    Raised when a plugin's manifest fails validation checks.

    Examples:
        - Missing required manifest fields (name, version, description)
        - Invalid version string format
        - Unknown trust level value
    """


class DependencyError(PluginError):
    """Error during dependency resolution.

    Raised when a plugin's dependencies cannot be satisfied.

    Examples:
        - Required library not installed
        - Library version constraint not satisfied
        - Required configuration key missing
    """


class InitializationError(PluginError):
    """Error during plugin initialization.

    Raised when a plugin's on_load() hook fails.

    Examples:
        - Plugin initialization hook raises exception
        - Required resource unavailable
        - Plugin-specific validation fails
    """


class ToolCreationError(PluginError):
    """Error during tool creation.

    Raised when a plugin fails to create a tool instance.

    Examples:
        - Tool factory function raises exception
        - Tool configuration invalid
        - Tool dependencies missing
    """


class SubagentCreationError(PluginError):
    """Error during subagent creation.

    Raised when a plugin fails to create a subagent instance.

    Examples:
        - Subagent factory function raises exception
        - Model creation fails
        - Subagent configuration invalid
    """
