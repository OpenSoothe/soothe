"""Exception types for the Soothe SDK."""


class PluginError(Exception):
    """Base error for plugin system."""

    pass


class DiscoveryError(PluginError):
    """Error during plugin discovery."""

    pass


class ValidationError(PluginError):
    """Error during manifest validation."""

    pass


class DependencyError(PluginError):
    """Error during dependency resolution."""

    pass


class InitializationError(PluginError):
    """Error during plugin initialization."""

    pass


class ToolCreationError(PluginError):
    """Error during tool creation."""

    pass


class SubagentCreationError(PluginError):
    """Error during subagent instance creation."""

    pass


class ConfigurationError(Exception):
    """Error in configuration validation or backend initialization."""

    pass
