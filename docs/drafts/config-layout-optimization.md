# Config Layout Optimization Proposal (v2)

## Current State Analysis

**File**: `config/config.template.yml` (444 lines)

### Problems with Current Layout

| Issue | Impact |
|-------|--------|
| Flat root-level structure | User must scroll 400+ lines to find settings |
| Mixed concern ordering | `providers` → `subagents` → `tools` → `persistence` → `protocols` → `agent_loop` (no logical grouping) |
| Scattered related settings | `assistant_name` (line 51) buried; `autonomous` and `autopilot` are duplicate concepts |
| Duplicate semantic sections | `autonomous` (goal self-driving) and `autopilot` (daemon self-driving) are the same concept split across 2 sections |
| Deeply nested sections | `agent_loop` has 90+ lines with 6 levels of nesting |
| Advanced settings orphaned | `agent_loop`, `protocols`, `code_interpreter` in separate "advanced" section |

---

## Proposed Layout

### Design Principles

1. **User-first ordering**: Most commonly edited settings at the top
2. **Logical grouping**: All agent behavior in ONE `agent` section
3. **Unified semantics**: Merge `autonomous` + `autopilot` into single concept
4. **Progressive disclosure**: Simple settings first, deep tuning nested below
5. **Collapsed defaults**: Internal defaults collapsed inline

### New Structure (8 Top-level Sections)

```yaml
# ============================================================
# SOOTHE CONFIGURATION
# ============================================================
# Quick Start: Edit [agent.name] and [providers] sections below.
# Advanced tuning nested under agent.loop, agent.protocols.

# ============================================================
# AGENT (Identity, Behavior, Self-Driving, Loop Tuning)
# ============================================================
# All agent-related settings consolidated in one section.
# Progressive disclosure: basic → behavior → autonomous → loop → protocols

agent:
  # === BASIC (User Identity) ===
  name: Soothe
  system_prompt: null

  # === BEHAVIOR (Response Mode) ===
  goal_completion_mode: llm_only
  final_response: adaptive

  # === AUTONOMOUS (Self-Driving / Autopilot - Unified) ===
  # Merges former 'autonomous' + 'autopilot' sections.
  # These control 24/7 self-running behavior.
  autonomous:
    enabled_by_default: false

    # Goal execution limits
    max_iterations: 10
    max_retries: 2
    max_total_goals: 50
    max_goal_depth: 5
    max_parallel_goals: 3
    enable_dynamic_goals: true

    # Autopilot orchestration (daemon-level self-driving)
    max_send_backs: 3
    checkpoint_interval: 10

    # Dreaming (background consolidation)
    dreaming_enabled: true
    dreaming_consolidation_interval: 300
    dreaming_health_check_interval: 60

    # Scheduled tasks
    scheduler_enabled: true
    max_scheduled_tasks: 100
    webhooks: {}

  # === LOOP (AgentLoop Internal Tuning) ===
  # Rarely edited. Defaults optimized for most use cases.
  loop:
    enabled: true
    max_iterations: 10
    max_subagent_tasks_per_wave: 4
    prior_conversation_limit: 10
    context_window_limit: 200000

    # Output streaming (RFC-614)
    output_streaming:
      mode: adaptive
      streaming_interval_ms: 200
      message_coalesce_enabled: true
      tui_flush_interval_ms: 200

    # Working memory
    working_memory:
      enabled: true
      max_inline_chars: 4000

    # Goal context
    goal_context:
      enabled: true
      plan_limit: 10
      execute_limit: 10

    # Limits (throttle controls)
    limits:
      max_parallel_steps: 2
      max_parallel_subagents: 4
      max_parallel_tools: 5
      llm_rpm_limit: 120
      llm_concurrent_limit: 10
      llm_call_timeout_seconds: 120
      tool_call_limit:
        global_thread_limit: 150
        global_run_limit: 56

    # Recovery
    recovery:
      progressive_checkpoints: true
      auto_resume_on_start: false

  # === PROTOCOLS (Planner, Policy, Durability) ===
  # Backend protocol selection. Rarely edited.
  protocols:
    planner:
      model: think
      routing: auto
      use_fast_model: true
    policy:
      profile: standard
    durability:
      backend: default
      thread_inactivity_timeout_hours: 72

  # === CODE INTERPRETER (Embedded QuickJS) ===
  code_interpreter:
    enabled: true
    memory_limit_mb: 128
    timeout_seconds: 30

# ============================================================
# PROVIDERS (LLM & Embedding Models)
# ============================================================
providers:
  - name: openai
    provider_type: openai
    api_key: ${OPENAI_API_KEY}
    models: [gpt-4o, gpt-4o-mini, o3-mini]

router:
  default: openai:gpt-4o-mini
  think: null
  fast: null
  embedding: null

embedding_dims: 1536

# ============================================================
# TOOLS (Capabilities Available to Agent)
# ============================================================
tools:
  execution: { enabled: true }
  file_ops: { enabled: true }
  datetime: { enabled: true }
  data: { enabled: true }
  wizsearch:
    enabled: true
    default_engines: [tavily]
    max_results_per_engine: 10
  deepxiv:
    enabled: true
    token: null
  http_requests:
    enabled: true
    allow_dangerous_requests: true

# ============================================================
# SUBAGENTS (Specialized Helper Agents)
# ============================================================
subagents:
  explore:
    enabled: true
    model: null
    config:
      thoroughness: medium
      max_iterations: { quick: 6, medium: 10, thorough: 16 }
  plan:
    enabled: true
  tacitus:
    enabled: true
    config:
      effort: normal

# ============================================================
# MEMORY (Agent Memory System)
# ============================================================
memory:
  enabled: true
  persist_dir: null
  enable_auto_categorization: true
  enable_category_summaries: true
  categories:
    - { name: personal_info, description: Personal information }
    - { name: preferences, description: User preferences }
    - { name: knowledge, description: Facts and learned information }
    - { name: experiences, description: Past experiences }
    - { name: goals, description: Goals and objectives }

# ============================================================
# UI & OBSERVABILITY (Display, Logging, Tracing)
# ============================================================
ui:
  theme: null
  tui_debug: false
  activity_max_lines: 300

observability:
  verbosity: normal
  log_file_level: INFO
  debug: false
  langfuse:
    enabled: false
    public_key: null
    secret_key: null

# ============================================================
# PERSISTENCE & STORAGE (Database, Vector Stores, Workspace)
# ============================================================
persistence:
  default_backend: sqlite
  soothe_postgres_dsn: null
  postgres_pool_min_size: 4

vector_stores:
  - name: sqlite_vec_default
    provider_type: sqlite_vec

vector_store_router:
  default: sqlite_vec_default:soothe_default

# ============================================================
# SECURITY (Access Control & Sandbox)
# ============================================================
security:
  sandbox: false
  allow_paths_outside_workspace: false
  denied_paths:
    - /etc/**
    - ~/.ssh/**
    - ~/.gnupg/**
    - ~/.aws/**
    - '**/.env'
  require_approval_for_file_types:
    - .env
    - .pem
    - .key
```

---

## Key Merges

### 1. Unified `agent` Section (All Agent Settings)

**Before**: Scattered across 6 locations
- `assistant_name` (root)
- `system_prompt` (root)
- `autonomous.*` (root section)
- `autopilot.*` (root section)
- `agent_loop.*` (root section)
- `protocols.*` (root section)

**After**: One unified `agent` section with nested subsections

```yaml
agent:
  name: ...
  system_prompt: ...
  autonomous: ...    # Merged autonomous + autopilot
  loop: ...          # Former agent_loop
  protocols: ...     # Planner, policy, durability
  code_interpreter: ...
```

### 2. Merge `autonomous` + `autopilot`

**Problem**: Two sections with overlapping semantics
- `autonomous`: Goal-level self-driving (max_iterations, max_goals)
- `autopilot`: Daemon-level self-driving (dreaming, scheduling)

**Both describe "agent running itself"** - should be unified.

**After**: Single `agent.autonomous` section

```yaml
agent:
  autonomous:
    # Goal execution (from old 'autonomous')
    enabled_by_default: false
    max_iterations: 10
    max_total_goals: 50
    max_parallel_goals: 3

    # Orchestration (from old 'autopilot')
    max_send_backs: 3
    checkpoint_interval: 10
    dreaming_enabled: true
    scheduler_enabled: true
```

### 3. Collapse `agent_loop` → `agent.loop`

**Before**: 90-line root-level `agent_loop` section

**After**: Nested `agent.loop` with collapsed defaults

```yaml
agent:
  loop:
    enabled: true
    max_iterations: 10
    # Deep tuning collapsed (limits, recovery, working_memory)
```

User sees `agent.loop.max_iterations` at top level of subsection - clear semantic path.

### 4. Collapse `protocols` → `agent.protocols`

**Before**: Root-level `protocols` section

**After**: Nested `agent.protocols` - these ARE agent behavior protocols

```yaml
agent:
  protocols:
    planner: { model: think, routing: auto }
    policy: { profile: standard }
    durability: { thread_inactivity_timeout_hours: 72 }
```

---

## Migration Mapping

| Old Location | New Location |
|--------------|--------------|
| `assistant_name` | `agent.name` |
| `system_prompt` | `agent.system_prompt` |
| `goal_completion_mode` (in agent_loop) | `agent.goal_completion_mode` |
| `final_response` (in agent_loop) | `agent.final_response` |
| `autonomous.*` | `agent.autonomous.*` |
| `autopilot.*` | `agent.autonomous.*` (merged) |
| `agent_loop.*` | `agent.loop.*` |
| `protocols.*` | `agent.protocols.*` |
| `code_interpreter.*` | `agent.code_interpreter.*` |
| `memory.*` (in protocols) | `memory.*` (top-level, user-facing) |
| `ui.theme` | `ui.theme` |
| `tui_debug` | `ui.tui_debug` |
| `activity_max_lines` | `ui.activity_max_lines` |

---

## Example: Minimal User Config

```yaml
# ============================================================
# SOOTHE CONFIGURATION - Quick Start
# ============================================================
# 1. Set API key: export OPENAI_API_KEY=sk-...
# 2. Edit agent.name if desired
# 3. Run: soothe --config this-file.yml

agent:
  name: Soothe
  autonomous:
    enabled_by_default: false

providers:
  - name: openai
    api_key: ${OPENAI_API_KEY}
    models: [gpt-4o, gpt-4o-mini]

router:
  default: openai:gpt-4o-mini

tools:
  wizsearch:
    default_engines: [tavily]

# All other sections use defaults.
# Edit nested agent.loop/agent.protocols only for advanced tuning.
```

**Lines for basic setup**: ~20 (vs 444 currently)

---

## Comparison

| Metric | Current | Proposed |
|--------|---------|----------|
| Total lines | 444 | ~180 (collapsed) |
| Lines for basic setup | 444 | **~20** |
| Top-level sections | 20+ flat keys | **8 logical groups** |
| Agent-related settings | Scattered in 6 sections | **One `agent` block** |
| Autonomous + Autopilot | 2 separate sections | **Unified `agent.autonomous`** |
| User-facing first | No | **Yes** |
| Progressive disclosure | No | **Yes** |

---

## Top-Level Sections (Final)

| Section | Purpose | User Edits |
|---------|---------|------------|
| `agent` | Identity, behavior, self-driving, loop, protocols | **Often** (name, autonomous.enabled) |
| `providers` | LLM providers and models | **Often** (api_key) |
| `tools` | Available capabilities | **Sometimes** (wizsearch.engines) |
| `subagents` | Helper agents | Rare |
| `memory` | Memory categories | Rare |
| `ui` + `observability` | Display and logging | Rare |
| `persistence` + `vector_stores` | Storage backends | Rare |
| `security` | Access control | Rare |

---

## Migration Path

### Step 1: Update Pydantic Models

Create unified `AgentConfig`:

```python
class AutonomousConfig(BaseModel):
    """Unified self-driving configuration (autonomous + autopilot merged)."""
    enabled_by_default: bool = False
    max_iterations: int = 10
    max_retries: int = 2
    max_total_goals: int = 50
    max_goal_depth: int = 5
    max_parallel_goals: int = 3
    enable_dynamic_goals: bool = True
    # From old autopilot:
    max_send_backs: int = 3
    checkpoint_interval: int = 10
    dreaming_enabled: bool = True
    dreaming_consolidation_interval: int = 300
    dreaming_health_check_interval: int = 60
    scheduler_enabled: bool = True
    max_scheduled_tasks: int = 100
    webhooks: dict = {}

class AgentLoopConfig(BaseModel):
    """AgentLoop internal tuning."""
    enabled: bool = True
    max_iterations: int = 10
    # ... collapsed nested fields ...

class AgentConfig(BaseModel):
    """Unified agent configuration."""
    name: str = "Soothe"
    system_prompt: Optional[str] = None
    goal_completion_mode: str = "llm_only"
    final_response: str = "adaptive"
    autonomous: AutonomousConfig = AutonomousConfig()
    loop: AgentLoopConfig = AgentLoopConfig()
    protocols: ProtocolConfig = ProtocolConfig()
    code_interpreter: CodeInterpreterConfig = CodeInterpreterConfig()
```

### Step 2: Backward Compatibility Aliases

```python
class SootheConfig(BaseModel):
    agent: AgentConfig = AgentConfig()

    # Legacy flat-key aliases (deprecated, warn on use)
    assistant_name: Optional[str] = None  # → agent.name
    autonomous: Optional[dict] = None     # → agent.autonomous
    autopilot: Optional[dict] = None      # → agent.autonomous (merged)
    agent_loop: Optional[dict] = None     # → agent.loop

    @field_validator("assistant_name", mode="before")
    def migrate_assistant_name(cls, v, info):
        if v is not None:
            info.data["agent"]["name"] = v
        return v
```

### Step 3: Update config.dev.yml + config.template.yml

Reorganize both files to match new structure.

### Step 4: Update User Guide

Document unified `agent` section in `docs/user_guide.md`.

---

## Recommendation

**Adopt v2 layout** with unified `agent` section as the centerpiece:

1. **Phase 1**: Reorganize YAML templates (config.template.yml, config.dev.yml)
2. **Phase 2**: Update Pydantic models with backward compatibility
3. **Phase 3**: Deprecate old flat keys with migration warnings
4. **Phase 4**: Update user documentation