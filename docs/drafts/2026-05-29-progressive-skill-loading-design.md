# Progressive Skill Loading

**Date:** 2026-05-29
**Status:** Draft
**Builds on:** RFC-104 (Dynamic System Context), RFC-206 (Prompt Architecture), RFC-214 (AgentLoop Loop Message Surface), RFC-600 (Plugin Extension System)
**Scope:** Replace deepagents' always-emit-all skills listing with a three-stage progressive disclosure pipeline modeled on Claude Code: budgeted turn-0 metadata listing with per-thread delta tracking, path-driven conditional activation during file-op tool calls, and lazy body injection on invocation.

---

## 1. Motivation

Soothe currently exposes skills through `deepagents.SkillsMiddleware`. The middleware walks every SKILL.md source path returned by `get_built_in_skills_paths()` plus any `config.skills` entries, parses frontmatter into `SkillMetadata`, and renders the `SKILLS_SYSTEM_PROMPT` block (name + description + path) into the system message on **every turn** for **every** discovered skill.

This works for the built-in set (~4 skills today: `skill-creator`, `weather`, `github`, `clawhub`) but degrades as soon as workspace and community skills appear:

- Listing tokens scale linearly with installed skills and pay turn-0 cache-creation cost on every cold cache
- No path-based filtering — a Python-only skill is emitted on a turn that touches only Markdown
- No delta tracking — the same listing re-bills tokens after compaction, after `/clear`, and on reconnect
- No per-listing budget — a community pack with 50 skills can crowd out other system-prompt sections (workspace, thread, protocols)

Claude Code solved the analogous problem with three-stage progressive disclosure (`src/skills/loadSkillsDir.ts`, `src/utils/attachments.ts`, `src/tools/SkillTool/`):

1. **Stage 1 — budgeted metadata listing**: only `name + description [+ whenToUse]` reach the model on turn 0, capped at 1% of context window in chars, per-entry hard cap of 250 chars, bundled skills never truncated, sent skills tracked per-agent so subsequent turns only announce deltas
2. **Stage 2 — conditional activation**: skills with `paths:` frontmatter are held in a `conditionalSkills` map and surfaced only when a file-op tool touches a matching path; gitignore-style glob matching via the `ignore` library
3. **Stage 3 — body on invocation**: full SKILL.md body enters context only when the model calls the Skill tool; substitutions (`${CLAUDE_SKILL_DIR}`, `${CLAUDE_SESSION_ID}`, `$ARGUMENTS`, inline shell) resolved at invocation time; for bundled skills, reference files are extracted to disk lazily and memoized per-process

Soothe already has the substrate for Stages 1 and 3:
- `skills/index.py:SkillIndex` — mtime-cached metadata index persisted to `~/.soothe/cache/skill_index.json`; `wire_entries()` (line 87–99) already serves a wire-safe metadata view without re-reading bodies
- `skills/catalog.py:build_skill_context_text` (line 304) — composes the full body string
- `skills/catalog.py:try_expand_slash_skill_user_line` (line 455) — existing explicit user-invoke path

What's missing is the budget, the deltas, the `paths:` field, the activation interceptor, and replacement of deepagents' stock emission. This draft specifies that replacement.

---

## 2. Design decisions

Three choices were settled before drafting:

| Decision | Resolution | Reason |
|---|---|---|
| Per-thread "activated skills" state location | Runtime on agent graph state (`state["skill_activation"]`); snapshotted to `LoopState` each iteration | Keeps middleware loop-agnostic; reuses the `goal_user_submission` snapshot pattern; LoopState snapshot still survives daemon restart, reconnect, and compaction |
| Stage-2 activation triggers | File-op tools only | Same scope as Claude Code's FileRead/Edit/Write; clearer mental model than scanning exec-tool arg strings for path-like substrings; lower false-positive rate |
| Rollout strategy | Replace existing skill loading entirely; no feature flag | Cleanest code path; avoids two competing skill-emission code paths; soothe owns the system-prompt assembly point (`SystemPromptOptimizationMiddleware`) so the replacement is local |

---

## 3. Architecture

```
Discovery (startup, lazy — unchanged structure, extended fields)
  catalog.wire_entries_for_agent_config(config) aggregates entries from:
    1. Built-in skill paths via get_built_in_skills_paths()
    2. User config via config.skills (covers ~/.soothe/skills and workspace .soothe/skills)
    3. Optional ~/.soothe-cache via SkillIndex (mtime-cached, single-root today)
  Each entry exposes the extended SkillIndexEntry:
    { name, description, tags, paths?, when_to_use?, source, path, mtime }

Partitioning (ProgressiveSkillRegistry, in-process singleton on daemon)
  unconditional = entries where paths is None or empty
  conditional   = entries where paths is non-empty (held back from listing)

Skill-activation state lives on the agent graph state at runtime under
state["skill_activation"] = { sent, activated, invoked, invoked_bodies }.
AgentLoop snapshots this dict into LoopState fields at each iteration boundary
(same pattern as goal_user_submission) so reconnect / resume / compaction restore
the per-thread view. This keeps middleware loop-agnostic and LoopState durable.

Stage 1: Budgeted metadata listing  (every turn, delta-only)
  SystemPromptOptimizationMiddleware._compose_skills_block (new private helper,
  invoked from _get_prompt_for_complexity alongside workspace/thread blocks)
    candidates = unconditional ∪ state["skill_activation"]["activated"]
    new       = candidates - state["skill_activation"]["sent"]
    formatted = format_skills_within_budget(new, budget = ctx_window * 0.01)
    emit as static-tier <AVAILABLE_SKILLS> block
    mark new names into state["skill_activation"]["sent"]

Stage 2: Path-based activation  (during file-op tool calls)
  SkillActivationMiddleware.awrap_tool_call
    if tool_name in FILE_OP_TOOLS:  # from BUILTIN_TOOL_TRIGGERS
      paths = extract_paths(tool_call.args)              # via local _PATH_KEYS
      async with self._activation_lock:                  # guards concurrent file-ops
        for skill in registry.conditional_for_workspace(ws):
          if skill.name in state["skill_activation"]["activated"]: continue
          if any pathspec.match_file(p, skill.paths) for p in paths:
            state["skill_activation"]["activated"].add(skill.name)
            await sync_specific_skill_to_workspace(config, ws, skill.name)
            await internal_bus.emit(InternalSkillActivatedEvent(...))
            yield custom_event(SkillActivatedEvent(...).to_dict())

Stage 3: Body on invocation  (two paths)
  Explicit (unchanged): /skill:<name> → try_expand_slash_skill_user_line → body wrapped in <SKILL_CONTEXT>
  Implicit (new):       model calls /skill:<name> OR a future invoke_skill tool
                        → _compose_skills_block appends build_skill_context_text(meta, body)
                          to semi-static tier for every name in state["skill_activation"]["invoked"]
                        → body cached in state["skill_activation"]["invoked_bodies"] so
                          re-emission after compaction doesn't re-read disk
```

The static/semi-static tiering follows RFC-214 volatility ordering so prompt-cache hits are preserved.

---

## 4. Frontmatter contract

Extends the existing `_parse_frontmatter` schema (`skills/catalog.py:28`) with two optional keys:

```yaml
---
name: python-helper
description: One-line summary shown in the listing.
when_to_use: |
  Multi-line guidance the model sees when this skill is in the listing.
paths:                                # NEW — optional; presence makes the skill conditional
  - "src/**/*.py"
  - "tests/**"
tools:                                # existing
  - read_file
default_model: opus                   # existing
---

# Full SKILL.md body... (Stage 3 only — never read at discovery time)
```

Semantics:
- No `paths:` → skill is **unconditional**; appears in every listing turn (subject to budget)
- Has `paths:` → skill is **conditional**; hidden until a file-op tool touches a matching path
- Patterns use gitignore semantics via `pathspec`, matched against paths relative to workspace root
- Trailing `/**` is stripped (matches the path and contents); all-`**` patterns treated as no filter (skill becomes unconditional)

`when_to_use` is rendered after `description` in the listing when present and budget allows, mirroring Claude Code's `whenToUse` field.

---

## 5. Module layout

### New modules

- **`packages/soothe/src/soothe/skills/registry.py`** — `ProgressiveSkillRegistry`
  - `partition(entries) -> (unconditional, conditional)` — splits aggregated catalog entries by `paths` presence
  - `new_for_thread(activation_state, candidates) -> list[SkillIndexEntry]` returns entries whose names are not yet in `activation_state["sent"]` and still present in the index (handles deleted-skill case)
  - `match_paths(activation_state, workspace, file_paths) -> list[str]` returns newly-activated skill names; idempotent against `activation_state["activated"]`
  - Helpers: `mark_sent(activation_state, names)`, `mark_activated(activation_state, names)`, `mark_invoked(activation_state, name, body)`, `cache_body(activation_state, name, body)`
  - Path matching delegates to `pathspec.PathSpec.from_lines("gitwildmatch", patterns)`
  - `activation_state` is the dict stored at `state["skill_activation"]`; registry never touches `LoopState` directly

- **`packages/soothe/src/soothe/skills/budget.py`** — `format_skills_within_budget(entries, budget_chars, per_entry_cap_chars)`
  - Mirrors `src/tools/SkillTool/prompt.ts:formatCommandsWithinBudget`
  - Under-budget → full descriptions joined with newlines
  - Over-budget → built-in skills keep full description; non-built-ins share remaining budget, truncated at `max(min_per_entry_chars, available // n)`
  - Extreme case (per-entry below threshold) → non-built-ins become names-only; built-ins keep full description
  - Returns `(formatted_text, telemetry_dict)` where telemetry has `included_count`, `truncated_count`, `mode ∈ {"full", "truncated", "names_only"}`

- **`packages/soothe/src/soothe/middleware/skill_activation.py`** — `SkillActivationMiddleware(AgentMiddleware)`
  - Pattern modeled on `middleware/file_lock.py:FileLockMiddleware` (path extraction shape) but with the canonical file-op set
  - `FILE_OP_TOOLS` sourced from `core/context/trigger_registry.py:BUILTIN_TOOL_TRIGGERS` filtered to workspace-scoped tools: `{read_file, write_file, edit_file, glob, grep, delete_file, insert_lines, apply_diff, file_info}` (note: `FileLockMiddleware`'s narrower 3-tool set is for its lock semantics and is unwired today — RFC-222 Q1)
  - `_PATH_KEYS = ("file_path", "path", "filepath", "file")` declared locally (small constant, avoids coupling to unwired middleware)
  - `awrap_tool_call`: extracts paths from `_PATH_KEYS`, calls `registry.match_paths`, schedules `sync_specific_skill_to_workspace` (fire-and-forget — activation never blocks the tool call), emits events. An `asyncio.Lock` per `(thread_id, skill_name)` guards concurrent file-op tool calls so the workspace-sync and event-emit run exactly once per activation.
  - Reads `thread_id` and `workspace` from the request via the existing `_thread_id_from_request` / `_workspace_from_request` helpers in `middleware/policy.py`
  - Reads/writes `state["skill_activation"]` (initialized to empty sets/dict in `before_agent` if missing)

### Modified modules

| File | Change |
|---|---|
| `skills/catalog.py:28` (`_parse_frontmatter`) | Accept `paths: str \| list[str]` and `when_to_use: str` (existing `tags: str` unchanged) |
| `skills/index.py:23` (`SkillIndexEntry`) | Add `paths: tuple[str, ...] \| None`, `when_to_use: str \| None`; keep existing `tags: str`; bump `wire_entries()` to include them |
| `core/loop/state/schemas.py` (`LoopState`) | Add `sent_skill_names: set[str]`, `activated_skill_names: set[str]`, `invoked_skill_names: set[str]`, `invoked_skill_bodies: dict[str, str]` — these are durable snapshots; runtime mutation happens on agent state |
| `core/loop/engine/agent_loop.py` | At each iteration boundary, copy `state["skill_activation"]` dict into the four `LoopState` fields (mirrors the existing `goal_user_submission` snapshot pattern); on resume, rehydrate `state["skill_activation"]` from `LoopState` |
| `middleware/system_prompt_optimization.py` | Add private `_compose_skills_block(state, config)` invoked from `_get_prompt_for_complexity` (around line 286–458); emits `<AVAILABLE_SKILLS>` into the static tier and `<SKILL_CONTEXT>` blocks for invoked skills into the semi-static tier |
| `middleware/_builder.py:59` (`build_soothe_middleware_stack`) | Insert `SkillActivationMiddleware` after `SoothePolicyMiddleware`, before `ToolConcurrencyMiddleware` (actual stack order: SoothePolicy → SkillActivation (new) → ToolConcurrency → NetworkToolErrors → SystemPromptOptimization → …) |
| `core/agent/_builder.py:199-211` | Pass `skills=None` to `create_deep_agent` so deepagents' `SkillsMiddleware` is never installed; soothe owns emission. No post-construction surgery on the deepagents middleware list. |
| `core/events/catalog.py:567` | Register `SkillActivatedEvent` (type `soothe.skill.activated`) and `SkillBodyLoadedEvent` (type `soothe.skill.body.loaded`) |
| `config/models.py:1001` (`AgentLoopConfig`) | `context_window_limit` already exists here — referenced for budget computation, no change needed |
| `config/models.py` | Add `ProgressiveSkillsConfig { budget_pct=0.01, max_listing_chars_per_entry=250, min_listing_chars_per_entry=20 }`; reference from `SootheConfig.progressive_skills` |
| `config/config.template.yml`, `config/config.dev.yml` | Mirror new `progressive_skills` section (CLAUDE.md Rule #2) |
| `packages/soothe/pyproject.toml` | Add `pathspec` runtime dependency (gitignore-style glob matching) if not already present |

### Removed behavior

- Deepagents' `SkillsMiddleware` is never installed (we pass `skills=None`). The model still has access to `read_file` for explicitly named SKILL.md paths if a skill body is referenced — only the always-on system-prompt injection is replaced.
- Slash-skill expansion (`try_expand_slash_skill_user_line`) is **kept** as the existing Stage-3 explicit path users already know.

---

## 6. Reused primitives

| Need | Existing API | File:Line |
|---|---|---|
| Skill metadata cache (single-root) | `SkillIndex` | `skills/index.py:36` |
| Wire-shape entries (multi-root aggregated) | `wire_entries_for_agent_config` | `skills/catalog.py:127` |
| Compose full body | `build_skill_context_text` | `skills/catalog.py:304` |
| Materialize skill files for model | `sync_specific_skill_to_workspace` | `skills/workspace_sync.py:170` |
| Token counting | `count_tokens` | `utils/token_counting.py` |
| Context-window limit | `AgentLoopConfig.context_window_limit` | `config/models.py:1001` |
| Canonical file-op tool set | `BUILTIN_TOOL_TRIGGERS` | `core/context/trigger_registry.py:12` |
| Path-key extraction pattern (reference only — middleware unwired) | `FileLockMiddleware._PATH_KEYS` | `middleware/file_lock.py:41` |
| Public event registration | `register_event`, `custom_event` | `core/events/catalog.py:567,116` |
| Internal pub/sub | `InternalEventBus.emit/subscribe` | `core/events/internal_bus.py:25,45,76` |
| System-prompt assembly site | `SystemPromptOptimizationMiddleware._get_prompt_for_complexity` (private — extend in-place) | `middleware/system_prompt_optimization.py:286` |
| Loop-state snapshot precedent | `goal_user_submission` mirrored from skill expansion | `core/loop/state/schemas.py` |
| Path-glob matching | `pathspec` (gitignore semantics) | **new dep** — add to `packages/soothe/pyproject.toml` |

---

## 7. Telemetry & observability

- Public events (RFC-401): `soothe.skill.activated`, `soothe.skill.body.loaded` — visible to subscribers via the stream bus, summarized via `register_event` `summary_template`
- Internal events: `InternalSkillActivatedEvent` for cross-middleware coordination without leaking to clients
- Per-turn telemetry attached to `<AVAILABLE_SKILLS>` block: `total_candidates`, `new_this_turn`, `truncated_count`, `mode`, `budget_chars`, `actual_chars`
- Langfuse trace shows `<AVAILABLE_SKILLS>` in static tier (cache-friendly), invoked-skill bodies in semi-static tier
- `LoopState` snapshot after a run includes populated `sent_skill_names` / `activated_skill_names` / `invoked_skill_names` / `invoked_skill_bodies` (size + names; bodies are content-addressable via skill name)

---

## 8. Cost model

| Stage | What lives in context | Approximate cost |
|---|---|---|
| Index built | nothing — disk only | 0 tokens |
| Stage 1 listing | name + ≤250-char desc per unconditional skill (delta-only) | ≤ 1% of window (~2K tokens cap on a 200K window) |
| Stage 2 activation | adds delta rows to next turn's listing | per-skill delta only |
| Stage 3 invocation | full SKILL.md body for invoked skills | per-skill, only when used; cached in `LoopState` for re-emission |

For a workspace with 60 skills (4 built-in unconditional, 56 conditional path-filtered), turn-0 cost drops from ~12K tokens (current: all 60 emitted) to ~600 tokens (4 built-ins, full description). A Python-editing session activates 2–3 skills over the first few turns; a Markdown-editing session activates none of the Python-tagged skills.

---

## 9. Edge cases

- **Skill with `paths: ["**"]`** → treated as unconditional (Claude Code parity); avoids the trap where a "match-all" pattern hides the skill from turn-0
- **Workspace switch mid-loop** → activation state is per-thread; if `workspace` changes via `RunnerState`, the next file-op call re-evaluates against the new workspace's conditional set
- **Skill removed between sessions** → `sent_skill_names` snapshot may reference deleted skills; `new_for_thread` skips entries no longer in the index (idempotent)
- **Two skills with the same name across roots** (built-in vs workspace) → existing `SkillIndex` / catalog precedence rules apply unchanged; registry inherits resolution
- **Compaction** → `invoked_skill_bodies` is snapshotted into `LoopState` each iteration; post-compact restoration rehydrates `state["skill_activation"]` and re-emits bodies into the next turn's semi-static tier without disk re-reads
- **Concurrent file-op tool calls** → `ToolConcurrencyMiddleware` permits parallel tool invocations. `SkillActivationMiddleware` holds a per-`(thread_id, skill_name)` `asyncio.Lock`; the first call to match a skill's pattern wins activation, runs `sync_specific_skill_to_workspace`, and emits the event exactly once. Subsequent racing matches observe the skill already in `activated` and short-circuit.
- **MCP-provided skills** → out of scope for this draft; `soothe.mcp.loader` module not yet present in the tree per Explore findings (broken imports in `core/thread/manager.py:24,553` reference it — separate cleanup). A follow-up can extend the registry to ingest MCP prompt manifests once that subsystem lands.

---

## 10. Verification

### Unit tests

- `packages/soothe/tests/unit/skills/test_registry_partition.py` — `paths:` presence partitions correctly; trailing `/**` stripped; all-`**` patterns demote to unconditional
- `packages/soothe/tests/unit/skills/test_registry_delta.py` — `new_for_thread` returns only un-sent skills; subsequent call returns `[]`; removing a skill between calls doesn't error
- `packages/soothe/tests/unit/skills/test_path_matching.py` — gitignore-style positive/negative, `**`, anchored paths, paths outside workspace are rejected (mirrors Claude Code's `activateConditionalSkillsForPaths` guard)
- `packages/soothe/tests/unit/skills/test_budget_formatter.py` — under-budget keeps full descs; over-budget truncates non-builtins; extreme case → names-only mode; built-ins always full

### Middleware tests

- `packages/soothe/tests/unit/middleware/test_skill_activation_middleware.py` — file-op tool with matching path activates skill; non-file-op tool doesn't; non-matching path doesn't; idempotent on re-call
- `packages/soothe/tests/unit/middleware/test_system_prompt_skills_block.py` — deepagents stock listing absent; `<AVAILABLE_SKILLS>` respects budget; invoked-skill body re-emitted from `LoopState.invoked_skill_bodies` cache

### Integration test

`packages/soothe/tests/integration/skills/test_progressive_skill_flow.py` — end-to-end: create fixture skill with `paths: ["src/**/*.py"]`, start agent, issue `read_file("src/main.py")`, assert next turn's system prompt contains the activated skill name; invoke via `/skill:name`, assert body present in subsequent turn; assert `LoopState` snapshot contains all three sets populated.

### Manual smoke (per CLAUDE.md Rule #5)

```bash
cd /Users/xiamingchen/Workspace/mirasurf/soothe
./scripts/verify_finally.sh                # mandatory: format + lint + 900+ unit tests

# Daemon smoke
soothe daemon start --workspace /tmp/soothe-skill-test
# In /tmp/soothe-skill-test/.soothe/skills/python-helper/SKILL.md, set paths: ["**/*.py"]

# Attach CLI, prompt: "list files in this directory"
# Confirm via Langfuse trace:
#   - turn-0 system prompt does NOT contain python-helper
#   - after a read_file or glob hits a .py path, next turn DOES contain it
#   - <AVAILABLE_SKILLS> token count ≤ 1% of configured context_window_limit
#   - soothe.skill.activated event appears in event stream on activation
```

---

## 11. Open questions

1. **Skill activation persistence across daemon restart** — `LoopState` is the right home, but should activation also seed from the workspace's `.soothe/state/` if a thread is resumed in a new daemon process? Current proposal: yes, via existing `AgentLoopStateManager.load()` (no additional code).
2. **Conditional skill listing on first activation** — should the activated skill be (a) auto-injected into the *current* turn's response context, or (b) deferred to the next turn's `<AVAILABLE_SKILLS>` block? Claude Code does (b). Recommend (b) for simplicity and to keep activation off the hot path.
3. **MCP skill integration** — explicitly deferred; `soothe.mcp.loader` module appears not yet present in the tree per Explore findings. Re-evaluate once that lands.
4. **Plugin-system integration (RFC-600)** — RFC-600 §"Extension Points" lists only Tools and Subagents today; skills are a separate subsystem. Whether to promote skills into the plugin extension point set is a follow-on RFC, not this draft.
