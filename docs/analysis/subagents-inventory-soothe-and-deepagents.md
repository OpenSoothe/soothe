# Subagents inventory: Soothe vs deepagents

This document describes **how subagents are exposed**, **what ships with deepagents**, and **which first-party subagents Soothe wires in** at agent construction time. For how subagents appear inside StrangeLoop plan steps, see [subagent-in-plan-steps-analysis.md](./subagent-in-plan-steps-analysis.md).

---

## How every subagent is reached

1. **Single user-facing tool**: the LangChain tool named **`task`** (built by deepagents `SubAgentMiddleware`).
2. **Selection**: the model passes **`subagent_type`** matching one of the registered subagent **`name`** strings (e.g. `general-purpose`, `explore`, `research`).
3. **Soothe patch**: `soothe/core/agent/_patch.py` replaces `deepagents.middleware.subagents._build_task_tool` so nested `invoke` / `ainvoke` receives **`runtime.config`** from the parent (streaming / configurable propagation).

---

## deepagents (upstream)

### Always present unless overridden: `general-purpose`

| Field | Value |
|--------|--------|
| **Name** | `general-purpose` |
| **Source** | `deepagents/graph.py` → `create_deep_agent()` builds `general_purpose_spec` from `GENERAL_PURPOSE_SUBAGENT` in `deepagents/middleware/subagents.py` |
| **Role** | Default delegate with the **same `tools`** as the main agent, plus standard middleware (todos, filesystem, summarization, prompt caching, patch tool calls; optional skills / interrupt_on) |
| **Suppression** | If the caller passes a subagent whose `name` is already `general-purpose`, deepagents **does not** add a second copy — that is the supported way to **replace** the general-purpose spec |

### Middleware and tool factory

| Component | Location | Role |
|-----------|----------|------|
| **`SubAgentMiddleware`** | `deepagents/middleware/subagents.py` | Exposes **`self.tools = [task_tool]`** to the main agent |
| **`_build_task_tool`** | Same module | Builds **`StructuredTool(name="task", ...)`** from the list of subagent specs (each with `name`, `description`, `runnable`) |
| **`TASK_TOOL_DESCRIPTION` / `TASK_SYSTEM_PROMPT`** | Same module | Default instructions and examples for when/how to use `task` |

### User / Soothe-provided entries

Anything passed as **`subagents=`** into `create_deep_agent()` (from Soothe: `resolve_subagents(config)` plus optional builder overrides) is merged according to deepagents rules:

- **`CompiledSubAgent`** (`name`, `description`, `runnable`): used as-is.
- **`SubAgent`** dict: deepagents fills defaults (`model`, `tools`, `middleware` stack) before compilation.

Soothe’s `AgentBuilder` passes that list here:

- `soothe/core/agent/_builder.py` → `create_deep_agent(..., subagents=all_subagents, ...)`

---

## Soothe first-party subagents

Factories are registered in **`soothe/core/resolver/_resolver_tools.py`** → **`SUBAGENT_FACTORIES`** (lazy import). Resolution order for each configured name: **plugin registry** (if loaded), else the core **`SUBAGENT_FACTORIES`** map (explore, plan, research only).

| `subagent_type` | Factory | Package / entry | In default `SootheConfig.subagents` merge? | Notes |
|-----------------|---------|-----------------|---------------------------------------------|--------|
| **`explore`** | `create_explore_subagent` | `soothe/subagents/explore/` | **Yes** (builtin merge; IG-324) | RFC-613 readonly filesystem search; `CompiledSubAgent`. |
| **`plan`** | `create_plan_subagent` | `soothe/subagents/plan/` | **Yes** | Planning delegate. |
| **`research`** | `create_research_subagent` | `soothe/subagents/research/` | **Yes** (builtin merge; IG-324) | Deep research / multi-source; receives full **`SootheConfig`** and `context.work_dir`. There is **no** `tools.research` group — research is **subagent-only**. |

Additional manifest ids (optional packages such as **`soothe-plugins`**) register through the plugin entry-point system; see that repository for names, factories, and YAML.

### Configuration defaults

- **`soothe/config/settings.py`** `_merge_subagents`: starts with **`explore`**, **`plan`**, and **`research`**; merges **plugin-discovered** subagent names from the global registry when plugins are loaded, then user YAML overrides.
- **`SubagentConfig.enabled`** defaults to **`true`**; set `enabled: false` under a name to drop it from `resolve_subagents()`.

### Plugin-discovered subagents

Third-party plugins can register additional names via the soothe plugin system; `resolve_subagents()` consults **`get_plugin_registry().get_subagent_factory(name)`** before `SUBAGENT_FACTORIES`.

---

## Effective subagent set at runtime

For a typical daemon with default config:

1. **`task`** is always available (deepagents).
2. **`subagent_type`** values always include **`general-purpose`** (deepagents).
3. Optional delegates from installed plugins (for example **`soothe-plugins`**) appear when those packages register factories; core defaults include **`explore`**, **`plan`**, and **`research`** when enabled.

The main graph’s tool list still includes deepagents builtins (e.g. todos, filesystem tools, **`task`**); Soothe adds toolkit tools separately via `resolve_tools()`.

---

## File index (quick navigation)

| Concern | Path |
|---------|------|
| Soothe agent build | `packages/soothe/src/soothe/core/agent/_builder.py` |
| Subagent list resolution | `packages/soothe/src/soothe/core/resolver/_resolver_tools.py` (`resolve_subagents`, `SUBAGENT_FACTORIES`) |
| `task` tool patch | `packages/soothe/src/soothe/core/agent/_patch.py` |
| Config merge | `packages/soothe/src/soothe/config/settings.py` (`_merge_subagents`) |
| deepagents `create_deep_agent` | site-packages `deepagents/graph.py` |
| deepagents subagent specs / `task` factory | site-packages `deepagents/middleware/subagents.py` |

---

## References

- [subagent-in-plan-steps-analysis.md](./subagent-in-plan-steps-analysis.md) — plan steps vs `task` usage
- deepagents docstrings: `SubAgent`, `CompiledSubAgent`, `GENERAL_PURPOSE_SUBAGENT`, `TASK_TOOL_DESCRIPTION` in `deepagents/middleware/subagents.py`
