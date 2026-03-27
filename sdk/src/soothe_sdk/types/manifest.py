"""Plugin manifest model for metadata declaration."""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


def _utc_now() -> datetime:
    """Get current UTC time."""
    return datetime.now(UTC)


class PluginManifest(BaseModel):
    """Complete plugin manifest.

    This is the single source of truth for plugin metadata,
    dependencies, and configuration requirements.

    Attributes:
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
        trust_level: Trust level for security.
        created_at: Manifest creation timestamp.
        updated_at: Last update timestamp.
    """

    model_config = ConfigDict(extra="forbid")

    # Core metadata
    name: str
    version: str
    description: str
    author: str = ""
    homepage: str = ""
    repository: str = ""
    license: str = "MIT"

    # Dependencies
    dependencies: list[str] = Field(default_factory=list)  # PEP 440 specifiers
    python_version: str = ">=3.11"
    soothe_version: str = ">=0.1.0"

    # Security
    trust_level: Literal["built-in", "trusted", "standard", "untrusted"] = "standard"

    # Metadata
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)
