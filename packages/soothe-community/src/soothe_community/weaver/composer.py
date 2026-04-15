"""AgentComposer -- skill harmonization and tool resolution (RFC-0005) -- community edition.

The composer is the core of Weaver's value proposition. It takes raw skills
from Skillify and resolves conflicts, overlaps, and gaps before handing
a coherent blueprint to the generator.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

from .models import (
    AgentBlueprint,
    CapabilitySignature,
    HarmonizedSkillSet,
    SkillConflictReport,
)

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

    from soothe_community.skillify.models import SkillBundle

logger = logging.getLogger(__name__)

# Constants for skill content formatting
_MAX_AGENT_NAME_WORDS = 4
_MAX_SKILL_CONTENT_LENGTH = 1500

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_CONFLICT_DETECTION_PROMPT = """\
You are analysing a set of agent skills for conflicts, overlaps, and gaps.

User objective: {objective}

Skills (each identified by ID):
{skills_text}

Analyse ALL skills and output ONLY valid JSON:
{{
  "conflicts": [
    {{
      "skill_a_id": "id",
      "skill_b_id": "id",
      "conflict_type": "contradictory|ambiguous|version_mismatch",
      "description": "what the conflict is",
      "severity": "low|medium|high",
      "resolution": "how to resolve it"
    }}
  ],
  "overlaps": [["id1", "id2"]],
  "gaps": ["missing capability description"],
  "harmonization_summary": "brief summary"
}}

If there are no conflicts, return empty lists. Be thorough but concise."""

_MERGE_PROMPT = """\
Given the conflict analysis below and the original skill contents, produce a \
deduplicated and merged skill set.

Objective: {objective}

Conflict report:
{report_json}

Original skill contents:
{skills_text}

For each skill, decide: KEEP (as-is), MERGE (combine with another), or DROP \
(redundant/conflicting). For merged skills, provide the merged content.

Output ONLY valid JSON:
{{
  "kept_skills": {{"skill_id": "content"}},
  "dropped_skills": ["skill_id"],
  "merge_log": ["decision description"]
}}"""

_GAP_ANALYSIS_PROMPT = """\
Given the user objective and the resolved skill set below, identify any \
missing connective logic -- instructions needed to make these skills work \
together coherently for this specific task.

Objective: {objective}

Capabilities needed: {capabilities}

Resolved skills:
{skills_text}

Generate bridge instructions (plain text) that fill the gaps. If no gaps \
exist, return "No additional instructions needed."."""


# ---------------------------------------------------------------------------
# Composer
# ---------------------------------------------------------------------------


class AgentComposer:
    """Composes an agent blueprint from skills and tools with harmonization.

    The three-step harmonization pipeline resolves conflicts, overlaps, and
    gaps that arise when combining skills from diverse creators.

    Args:
        model: Chat model for LLM-assisted harmonization.
        allowed_tool_groups: Tool groups the generated agent may use.
    """

    def __init__(
        self,
        model: BaseChatModel,
        allowed_tool_groups: list[str] | None = None,
    ) -> None:
        """Initialize the agent composer.

        Args:
            model: Chat model for LLM-assisted harmonization.
            allowed_tool_groups: Tool groups the generated agent may use.
        """
        self._model = model
        self._allowed_tools = allowed_tool_groups or []

    async def compose(
        self,
        capability: CapabilitySignature,
        skill_bundle: "SkillBundle",
    ) -> AgentBlueprint:
        """Compose an agent blueprint from skills and tools.

        Args:
            capability: Analysed capability signature.
            skill_bundle: Skills retrieved from Skillify.

        Returns:
            Complete agent blueprint ready for generation.
        """
        skill_contents = self._load_skill_contents(skill_bundle)
        harmonized = await self.harmonize_skills(skill_contents, capability)
        tools = self._resolve_tools(capability)
        agent_name = self._generate_name(capability.description)

        return AgentBlueprint(
            capability=capability,
            harmonized=harmonized,
            tools=tools,
            agent_name=agent_name,
        )

    async def harmonize_skills(
        self,
        skill_contents: dict[str, str],
        capability: CapabilitySignature,
    ) -> HarmonizedSkillSet:
        """Three-step skill harmonization pipeline.

        Args:
            skill_contents: Mapping of skill_id to SKILL.md content.
            capability: The target capability signature.

        Returns:
            Harmonized skill set with conflicts resolved and gaps filled.
        """
        if not skill_contents:
            return HarmonizedSkillSet(bridge_instructions="No skills available.")

        if len(skill_contents) == 1:
            sid, content = next(iter(skill_contents.items()))
            return HarmonizedSkillSet(
                skills=[sid],
                skill_contents={sid: content},
            )

        # Step 1: Conflict detection
        report = await self._detect_conflicts(skill_contents, capability)

        # Step 2: Deduplication and merging
        merged_contents, dropped, merge_log = await self._merge_skills(skill_contents, report, capability)

        # Step 3: Gap analysis
        bridge = await self._analyze_gaps(merged_contents, capability)

        return HarmonizedSkillSet(
            skills=list(merged_contents.keys()),
            skill_contents=merged_contents,
            bridge_instructions=bridge,
            dropped_skills=dropped,
            merge_log=merge_log,
        )

    # -- Step 1: Conflict detection -----------------------------------------

    async def _detect_conflicts(
        self,
        skill_contents: dict[str, str],
        capability: CapabilitySignature,
    ) -> SkillConflictReport:
        """Detect conflicts, overlaps, and gaps across candidate skills."""
        skills_text = self._format_skills_for_prompt(skill_contents)
        prompt = _CONFLICT_DETECTION_PROMPT.format(
            objective=capability.description,
            skills_text=skills_text,
        )

        try:
            resp = await self._model.ainvoke([{"role": "user", "content": prompt}])
            parsed = json.loads(str(resp.content))
            return SkillConflictReport(**parsed)
        except (json.JSONDecodeError, Exception):
            logger.warning("Conflict detection LLM call failed, assuming no conflicts", exc_info=True)
            return SkillConflictReport(harmonization_summary="Analysis skipped due to error.")

    # -- Step 2: Deduplication and merging ----------------------------------

    async def _merge_skills(
        self,
        skill_contents: dict[str, str],
        report: SkillConflictReport,
        capability: CapabilitySignature,
    ) -> tuple[dict[str, str], list[str], list[str]]:
        """Deduplicate and merge skills based on the conflict report.

        Returns:
            Tuple of (merged_contents, dropped_ids, merge_log).
        """
        if not report.conflicts and not report.overlaps:
            return skill_contents, [], ["No conflicts or overlaps detected."]

        skills_text = self._format_skills_for_prompt(skill_contents)
        prompt = _MERGE_PROMPT.format(
            objective=capability.description,
            report_json=report.model_dump_json(indent=2),
            skills_text=skills_text,
        )

        try:
            resp = await self._model.ainvoke([{"role": "user", "content": prompt}])
            parsed = json.loads(str(resp.content))
            kept = parsed.get("kept_skills", {})
            dropped = parsed.get("dropped_skills", [])
            log = parsed.get("merge_log", [])

            if not kept:
                return skill_contents, [], ["Merge returned empty; keeping all skills."]

        except (json.JSONDecodeError, Exception):
            logger.warning("Merge LLM call failed, keeping all skills", exc_info=True)
            return skill_contents, [], ["Merge skipped due to error."]
        else:
            return kept, dropped, log

    # -- Step 3: Gap analysis -----------------------------------------------

    async def _analyze_gaps(
        self,
        resolved_contents: dict[str, str],
        capability: CapabilitySignature,
    ) -> str:
        """Identify missing glue logic and generate bridge instructions."""
        skills_text = self._format_skills_for_prompt(resolved_contents)
        caps = ", ".join(capability.required_capabilities) or capability.description[:200]
        prompt = _GAP_ANALYSIS_PROMPT.format(
            objective=capability.description,
            capabilities=caps,
            skills_text=skills_text,
        )

        try:
            resp = await self._model.ainvoke([{"role": "user", "content": prompt}])
            return str(resp.content).strip()
        except Exception:
            logger.warning("Gap analysis LLM call failed", exc_info=True)
            return ""

    # -- Helpers ------------------------------------------------------------

    def _resolve_tools(self, capability: CapabilitySignature) -> list[str]:
        """Match capabilities to allowed tool groups."""
        cap_lower = {c.lower() for c in capability.required_capabilities}
        return [
            tool_group
            for tool_group in self._allowed_tools
            if tool_group.lower() in cap_lower or any(tool_group.lower() in c for c in cap_lower)
        ]

    @staticmethod
    def _generate_name(description: str) -> str:
        """Generate a hyphenated agent name from a description."""
        words = re.sub(r"[^a-z0-9\s]", "", description.lower()).split()
        name_words = words[:_MAX_AGENT_NAME_WORDS] if len(words) > _MAX_AGENT_NAME_WORDS else words
        return "-".join(name_words) if name_words else "generated-agent"

    @staticmethod
    def _format_skills_for_prompt(skill_contents: dict[str, str]) -> str:
        """Format skill contents for inclusion in LLM prompts."""
        parts: list[str] = []
        for sid, content in skill_contents.items():
            truncated = content[:_MAX_SKILL_CONTENT_LENGTH] if len(content) > _MAX_SKILL_CONTENT_LENGTH else content
            parts.append(f"--- Skill ID: {sid} ---\n{truncated}\n")
        return "\n".join(parts)

    @staticmethod
    def _load_skill_contents(skill_bundle: "SkillBundle") -> dict[str, str]:
        """Load full SKILL.md content for each skill in the bundle."""
        contents: dict[str, str] = {}
        for sr in skill_bundle.results:
            skill_md = Path(sr.record.path) / "SKILL.md"
            if skill_md.is_file():
                try:
                    contents[sr.record.id] = skill_md.read_text(encoding="utf-8")
                except Exception:
                    logger.warning("Failed to read %s", skill_md, exc_info=True)
        return contents
