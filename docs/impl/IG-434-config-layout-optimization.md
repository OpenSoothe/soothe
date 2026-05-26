# IG-434: Config Layout Optimization

## Goal

Reorganize `config.template.yml` and `config.dev.yml` for better user experience by:
1. Creating unified `agent` section consolidating all agent-related settings
2. Merging `autonomous` + `autopilot` (duplicate semantics) into single concept
3. Nesting advanced settings (loop, protocols, code_interpreter) under `agent`
4. Maintaining backward compatibility for existing configs

## Motivation

**Current Problems**:
- 444-line flat structure forces users to scroll entire file
- Agent-related settings scattered across 6 locations (assistant_name, autonomous, autopilot, agent_loop, protocols, code_interpreter)
- `autonomous` and `autopilot` describe same concept (self-driving) but are separate sections
- No progressive disclosure - internal tuning mixed with user-facing settings

**Target Outcome**:
- ~180 lines with collapsed defaults
- 8 logical top-level sections
- All agent settings in one `agent` block with progressive disclosure
- Minimal user config reduced to ~20 lines

## Files to Modify

| File | Change |
|------|--------|
| `packages/soothe/src/soothe/config/models.py` | Add `AgentConfig`, merge `AutonomousConfig+AutopilotConfig` |
| `packages/soothe/src/soothe/config/settings.py` | Use `AgentConfig`, add backward compatibility aliases |
| `config/config.template.yml` | Reorganize layout per proposal |
| `config/config.dev.yml` | Mirror new structure |

## Implementation Plan

### Phase 1: Pydantic Models (config/models.py)

#### Step 1.1: Create Unified AutonomousConfig

Merge `AutonomousConfig` + `AutopilotConfig` into single model:

```python
class AutonomousConfig(BaseModel):
    """Unified self-driving configuration (autonomous + autopilot merged).

    Controls 24/7 self-running behavior for both goal-level and daemon-level.

    Args:
        enabled_by_default: Whether new runs default to autonomous mode.
        max_iterations: Maximum iterations per autonomous thread.
        max_retries: Maximum retries per goal on failure.
        max_total_goals: Maximum goals allowed (RFC-0007 §5.6).
        max_goal_depth: Maximum hierarchy depth (RFC-0007 §5.6).
        max_parallel_goals: Maximum goals running simultaneously.
        enable_dynamic_goals: Enable/disable dynamic creation (RFC-0007 §5.4).

        # Former autopilot fields:
        max_send_backs: Per-goal send-back budget for consensus validation.
        checkpoint_interval: Iterations between periodic checkpoints.
        dreaming_enabled: Enter dreaming mode when all goals complete.
        dreaming_consolidation_interval: Seconds between memory consolidation.
        dreaming_health_check_interval: Seconds between health checks.
        scheduler_enabled: Whether scheduler service is active.
        max_scheduled_tasks: Maximum pending scheduled tasks.
        webhooks: Webhook URLs by event type.
    """

    # Goal execution (from old autonomous)
    enabled_by_default: bool = False
    max_iterations: int = 10
    max_retries: int = 2
    max_total_goals: int = Field(default=50, ge=1, le=500)
    max_goal_depth: int = Field(default=5, ge=1, le=10)
    max_parallel_goals: int = Field(default=3, ge=1, le=10)
    enable_dynamic_goals: bool = True

    # Orchestration (from old autopilot)
    max_send_backs: int = Field(default=3, ge=1, le=10)
    checkpoint_interval: int = Field(default=10, ge=1, le=100)

    # Dreaming
    dreaming_enabled: bool = True
    dreaming_consolidation_interval: int = Field(default=300, ge=10)
    dreaming_health_check_interval: int = Field(default=60, ge=5)

    # Scheduler
    scheduler_enabled: bool = True
    max_scheduled_tasks: int = Field(default=100, ge=1, le=1000)
    webhooks: dict[str, str | None] = Field(default_factory=dict)
```

#### Step 1.2: Create AgentConfig

New unified agent configuration:

```python
class AgentConfig(BaseModel):
    """Unified agent configuration with progressive disclosure.

    All agent-related settings consolidated in one section:
    - Basic: name, system_prompt (user identity)
    - Behavior: goal_completion_mode, final_response (response mode)
    - Autonomous: self-driving configuration (merged autonomous+autopilot)
    - Loop: AgentLoop internal tuning (collapsed)
    - Protocols: Planner, Policy, Durability backend selection
    - CodeInterpreter: Embedded QuickJS configuration

    Args:
        name: Display name for the assistant identity.
        system_prompt: System prompt override. None generates default using name.
        goal_completion_mode: How planner completion combines with execution heuristics.
        final_response: Whether to always synthesize final report or use adaptive heuristics.
        autonomous: Unified self-driving configuration.
        loop: AgentLoop configuration (IG-407).
        protocols: Protocol backends configuration.
        code_interpreter: Code interpreter middleware configuration.
    """

    # === BASIC (User Identity) ===
    name: str = "Soothe"
    system_prompt: str | None = None

    # === BEHAVIOR (Response Mode) ===
    goal_completion_mode: AgenticGoalCompletionMode = "llm_only"
    final_response: AgenticFinalResponseMode = "adaptive"

    # === AUTONOMOUS (Self-Driving - Unified) ===
    autonomous: AutonomousConfig = Field(default_factory=AutonomousConfig)

    # === LOOP (AgentLoop Internal Tuning) ===
    loop: AgentLoopConfig = Field(default_factory=AgentLoopConfig)

    # === PROTOCOLS (Backend Selection) ===
    protocols: ProtocolsConfig = Field(default_factory=ProtocolsConfig)

    # === CODE INTERPRETER ===
    code_interpreter: CodeInterpreterConfig = Field(default_factory=CodeInterpreterConfig)
```

#### Step 1.3: Deprecate Old AutopilotConfig

Mark `AutopilotConfig` as deprecated but keep for backward compatibility:

```python
class AutopilotConfig(BaseModel):
    """DEPRECATED: Use AgentConfig.autonomous instead.

    This model is retained for backward compatibility with old config files.
    All fields migrate to AutonomousConfig in unified agent section.
    """

    # ... same fields, add deprecation warning in docstring
```

### Phase 2: Settings (config/settings.py)

#### Step 2.1: Add Agent Field

```python
class SootheConfig(BaseSettings):
    # === NEW UNIFIED AGENT SECTION ===
    agent: AgentConfig = Field(default_factory=AgentConfig)

    # === BACKWARD COMPATIBILITY ALIASES (deprecated) ===
    assistant_name: str | None = None  # → agent.name
    system_prompt: str | None = None   # → agent.system_prompt
    autonomous: AutonomousConfig | None = None  # → agent.autonomous
    autopilot: AutopilotConfig | None = None    # → agent.autonomous
    agent_loop: AgentLoopConfig | None = None   # → agent.loop
    protocols: ProtocolsConfig | None = None    # → agent.protocols
    code_interpreter: CodeInterpreterConfig | None = None  # → agent.code_interpreter
```

#### Step 2.2: Add Migration Validators

```python
@model_validator(mode="before")
@classmethod
def _migrate_legacy_flat_keys(cls, data: Any) -> Any:
    """Migrate old flat keys to unified agent section."""
    if not isinstance(data, dict):
        return data

    agent = dict(data.get("agent") or {})

    # Migrate assistant_name → agent.name
    if "assistant_name" in data and "name" not in agent:
        agent["name"] = data["assistant_name"]

    # Migrate system_prompt → agent.system_prompt
    if "system_prompt" in data and "system_prompt" not in agent:
        agent["system_prompt"] = data["system_prompt"]

    # Migrate autonomous → agent.autonomous
    if "autonomous" in data and "autonomous" not in agent:
        autonomous_data = data["autonomous"]
        if isinstance(autonomous_data, dict):
            agent["autonomous"] = autonomous_data

    # Migrate autopilot → agent.autonomous (merge)
    if "autopilot" in data:
        autopilot_data = data["autopilot"]
        if isinstance(autopilot_data, dict):
            existing_autonomous = agent.get("autonomous") or {}
            merged = {**existing_autonomous, **autopilot_data}
            agent["autonomous"] = merged

    # Migrate agent_loop → agent.loop
    if "agent_loop" in data and "loop" not in agent:
        agent["loop"] = data["agent_loop"]

    # Migrate protocols → agent.protocols
    if "protocols" in data and "protocols" not in agent:
        agent["protocols"] = data["protocols"]

    # Migrate code_interpreter → agent.code_interpreter
    if "code_interpreter" in data and "code_interpreter" not in agent:
        agent["code_interpreter"] = data["code_interpreter"]

    if agent:
        data["agent"] = agent

    return data
```

#### Step 2.3: Update Property Accessors

```python
@property
def assistant_name(self) -> str:
    """Backward compatibility: maps to agent.name."""
    return self.agent.name

@property
def system_prompt(self) -> str | None:
    """Backward compatibility: maps to agent.system_prompt."""
    return self.agent.system_prompt

def resolve_system_prompt(self) -> str:
    """Return effective system prompt using agent.name."""
    ...
```

### Phase 3: YAML Templates

#### Step 3.1: config.template.yml New Layout

```yaml
# ============================================================
# SOOTHE CONFIGURATION
# ============================================================

# ============================================================
# AGENT (Identity, Behavior, Self-Driving, Loop, Protocols)
# ============================================================
agent:
  name: Soothe
  system_prompt: null
  goal_completion_mode: llm_only
  final_response: adaptive

  autonomous:
    enabled_by_default: false
    max_iterations: 10
    max_parallel_goals: 3
    dreaming_enabled: true
    scheduler_enabled: true

  loop:
    enabled: true
    max_iterations: 10
    limits:
      max_parallel_tools: 5

  protocols:
    planner: { model: think, routing: auto }
    policy: { profile: standard }

  code_interpreter:
    enabled: true

# ============================================================
# PROVIDERS (LLM & Embedding)
# ============================================================
providers:
  - name: openai
    api_key: ${OPENAI_API_KEY}
    models: [gpt-4o, gpt-4o-mini]

router:
  default: openai:gpt-4o-mini

# ... rest of sections ...
```

#### Step 3.2: config.dev.yml Mirror Structure

Same layout with dev-specific defaults.

### Phase 4: Verification

1. Run `./scripts/verify_finally.sh` - all tests must pass
2. Test backward compatibility: old config files should still work
3. Test new config: `soothe --config config.template.yml` should parse correctly

## Status

- [ ] Phase 1: Pydantic models (models.py)
- [ ] Phase 2: Settings integration (settings.py)
- [ ] Phase 3: YAML templates reorganization
- [ ] Phase 4: Verification and testing

## Notes

- Backward compatibility is CRITICAL - existing user configs must work
- Deprecation warnings will be logged for old flat keys
- Migration is automatic via validators
- Target: minimal user config ~20 lines vs current 444