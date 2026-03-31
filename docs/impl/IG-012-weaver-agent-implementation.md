# Weaver Agent Implementation Guide

**Guide**: IG-012
**Title**: Weaver Agent Implementation
**Created**: 2026-03-13
**Related RFCs**: RFC-000, RFC-001, RFC-500, RFC-601, RFC-601

## Overview

This guide describes implementation of Weaver, a generative subagent framework that composes Skillify results, tools, and MCP resources into instant Soothe-compatible generated subagents. It focuses on the reuse-first strategy, skill harmonization pipeline, and dynamic loading of generated agents.

## Prerequisites

- [x] RFC-601 (Weaver Architecture Design)
- [x] Skillify subagent implemented (IG-011)
- [x] VectorStoreProtocol implemented (IG-006)
- [x] SootheConfig with WeaverConfig section (Phase 5 wiring)

## File Structure

```text
src/soothe/subagents/weaver/
  __init__.py       # create_weaver_subagent() factory, LangGraph
  models.py         # AgentManifest, CapabilitySignature, SkillConflict, etc.
  analyzer.py       # RequirementAnalyzer: LLM-based capability extraction
  reuse.py          # ReuseIndex: vector search over generated agents
  composer.py       # AgentComposer: Skillify fetch + harmonization + tool resolution
  generator.py      # AgentGenerator: manifest + system prompt generation
  registry.py       # GeneratedAgentRegistry: JSON CRUD + filesystem management
```

## Module APIs

### models.py

```python
class CapabilitySignature(BaseModel):
    description: str
    required_capabilities: list[str]
    constraints: list[str]
    expected_input: str
    expected_output: str

class AgentManifest(BaseModel):
    name: str
    description: str
    type: Literal["subagent"] = "subagent"
    system_prompt_file: str = "system_prompt.md"
    skills: list[str] = []
    tools: list[str] = []
    capabilities: list[str] = []
    created_at: datetime
    version: int = 1

class ReuseCandidate(BaseModel):
    manifest: AgentManifest
    confidence: float
    path: str

class SkillConflict(BaseModel):
    skill_a_id: str
    skill_b_id: str
    conflict_type: Literal["contradictory", "ambiguous", "version_mismatch"]
    description: str
    severity: Literal["low", "medium", "high"]
    resolution: str

class SkillConflictReport(BaseModel):
    conflicts: list[SkillConflict]
    overlaps: list[tuple[str, str]]
    gaps: list[str]
    harmonization_summary: str

class HarmonizedSkillSet(BaseModel):
    skills: list[str]
    skill_contents: dict[str, str]
    bridge_instructions: str
    dropped_skills: list[str]
    merge_log: list[str]

class AgentBlueprint(BaseModel):
    """Complete specification for agent generation."""
    capability: CapabilitySignature
    harmonized: HarmonizedSkillSet
    tools: list[str]
    agent_name: str
```

### analyzer.py

```python
class RequirementAnalyzer:
    def __init__(self, model: BaseChatModel) -> None: ...

    async def analyze(self, request: str) -> CapabilitySignature:
        """LLM call: extract structured capability signature from user request.

        Prompt instructs the LLM to output JSON with:
        - description: one-paragraph summary of what the agent should do
        - required_capabilities: list of capability keywords
        - constraints: operational limits
        - expected_input/output: what the agent receives and produces
        """
        ...
```

### reuse.py

```python
class ReuseIndex:
    def __init__(
        self,
        vector_store: VectorStoreProtocol,
        embeddings: Embeddings,
        threshold: float = 0.85,
        collection: str = "soothe_weaver_reuse",
        embedding_dims: int = 1536,
    ) -> None: ...

    async def find_reusable(self, capability: CapabilitySignature) -> ReuseCandidate | None:
        """Search for an existing generated agent matching the capability.

        1. Embed capability.description
        2. Search vector store with top-k=5
        3. If best score >= threshold, load manifest and return ReuseCandidate
        4. Otherwise return None
        """
        ...

    async def index_agent(self, manifest: AgentManifest, path: str) -> None:
        """Add a newly generated agent to the reuse index."""
        ...
```

### composer.py

```python
class AgentComposer:
    def __init__(
        self,
        model: BaseChatModel,
        skillify_retriever: SkillRetriever | None = None,
        allowed_tool_groups: list[str] | None = None,
    ) -> None: ...

    async def compose(
        self,
        capability: CapabilitySignature,
        skill_bundle: SkillBundle,
    ) -> AgentBlueprint:
        """Compose an agent blueprint from skills and tools.

        1. Read full SKILL.md content for each skill in bundle
        2. Run harmonize_skills() -- the core three-step pipeline
        3. Resolve tools from allowed_tool_groups matching capabilities
        4. Generate agent name from capability description
        5. Return AgentBlueprint
        """
        ...

    async def harmonize_skills(
        self,
        skill_contents: dict[str, str],
        capability: CapabilitySignature,
    ) -> HarmonizedSkillSet:
        """Three-step skill harmonization pipeline.

        Step 1 - Conflict detection:
          Single LLM call with all skill summaries.
          Output: SkillConflictReport (conflicts, overlaps, gaps)

        Step 2 - Deduplication and merging:
          For each overlap: select best-fit or merge complementary sections.
          For each conflict: apply resolution (prefer one, merge, or drop).
          Prune skills irrelevant to objective.

        Step 3 - Gap analysis:
          LLM identifies missing glue logic given resolved skills + objective.
          Generates bridge_instructions to connect skills coherently.
        """
        ...
```

### generator.py

```python
class AgentGenerator:
    def __init__(self, model: BaseChatModel) -> None: ...

    async def generate(
        self,
        blueprint: AgentBlueprint,
        output_dir: Path,
    ) -> AgentManifest:
        """Generate an agent package from a blueprint.

        1. Create output_dir and skills/ subdirectory
        2. Copy referenced skill files into skills/
        3. LLM call: craft system_prompt.md from harmonized skills + tools + bridge instructions
        4. Write manifest.yml
        5. Return AgentManifest
        """
        ...
```

### registry.py

```python
class GeneratedAgentRegistry:
    def __init__(self, base_dir: Path) -> None: ...

    def list_agents(self) -> list[AgentManifest]:
        """Scan base_dir for */manifest.yml, return parsed manifests."""
        ...

    def get_agent(self, name: str) -> tuple[AgentManifest, Path] | None:
        """Get a specific agent by name."""
        ...

    def register(self, manifest: AgentManifest, path: Path) -> None:
        """Validate and record a new agent entry (idempotent)."""
        ...

    def load_as_subagent(self, name: str) -> SubAgent | None:
        """Load a generated agent as a deepagents SubAgent dict.

        1. Find manifest by name
        2. Read system_prompt.md
        3. Return {"name": ..., "description": ..., "system_prompt": ...}
        """
        ...
```

### __init__.py

```python
def create_weaver_subagent(
    model: str | BaseChatModel | None = None,
    *,
    config: SootheConfig | None = None,
    **kwargs: Any,
) -> CompiledSubAgent:
    """Create Weaver CompiledSubAgent.

    1. Resolve model, VectorStore, Embeddings from config
    2. Create RequirementAnalyzer, ReuseIndex, AgentComposer, AgentGenerator, Registry
    3. Build LangGraph (analyze -> check_reuse -> [reuse|compose] -> execute)
    4. Return CompiledSubAgent
    """
    ...
```

## LangGraph Node Implementation

```python
class WeaverState(dict):
    messages: Annotated[list, add_messages]

def _build_weaver_graph(
    analyzer: RequirementAnalyzer,
    reuse_index: ReuseIndex,
    composer: AgentComposer,
    generator: AgentGenerator,
    registry: GeneratedAgentRegistry,
    skillify_retriever: SkillRetriever | None,
    model: BaseChatModel,
) -> CompiledGraph:
    # Nodes:
    #   analyze_request: extract CapabilitySignature
    #   check_reuse: search reuse index
    #   route_reuse: conditional edge (hit vs miss)
    #   load_existing: read manifest + prompt from disk
    #   fetch_skills: call skillify retriever
    #   harmonize_and_compose: run composer.compose()
    #   generate_agent: run generator.generate()
    #   register_agent: run registry.register() + reuse_index.index_agent()
    #   execute_agent: instantiate SubAgent and run inline
    #   format_response: return result as AIMessage
    ...
```

## Wiring Steps

1. **config.py**: Add `WeaverConfig` to `SootheConfig` (see Phase 5)
2. **agent.py**: Add `"weaver": create_weaver_subagent` to `_SUBAGENT_FACTORIES`; add `_resolve_generated_subagents()` for startup loading
3. **subagents/__init__.py**: Export `create_weaver_subagent`
4. **config.py default subagents**: Add `"weaver": SubagentConfig(enabled=False)`

## Dynamic Loading in agent.py

```python
def _resolve_generated_subagents(config: SootheConfig) -> list[SubAgent]:
    """Load generated agents from manifest files at startup."""
    from soothe.subagents.weaver.registry import GeneratedAgentRegistry
    agents_dir = Path(config.weaver.generated_agents_dir or
                      str(Path(SOOTHE_HOME) / "generated_agents"))
    registry = GeneratedAgentRegistry(agents_dir)
    subagents = []
    for manifest in registry.list_agents():
        agent = registry.load_as_subagent(manifest.name)
        if agent:
            subagents.append(agent)
    return subagents
```

## Skill Harmonization Prompts

### Conflict Detection Prompt

```
You are analyzing a set of agent skills for conflicts, overlaps, and gaps.

User objective: {objective}

Skills:
{skills_with_ids}

Analyze ALL skills and output JSON:
{
  "conflicts": [{"skill_a_id": "...", "skill_b_id": "...", "conflict_type": "contradictory|ambiguous|version_mismatch", "description": "...", "severity": "low|medium|high", "resolution": "..."}],
  "overlaps": [["skill_id_1", "skill_id_2"]],
  "gaps": ["missing capability description"],
  "harmonization_summary": "..."
}
```

### Gap Analysis Prompt

```
Given the user objective and the resolved skill set below, identify any missing
connective logic -- instructions needed to make these skills work together
coherently for this specific task.

Objective: {objective}
Resolved skills: {resolved_skill_summaries}
Capability requirements: {capabilities}

Generate bridge instructions (markdown) that fill the gaps.
```

## Testing Strategy

### Unit Tests

- `RequirementAnalyzer.analyze()` with mocked LLM returning structured JSON
- `ReuseIndex.find_reusable()` with mocked vector store (hit and miss cases)
- `AgentComposer.harmonize_skills()` with mocked LLM for conflict detection and gap analysis
- `AgentGenerator.generate()` verifies filesystem output (manifest.yml, system_prompt.md)
- `GeneratedAgentRegistry.load_as_subagent()` returns valid SubAgent dict

### Integration Tests

- Full pipeline: analyze -> compose -> generate -> register -> load_as_subagent
- Reuse path: register agent, then verify reuse hit on similar request
- Skill harmonization: provide conflicting skills, verify conflicts detected and resolved
- Dynamic loading: generate agent, verify it appears in `_resolve_generated_subagents()`

## Verification Checklist

- [ ] Weaver is routable as a Soothe CompiledSubAgent
- [ ] Reuse-first logic works with configurable threshold
- [ ] Skill harmonization detects conflicts, overlaps, and gaps
- [ ] Generated agents have valid manifest.yml and system_prompt.md
- [ ] Generated agents load at startup via `_resolve_generated_subagents()`
- [ ] Inline execution works within the Weaver graph
- [ ] Policy checks are enforced for tool/MCP access
- [ ] Custom events for all stages are emitted

## Related Documents

- [RFC-601](../specs/RFC-601.md) -- Weaver Architecture Design
- [RFC-601](../specs/RFC-601.md) -- Skillify Architecture Design
- [IG-011](./011-skillify-agent-implementation.md) -- Skillify Implementation
