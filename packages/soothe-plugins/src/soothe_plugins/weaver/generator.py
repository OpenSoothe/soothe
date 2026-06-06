"""AgentGenerator -- manifest and system prompt generation (RFC-0005) -- community edition."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from langchain_core.language_models import BaseChatModel

import anyio

from .models import AgentBlueprint, AgentManifest

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT_GENERATION = """\
You are generating a system prompt for a specialist AI agent.

Agent name: {agent_name}
Agent description: {description}

The agent must fulfil this objective:
{objective}

Expected input: {expected_input}
Expected output: {expected_output}
Constraints: {constraints}

The agent has access to these skills (integrated instructions):
{skills_text}

{bridge_instructions}

The agent has these tools available: {tools}

Generate a comprehensive system prompt for this agent. The prompt should:
1. Define the agent's role and responsibilities clearly
2. Incorporate the skill instructions naturally (do not reference them as "skills")
3. Include the bridge instructions as part of the workflow
4. Specify the expected input/output format
5. Include any constraints as operational rules

Output ONLY the system prompt text (markdown format). Do not include meta-commentary."""


class AgentGenerator:
    """Generates agent packages (manifest + system prompt) from blueprints.

    Args:
        model: Chat model for system prompt generation.
    """

    def __init__(self, model: BaseChatModel) -> None:
        """Initialize the agent generator.

        Args:
            model: Chat model for system prompt generation.
        """
        self._model = model

    async def generate(
        self,
        blueprint: AgentBlueprint,
        output_dir: Path,
    ) -> AgentManifest:
        """Generate an agent package from a blueprint.

        Creates the output directory with ``manifest.yml``, ``system_prompt.md``,
        and a ``skills/`` subdirectory with copied skill files.

        Args:
            blueprint: Complete agent specification.
            output_dir: Directory to write the agent package into.

        Returns:
            The generated ``AgentManifest``.
        """
        adir = anyio.Path(output_dir)
        await adir.mkdir(parents=True, exist_ok=True)

        skills_dir = output_dir / "skills"
        await anyio.Path(skills_dir).mkdir(exist_ok=True)
        copied_skills = self._copy_skills(blueprint, skills_dir)

        system_prompt = await self._generate_system_prompt(blueprint)

        prompt_path = output_dir / "system_prompt.md"
        await anyio.Path(prompt_path).write_text(system_prompt, encoding="utf-8")

        manifest = AgentManifest(
            name=blueprint.agent_name,
            description=blueprint.capability.description,
            skills=copied_skills,
            tools=blueprint.tools,
            capabilities=blueprint.capability.required_capabilities,
            created_at=datetime.now(UTC),
        )

        manifest_path = output_dir / "manifest.yml"
        self._write_manifest(manifest, manifest_path)

        logger.info("Generated agent '%s' at %s", blueprint.agent_name, output_dir)
        return manifest

    async def _generate_system_prompt(self, blueprint: AgentBlueprint) -> str:
        """Use LLM to craft a system prompt from the blueprint."""
        skills_text = (
            "\n\n".join(f"### {sid}\n{content[:2000]}" for sid, content in blueprint.harmonized.skill_contents.items())
            or "(no specific skills)"
        )

        bridge = ""
        if blueprint.harmonized.bridge_instructions:
            bridge = f"Additional integration instructions:\n{blueprint.harmonized.bridge_instructions}"

        constraints = ", ".join(blueprint.capability.constraints) or "none"
        tools = ", ".join(blueprint.tools) or "standard file and shell tools"

        prompt = _SYSTEM_PROMPT_GENERATION.format(
            agent_name=blueprint.agent_name,
            description=blueprint.capability.description,
            objective=blueprint.capability.description,
            expected_input=blueprint.capability.expected_input or "user request",
            expected_output=blueprint.capability.expected_output or "task result",
            constraints=constraints,
            skills_text=skills_text,
            bridge_instructions=bridge,
            tools=tools,
        )

        try:
            resp = await self._model.ainvoke([{"role": "user", "content": prompt}])
            return str(resp.content).strip()
        except Exception:
            logger.exception("System prompt generation failed")
            return self._fallback_prompt(blueprint)

    @staticmethod
    def _fallback_prompt(blueprint: AgentBlueprint) -> str:
        """Generate a minimal system prompt when LLM call fails."""
        return (
            f"You are {blueprint.agent_name}, a specialist agent.\n\n"
            f"## Objective\n{blueprint.capability.description}\n\n"
            f"## Expected Input\n{blueprint.capability.expected_input}\n\n"
            f"## Expected Output\n{blueprint.capability.expected_output}\n"
        )

    @staticmethod
    def _copy_skills(blueprint: AgentBlueprint, skills_dir: Path) -> list[str]:
        """Copy skill files into the agent's skills directory."""
        copied: list[str] = []
        for sid, content in blueprint.harmonized.skill_contents.items():
            skill_subdir = skills_dir / sid
            skill_subdir.mkdir(exist_ok=True)
            (skill_subdir / "SKILL.md").write_text(content, encoding="utf-8")
            copied.append(str(skill_subdir))
        return copied

    @staticmethod
    def _write_manifest(manifest: AgentManifest, path: Path) -> None:
        """Write the manifest as YAML."""
        try:
            import yaml

            data = manifest.model_dump(mode="json")
            if "created_at" in data and hasattr(data["created_at"], "isoformat"):
                data["created_at"] = data["created_at"].isoformat()
            path.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False), encoding="utf-8")
        except ImportError:
            import json

            data = manifest.model_dump(mode="json")
            path.with_suffix(".json").write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
