"""Filesystem factory and configuration for creating filesystem instances.

This module provides factory methods and configuration classes for creating
filesystem instances with proper security settings and validation.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .exceptions import FilesystemError, InvalidPathError
from .local import LocalFilesystem
from .unified import UnifiedFilesystem

if TYPE_CHECKING:
    from collections.abc import Mapping


class FilesystemType(Enum):
    """Types of filesystem implementations available."""

    LOCAL = auto()
    MEMORY = auto()
    REMOTE = auto()


@dataclass(frozen=True)
class PathValidationConfig:
    """Configuration for path validation rules.

    Attributes:
        block_traversal: Whether to block '..' path traversal sequences.
        block_absolute: Whether to block absolute paths outside workspace.
        block_home_expansion: Whether to block '~' home directory expansion.
        block_symlinks: Whether to block symbolic link following.
        allowed_extensions: Optional list of allowed file extensions.
        blocked_patterns: List of glob patterns to block.
        max_path_length: Maximum allowed path length in characters.
    """

    block_traversal: bool = True
    block_absolute: bool = True
    block_home_expansion: bool = True
    block_symlinks: bool = True
    allowed_extensions: frozenset[str] | None = None
    blocked_patterns: tuple[str, ...] = field(default_factory=tuple)
    max_path_length: int = 4096

    def __post_init__(self) -> None:
        """Validate configuration values."""
        if self.max_path_length < 1:
            raise ValueError("max_path_length must be positive")


@dataclass(frozen=True)
class SecurityConfig:
    """Security configuration for filesystem operations.

    Attributes:
        virtual_mode: Whether to sandbox paths to workspace.
        enforce_workspace_boundary: Whether to strictly enforce workspace bounds.
        require_explicit_paths: Whether to require explicit relative paths.
        audit_logging: Whether to log all filesystem operations.
        max_file_size_mb: Maximum file size in megabytes.
        max_files_per_operation: Maximum files per batch operation.
    """

    virtual_mode: bool = True
    enforce_workspace_boundary: bool = True
    require_explicit_paths: bool = False
    audit_logging: bool = False
    max_file_size_mb: int = 10
    max_files_per_operation: int = 1000

    def __post_init__(self) -> None:
        """Validate security configuration."""
        if self.max_file_size_mb < 1:
            raise ValueError("max_file_size_mb must be positive")
        if self.max_files_per_operation < 1:
            raise ValueError("max_files_per_operation must be positive")


@dataclass(frozen=True)
class FilesystemConfig:
    """Complete configuration for filesystem creation.

    This configuration class combines all settings needed to create
    a properly configured and secured filesystem instance.

    Attributes:
        workspace: Root workspace directory path.
        filesystem_type: Type of filesystem to create.
        security: Security configuration.
        path_validation: Path validation configuration.
        backup_enabled: Whether to enable automatic backups.
        backup_dir: Directory for backup files.
        cache_enabled: Whether to enable path caching.
        cache_size: Maximum number of cached paths.
        encoding: Default file encoding.
        follow_gitignore: Whether to respect .gitignore files.
    """

    workspace: Path = field(default_factory=lambda: Path(os.getcwd()))
    filesystem_type: FilesystemType = FilesystemType.LOCAL
    security: SecurityConfig = field(default_factory=SecurityConfig)
    path_validation: PathValidationConfig = field(default_factory=PathValidationConfig)
    backup_enabled: bool = True
    backup_dir: Path = field(default_factory=lambda: Path(".backups"))
    cache_enabled: bool = False
    cache_size: int = 1000
    encoding: str = "utf-8"
    follow_gitignore: bool = True

    def __post_init__(self) -> None:
        """Validate and normalize configuration."""
        # Ensure workspace is absolute and resolved
        object.__setattr__(self, "workspace", Path(self.workspace).expanduser().resolve())

        # Ensure backup_dir is relative to workspace if not absolute
        backup = Path(self.backup_dir)
        if not backup.is_absolute():
            backup = self.workspace / backup
        object.__setattr__(self, "backup_dir", backup.resolve())

        # Validate workspace exists or can be created
        if not self.workspace.exists() and not self.workspace.parent.exists():
            raise InvalidPathError(
                f"Workspace parent directory does not exist: {self.workspace.parent}",
                path=str(self.workspace),
            )

    def to_dict(self) -> dict[str, Any]:
        """Convert configuration to dictionary."""
        return {
            "workspace": str(self.workspace),
            "filesystem_type": self.filesystem_type.name,
            "security": {
                "virtual_mode": self.security.virtual_mode,
                "enforce_workspace_boundary": self.security.enforce_workspace_boundary,
                "require_explicit_paths": self.security.require_explicit_paths,
                "audit_logging": self.security.audit_logging,
                "max_file_size_mb": self.security.max_file_size_mb,
                "max_files_per_operation": self.security.max_files_per_operation,
            },
            "path_validation": {
                "block_traversal": self.path_validation.block_traversal,
                "block_absolute": self.path_validation.block_absolute,
                "block_home_expansion": self.path_validation.block_home_expansion,
                "block_symlinks": self.path_validation.block_symlinks,
                "allowed_extensions": (
                    list(self.path_validation.allowed_extensions)
                    if self.path_validation.allowed_extensions
                    else None
                ),
                "blocked_patterns": list(self.path_validation.blocked_patterns),
                "max_path_length": self.path_validation.max_path_length,
            },
            "backup_enabled": self.backup_enabled,
            "backup_dir": str(self.backup_dir),
            "cache_enabled": self.cache_enabled,
            "cache_size": self.cache_size,
            "encoding": self.encoding,
            "follow_gitignore": self.follow_gitignore,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> FilesystemConfig:
        """Create configuration from dictionary."""
        security_data = data.get("security", {})
        path_validation_data = data.get("path_validation", {})

        security = SecurityConfig(
            virtual_mode=security_data.get("virtual_mode", True),
            enforce_workspace_boundary=security_data.get("enforce_workspace_boundary", True),
            require_explicit_paths=security_data.get("require_explicit_paths", False),
            audit_logging=security_data.get("audit_logging", False),
            max_file_size_mb=security_data.get("max_file_size_mb", 10),
            max_files_per_operation=security_data.get("max_files_per_operation", 1000),
        )

        allowed_exts = path_validation_data.get("allowed_extensions")
        path_validation = PathValidationConfig(
            block_traversal=path_validation_data.get("block_traversal", True),
            block_absolute=path_validation_data.get("block_absolute", True),
            block_home_expansion=path_validation_data.get("block_home_expansion", True),
            block_symlinks=path_validation_data.get("block_symlinks", True),
            allowed_extensions=frozenset(allowed_exts) if allowed_exts else None,
            blocked_patterns=tuple(path_validation_data.get("blocked_patterns", [])),
            max_path_length=path_validation_data.get("max_path_length", 4096),
        )

        return cls(
            workspace=Path(data.get("workspace", os.getcwd())),
            filesystem_type=FilesystemType[data.get("filesystem_type", "LOCAL")],
            security=security,
            path_validation=path_validation,
            backup_enabled=data.get("backup_enabled", True),
            backup_dir=Path(data.get("backup_dir", ".backups")),
            cache_enabled=data.get("cache_enabled", False),
            cache_size=data.get("cache_size", 1000),
            encoding=data.get("encoding", "utf-8"),
            follow_gitignore=data.get("follow_gitignore", True),
        )

    @classmethod
    def secure(cls, workspace: str | Path) -> FilesystemConfig:
        """Create a secure configuration with all protections enabled.

        This is the recommended configuration for production use.
        All path traversal protections are enabled by default.

        Args:
            workspace: Root workspace directory.

        Returns:
            FilesystemConfig with maximum security settings.
        """
        return cls(
            workspace=Path(workspace),
            filesystem_type=FilesystemType.LOCAL,
            security=SecurityConfig(
                virtual_mode=True,
                enforce_workspace_boundary=True,
                require_explicit_paths=True,
                audit_logging=True,
                max_file_size_mb=10,
                max_files_per_operation=100,
            ),
            path_validation=PathValidationConfig(
                block_traversal=True,
                block_absolute=True,
                block_home_expansion=True,
                block_symlinks=True,
                allowed_extensions=None,
                blocked_patterns=("*.secret", "*.key", ".env*"),
                max_path_length=4096,
            ),
            backup_enabled=True,
            cache_enabled=False,
            follow_gitignore=True,
        )

    @classmethod
    def development(cls, workspace: str | Path) -> FilesystemConfig:
        """Create a development-friendly configuration.

        This configuration is suitable for development environments
        with relaxed security settings for convenience.

        Args:
            workspace: Root workspace directory.

        Returns:
            FilesystemConfig with development-friendly settings.
        """
        return cls(
            workspace=Path(workspace),
            filesystem_type=FilesystemType.LOCAL,
            security=SecurityConfig(
                virtual_mode=True,
                enforce_workspace_boundary=True,
                require_explicit_paths=False,
                audit_logging=False,
                max_file_size_mb=50,
                max_files_per_operation=1000,
            ),
            path_validation=PathValidationConfig(
                block_traversal=True,
                block_absolute=False,
                block_home_expansion=False,
                block_symlinks=False,
                allowed_extensions=None,
                blocked_patterns=(),
                max_path_length=8192,
            ),
            backup_enabled=True,
            cache_enabled=True,
            follow_gitignore=False,
        )


class FilesystemFactory:
    """Factory for creating filesystem instances with proper configuration.

    This factory ensures that all filesystem instances are created with
    appropriate security settings and path validation.

    Example:
        >>> config = FilesystemConfig.secure("/workspace")
        >>> factory = FilesystemFactory(config)
        >>> fs = factory.create_filesystem()
        >>> result = fs.read("config.json")

        >>> # Or use the convenience method
        >>> fs = FilesystemFactory.create_secure("/workspace")
    """

    def __init__(self, config: FilesystemConfig | None = None) -> None:
        """Initialize the factory with configuration.

        Args:
            config: Filesystem configuration. If None, uses secure defaults
                   with current working directory as workspace.
        """
        self._config = config or FilesystemConfig.secure(os.getcwd())

    @property
    def config(self) -> FilesystemConfig:
        """Get the factory configuration."""
        return self._config

    def create_filesystem(self) -> UnifiedFilesystem:
        """Create a filesystem instance based on configuration.

        Returns:
            Configured UnifiedFilesystem instance.

        Raises:
            FilesystemError: If filesystem creation fails.
            InvalidPathError: If workspace path is invalid.
        """
        try:
            if self._config.filesystem_type == FilesystemType.LOCAL:
                return self._create_local_filesystem()
            elif self._config.filesystem_type == FilesystemType.MEMORY:
                return self._create_memory_filesystem()
            elif self._config.filesystem_type == FilesystemType.REMOTE:
                return self._create_remote_filesystem()
            else:
                raise FilesystemError(f"Unknown filesystem type: {self._config.filesystem_type}")
        except Exception as e:
            if isinstance(e, FilesystemError):
                raise
            raise FilesystemError(
                f"Failed to create filesystem: {e}",
                details={"workspace": str(self._config.workspace)},
            ) from e

    def _create_local_filesystem(self) -> LocalFilesystem:
        """Create a local filesystem instance."""
        return LocalFilesystem(
            workspace=self._config.workspace,
            virtual_mode=self._config.security.virtual_mode,
            max_file_size_mb=self._config.security.max_file_size_mb,
            backup_dir=self._config.backup_dir,
        )

    def _create_memory_filesystem(self) -> UnifiedFilesystem:
        """Create an in-memory filesystem instance."""
        # TODO: Implement MemoryFilesystem
        # For now, fall back to local filesystem with virtual mode
        return self._create_local_filesystem()

    def _create_remote_filesystem(self) -> UnifiedFilesystem:
        """Create a remote filesystem instance."""
        raise NotImplementedError("Remote filesystem not yet implemented")

    def create_with_validation(self, path_validator: Any) -> UnifiedFilesystem:
        """Create filesystem with custom path validator.

        Args:
            path_validator: Custom path validator instance.

        Returns:
            Configured UnifiedFilesystem with custom validation.
        """
        fs = self.create_filesystem()
        # Attach validator to filesystem if supported
        if hasattr(fs, "set_path_validator"):
            fs.set_path_validator(path_validator)
        return fs

    @classmethod
    def create_secure(cls, workspace: str | Path) -> UnifiedFilesystem:
        """Convenience method to create a secure filesystem.

        Args:
            workspace: Root workspace directory.

        Returns:
            Securely configured LocalFilesystem instance.
        """
        config = FilesystemConfig.secure(workspace)
        factory = cls(config)
        return factory.create_filesystem()

    @classmethod
    def create_development(cls, workspace: str | Path) -> UnifiedFilesystem:
        """Convenience method to create a development filesystem.

        Args:
            workspace: Root workspace directory.

        Returns:
            Development-friendly LocalFilesystem instance.
        """
        config = FilesystemConfig.development(workspace)
        factory = cls(config)
        return factory.create_filesystem()

    @classmethod
    def from_env(cls, prefix: str = "SOOTHE_FS_") -> FilesystemFactory:
        """Create factory from environment variables.

        Environment variables:
            {prefix}WORKSPACE: Workspace directory
            {prefix}VIRTUAL_MODE: Enable virtual mode (true/false)
            {prefix}MAX_FILE_SIZE_MB: Maximum file size in MB
            {prefix}BACKUP_ENABLED: Enable backups (true/false)
            {prefix}AUDIT_LOGGING: Enable audit logging (true/false)

        Args:
            prefix: Environment variable prefix.

        Returns:
            Configured FilesystemFactory instance.
        """
        workspace = os.environ.get(f"{prefix}WORKSPACE", os.getcwd())
        virtual_mode = os.environ.get(f"{prefix}VIRTUAL_MODE", "true").lower() == "true"
        max_file_size = int(os.environ.get(f"{prefix}MAX_FILE_SIZE_MB", "10"))
        backup_enabled = os.environ.get(f"{prefix}BACKUP_ENABLED", "true").lower() == "true"
        audit_logging = os.environ.get(f"{prefix}AUDIT_LOGGING", "false").lower() == "true"

        security = SecurityConfig(
            virtual_mode=virtual_mode,
            audit_logging=audit_logging,
            max_file_size_mb=max_file_size,
        )

        config = FilesystemConfig(
            workspace=Path(workspace),
            security=security,
            backup_enabled=backup_enabled,
        )

        return cls(config)


def create_filesystem(
    workspace: str | Path | None = None,
    *,
    virtual_mode: bool = True,
    max_file_size_mb: int = 10,
    backup_enabled: bool = True,
    secure: bool = True,
) -> UnifiedFilesystem:
    """Convenience function to create a filesystem instance.

    This is the simplest way to create a filesystem with common settings.

    Args:
        workspace: Root workspace directory. Defaults to current directory.
        virtual_mode: Whether to sandbox paths to workspace.
        max_file_size_mb: Maximum file size in megabytes.
        backup_enabled: Whether to enable automatic backups.
        secure: Whether to use secure defaults (recommended).

    Returns:
        Configured UnifiedFilesystem instance.

    Example:
        >>> fs = create_filesystem("/workspace", secure=True)
        >>> result = fs.read("config.json")
    """
    workspace = Path(workspace or os.getcwd()).resolve()

    if secure:
        config = FilesystemConfig.secure(workspace)
    else:
        config = FilesystemConfig(
            workspace=workspace,
            security=SecurityConfig(
                virtual_mode=virtual_mode,
                max_file_size_mb=max_file_size_mb,
            ),
            backup_enabled=backup_enabled,
        )

    factory = FilesystemFactory(config)
    return factory.create_filesystem()
