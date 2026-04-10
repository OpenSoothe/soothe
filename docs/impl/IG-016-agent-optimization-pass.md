# IG-016: Agent Optimization Pass

## Objective

Optimise Soothe's runtime defaults, planner protocol, streaming output, and system
prompts so the agent works correctly out of the box and presents a professional identity.

## Scope

1. **Bug fixes**: workspace_dir defaults, Claude model type, vector backend fallback,
   headless session logging.
2. **Subagent cwd**: Scout gets its own FilesystemBackend; unused cwd removed from
   research/browser/skillify/weaver.
3. **Streaming output**: Resolve friendly capitalized subagent names from LangGraph
   namespace UUIDs.
4. **Planner protocol**: Three backends (DirectPlanner, SubagentPlanner, ClaudePlanner)
   plus AutoPlanner hybrid complexity router. Remove `none` option; default to `auto`.
5. **System prompts**: Rewrite main and subagent prompts; configurable assistant name;
   hide framework internals; emphasise long-running capability.
6. **Config defaults**: All subagents enabled; planner_routing `auto`.

## Changes

### 0. Bug Fixes

| File | Change |
|------|--------|
| `config.py` | `workspace_dir` default `"."` instead of `None` |
| `cli/main.py` | Resolve workspace_dir to absolute path; add `ThreadLogger` to headless mode |
| `core/resolver.py` | Claude model passed as string; vector context/memory with try/except fallback to keyword |

### 1. Subagent cwd

| File | Change |
|------|--------|
| `subagents/scout.py` | Add `FilesystemBackend` read-only tools using `cwd` |
| `subagents/research.py` | Remove `cwd` parameter |
| `subagents/browser.py` | Remove `cwd` parameter |
| `subagents/skillify/__init__.py` | Remove `cwd` parameter |
| `subagents/weaver/__init__.py` | Remove `cwd` parameter |
| `core/resolver.py` | Inject cwd only for `planner`, `scout`, `claude` |

### 2. Streaming Output

| File | Change |
|------|--------|
| `utils/streaming.py` | Track `tool_call_id -> subagent_name` mapping; capitalised display names |
| `cli/tui_shared.py` | Apply same friendly-name resolution for shared TUI handlers |

### 3. Planner Protocol

| File | Change |
|------|--------|
| `config.py` | Routing: `auto \| always_direct \| always_planner \| always_claude` (no `none`) |
| `cognition/planning/direct.py` | No change |
| `cognition/planning/subagent.py` | **New** -- SubagentPlanner via compiled planner subagent |
| `cognition/planning/claude.py` | **New** -- ClaudePlanner via compiled Claude subagent with planning prompt |
| `cognition/planning/router.py` | **New** -- AutoPlanner hybrid complexity router |
| `core/resolver.py` | Updated `resolve_planner()` with fallback chain |

### 4. System Prompts

| File | Change |
|------|--------|
| `config.py` | `assistant_name` field; rewritten default system prompt |
| `subagents/planner.py` | Cleaned prompt; no framework references |
| `subagents/scout.py` | Cleaned prompt; no framework references |
| `subagents/research.py` | Cleaned prompt; no framework references |
| `subagents/browser.py` | Cleaned description; no library references |

### 5. Config Defaults

| File | Change |
|------|--------|
| `config.py` | All subagents enabled by default |
| `config/config.yml` | Updated example config |

### 6. Tests

| File | Change |
|------|--------|
| `tests/unit_tests/test_subagents.py` | Updated for cwd changes |
| `tests/unit_tests/test_config.py` | Test new routing, assistant_name, defaults |

## Non-Goals

- Changing the PlannerProtocol interface itself (create_plan/revise_plan/reflect).
- Adding new subagent types.
- Modifying the TUI Textual layout.
