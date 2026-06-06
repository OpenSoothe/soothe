"""Weaver data models (RFC-0005) -- community edition."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field


class CapabilitySignature(BaseModel):
    """Structured analysis of what the user request requires.

    Args:
        description: One-paragraph summary of what the agent should do.
        required_capabilities: Capability keywords (e.g. ``arxiv_search``).
        constraints: Operational limits or requirements.
        expected_input: What the agent receives from the user.
        expected_output: What the agent should produce.
    """

    description: str
    required_capabilities: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    expected_input: str = ""
    expected_output: str = ""


class AgentManifest(BaseModel):
    """Metadata file for a generated agent package.

    Args:
        name: Agent identifier (lowercase, hyphenated).
        description: Human-readable description for the ``task`` tool.
        type: Agent type (currently always ``subagent``).
        system_prompt_file: Filename of the system prompt markdown.
        skills: Skill paths copied into the package.
        tools: Langchain tool group names enabled for this agent.
        capabilities: Capability keywords this agent provides.
        created_at: Creation timestamp.
        version: Monotonically increasing version number.
    """

    name: str
    description: str
    type: Literal["subagent"] = "subagent"
    system_prompt_file: str = "system_prompt.md"
    skills: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    version: int = 1


class ReuseCandidate(BaseModel):
    """A previously generated agent that may fulfill the current request.

    Args:
        manifest: The agent's manifest metadata.
        confidence: Semantic similarity score in [0, 1].
        path: Absolute path to the agent directory.
    """

    manifest: AgentManifest
    confidence: float
    path: str


class SkillConflict(BaseModel):
    """A detected conflict between two skills.

    Args:
        skill_a_id: First skill identifier.
        skill_b_id: Second skill identifier.
        conflict_type: Nature of the conflict.
        description: Human-readable conflict description.
        severity: Impact level.
        resolution: LLM-proposed resolution strategy.
    """

    skill_a_id: str
    skill_b_id: str
    conflict_type: Literal["contradictory", "ambiguous", "version_mismatch"]
    description: str
    severity: Literal["low", "medium", "high"]
    resolution: str


class SkillConflictReport(BaseModel):
    """Full analysis of conflicts, overlaps, and gaps in a candidate skill set.

    Args:
        conflicts: Typed conflict entries between skill pairs.
        overlaps: Pairs of skill IDs with redundant coverage.
        gaps: Missing capabilities identified by analysis.
        harmonization_summary: Human-readable summary of the analysis.
    """

    conflicts: list[SkillConflict] = Field(default_factory=list)
    overlaps: list[list[str]] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    harmonization_summary: str = ""


class HarmonizedSkillSet(BaseModel):
    """Output of skill harmonization -- a clean, unified instruction corpus.

    Args:
        skills: Final skill IDs retained after harmonization.
        skill_contents: Mapping of skill_id to merged/cleaned content.
        bridge_instructions: LLM-generated glue logic connecting skills.
        dropped_skills: Skill IDs removed during deduplication.
        merge_log: Human-readable log of merge decisions.
    """

    skills: list[str] = Field(default_factory=list)
    skill_contents: dict[str, str] = Field(default_factory=dict)
    bridge_instructions: str = ""
    dropped_skills: list[str] = Field(default_factory=list)
    merge_log: list[str] = Field(default_factory=list)


class AgentBlueprint(BaseModel):
    """Complete specification for agent generation.

    Args:
        capability: The analysed capability signature.
        harmonized: The harmonized skill set.
        tools: Resolved tool group names.
        agent_name: Generated agent name (lowercase, hyphenated).
    """

    capability: CapabilitySignature
    harmonized: HarmonizedSkillSet
    tools: list[str] = Field(default_factory=list)
    agent_name: str = ""
