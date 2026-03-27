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

Combining skills from heterogeneous sources is the hardest part of agent composition. The AgentComposer performs a dedicated three-step harmonization pipeline -- conflict detection, deduplication/merging, and gap analysis -- producing a coherent instruction corpus before generation.

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
    overlaps: list[tuple[str, str]]       # pairs of skill IDs with redundancy
    gaps: list[str]                       # missing capabilities identified
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

```
[START] → analyze_request → check_reuse → [route]
                                             │
                                ┌────────────┴────────────┐
                                │ reuse hit                │ reuse miss
                                ▼                          ▼
                          load_existing            fetch_skills
                                │                          │
                                │                   harmonize_skills
                                │                          │
                                │                    resolve_tools
                                │                          │
                                │                   generate_agent
                                │                          │
                                │                  validate_package
                                │                          │
                                │                     register
                                │                          │
                                └──────────┬───────────────┘
                                           ▼
                                    execute_agent
                                           │
                                         [END]
```

### Node Responsibilities

| Node | Description |
|------|-------------|
| `analyze_request` | LLM call: extract `CapabilitySignature` from user message |
| `check_reuse` | Embed capability description, search reuse index, return `ReuseCandidate` if above threshold |
| `load_existing` | Read manifest and system prompt from existing agent directory |
| `fetch_skills` | Call Skillify retrieval to get `SkillBundle` for the capability signature |
| `harmonize_skills` | Run three-step skill harmonization (see below), produce `HarmonizedSkillSet` |
| `resolve_tools` | Match required capabilities to available langchain tool groups and MCP servers |
| `generate_agent` | LLM call: craft system prompt from harmonized skills + tools, write `manifest.yml` and `system_prompt.md` |
| `validate_package` | Check manifest completeness, verify system prompt is non-empty, policy check on tool/MCP access |
| `register` | Write agent package to `generated_agents_dir`, update registry, upsert reuse index |
| `execute_agent` | Instantiate a temporary SubAgent from the manifest and execute inline with the user's task |

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
    capability: CapabilitySignature | None
    reuse_candidate: ReuseCandidate | None
    skill_bundle: SkillBundle | None
    harmonized: HarmonizedSkillSet | None
    resolved_tools: list[str]
    manifest: AgentManifest | None
    agent_path: str
    execution_result: str
```

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

1. Scans `generated_agents_dir` for `*/manifest.yml` files
2. Parses each manifest into `AgentManifest`
3. Reads the corresponding `system_prompt.md`
4. Constructs a deepagents `SubAgent` dict: `{"name": ..., "description": ..., "system_prompt": ...}`
5. Appends to the subagent list alongside built-in subagents

Generated agents appear in the `task` tool's subagent list and can be routed to by the orchestrator or user.

### Inline Execution

When Weaver generates and immediately needs to execute an agent (within the same session), it instantiates a temporary `SubAgent` inside the `execute_agent` graph node. This bypasses the need to rebuild the entire agent graph:

1. Create a `SubAgent` dict from the manifest
2. Call `create_deep_agent()` with just that subagent and the user's task
3. Stream execution results back through the Weaver graph
4. The generated agent is also registered for future startup loading

## Reuse Index

The reuse index is a VectorStore collection (`soothe_weaver_reuse`) that stores embeddings of generated agent descriptions and capability signatures. On each new request:

1. Embed the `CapabilitySignature.description`
2. Search with top-k=5
3. If best match confidence >= `weaver.reuse_threshold` (default 0.85), route to `load_existing`
4. Otherwise proceed with generation

The index is updated after each successful generation and registration.

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
```

## Observability

Custom stream events:

| Event Type | Fields | When |
|------------|--------|------|
| `soothe.weaver.analysis.completed` | `capabilities`, `constraints` | Capability signature extracted |
| `soothe.weaver.reuse.hit` | `agent_name`, `confidence` | Existing agent matched |
| `soothe.weaver.reuse.miss` | `best_confidence` | No suitable existing agent |
| `soothe.weaver.harmonize.started` | `skill_count` | Harmonization begins |
| `soothe.weaver.harmonize.conflicts` | `conflict_count`, `overlap_count`, `gap_count` | Conflict report ready |
| `soothe.weaver.harmonize.completed` | `retained`, `dropped`, `bridge_length` | Harmonization done |
| `soothe.weaver.generate.started` | `agent_name` | Agent generation begins |
| `soothe.weaver.generate.completed` | `agent_name`, `path` | Agent package written |
| `soothe.weaver.execute.started` | `agent_name`, `task_preview` | Inline execution begins |
| `soothe.weaver.execute.completed` | `agent_name`, `result_length` | Execution done |
| `soothe.weaver.registry.updated` | `agent_name`, `version` | Registry entry created/updated |

## Architectural Constraints

- Weaver MUST run as a Soothe `CompiledSubAgent`.
- Generated agents MUST be SubAgent-type (declarative, no Python code generation).
- Skill harmonization MUST be performed before agent generation when combining multiple skills.
- Generated agents MUST be loadable at Soothe startup via manifest scanning.
- Tool selection MUST reuse langchain tools (`BaseTool` / `@tool`) where available.
- MCP connections MUST use `langchain-mcp-adapters`.
- Every generation and registration action MUST pass `PolicyProtocol`.
- The reuse index and registry MUST be durable across restarts.

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
