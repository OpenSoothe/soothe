"""GeneratedAgentRegistry -- filesystem-based agent registry (RFC-0005) -- community edition."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from .models import AgentManifest

if TYPE_CHECKING:
    from deepagents.middleware.subagents import SubAgent

logger = logging.getLogger(__name__)


class GeneratedAgentRegistry:
    """Manages generated agent packages under a base directory.

    Each agent is a subdirectory containing ``manifest.yml`` (or
    ``manifest.json``) and ``system_prompt.md``.

    Args:
        base_dir: Root directory for generated agents
            (e.g. ``~/.soothe/generated_agents``).
    """

    def __init__(self, base_dir: Path) -> None:
        """Initialize the generated agent registry.

        Args:
            base_dir: Root directory for generated agents
                (e.g. ``~/.soothe/generated_agents``).
        """
        self._base_dir = Path(base_dir).expanduser().resolve()

    @property
    def base_dir(self) -> Path:
        """The base directory for generated agents."""
        return self._base_dir

    def list_agents(self) -> list[AgentManifest]:
        """Scan base_dir for ``*/manifest.yml`` and return parsed manifests.

        Returns:
            List of valid ``AgentManifest`` objects found.
        """
        manifests: list[AgentManifest] = []
        if not self._base_dir.is_dir():
            return manifests

        for manifest_path in self._base_dir.glob("*/manifest.yml"):
            try:
                manifest = self._load_manifest(manifest_path)
                if manifest:
                    manifests.append(manifest)
            except Exception:
                logger.warning("Failed to load manifest %s", manifest_path, exc_info=True)

        for manifest_path in self._base_dir.glob("*/manifest.json"):
            try:
                manifest = self._load_manifest_json(manifest_path)
                if manifest:
                    manifests.append(manifest)
            except Exception:
                logger.warning("Failed to load manifest %s", manifest_path, exc_info=True)

        return manifests

    def get_agent(self, name: str) -> tuple[AgentManifest, Path] | None:
        """Get a specific agent by name.

        Args:
            name: Agent name to look up.

        Returns:
            Tuple of (manifest, agent_dir) or ``None``.
        """
        agent_dir = self._base_dir / name
        if not agent_dir.is_dir():
            return None

        for ext in ("yml", "json"):
            manifest_path = agent_dir / f"manifest.{ext}"
            if manifest_path.is_file():
                loader = self._load_manifest if ext == "yml" else self._load_manifest_json
                manifest = loader(manifest_path)
                if manifest:
                    return manifest, agent_dir
        return None

    def register(self, manifest: AgentManifest, path: Path) -> None:
        """Record a new agent entry (idempotent).

        Args:
            manifest: The agent manifest.
            path: Absolute path to the agent directory.
        """
        logger.info("Registered generated agent '%s' at %s", manifest.name, path)

    def load_as_subagent(self, name: str) -> "SubAgent" | None:
        """Load a generated agent as a deepagents SubAgent dict.

        Args:
            name: Agent name to load.

        Returns:
            A ``SubAgent`` dict or ``None`` if not found.
        """
        result = self.get_agent(name)
        if result is None:
            return None

        manifest, agent_dir = result
        prompt_path = agent_dir / manifest.system_prompt_file
        system_prompt = ""
        if prompt_path.is_file():
            try:
                system_prompt = prompt_path.read_text(encoding="utf-8")
            except Exception:
                logger.warning("Failed to read system prompt for '%s'", name, exc_info=True)

        return {
            "name": manifest.name,
            "description": manifest.description,
            "system_prompt": system_prompt,
        }

    def cleanup_old_agents(self, max_age_days: int = 30, max_agents: int = 100) -> int:
        """Remove old/unused generated agents.

        Args:
            max_age_days: Delete agents not accessed for N days.
            max_agents: Keep at most N agents (delete oldest first).

        Returns:
            Number of agents deleted.
        """
        import shutil
        from datetime import UTC, datetime, timedelta

        deleted = 0

        if not self._base_dir.is_dir():
            return deleted

        # Get all agents with their access times
        agents: list[tuple[Path, datetime]] = []
        try:
            for manifest_file in self._base_dir.glob("*/manifest.yml"):
                try:
                    stat = manifest_file.stat()
                    atime = datetime.fromtimestamp(stat.st_atime, tz=UTC)
                    agents.append((manifest_file.parent, atime))
                except Exception:
                    logger.debug("Failed to stat %s", manifest_file, exc_info=True)
                    continue

            # Sort by access time (oldest first)
            agents.sort(key=lambda x: x[1])

            # Delete by age
            cutoff = datetime.now(UTC) - timedelta(days=max_age_days)
            for agent_dir, atime in agents:
                if atime < cutoff:
                    try:
                        shutil.rmtree(agent_dir)
                        deleted += 1
                        logger.info("Deleted old generated agent: %s", agent_dir.name)
                    except Exception:
                        logger.warning("Failed to delete agent %s", agent_dir, exc_info=True)

            # Delete by count (if still over limit)
            remaining = [(d, t) for d, t in agents if t >= cutoff]
            if len(remaining) > max_agents:
                for agent_dir, _ in remaining[:-max_agents]:
                    try:
                        shutil.rmtree(agent_dir)
                        deleted += 1
                        logger.info("Deleted excess generated agent: %s", agent_dir.name)
                    except Exception:
                        logger.warning("Failed to delete agent %s", agent_dir, exc_info=True)
        except Exception:
            logger.warning("Agent cleanup failed", exc_info=True)

        return deleted

    @staticmethod
    def _load_manifest(path: Path) -> AgentManifest | None:
        """Load a YAML manifest file."""
        try:
            import yaml

            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return None
            return AgentManifest(**data)
        except Exception:
            logger.debug("Failed to parse YAML manifest %s", path, exc_info=True)
            return None

    @staticmethod
    def _load_manifest_json(path: Path) -> AgentManifest | None:
        """Load a JSON manifest file."""
        import json

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return None
            return AgentManifest(**data)
        except Exception:
            logger.debug("Failed to parse JSON manifest %s", path, exc_info=True)
            return None
