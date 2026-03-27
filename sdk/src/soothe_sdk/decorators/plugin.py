"""@plugin decorator for defining Soothe plugins.

This decorator marks a class as a Soothe plugin and automatically attaches
the manifest metadata and helper methods.
"""

from collections.abc import Callable
from typing import Any

from soothe_sdk.types.manifest import PluginManifest


def plugin(
    name: str,
    version: str,
    description: str,
    author: str = "",
    homepage: str = "",
    repository: str = "",
    license: str = "MIT",
    dependencies: list[str] | None = None,
    python_version: str = ">=3.11",
    soothe_version: str = ">=0.1.0",
    trust_level: str = "standard",
) -> Callable[[type], type]:
    """Decorator that marks a class as a Soothe plugin.

    This decorator attaches a PluginManifest to the class and adds helper
    methods for extracting tools and subagents.

    Args:
        name: Unique plugin identifier (lowercase, hyphenated).
        version: Semantic version string (e.g., "1.0.0").
        description: Human-readable description.
        author: Author name or organization.
        homepage: Project homepage URL.
        repository: Source repository URL.
        license: License identifier (SPDX format).
        dependencies: List of library dependencies (PEP 440 format).
        python_version: Python version constraint (PEP 440).
        soothe_version: Soothe version constraint (PEP 440).
        trust_level: Trust level ("built-in", "trusted", "standard", "untrusted").

    Returns:
        Decorated class with manifest and helper methods.

    Example:
        ```python
        @plugin(
            name="my-plugin",
            version="1.0.0",
            description="My awesome plugin",
            dependencies=["langchain>=0.1.0"],
        )
        class MyPlugin:
            @tool(name="greet", description="Greet someone")
            def greet(self, name: str) -> str:
                return f"Hello, {name}!"
        ```
    """

    def decorator(cls: type) -> type:
        # Create and attach manifest
        cls._plugin_manifest = PluginManifest(
            name=name,
            version=version,
            description=description,
            author=author,
            homepage=homepage,
            repository=repository,
            license=license,
            dependencies=dependencies or [],
            python_version=python_version,
            soothe_version=soothe_version,
            trust_level=trust_level,
        )

        # Add manifest property
        @property
        def manifest(self) -> PluginManifest:
            """Return the plugin manifest."""
            return self._plugin_manifest

        cls.manifest = manifest

        # Add get_tools() method to extract @tool decorated methods
        def get_tools(self) -> list[Any]:
            """Extract all tools from this plugin.

            Returns:
                List of tool functions with _is_tool metadata.
            """
            tools = []
            for attr_name in dir(self):
                if attr_name.startswith("_"):
                    continue
                attr = getattr(self, attr_name)
                if callable(attr) and hasattr(attr, "_is_tool"):
                    tools.append(attr)
            return tools

        cls.get_tools = get_tools

        # Add get_subagents() method to extract @subagent decorated methods
        def get_subagents(self) -> list[Any]:
            """Extract all subagents from this plugin.

            Returns:
                List of subagent factory functions with _is_subagent metadata.
            """
            subagents = []
            for attr_name in dir(self):
                if attr_name.startswith("_"):
                    continue
                attr = getattr(self, attr_name)
                if callable(attr) and hasattr(attr, "_is_subagent"):
                    subagents.append(attr)
            return subagents

        cls.get_subagents = get_subagents

        return cls

    return decorator
