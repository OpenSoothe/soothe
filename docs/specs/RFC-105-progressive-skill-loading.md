# RFC-105: Progressive Skill Loading

**RFC**: 105
**Title**: Progressive Skill Loading
**Status**: Draft
**Kind**: Implementation Interface Design
**Created**: 2026-05-29
**Last Updated**: 2026-07-03
**Authors**: Platonic brainstorming session
**Design Draft**: [2026-05-29-progressive-skill-loading-design.md](../archive/drafts/2026-05-29-progressive-skill-loading-design.md)
**Revision Draft**: [2026-07-03-skill-runtime-discovery-design.md](../archive/drafts/2026-07-03-skill-runtime-discovery-design.md) (IG-543)
**Depends On**: RFC-100 (CoreAgent Runtime), RFC-104 (Dynamic System Context), RFC-214 (StrangeLoop Loop Message Surface), RFC-600 (Plugin Extension System)

## Abstract

This RFC replaces deepagents' always-emit-all skill listing with a progressive disclosure pipeline modeled on Claude Code and symmetric with `progressive_tools`: (1) a budgeted, delta-only **core-tier** metadata listing on turn 0; (2) **deferred** skills discovered via path hooks or `search_skills`; (3) lazy SKILL.md body injection via `invoke_skill` or `/skill:`. Activation state lives on the agent graph state at runtime and is snapshotted to `LoopState` at each iteration boundary so reconnect, resume, and compaction restore the per-thread view. The change is local to `SystemPromptMiddleware._compose_skills_block` and `SkillActivationMiddleware`; deepagents' `SkillsMiddleware` is suppressed at construction time by passing `skills=None` to `create_deep_agent`.

### Revision 2026-07-03 — Runtime discovery (IG-543)

**Problem addressed**: RFC-105 P0 listed every skill without `paths:` on turn 0; no model-facing search; three disjoint discovery channels.

**Changes**:

1. **Core / deferred partition** replaces unconditional / conditional for **listing**. Built-ins (and `core: true` / `core_skills` config) are core; all others deferred and hidden until discovered.
2. **`paths:`** remains an auto-discovery rule on **deferred** skills (file-op hook unchanged).
3. **`search_skills(query)`** — model discovers deferred skills by substring match; promotes metadata to next turn's `<AVAILABLE_SKILLS>`.
4. **`invoke_skill(name, args?)`** — model loads full SKILL.md body into `<SKILL_CONTEXT>` (CLI `/skill:` unchanged).
5. **`discover()`** — single registry mutation for path, search, and explicit channels; stored in `activation_state["activated"]` (LoopState: `activated_skill_names`).

### Revision 2026-07-03b — Semantic search + intent prefetch (IG-543 P1/P2)

**Changes**:

1. **`search_skills`** — when `progressive_skills.semantic_search_enabled`, substring results are supplemented by Skillify vector retrieval (`foundation/skillify` daemon-shared service).
2. **Turn-0 intent prefetch** — when `progressive_skills.intent_prefetch_enabled`, `SkillActivationMiddleware.abefore_agent` matches deferred skill names in the first user message (corpus match) and optionally semantic top-K; sets `intent_prefetched` so prefetch runs once per thread.
3. **Config** — `semantic_search_enabled`, `semantic_search_min_score`, `intent_prefetch_enabled`, `intent_prefetch_top_k`, `intent_prefetch_min_query_chars`.


### Problem: Linear cost, no filtering, no deltas

`deepagents.SkillsMiddleware` walks every SKILL.md path returned by `get_built_in_skills_paths()` plus any `config.skills` entries, parses frontmatter into `SkillMetadata`, and renders the `SKILLS_SYSTEM_PROMPT` block (name + description + path) into the system message on **every turn** for **every** discovered skill. This works for the built-in set (~4 skills today) but degrades as soon as workspace and community skills appear:

- Listing tokens scale linearly with installed skills and pay turn-0 cache-creation cost on every cold cache
- No path-based filtering — a Python-only skill is emitted on a turn that touches only Markdown
- No delta tracking — the same listing re-bills tokens after compaction, after `/clear`, and on reconnect
- No per-listing budget — a community pack with 50 skills can crowd out other system-prompt sections (workspace, thread, protocols)

### Reference: Claude Code's three-stage disclosure

Claude Code solved the analogous problem (`src/skills/loadSkillsDir.ts`, `src/utils/attachments.ts`, `src/tools/SkillTool/`) with:

1. **Budgeted metadata listing** — only `name + description [+ whenToUse]` reach the model on turn 0, capped at 1% of context window in chars, per-entry hard cap of 250 chars, bundled skills never truncated, sent skills tracked per-agent so subsequent turns only announce deltas.
2. **Conditional activation** — skills with `paths:` frontmatter are held in a `conditionalSkills` map and surfaced only when a file-op tool touches a matching path; gitignore-style glob matching via the `ignore` library.
3. **Body on invocation** — full SKILL.md body enters context only when the model calls the Skill tool; substitutions resolved at invocation time; bundled-skill reference files extracted lazily and memoized per-process.

### Design goals

1. **Bounded turn-0 cost** — only **core-tier** skills appear on turn 0; deferred skills stay hidden until discovered.
2. **Intent-based discovery** — `search_skills(query)` surfaces deferred skills on demand (parity with `search_tools`).
3. **Path-aware auto-discovery** — deferred skills with `paths:` frontmatter activate when a file-op tool touches a matching path.
4. **Delta-only re-emission** — a skill that has been announced to a thread is never re-announced unless evicted by compaction; state survives daemon restart, reconnect, and compaction.
5. **No double-listing** — exactly one source of truth for the `<AVAILABLE_SKILLS>` block; deepagents' stock listing is suppressed at agent construction.
6. **No new loop concept** — middleware operates on agent graph state and remains loop-agnostic; durability is achieved via a snapshot copy into `LoopState` at iteration boundaries (same pattern as `goal_user_submission`).

## Scope

- New: `ProgressiveSkillRegistry` (core/deferred partition + delta + path matching + `search_deferred` + `discover`), `format_skills_within_budget` (formatter), `SkillActivationMiddleware` (path + `search_skills` + `invoke_skill`), `ProgressiveSkillsConfig` (tunables), `<AVAILABLE_SKILLS>` and `<SKILL_CONTEXT>` system-prompt blocks, `search_skills` / `invoke_skill` tool stubs, `SkillActivatedEvent` / `SkillBodyLoadedEvent` events.
- Modified: `_parse_frontmatter`, `SkillIndexEntry`, `SystemPromptOptimizationMiddleware._get_prompt_for_complexity`, `build_soothe_middleware_stack`, `create_soothe_agent` (passes `skills=None`), `LoopState` (four snapshot fields), `StrangeLoop` iteration boundary (snapshot/rehydrate).
- Reused unchanged: `SkillIndex` metadata cache, `catalog.wire_entries_for_agent_config` aggregation, `build_skill_context_text`, `try_expand_slash_skill_user_line`, `sync_specific_skill_to_workspace`, `BUILTIN_TOOL_TRIGGERS`, `InternalEventBus`, `register_event` / `custom_event`, `_thread_id_from_request` / `_workspace_from_request`.

## Non-Goals

- MCP-provided skills (no `soothe.mcp.loader` exists in the tree today; broken imports at `core/thread/manager.py:24,553` reference a missing module — separate cleanup).
- Promotion of skills into the RFC-600 plugin extension point set (today only Tools and Subagents are extension points; skills remain a separate subsystem).
- Substitution semantics (`${CLAUDE_SKILL_DIR}`, `$ARGUMENTS`, inline shell) for invoked skill bodies — current explicit `/skill:<name>` path already handles this and is unchanged.
- Cross-thread skill bundling or sharing between concurrent threads.

## Guiding Principles

1. **Progressive disclosure over flat enumeration** — turn-0 carries only what the model needs to *decide* to use a skill; full body arrives at invocation.
2. **Workspace-aware, file-op-anchored activation** — file-op tools are the canonical signal for "the model is working on this kind of file"; broader heuristics (scanning exec-tool args for path-like substrings) are explicitly rejected for false-positive control.
3. **Cache-friendly tiering** — `<AVAILABLE_SKILLS>` lives in the static tier; `<SKILL_CONTEXT>` bodies live in the semi-static tier; both follow RFC-214 volatility ordering so prompt-cache hits are preserved.
4. **Durable snapshot, not loop coupling** — middleware mutates ordinary agent state; `LoopState` snapshots that state at iteration boundaries for restart/resume durability. No new cross-layer coupling.
5. **Replace, don't coexist** — deepagents' `SkillsMiddleware` is suppressed at construction (`skills=None`); soothe owns the single skill emission path.

## Architecture

### Component overview

```
                   ┌─────────────────────────────────┐
                   │  catalog.wire_entries_for_      │  (existing)
                   │  agent_config(config)           │
                   │  multi-root aggregation         │
                   └──────────────┬──────────────────┘
                                  │ SkillIndexEntry[]
                                  ▼
                   ┌─────────────────────────────────┐
                   │  ProgressiveSkillRegistry       │  (new)
                   │  partition / new_for_thread /   │
                   │  match_paths / mark_*           │
                   └──┬──────────────────────────┬───┘
                      │                          │
        unconditional │                          │ conditional
                      ▼                          ▼
   ┌──────────────────────────────┐  ┌─────────────────────────────┐
   │ SystemPromptOptimization     │  │ SkillActivationMiddleware   │
   │ ._compose_skills_block       │  │ .awrap_tool_call            │
   │                              │  │                             │
   │ writes <AVAILABLE_SKILLS> +  │  │ extracts paths from file-op │
   │ <SKILL_CONTEXT> blocks       │  │ tool args, matches via      │
   │                              │  │ pathspec, mutates state     │
   └──────────┬───────────────────┘  └──────────┬──────────────────┘
              │                                 │
              └────────────────┬────────────────┘
                               ▼
               ┌────────────────────────────────┐
               │ state["skill_activation"] =    │
               │   { sent, activated, invoked,  │
               │     invoked_bodies }           │
               └────────────────┬───────────────┘
                                │ snapshot at iteration boundary
                                ▼
               ┌────────────────────────────────┐
               │  LoopState                     │
               │  .sent_skill_names             │
               │  .activated_skill_names        │
               │  .invoked_skill_names          │
               │  .invoked_skill_bodies         │
               └────────────────────────────────┘
```

### Data flow

#### Flow 1: Turn 0 (cold cache, no prior activation)

1. `SystemPromptOptimizationMiddleware._get_prompt_for_complexity` runs during `modify_request`.
2. `_compose_skills_block(state, config)` reads `state["skill_activation"]` (empty dict on first turn, initialized lazily).
3. `ProgressiveSkillRegistry.partition(catalog_entries)` returns `(unconditional, conditional)`.
4. `candidates = unconditional ∪ activation_state["activated"]` (empty on turn 0).
5. `new = candidates - activation_state["sent"]` (= `unconditional` on turn 0).
6. `format_skills_within_budget(new, budget_chars)` returns truncated/full listing under budget.
7. Block emitted as static-tier `<AVAILABLE_SKILLS>`; names marked into `activation_state["sent"]`.

#### Flow 2: File-op tool call triggers activation

1. Model calls `read_file(file_path="src/main.py")`.
2. `SkillActivationMiddleware.awrap_tool_call` intercepts.
3. `tool_name` is in `FILE_OP_TOOLS` (sourced from `BUILTIN_TOOL_TRIGGERS`).
4. Paths extracted from `tool_call.args` via `_PATH_KEYS = ("file_path", "path", "filepath", "file")`.
5. Inside `asyncio.Lock` keyed by `(thread_id, skill_name)`, iterate conditional skills not yet activated.
6. For each: `pathspec.PathSpec.from_lines("gitwildmatch", skill.paths).match_file(p)` for each path.
7. On match: add to `activation_state["activated"]`, schedule fire-and-forget `sync_specific_skill_to_workspace`, emit `InternalSkillActivatedEvent` and `SkillActivatedEvent`.
8. Tool call proceeds unblocked; next `modify_request` picks up the new entry as a Stage-1 delta.

#### Flow 3: Skill invocation injects body

1. Model emits `/skill:python-helper` (or future `invoke_skill` tool).
2. `try_expand_slash_skill_user_line` expands the slash form into a user-turn block on **the current turn** (unchanged explicit path) and marks the skill in `state["skill_activation"]["invoked"]` with its body cached in `["invoked_bodies"]`.
3. On **subsequent** turns, `_compose_skills_block` reads `["invoked"]` and re-emits the body as a semi-static-tier `<SKILL_CONTEXT>` block from the `["invoked_bodies"]` cache. **De-duplication**: slash expansion is responsible only for the turn it fires on; `_compose_skills_block` skips any name whose body was injected by slash expansion on the current turn (signaled by a transient `state["skill_activation"]["just_invoked"]` set, cleared at the end of each `modify_request`). This ensures the body appears exactly once per turn.

#### Flow 4: Iteration boundary snapshot

1. `StrangeLoop` reaches iteration boundary in `core/loop/engine/strange_loop.py`.
2. Copies `state["skill_activation"]["sent" | "activated" | "invoked"]` into `LoopState.sent_skill_names`, `.activated_skill_names`, `.invoked_skill_names`.
3. Copies `state["skill_activation"]["invoked_bodies"]` dict into `LoopState.invoked_skill_bodies`.
4. On thread resume (cold daemon start, reconnect), `StrangeLoop` rehydrates `state["skill_activation"]` from `LoopState` before the first `modify_request`.

## Type Definitions

### Extended `SkillIndexEntry`

```python
@dataclass(frozen=True, slots=True)
class SkillIndexEntry:
    name: str
    description: str
    tags: str                          # existing — unchanged
    paths: tuple[str, ...] | None      # NEW — None means unconditional
    when_to_use: str | None            # NEW — multi-line guidance
    source: str
    path: Path
    mtime: float
```

`paths` uses a `tuple[str, ...]` for hashability and frozenness; `None` (not empty tuple) signals "unconditional" so the partitioner can treat `paths: []` in frontmatter as also unconditional without ambiguity.

### Frontmatter contract

```yaml
---
name: python-helper
description: One-line summary shown in the listing.
when_to_use: |
  Multi-line guidance the model sees when this skill is in the listing.
paths:                               # NEW — optional; presence makes the skill conditional
  - "src/**/*.py"
  - "tests/**"
tags: python                         # existing — unchanged
default_model: opus                  # existing — unchanged
---

# Full SKILL.md body... (Stage 3 only — never read at discovery time)
```

Semantics:
- No `paths:` or `paths: []` or `paths: ["**"]` → **unconditional**; appears in every listing turn (subject to budget).
- Has `paths: [<patterns>]` (non-empty, not all-`**`) → **conditional**; hidden until a file-op tool touches a matching path.
- Patterns use gitignore semantics via `pathspec`, matched against paths relative to workspace root.
- Trailing `/**` is stripped (matches the path and contents).
- `when_to_use` renders after `description` in the listing when present and budget allows; mirrors Claude Code's `whenToUse` field.

### Runtime state shape

```python
# state["skill_activation"] — agent graph state, mutated by middleware
{
    "sent": set[str],              # skill names already in <AVAILABLE_SKILLS> on prior turn
    "activated": set[str],         # conditional skills that matched a file-op path
    "invoked": set[str],           # skills whose body was injected via Stage 3
    "invoked_bodies": dict[str, str],   # body cache keyed by skill name; survives compaction
    "just_invoked": set[str],      # transient — slash expansion sets it on the current turn;
                                   # cleared at end of modify_request; used for de-duplication
                                   # so <SKILL_CONTEXT> doesn't double-print bodies
}
```

### LoopState snapshot fields

```python
class LoopState(BaseModel):
    # ... existing fields ...
    sent_skill_names: set[str] = Field(default_factory=set)
    activated_skill_names: set[str] = Field(default_factory=set)
    invoked_skill_names: set[str] = Field(default_factory=set)
    invoked_skill_bodies: dict[str, str] = Field(default_factory=dict)
```

These four fields are durable snapshots only; middleware reads/writes the agent graph state, never `LoopState` directly.

### `ProgressiveSkillsConfig`

```python
class ProgressiveSkillsConfig(BaseModel):
    budget_pct: float = 0.01
    max_listing_chars_per_entry: int = 250
    min_listing_chars_per_entry: int = 20
    core_skills: list[str] | None = None          # None → built-in defaults
    search_skills_enabled: bool = True            # bind search_skills + invoke_skill tools
```

### Discovery tools (2026-07-03)

Location: `packages/soothe/src/soothe/skills/discovery_tools.py`

```python
def create_search_skills_tool() -> StructuredTool: ...
def create_invoke_skill_tool() -> StructuredTool: ...
```

`SkillActivationMiddleware.awrap_tool_call` handles both tools (returns `Command` with `skill_activation` update). Path hook and slash expansion unchanged.

### Core / deferred partition

```python
DEFAULT_CORE_SKILL_NAMES = frozenset({"weather", "github", "clawhub", "skill-creator"})

def partition_core_deferred(
    entries: Sequence[SkillIndexEntry],
    core_names: frozenset[str],
) -> tuple[list[SkillIndexEntry], list[SkillIndexEntry]]: ...

def search_deferred(
    query: str,
    deferred: Sequence[SkillIndexEntry],
    *,
    discovered: set[str],
    limit: int = 10,
) -> list[SkillIndexEntry]: ...

def discover(activation_state: dict, names: Iterable[str], *, via: str) -> None: ...
```

Listing candidates: `core ∪ activated` (where `activated` = discovered set). Deferred skills enter `activated` via path, search, or explicit invoke.

## API Contracts

### `ProgressiveSkillRegistry`

Location: `packages/soothe/src/soothe/skills/registry.py`

```python
class ProgressiveSkillRegistry:
    def partition(
        self, entries: Sequence[SkillIndexEntry]
    ) -> tuple[list[SkillIndexEntry], list[SkillIndexEntry]]:
        """Split entries into (unconditional, conditional)."""

    def new_for_thread(
        self,
        activation_state: dict,
        candidates: Sequence[SkillIndexEntry],
    ) -> list[SkillIndexEntry]:
        """Return entries whose names are not yet in activation_state['sent']
        AND still present in the catalog (handles deleted-skill case)."""

    def match_paths(
        self,
        activation_state: dict,
        workspace: Path,
        file_paths: Sequence[str],
        conditional_skills: Sequence[SkillIndexEntry],
    ) -> list[str]:
        """Return newly-activated skill names. Idempotent against
        activation_state['activated']."""

    def mark_sent(self, activation_state: dict, names: Iterable[str]) -> None: ...
    def mark_activated(self, activation_state: dict, names: Iterable[str]) -> None: ...
    def mark_invoked(self, activation_state: dict, name: str, body: str) -> None: ...
    def cache_body(self, activation_state: dict, name: str, body: str) -> None: ...

    @staticmethod
    def init_activation_state() -> dict:
        """Return an empty activation_state dict in the canonical shape."""
```

Path matching delegates to `pathspec.PathSpec.from_lines("gitwildmatch", patterns)`. The registry is a stateless helper — all state lives in the `activation_state` dict the caller passes in.

### `format_skills_within_budget`

Location: `packages/soothe/src/soothe/skills/budget.py`

```python
def format_skills_within_budget(
    entries: Sequence[SkillIndexEntry],
    *,
    budget_chars: int,
    per_entry_cap_chars: int = 250,
    min_per_entry_chars: int = 20,
) -> tuple[str, BudgetTelemetry]:
    """Format skill listing within a character budget.

    Modes:
      - "full"        — under budget, every entry gets full description
      - "truncated"   — over budget, non-built-ins share remaining budget;
                        built-ins always keep full description
      - "names_only"  — extreme case (per-entry quota < min), non-built-ins
                        become names-only; built-ins keep full description

    Returns:
      (formatted_text, telemetry) where telemetry is a TypedDict with
      included_count, truncated_count, mode, budget_chars, actual_chars.
    """
```

Mirrors `src/tools/SkillTool/prompt.ts:formatCommandsWithinBudget` in Claude Code.

### `SkillActivationMiddleware`

Location: `packages/soothe/src/soothe/middleware/skill_activation.py`

```python
class SkillActivationMiddleware(AgentMiddleware):
    FILE_OP_TOOLS: frozenset[str] = frozenset(
        # subset of BUILTIN_TOOL_TRIGGERS that takes a file path
        {"read_file", "write_file", "edit_file", "glob", "grep",
         "delete_file", "insert_lines", "apply_diff", "file_info"}
    )
    _PATH_KEYS: tuple[str, ...] = ("file_path", "path", "filepath", "file")

    def __init__(
        self,
        registry: ProgressiveSkillRegistry,
        catalog_provider: Callable[[], Sequence[SkillIndexEntry]],
        config: SootheConfig,
        internal_bus: InternalEventBus,
    ) -> None: ...

    async def abefore_agent(self, state, runtime) -> dict | None:
        """Lazy-init state['skill_activation'] if missing; rehydrate from
        LoopState snapshot if StrangeLoop placed it there."""

    async def awrap_tool_call(self, request, handler, runtime):
        """If request.tool_name in FILE_OP_TOOLS, extract paths and run
        registry.match_paths. Newly-activated skills are added to
        activation_state['activated'], synced to workspace (fire-and-forget),
        and announced via SkillActivatedEvent + InternalSkillActivatedEvent.
        Activation never blocks the tool call; the lock guards only the
        activation side-effects per (thread_id, skill_name)."""
```

Order in `build_soothe_middleware_stack`:
`SoothePolicy → SkillActivation (new) → ToolConcurrency → NetworkToolErrors → SystemPromptOptimization → …`

### `_compose_skills_block` extension to `SystemPromptOptimizationMiddleware`

Private helper added to `packages/soothe/src/soothe/middleware/system_prompt_optimization.py`, invoked from `_get_prompt_for_complexity` (around line 286–458):

```python
def _compose_skills_block(
    self,
    state: dict,
    config: SootheConfig,
    registry: ProgressiveSkillRegistry,
    catalog_provider: Callable[[], Sequence[SkillIndexEntry]],
) -> tuple[str, str]:
    """Compose the static-tier <AVAILABLE_SKILLS> block and the
    semi-static-tier <SKILL_CONTEXT> blocks.

    Returns:
      (available_skills_block, invoked_skill_context_blocks)
    """
```

The block layout follows existing static/semi-static tiering so prompt-cache hits are preserved (RFC-214 §"Cache volatility ordering").

### Agent builder change

In `packages/soothe/src/soothe/core/agent/_builder.py:199-211`, the existing:

```python
all_skills = get_built_in_skills_paths() + (config.skills or [])
agent = create_deep_agent(..., skills=all_skills or None, ...)
```

becomes:

```python
# Skills emission is owned by SystemPromptOptimizationMiddleware via
# ProgressiveSkillRegistry; deepagents' SkillsMiddleware must not also emit.
agent = create_deep_agent(..., skills=None, ...)
```

No post-construction surgery on the deepagents middleware list.

### StrangeLoop snapshot bridge

In `packages/soothe/src/soothe/core/loop/engine/strange_loop.py`, at each iteration boundary (the same point that snapshots `goal_user_submission` and other transient fields onto `LoopState`):

```python
activation = state.get("skill_activation") or ProgressiveSkillRegistry.init_activation_state()
loop_state.sent_skill_names = set(activation["sent"])
loop_state.activated_skill_names = set(activation["activated"])
loop_state.invoked_skill_names = set(activation["invoked"])
loop_state.invoked_skill_bodies = dict(activation["invoked_bodies"])
```

On resume (cold daemon start or reconnect), the inverse copy happens once before the first `modify_request`.

## Events

Two new public events registered via `register_event` in `packages/soothe/src/soothe/core/events/catalog.py:567`:

```python
class SkillActivatedEvent(SootheEvent):
    type: str = "soothe.skill.activated"
    skill_name: str
    matched_path: str
    pattern: str
    thread_id: str

class SkillBodyLoadedEvent(SootheEvent):
    type: str = "soothe.skill.body.loaded"
    skill_name: str
    body_chars: int
    thread_id: str
```

Plus an internal event for cross-middleware coordination (does not leak to clients):

```python
class InternalSkillActivatedEvent(BaseModel):
    skill_name: str
    matched_path: str
    pattern: str
    thread_id: str
```

Naming follows the four-segment convention (`soothe.<domain>.<component>.<action>`) defined in RFC-401 and canonicalized in RFC-403. Domain is `skill` (new). Both events register `summary_template` strings for the event renderer.

## Module Layout

### New files

- `packages/soothe/src/soothe/skills/registry.py` — `ProgressiveSkillRegistry`
- `packages/soothe/src/soothe/skills/budget.py` — `format_skills_within_budget`
- `packages/soothe/src/soothe/middleware/skill_activation.py` — `SkillActivationMiddleware`
- `packages/soothe/src/soothe/skills/events.py` — event **model definitions** for `SkillActivatedEvent`, `SkillBodyLoadedEvent`, `InternalSkillActivatedEvent` (registration is performed centrally by `core/events/catalog.py:567` importing from here, per IG-052 self-registration pattern)

### Modified files

| File | Change |
|---|---|
| `skills/catalog.py:28` (`_parse_frontmatter`) | Accept `paths: str \| list[str]` and `when_to_use: str` (existing `tags: str` unchanged) |
| `skills/index.py:23` (`SkillIndexEntry`) | Add `paths: tuple[str, ...] \| None`, `when_to_use: str \| None`; keep existing `tags: str`; bump `SkillIndex.wire_entries()` (line 87) AND `catalog.wire_entries_for_agent_config()` (line 127) to surface the new fields in the wire-safe view |
| `core/loop/state/schemas.py` (`LoopState`) | Add four snapshot fields (`sent_skill_names`, `activated_skill_names`, `invoked_skill_names`, `invoked_skill_bodies`) |
| `core/loop/engine/strange_loop.py` | Iteration-boundary snapshot/rehydrate of `state["skill_activation"]` ↔ `LoopState` |
| `middleware/system_prompt_optimization.py` | Add private `_compose_skills_block`; wire into `_get_prompt_for_complexity` |
| `middleware/_builder.py:59` | Insert `SkillActivationMiddleware` after `SoothePolicyMiddleware`, before `ToolConcurrencyMiddleware` |
| `core/agent/_builder.py:199-211` | Pass `skills=None` to `create_deep_agent` |
| `core/events/catalog.py:567` | Register `SkillActivatedEvent` and `SkillBodyLoadedEvent` |
| `config/models.py` | Add `ProgressiveSkillsConfig`; expose as `SootheConfig.progressive_skills` |
| `config/config.template.yml`, `config/develop/nano.yml` | Mirror new `progressive_skills` section |
| `packages/soothe/pyproject.toml` | Add `pathspec` runtime dependency |

### Removed behavior

- Deepagents' `SkillsMiddleware` is never installed (we pass `skills=None`). The model retains access to `read_file` for explicit SKILL.md paths if needed.
- Slash-skill expansion (`try_expand_slash_skill_user_line`) is **kept** as the existing Stage-3 explicit path.

## Reused Primitives

| Need | Existing API | File:Line |
|---|---|---|
| Skill metadata cache (single-root) | `SkillIndex` | `skills/index.py:36` |
| Wire-shape entries (multi-root aggregated) | `wire_entries_for_agent_config` | `skills/catalog.py:127` |
| Compose full body | `build_skill_context_text` | `skills/catalog.py:304` |
| Materialize skill files for model | `sync_specific_skill_to_workspace` | `skills/workspace_sync.py:170` |
| Token counting | `count_tokens` | `utils/token_counting.py` |
| Context-window limit | `StrangeLoopConfig.context_window_limit` | `config/models.py:1001` |
| Canonical file-op tool set | `BUILTIN_TOOL_TRIGGERS` | `core/context/trigger_registry.py:12` |
| Path-key extraction (reference; middleware unwired today) | `FileLockMiddleware._PATH_KEYS` | `middleware/file_lock.py:41` |
| Public event registration | `register_event`, `custom_event` | `core/events/catalog.py:567,116` |
| Internal pub/sub | `InternalEventBus.emit/subscribe` | `core/events/internal_bus.py:25,45,76` |
| System-prompt assembly site | `SystemPromptOptimizationMiddleware._get_prompt_for_complexity` (private — extend in place) | `middleware/system_prompt_optimization.py:286` |
| Snapshot precedent | `goal_user_submission` mirrored at iteration boundary | `core/loop/state/schemas.py` |
| Path-glob matching | `pathspec` (gitignore semantics) | **new dep** |

## Cost Model

| Stage | What lives in context | Approximate cost |
|---|---|---|
| Index built | nothing — disk only | 0 tokens |
| Stage 1 listing | name + ≤250-char desc per unconditional skill (delta-only) | ≤ 1% of window (~2K tokens cap on a 200K window) |
| Stage 2 activation | adds delta rows to next turn's listing | per-skill delta only |
| Stage 3 invocation | full SKILL.md body for invoked skills | per-skill, only when used; cached in `invoked_bodies` |

For a workspace with 60 skills (4 built-in unconditional, 56 conditional path-filtered), turn-0 cost drops from ~12K tokens (current: all 60 emitted) to ~600 tokens (4 built-ins, full description). A Python-editing session activates 2–3 skills over the first few turns; a Markdown-editing session activates none of the Python-tagged skills.

## Concurrency & Edge Cases

- **`paths: ["**"]`** → treated as unconditional (Claude Code parity); avoids the trap where a "match-all" pattern hides the skill from turn-0.
- **Workspace switch mid-loop** → activation state is per-thread; if `workspace` changes via `RunnerState`, the next file-op call re-evaluates against the new workspace's conditional set.
- **Skill removed between sessions** → `sent_skill_names` snapshot may reference deleted skills; `new_for_thread` skips entries no longer in the index (idempotent).
- **Two skills with the same name across roots** (built-in vs workspace) → existing `SkillIndex` / catalog precedence rules apply unchanged.
- **Compaction** → `invoked_skill_bodies` snapshot rehydrates `state["skill_activation"]["invoked_bodies"]`; the next `modify_request` re-emits bodies into the semi-static tier without disk re-reads.
- **Concurrent file-op tool calls** → `ToolConcurrencyMiddleware` permits parallelism. `SkillActivationMiddleware` holds an `asyncio.Lock` per `(thread_id, skill_name)`; the first racing call wins activation, runs `sync_specific_skill_to_workspace`, and emits the event exactly once. Subsequent callers observe `skill.name in activation_state["activated"]` and short-circuit.
- **Paths outside workspace** → rejected (mirrors Claude Code's `activateConditionalSkillsForPaths` guard); the path must be within or relative to `workspace`.

## Verification Plan

### Unit tests

- `packages/soothe/tests/unit/skills/test_registry_partition.py` — `paths:` presence partitions correctly; trailing `/**` stripped; all-`**` patterns demote to unconditional.
- `packages/soothe/tests/unit/skills/test_registry_delta.py` — `new_for_thread` returns only un-sent skills; subsequent call returns `[]`; removing a skill between calls doesn't error.
- `packages/soothe/tests/unit/skills/test_path_matching.py` — gitignore-style positive/negative, `**`, anchored paths, paths outside workspace are rejected.
- `packages/soothe/tests/unit/skills/test_budget_formatter.py` — under-budget keeps full descs; over-budget truncates non-builtins; extreme case → names-only mode; built-ins always full.

### Middleware tests

- `packages/soothe/tests/unit/middleware/test_skill_activation_middleware.py` — file-op tool with matching path activates skill; non-file-op tool doesn't; non-matching path doesn't; idempotent on re-call; concurrent calls race-safe.
- `packages/soothe/tests/unit/middleware/test_system_prompt_skills_block.py` — deepagents stock listing absent; `<AVAILABLE_SKILLS>` respects budget; invoked-skill body re-emitted from `state["skill_activation"]["invoked_bodies"]` cache.

### Integration test

- `packages/soothe/tests/integration/skills/test_progressive_skill_flow.py` — end-to-end: create fixture skill with `paths: ["src/**/*.py"]`, start agent, issue `read_file("src/main.py")`, assert next turn's system prompt contains the activated skill name; invoke via `/skill:name`, assert body present in subsequent turn; assert `LoopState` snapshot contains all three sets populated after iteration boundary.

### Manual smoke (per CLAUDE.md Rule #5)

```bash
cd /Users/xiamingchen/Workspace/mirasurf/soothe
./scripts/verify_finally.sh                # mandatory: format + lint + 900+ unit tests

soothe daemon start --workspace /tmp/soothe-skill-test
# In /tmp/soothe-skill-test/.soothe/skills/python-helper/SKILL.md, set paths: ["**/*.py"]

# Attach CLI, prompt: "list files in this directory"
# Confirm via Langfuse trace:
#   - turn-0 system prompt does NOT contain python-helper
#   - after read_file / glob hits a .py path, next turn DOES contain it
#   - <AVAILABLE_SKILLS> token count ≤ 1% of context_window_limit
#   - soothe.skill.activated event appears in event stream on activation
```

## Open Questions

1. **Resume seeding** — `LoopState` is the right home, but should activation also seed from the workspace's `.soothe/state/` if a thread is resumed in a new daemon process? Current proposal: yes, via existing `StrangeLoopStateManager.load()` (no additional code path needed).
2. **Activation on current vs next turn** — should the newly-activated skill be (a) auto-injected into the *current* turn's response context, or (b) deferred to the next turn's `<AVAILABLE_SKILLS>` block? Claude Code does (b). Recommendation: (b) — keeps activation off the hot path and matches Claude Code semantics.
3. **MCP skill integration** — deferred; `soothe.mcp.loader` not yet present. Broken imports at `core/thread/manager.py:24,553` referencing the missing module are a separate cleanup.
4. **RFC-600 plugin extension** — promoting skills into the RFC-600 plugin extension point set is a follow-on RFC, not this one.

## Naming Conventions

- Block names: `<AVAILABLE_SKILLS>` (static tier listing) and `<SKILL_CONTEXT>` (semi-static tier body) — both bracketed XML-style tags consistent with RFC-104's `<SOOTHE_*>` convention.
- Event domain: `skill` (new; reserves `soothe.skill.*` for related events).
- State key: `state["skill_activation"]` — singular noun consistent with `state["files"]`, `state["todos"]` deepagents conventions.
- Config field: `SootheConfig.progressive_skills` (snake_case) matching peer config sections.

## Error Handling

- **Malformed `paths:` frontmatter** (not a string or list of strings) → log warning, treat skill as unconditional, continue catalog load.
- **`pathspec` parse error on a pattern** → log warning, skip that pattern, retain remaining patterns; if all patterns invalid, treat skill as unconditional.
- **`sync_specific_skill_to_workspace` failure** during activation → log error with `skill_name`, emit error event, keep activation state set so we don't retry on every subsequent file-op call.
- **Body cache miss after compaction** (invoked skill but body not in `invoked_bodies`) → re-read from `skill.path` and re-populate; log warning.
- **Activation lock acquisition timeout** (should never happen in practice but bounded) → log warning, skip activation for this tool call; the next file-op call retries.

## Related Documents

- [RFC-100: CoreAgent Runtime](RFC-100-coreagent-runtime.md)
- [RFC-104: Dynamic System Context Injection](RFC-104-dynamic-system-context.md)
- [RFC-214: StrangeLoop Loop Message Surface](RFC-214-strangeloop-loop-message-surface.md)
- [RFC-600: Plugin Extension System](RFC-600-plugin-extension-system.md)
- [Design Draft: Progressive Skill Loading](../archive/drafts/2026-05-29-progressive-skill-loading-design.md)
- [RFC Standard](./rfc-standard.md)
- [RFC Index](./rfc-index.md)
