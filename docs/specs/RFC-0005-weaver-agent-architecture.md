# RFC-0005: Weaver Agent Architecture Design

**RFC**: 0005
**Title**: Weaver Agent Architecture Design
**Status**: Implemented
**Created**: 2026-03-13
**Updated**: 2026-03-27
**Related**: RFC-0001, RFC-0002, RFC-0003, RFC-0004

## Abstract

This RFC defines the architecture of the Weaver agent, a generative subagent framework that composes skills, tools, and MCP capabilities into instant Soothe-compatible subagents. Weaver implements a reuse-first strategy with a dedicated skill harmonization pipeline that resolves conflicts, overlaps, and gaps when combining skills from diverse sources. Generated agents are SubAgent-type (declarative, system-prompt-based) and can be loaded dynamically at startup or executed inline during the session.

## Motivation

Soothe currently provides fixed bundled subagents. Users also need dynamic, task-specific subagents created at runtime from existing building blocks without manual scaffolding. The skill warehouse typically contains skills from many different creators with different conventions, intended scenarios, and levels of detail. Naively combining them produces contradictions, redundancy, and missing glue logic. Weaver addresses both problems: adaptive agent generation with robust skill harmonization.

## Design Principles

### Reuse first, generate second

Before generating a new agent, Weaver searches a vector index of previously generated agents. If an existing agent meets a configurable confidence threshold, it is reused directly. This avoids redundant LLM calls and warehouse sprawl.

### Skill harmonization as a first-class concern

Combining skills from heterogeneous sources is the hardest part of agent composition. The AgentComposer performs a dedicated three-step harmonization pipeline -- conflict detection, deduplication/merging, and gap analysis -- producing a coherent instruction corpus before generation. In the current implementation, the single-skill fast path bypasses the merge/gap phases and returns the one retrieved skill directly.

### SubAgent-type output, no code generation

Generated agents are SubAgent-type (declarative): a `manifest.yml` and `system_prompt.md`. No Python code is generated, keeping the process reliable and auditable. The LLM crafts a focused system prompt that incorporates harmonized skills and selected tools.

### Policy-gated generation

Every generation and registration action passes through `PolicyProtocol`. Tool and MCP access in generated agents is bounded by the configured allowed lists.

## Data Models

### Core Models

```python
class CapabilitySignature(BaseModel):
    """Structured analysis of what the user request requires."""
    description: str
    required_capabilities: list[str]
    constraints: list[str]
    expected_input: str
    expected_output: str

class AgentManifest(BaseModel):
    """Metadata file for a generated agent package."""
    name: str
    description: str
    type: Literal["subagent"] = "subagent"
    system_prompt_file: str = "system_prompt.md"
    skills: list[str] = []       # skill paths copied into the package
    tools: list[str] = []        # langchain tool group names
    capabilities: list[str] = []
    created_at: datetime
    version: int = 1

class ReuseCandidate(BaseModel):
    """A previously generated agent that may fulfill the current request."""
    manifest: AgentManifest
    confidence: float            # [0, 1] semantic similarity
    path: str                    # absolute path to agent directory
```

### Skill Harmonization Models

```python
class SkillConflict(BaseModel):
    """A detected conflict between two skills."""
    skill_a_id: str
    skill_b_id: str
    conflict_type: Literal["contradictory", "ambiguous", "version_mismatch"]
    description: str
    severity: Literal["low", "medium", "high"]
    resolution: str              # LLM-proposed resolution

class SkillConflictReport(BaseModel):
    """Full analysis of conflicts, overlaps, and gaps in a candidate skill set."""
    conflicts: list[SkillConflict]
    overlaps: list[list[str]]            # pairs of skill IDs with redundancy
    gaps: list[str]                      # missing capabilities identified
    harmonization_summary: str

class HarmonizedSkillSet(BaseModel):
    """The output of skill harmonization -- a clean, unified instruction corpus."""
    skills: list[str]                     # final skill IDs retained
    skill_contents: dict[str, str]        # skill_id -> merged/cleaned content
    bridge_instructions: str              # LLM-generated glue logic
    dropped_skills: list[str]             # skill IDs removed during dedup
    merge_log: list[str]                  # human-readable log of merge decisions
```

## Architecture

### LangGraph Pipeline

The current Weaver graph is exposed as a `CompiledSubAgent`, but the compiled LangGraph currently contains a single `weave` node:

```
[START] → weave → [END]
```

That `weave` node performs the full orchestration path internally:

1. analyze the request into a `CapabilitySignature`
2. query the reuse index for an existing generated agent
3. if reuse misses, fetch skills from Skillify when available
4. harmonize retrieved skills and resolve allowed tool groups
5. generate the package files
6. validate the generated package and policy-check declared tools/spawn actions
7. register the package and upsert the reuse index
8. execute either the reused or newly generated agent inline

### Internal Phase Responsibilities

| Phase inside `weave` | Description |
|----------------------|-------------|
| Analyze request | LLM call: extract `CapabilitySignature` from the user message |
| Check reuse | Embed capability description, search reuse index, return `ReuseCandidate` if above threshold |
| Fetch skills | Call Skillify retrieval to get a `SkillBundle` for the capability signature when Skillify is configured |
| Harmonize skills | Run the current conflict/merge/gap pipeline in `AgentComposer` and produce `HarmonizedSkillSet` |
| Resolve tools | Match required capabilities to configured allowed tool groups using simple name matching |
| Generate agent | LLM call: craft system prompt from harmonized skills + tools, write `manifest.yml` and `system_prompt.md` |
| Validate package | Check manifest completeness, verify the system prompt is non-empty, and policy-check declared tools/spawn actions |
| Register | Log registration through `GeneratedAgentRegistry.register()` and upsert the reuse index |
| Execute agent | Read `system_prompt.md`, build a prompt-driven deep agent, and execute inline with the user's task |

### Skill Harmonization Pipeline

The `harmonize_skills` node is the core differentiator. It handles the complexity of combining skills from diverse creators:

**Step 1: Conflict Detection**

The LLM analyzes all candidate skills (from Skillify retrieval) for pairwise contradictions. For N skills, this is done efficiently by providing all skill summaries in a single prompt and asking for conflict pairs, rather than O(N^2) individual comparisons.

Input: list of skill contents + user objective
Output: `SkillConflictReport` with typed conflicts, overlaps, and gaps

**Step 2: Deduplication and Merging**

For each overlap pair, the LLM selects the best-fit version or merges complementary sections. For each conflict, the LLM applies the proposed resolution (prefer one, merge with caveats, or drop both). Skills not relevant to the objective are pruned.

Input: `SkillConflictReport` + original skill contents
Output: deduplicated skill set with merge log

**Step 3: Gap Analysis**

Given the user objective and the resolved skill set, the LLM identifies missing connective logic -- the glue instructions needed to make the skills work together coherently for the specific task. These bridge instructions become part of the generated system prompt.

Input: resolved skills + user objective + capability signature
Output: bridge instructions string

The complete output is a `HarmonizedSkillSet` that feeds into `generate_agent`.

### State Schema

```python
class WeaverState(dict):
    messages: Annotated[list, add_messages]
```

The richer objects used during analysis, reuse, harmonization, generation, validation, and execution are currently held as local variables inside the single `weave` node rather than persisted as explicit LangGraph state fields.

## Dynamic Loading

### Generated Agent Package Layout

```
~/.soothe/generated_agents/<agent-name>/
  manifest.yml          # AgentManifest serialized as YAML
  system_prompt.md      # LLM-crafted system prompt
  skills/               # copied SKILL.md files from warehouse
    skill-a/SKILL.md
    skill-b/SKILL.md
```

### Startup Loading

At agent creation time, `create_soothe_agent()` calls `_resolve_generated_subagents()` which:

1. Resolves `generated_agents_dir`
2. Uses `GeneratedAgentRegistry.list_agents()` to scan `*/manifest.yml` and `*/manifest.json`
3. Loads each manifest plus the corresponding `system_prompt.md`
4. Constructs a deepagents-compatible subagent dict: `{"name": ..., "description": ..., "system_prompt": ...}`
5. Appends those generated agents alongside built-in subagents

Generated agents appear in the `task` tool's subagent list and can be routed to by the orchestrator or user.

### Inline Execution

When Weaver needs to execute an agent immediately, it currently reads the generated `system_prompt.md` and calls `create_deep_agent(model=..., system_prompt=...)` directly. This is a prompt-driven inline execution path rather than a full manifest-to-SubAgent reconstruction flow.

## Reuse Index

The reuse index is a VectorStore collection (`soothe_weaver_reuse`) that stores embeddings derived from generated agent manifest metadata. On each new request:

1. Embed the `CapabilitySignature.description`
2. Search with top-k=5
3. If best match confidence >= `weaver.reuse_threshold` (default 0.85), reuse the existing generated package
4. Otherwise proceed with generation

After successful generation, Weaver upserts the reuse index using text derived from `manifest.name`, `manifest.description`, and any declared capabilities. Current reuse-miss telemetry emits `best_confidence=0.0` rather than the highest below-threshold score.

## Configuration Surface

```python
class WeaverConfig(BaseModel):
    enabled: bool = False
    generated_agents_dir: str = ""   # default: SOOTHE_HOME / "generated_agents"
    reuse_threshold: float = 0.85
    reuse_collection: str = "soothe_weaver_reuse"
    max_generation_attempts: int = 2
    allowed_tool_groups: list[str] = []
    allowed_mcp_servers: list[str] = []
    cleanup_old_agents_days: int = 100
    max_generated_agents: int = 100
```

Current implementation note: `allowed_tool_groups` is used during simple capability-name matching in `AgentComposer`. `allowed_mcp_servers`, `max_generation_attempts`, `cleanup_old_agents_days`, and `max_generated_agents` exist on the config surface, but are not yet wired into the main Weaver generation/runtime flow.

## Observability

Custom stream events:

| Event Type | Fields | When |
|------------|--------|------|
| `soothe.subagent.weaver.analysis_started` | `task_preview` | Capability analysis begins |
| `soothe.subagent.weaver.analysis_completed` | `capabilities`, `constraints` | Capability signature extracted |
| `soothe.subagent.weaver.reuse_hit` | `agent_name`, `confidence` | Existing agent matched |
| `soothe.subagent.weaver.reuse_miss` | `best_confidence` | No suitable existing agent |
| `soothe.subagent.weaver.skillify_pending` | standard event envelope only | Skillify is still warming up when Weaver tries retrieval |
| `soothe.subagent.weaver.harmonize_started` | `skill_count` | Harmonization begins |
| `soothe.subagent.weaver.harmonize_completed` | `retained`, `dropped`, `bridge_length` | Harmonization done |
| `soothe.subagent.weaver.generate_started` | `agent_name` | Agent generation begins |
| `soothe.subagent.weaver.generate_completed` | `agent_name`, `path` | Agent package written |
| `soothe.subagent.weaver.validate_started` | `agent_name` | Generated package validation begins |
| `soothe.subagent.weaver.validate_completed` | `agent_name` | Generated package validation completes |
| `soothe.subagent.weaver.registry_updated` | `agent_name`, `version` | Registration/index update step completes |
| `soothe.subagent.weaver.execute_started` | `agent_name`, `task_preview` | Inline execution begins |
| `soothe.subagent.weaver.execute_completed` | `agent_name`, `result_length` | Execution done |

The current implementation does not emit a separate harmonization-conflicts event.

## Architectural Constraints

- Weaver MUST run as a Soothe `CompiledSubAgent`.
- Generated agents MUST be SubAgent-type (declarative, no Python code generation).
- Skill harmonization MUST be performed before agent generation when combining multiple skills.
- Generated agents MUST be loadable at Soothe startup via manifest scanning.
- Tool selection currently resolves only configured langchain tool-group names through simple capability-name matching.
- MCP server configuration exists on `WeaverConfig`, but MCP resolution/runtime wiring is not currently implemented in Weaver.
- Generation, validation, and registration-related spawn/tool checks currently call the configured policy implementation.
- Durability currently comes from generated package files plus the reuse-index vector collection; `GeneratedAgentRegistry.register()` itself is logging-only.

## Dependencies

- RFC-0001 (System Conceptual Design)
- RFC-0002 (Core Modules Architecture Design) -- VectorStoreProtocol, PolicyProtocol
- RFC-0003 (CLI TUI Architecture Design) -- stream event format
- RFC-0004 (Skillify Agent Architecture Design) -- skill retrieval

## Related Documents

- [RFC-0001](./RFC-0001.md)
- [RFC-0002](./RFC-0002.md)
- [RFC-0003](./RFC-0003.md)
- [RFC-0004](./RFC-0004.md)
- [IG-012](../impl/012-weaver-agent-implementation.md)
