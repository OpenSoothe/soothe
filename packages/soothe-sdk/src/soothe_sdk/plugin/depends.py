"""Dependency helpers for declaring plugin dependencies.

This module provides helper functions for declaring library and configuration
dependencies in plugin manifests. These helpers are optional but provide
a more structured way to declare dependencies.

Example:
    ```python
    from soothe_sdk.plugin import library, plugin


    @plugin(
        name="my-plugin",
        version="1.0.0",
        description="My plugin",
        dependencies=[
            library("langchain", ">=0.1.0"),
            library("arxiv", ">=2.0.0"),
        ],
    )
    class MyPlugin:
        pass
    ```
"""


def library(name: str, version_constraint: str = "*") -> str:
    """Declare a library dependency.

    This helper constructs a PEP 440 dependency specifier for a Python package.

    Args:
        name: Package name (e.g., "langchain", "arxiv").
        version_constraint: Version constraint (e.g., ">=0.1.0", "~=2.1").

    Returns:
        PEP 440 dependency string (e.g., "langchain>=0.1.0").

    Example:
        ```python
        dependencies = [
            library("langchain", ">=0.1.0"),
            library("arxiv", ">=2.0.0"),
        ]
        ```
    """
    if version_constraint == "*":
        return name
    return f"{name}{version_constraint}"


# Note: Configuration dependencies are declared differently
# They will be validated at runtime by checking config paths
# Example: config_requirements=["providers.openai.api_key"]
# This is kept in the manifest, not as a dependency string
