"""Plugin loader with dependency resolution.

This module provides the PluginLoader class that handles dynamic plugin
loading, dependency checking, and instantiation.
"""

import importlib
import importlib.metadata
import logging
from typing import TYPE_CHECKING, Any

from packaging.requirements import Requirement

from soothe.plugin.exceptions import DependencyError, DiscoveryError, ValidationError
from soothe_sdk.types.manifest import PluginManifest

if TYPE_CHECKING:
    from soothe.config.settings import SootheConfig
    from soothe.plugin.registry import PluginRegistry

logger = logging.getLogger(__name__)


class PluginLoader:
    """Plugin loader with dependency resolution and instantiation.

    This class handles:
    - Dynamic module import and plugin class instantiation
    - Library dependency checking (pip packages)
    - Configuration dependency checking
    - Graceful error handling

    Attributes:
        registry: Plugin registry to register loaded plugins.
    """

    def __init__(self, registry: "PluginRegistry") -> None:
        """Initialize plugin loader.

        Args:
            registry: Plugin registry for registering loaded plugins.
        """
        self.registry = registry

    def load_plugin(
        self,
        module_path: str,
        config: "SootheConfig",
        plugin_config: dict[str, Any],  # noqa: ARG002
    ) -> Any:
        """Load a plugin from a module path.

        This method:
        1. Imports the module dynamically
        2. Extracts the plugin class
        3. Instantiates the plugin
        4. Returns the plugin instance

        Args:
            module_path: Python import path (e.g., "my_package:MyPlugin").
            config: Soothe configuration.
            plugin_config: Plugin-specific configuration dictionary.

        Returns:
            Loaded plugin instance.

        Raises:
            DiscoveryError: If module cannot be imported.
            DependencyError: If dependencies are not satisfied.
            InitializationError: If plugin instantiation fails.
        """
        try:
            # Parse module path
            if ":" not in module_path:
                msg = f"Invalid module path format: {module_path}. Expected 'module_path:ClassName'"
                raise DiscoveryError(
                    msg,
                )

            module_name, class_name = module_path.split(":", 1)

            # Import module
            logger.debug("Importing module: %s", module_name)
            module = importlib.import_module(module_name)

            # Get plugin class
            if not hasattr(module, class_name):
                msg = f"Module {module_name} has no class '{class_name}'"
                raise DiscoveryError(
                    msg,
                )

            plugin_class = getattr(module, class_name)

            # Check for manifest (plugin decorator was applied)
            if not hasattr(plugin_class, "_plugin_manifest"):
                msg = f"Class {class_name} is not a plugin (missing @plugin decorator)"
                raise DiscoveryError(
                    msg,
                )

            # Get manifest
            manifest: PluginManifest = plugin_class._plugin_manifest

            # Validate trust level
            self.validate_trust_level(manifest)

            # Resolve dependencies
            self.resolve_dependencies(manifest, config)

            # Instantiate plugin
            logger.info("Instantiating plugin: %s", manifest.name)
            return plugin_class()

        except DiscoveryError:
            raise
        except DependencyError:
            raise
        except ValidationError:
            raise
        except Exception as e:
            logger.exception("Failed to load plugin from %s", module_path)
            msg = f"Failed to load plugin: {e}"
            raise DiscoveryError(msg) from e

    def resolve_dependencies(
        self,
        manifest: PluginManifest,
        config: "SootheConfig",
    ) -> None:
        """Check if plugin dependencies are satisfied.

        Checks library dependencies (pip packages), configuration
        dependencies, and version constraints. If any required
        dependency is missing, raises an error.

        Args:
            manifest: Plugin manifest with dependency declarations.
            config: Soothe configuration.

        Raises:
            DependencyError: If required dependencies are not satisfied.
        """
        # Check library dependencies
        missing_libs = [
            dep_string for dep_string in manifest.dependencies if not self._check_library_dependency(dep_string)
        ]

        if missing_libs:
            msg = f"Missing library dependencies: {', '.join(missing_libs)}"
            raise DependencyError(
                msg,
                plugin_name=manifest.name,
            )

        # Check configuration dependencies
        missing_configs = [
            key for key in manifest.config_requirements if not self._check_config_dependency(key, config)
        ]

        if missing_configs:
            msg = f"Missing configuration dependencies: {', '.join(missing_configs)}"
            raise DependencyError(
                msg,
                plugin_name=manifest.name,
            )

        # Check Python version
        if not self._check_python_version(manifest.python_version):
            msg = f"Python version constraint not satisfied: {manifest.python_version}"
            raise DependencyError(
                msg,
                plugin_name=manifest.name,
            )

        # Check Soothe version
        if not self._check_soothe_version(manifest.soothe_version):
            msg = f"Soothe version constraint not satisfied: {manifest.soothe_version}"
            raise DependencyError(
                msg,
                plugin_name=manifest.name,
            )

        logger.debug("All dependencies satisfied for plugin '%s'", manifest.name)

    def _check_config_dependency(self, key: str, config: "SootheConfig") -> bool:
        """Check if a configuration dependency is satisfied.

        Supports dot-notation keys (e.g., "providers.openai.api_key")
        that traverse the SootheConfig object.

        Args:
            key: Dot-notation config key (e.g., "providers.openai.api_key").
            config: Soothe configuration instance.

        Returns:
            True if the key exists and has a non-empty value.
        """
        try:
            parts = key.split(".")
            value = config
            for part in parts:
                if not hasattr(value, part):
                    return False
                value = getattr(value, part)
            result = value is not None and value != ""
        except Exception:
            result = False
        return result

    def validate_trust_level(self, manifest: PluginManifest) -> None:
        """Validate plugin trust level.

        Untrusted plugins are rejected by default unless explicitly
        allowed via environment variable SOOTHE_ALLOW_UNTRUSTED_PLUGINS.

        Args:
            manifest: Plugin manifest to validate.

        Raises:
            ValidationError: If trust level is not permitted.
        """
        trust_level = manifest.trust_level

        # Always allow built-in, trusted, and standard
        if trust_level in ("built-in", "trusted", "standard"):
            return

        # Untrusted plugins require explicit opt-in
        if trust_level == "untrusted":
            import os

            allow_untrusted = os.environ.get("SOOTHE_ALLOW_UNTRUSTED_PLUGINS", "").lower() in ("true", "1", "yes")

            if not allow_untrusted:
                msg = (
                    f"Plugin '{manifest.name}' has trust_level='untrusted' which is "
                    f"blocked by default. Set SOOTHE_ALLOW_UNTRUSTED_PLUGINS=true to allow."
                )
                raise ValidationError(msg, plugin_name=manifest.name)

    def _check_library_dependency(self, dep_string: str) -> bool:
        """Check if a library dependency is satisfied.

        Args:
            dep_string: PEP 440 dependency string (e.g., "langchain>=0.1.0").

        Returns:
            True if library is installed and version constraint is satisfied.
        """
        try:
            req = Requirement(dep_string)
            version = importlib.metadata.version(req.name)

            if req.specifier and version not in req.specifier:
                logger.warning("Library %s version %s does not satisfy %s", req.name, version, req.specifier)
                return False

        except importlib.metadata.PackageNotFoundError:
            logger.debug("Library not installed: %s", dep_string)
            return False
        except Exception as e:
            logger.warning("Failed to check dependency '%s': %s", dep_string, e)
            return False

    def _check_python_version(self, constraint: str) -> bool:
        """Check if Python version constraint is satisfied.

        Args:
            constraint: PEP 440 version constraint (e.g., ">=3.11").

        Returns:
            True if constraint is satisfied.
        """
        import sys

        try:
            from packaging.specifiers import SpecifierSet

            python_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
            specifier = SpecifierSet(constraint)
        except Exception as e:
            logger.warning("Failed to check Python version constraint: %s", e)
            return True  # Assume satisfied on error
        else:
            return python_version in specifier

    def _check_soothe_version(self, constraint: str) -> bool:
        """Check if Soothe version constraint is satisfied.

        Args:
            constraint: PEP 440 version constraint (e.g., ">=0.1.0").

        Returns:
            True if constraint is satisfied.
        """
        try:
            from packaging.specifiers import SpecifierSet

            soothe_version = importlib.metadata.version("soothe")
            specifier = SpecifierSet(constraint)
        except importlib.metadata.PackageNotFoundError:
            # Soothe not installed as package (development mode)
            logger.debug("Soothe not installed as package, skipping version check")
            return True
        except Exception as e:
            logger.warning("Failed to check Soothe version constraint: %s", e)
            return True  # Assume satisfied on error
        else:
            return soothe_version in specifier
