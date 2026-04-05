"""Plugin discovery mechanisms.

This module implements three plugin discovery mechanisms:
1. Python entry points (soothe.plugins group)
2. Config-declared plugins (from SootheConfig.plugins)
3. Filesystem discovery (~/.soothe/plugins/)
"""

import importlib.metadata
import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from soothe.config.settings import SootheConfig

logger = logging.getLogger(__name__)


def _try_extract_plugin_name(module_path: str) -> str | None:
    """Attempt to extract plugin name from module path without full import.

    For entry point and filesystem discovery, tries to get the plugin
    name from the manifest so deduplication works by name rather than
    module path. Returns None if the manifest can't be loaded.
    """
    try:
        if ":" in module_path:
            module_name, class_name = module_path.split(":", 1)
        else:
            class_name = None
            module_name = module_path

        import importlib
        mod = importlib.import_module(module_name)
        if class_name and hasattr(mod, class_name):
            cls = getattr(mod, class_name)
            if hasattr(cls, "_plugin_manifest"):
                return cls._plugin_manifest.name
        # Fallback: look for any class with _plugin_manifest
        if class_name is None:
            for attr_name in dir(mod):
                if attr_name.endswith("Plugin") and not attr_name.startswith("_"):
                    cls = getattr(mod, attr_name)
                    if hasattr(cls, "_plugin_manifest"):
                        return cls._plugin_manifest.name
    except Exception:
        pass
    return None
    """Discover plugins from Python entry points.

    Scans the `soothe.plugins` entry point group for plugin declarations.

    Returns:
        List of module paths (e.g., ["my_package:MyPlugin", "other:Plugin"]).

    Example:
        ```python
        # In pyproject.toml:
        [project.entry-points."soothe.plugins"]
        my_plugin = "my_package:MyPlugin"

        # Discovery result:
        ["my_package:MyPlugin"]
        ```
    """
    plugins = []
    try:
        entry_points = importlib.metadata.entry_points(group="soothe.plugins")
        for ep in entry_points:
            module_path = ep.value
            plugins.append(module_path)
            logger.info("Discovered plugin '%s' from entry point: %s", ep.name, module_path)
    except Exception as e:
        logger.debug("No soothe.plugins entry points found: %s", e)

    return plugins


def discover_config_declared(config: "SootheConfig") -> list[tuple[str, dict]]:
    """Discover plugins declared in Soothe configuration.

    Args:
        config: Resolved Soothe configuration.

    Returns:
        List of (module_path, config_dict) tuples for enabled plugins.

    Example:
        ```yaml
        # In config.yml:
        plugins:
          - name: my-plugin
            enabled: true
            module: "my_package:MyPlugin"
            config:
              api_key: "${MY_API_KEY}"

        # Discovery result:
        [("my_package:MyPlugin", {"api_key": "..."})]
        ```
    """
    plugins = []

    if not hasattr(config, "plugins"):
        logger.debug("No plugins field in config")
        return plugins

    for plugin_config in config.plugins:
        if not plugin_config.enabled:
            logger.debug("Plugin '%s' is disabled", plugin_config.name)
            continue

        if not plugin_config.module:
            logger.warning("Plugin '%s' has no module path", plugin_config.name)
            continue

        plugins.append((plugin_config.module, plugin_config.config))
        logger.info("Discovered plugin '%s' from config: %s", plugin_config.name, plugin_config.module)

    return plugins


def discover_filesystem(base_dir: Path | None = None) -> list[str]:
    """Discover plugins from filesystem directory.

    Scans a directory for plugin directories containing plugin.py or __init__.py.

    Args:
        base_dir: Base directory for discovery. Defaults to ~/.soothe/plugins/

    Returns:
        List of module paths (e.g., ["my_plugin.plugin", "research"]).

    Directory structure:
        ```
        ~/.soothe/plugins/
          my_plugin/
            plugin.py  # Contains MyPlugin class
          research/
            __init__.py  # Contains ResearchPlugin class
        ```

    Example:
        ```python
        # Discovery result:
        ["my_plugin.plugin", "research"]
        ```
    """
    if base_dir is None:
        base_dir = Path.home() / ".soothe" / "plugins"

    base = base_dir.expanduser()

    if not base.is_dir():
        logger.debug("Plugin directory does not exist: %s", base)
        return []

    # Add plugin directory to sys.path so plugins can be imported
    plugin_dir_str = str(base)
    if plugin_dir_str not in sys.path:
        sys.path.insert(0, plugin_dir_str)
        logger.debug("Added plugin directory to sys.path: %s", plugin_dir_str)
        return []

    plugins = []

    for plugin_dir in base.iterdir():
        if not plugin_dir.is_dir():
            continue

        # Skip hidden directories
        if plugin_dir.name.startswith("."):
            continue

        # Look for plugin.py or __init__.py
        plugin_file = plugin_dir / "plugin.py"
        init_file = plugin_dir / "__init__.py"

        if plugin_file.exists():
            # plugin.py -> module_name.plugin
            module_path = f"{plugin_dir.name}.plugin"
            plugins.append(module_path)
            logger.info("Discovered plugin from filesystem: %s", module_path)
        elif init_file.exists():
            # __init__.py -> module_name
            module_path = plugin_dir.name
            plugins.append(module_path)
            logger.info("Discovered plugin from filesystem: %s", module_path)

    return plugins


def discover_all_plugins(config: "SootheConfig") -> dict[str, tuple[str, dict]]:
    """Run all discovery mechanisms and return plugin module paths.

    This function runs all discovery mechanisms and returns a dict
    mapping plugin names to (module_path, config_dict) tuples. Duplicate
    names are resolved later by the registry based on priority.

    Args:
        config: Soothe configuration.

    Returns:
        Dict mapping unique identifiers to (module_path, config_dict) tuples.
        The identifier is the module path for entry_points and filesystem,
        or the plugin name for config-declared plugins.

    Note:
        This function does NOT handle priority conflicts. The PluginRegistry
        is responsible for resolving conflicts when plugins are registered.
    """
    discovered = {}

    # Built-in subagent plugins (new module structure)
    for subagent_name in ["browser", "claude"]:
        module_path = f"soothe.subagents.{subagent_name}"
        discovered[subagent_name] = (module_path, {})
        logger.debug("Discovered built-in subagent plugin: %s", subagent_name)

    # Built-in tool plugins (new module structure)
    for tool_name in [
        "execution",
        "file_ops",
        "code_edit",
        "data",
        "datetime",
        "goals",
        "web_search",
        "research",
        "image",
        "audio",
        "video",
    ]:
        module_path = f"soothe.tools.{tool_name}"
        discovered[tool_name] = (module_path, {})
        logger.debug("Discovered built-in tool plugin: %s", tool_name)

    # Entry points (no config available)
    for module_path in discover_entry_points():
        name = _try_extract_plugin_name(module_path) or module_path
        discovered[name] = (module_path, {})

    # Config-declared (has config)
    for module_path, plugin_config in discover_config_declared(config):
        discovered[module_path] = (module_path, plugin_config)

    # Filesystem (no config available)
    for module_path in discover_filesystem():
        name = _try_extract_plugin_name(f"{module_path}:Plugin") or module_path
        discovered[name] = (module_path, {})

    logger.info("Discovered %s total plugins", len(discovered))
    return discovered
