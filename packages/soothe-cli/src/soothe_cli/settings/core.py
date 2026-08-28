"""Global settings and environment detection for Soothe."""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path

from soothe_sdk.paths import SOOTHE_HOME

from soothe_cli._version import (
    is_editable_install as _is_editable_install,
)
from soothe_cli.settings.bootstrap import _bootstrap_start_path, _ensure_bootstrap, _singleton_lock
from soothe_cli.settings.shell_allow import parse_shell_allow_list
from soothe_cli.settings.skills_dirs import _parse_extra_skills_dirs, _read_config_yaml_skills_dirs

__all__ = ["_is_editable_install"]

logger = logging.getLogger(__name__)


@dataclass
class Settings:
    """Global settings and environment detection for Soothe."""

    openai_api_key: str | None
    """OpenAI API key if available."""

    anthropic_api_key: str | None
    """Anthropic API key if available."""

    google_api_key: str | None
    """Google API key if available."""

    nvidia_api_key: str | None
    """NVIDIA API key if available."""

    tavily_api_key: str | None
    """Tavily API key if available."""

    google_cloud_project: str | None
    """Google Cloud project ID for VertexAI authentication."""

    model_name: str | None = None
    """Currently active model name, set after model creation."""

    model_provider: str | None = None
    """Provider identifier (e.g., `openai`, `anthropic`, `google_genai`)."""

    model_context_limit: int | None = None
    """Maximum input token count from the model profile."""

    project_root: Path | None = None
    """Current project root directory, or `None` if not in a git project."""

    shell_allow_list: list[str] | None = None
    """Shell commands that don't require user approval."""

    extra_skills_dirs: list[Path] | None = None
    """Extra directories added to the skill path containment allowlist."""

    @classmethod
    def from_environment(cls, *, start_path: Path | None = None) -> Settings:
        """Create settings by detecting the current environment."""
        # Detect API keys (normalize empty strings to None).
        from soothe_cli.model_config import resolve_env_var

        openai_key = resolve_env_var("OPENAI_API_KEY")
        anthropic_key = resolve_env_var("ANTHROPIC_API_KEY")
        google_key = resolve_env_var("GOOGLE_API_KEY")
        nvidia_key = resolve_env_var("NVIDIA_API_KEY")
        tavily_key = resolve_env_var("TAVILY_API_KEY")
        google_cloud_project = resolve_env_var("GOOGLE_CLOUD_PROJECT")

        from soothe_cli._env_vars import (
            EXTRA_SKILLS_DIRS,
            SHELL_ALLOW_LIST,
        )

        # Detect project
        from soothe_cli.project_utils import find_project_root

        project_root = find_project_root(start_path)

        # Parse shell command allow-list from environment
        # Format: comma-separated list of commands (e.g., "ls,cat,grep,pwd")

        shell_allow_list_str = os.environ.get(SHELL_ALLOW_LIST)
        shell_allow_list = parse_shell_allow_list(shell_allow_list_str)

        # Parse extra skill containment roots from env var or cli.yml.
        # These extend the path allowlist for load_skill_content but do not
        # add new skill discovery locations.
        extra_skills_dirs = _parse_extra_skills_dirs(
            os.environ.get(EXTRA_SKILLS_DIRS),
            _read_config_yaml_skills_dirs(),
        )

        return cls(
            openai_api_key=openai_key,
            anthropic_api_key=anthropic_key,
            google_api_key=google_key,
            nvidia_api_key=nvidia_key,
            tavily_api_key=tavily_key,
            google_cloud_project=google_cloud_project,
            project_root=project_root,
            shell_allow_list=shell_allow_list,
            extra_skills_dirs=extra_skills_dirs,
        )

    def reload_from_environment(self, *, start_path: Path | None = None) -> list[str]:
        """Reload selected settings from environment variables and project files.

        This refreshes only fields that are expected to change at runtime
        (API keys, Google Cloud project, project root, and shell allow-list).

        Runtime model state (`model_name`, `model_provider`,
        `model_context_limit`) is intentionally preserved — it is not in
        `reloadable_fields` and is never touched by this method.

        !!! note

        `.env` files are loaded with `override=False`, so shell-exported
        variables always take precedence. To override a shell-exported key
        from `.env`, use the `SOOTHE_` prefix (e.g.
        `SOOTHE_OPENAI_API_KEY`).

        Args:
        start_path: Directory to start project detection from (defaults to cwd).

        Returns:
        A list of human-readable change descriptions.
        """
        from soothe_cli.settings.bootstrap import _load_dotenv

        _load_dotenv(start_path=start_path)

        api_key_fields = {
            "openai_api_key",
            "anthropic_api_key",
            "google_api_key",
            "nvidia_api_key",
            "tavily_api_key",
        }
        """Fields that hold API keys — used to mask values in change reports
        so secrets are not logged as plaintext."""

        reloadable_fields = (
            "openai_api_key",
            "anthropic_api_key",
            "google_api_key",
            "nvidia_api_key",
            "tavily_api_key",
            "google_cloud_project",
            "project_root",
            "shell_allow_list",
            "extra_skills_dirs",
        )
        """Fields refreshed on `/reload`.

        Runtime model state (`model_name`, `model_provider`, `model_context_limit`)
        is intentionally excluded — it is set once and should not change across
        reloads.
        """

        previous = {field: getattr(self, field) for field in reloadable_fields}

        from soothe_cli._env_vars import (
            EXTRA_SKILLS_DIRS,
            SHELL_ALLOW_LIST,
        )

        try:
            shell_allow_list = parse_shell_allow_list(os.environ.get(SHELL_ALLOW_LIST))
        except ValueError:
            logger.warning(
                "Invalid %s during reload; keeping previous value",
                SHELL_ALLOW_LIST,
            )
            shell_allow_list = previous["shell_allow_list"]

        try:
            from soothe_cli.project_utils import find_project_root

            project_root = find_project_root(start_path)
        except OSError:
            logger.warning("Could not detect project root during reload; keeping previous value")
            project_root = previous["project_root"]

        from soothe_cli.model_config import resolve_env_var

        refreshed = {
            "openai_api_key": resolve_env_var("OPENAI_API_KEY"),
            "anthropic_api_key": resolve_env_var("ANTHROPIC_API_KEY"),
            "google_api_key": resolve_env_var("GOOGLE_API_KEY"),
            "nvidia_api_key": resolve_env_var("NVIDIA_API_KEY"),
            "tavily_api_key": resolve_env_var("TAVILY_API_KEY"),
            "google_cloud_project": resolve_env_var("GOOGLE_CLOUD_PROJECT"),
            "project_root": project_root,
            "shell_allow_list": shell_allow_list,
            "extra_skills_dirs": _parse_extra_skills_dirs(
                os.environ.get(EXTRA_SKILLS_DIRS),
                _read_config_yaml_skills_dirs(),
            ),
        }

        for field, value in refreshed.items():
            setattr(self, field, value)

        def _display(field: str, value: object) -> str:
            if field in api_key_fields:
                return "set" if value else "unset"
            return str(value)

        changes: list[str] = []
        for field in reloadable_fields:
            old_value = previous[field]
            new_value = refreshed[field]
            if old_value != new_value:
                changes.append(
                    f"{field}: {_display(field, old_value)} -> {_display(field, new_value)}"
                )
        return changes

    @property
    def has_anthropic(self) -> bool:
        """Check if Anthropic API key is configured."""
        return self.anthropic_api_key is not None

    @property
    def has_google(self) -> bool:
        """Check if Google API key is configured."""
        return self.google_api_key is not None

    @property
    def has_vertex_ai(self) -> bool:
        """Check if VertexAI is available (Google Cloud project set, no API key).

        VertexAI uses Application Default Credentials (ADC) for authentication,
        so if GOOGLE_CLOUD_PROJECT is set and GOOGLE_API_KEY is not, we assume
        VertexAI.
        """
        return self.google_cloud_project is not None and self.google_api_key is None

    @staticmethod
    def _is_valid_agent_name(agent_name: str) -> bool:
        """Validate to prevent invalid filesystem paths and security issues.

        Returns:
        True if the agent name is valid, False otherwise.
        """
        if not agent_name or not agent_name.strip():
            return False
        # Allow only alphanumeric, hyphens, underscores, and whitespace
        return bool(re.match(r"^[a-zA-Z0-9_\-\s]+$", agent_name))

    def get_agent_dir(self, agent_name: str) -> Path:
        """Get the global agent directory path.

        Args:
        agent_name: Name of the agent

        Returns:
        Path to ~/SOOTHE_HOME/{agent_name}

        Raises:
        ValueError: If the agent name contains invalid characters.
        """
        if not self._is_valid_agent_name(agent_name):
            msg = (
                f"Invalid agent name: {agent_name!r}. Agent names can only "
                "contain letters, numbers, hyphens, underscores, and spaces."
            )
            raise ValueError(msg)
        return Path(SOOTHE_HOME) / agent_name


def _get_settings() -> Settings:
    """Return the lazily-initialized global `Settings` instance.

    Ensures bootstrap has run before constructing settings. The result is cached
    in `globals()["settings"]` so subsequent access — including
    `from config import settings` in other modules — resolves instantly.

    Returns:
    The global `Settings` singleton.
    """
    cached = globals().get("settings")
    if cached is not None:
        return cached
    with _singleton_lock:
        cached = globals().get("settings")
        if cached is not None:
            return cached
        _ensure_bootstrap()
        try:
            inst = Settings.from_environment(start_path=_bootstrap_start_path)
        except Exception:
            logger.exception(
                "Failed to initialize settings from environment (start_path=%s)",
                _bootstrap_start_path,
            )
            raise
        globals()["settings"] = inst
        return inst
