# Implementation Guide: config layout separation for soothe-nano and soothe

## Goal

Define an explicit, stable config architecture where:

- `soothe-nano` owns CoreAgent config schema and loading behavior.
- `soothe` owns host orchestration overlays and host-only services.
- operators configure agent behavior with two files:
  - `nano.yml` for core/shared settings
  - `soothe.yml` for host-only overlays

## Scope

- Define file ownership and key ownership for:
  - `~/.soothe/config/nano.yml`
  - `~/.soothe/config/soothe.yml`
  - `~/.soothe/config/daemon.yml` linkage
- Reorganize Python config modules so ownership is explicit in package structure.
- Define composition order, validation boundaries, and conflict semantics.
- Define migration phases from monolithic `config.yml`.

## Non-goals

- No behavior tuning of defaults (loop/autopilot/middleware thresholds).
- No daemon transport, protocol, or runner behavioral changes.
- No rewrite of Pydantic model semantics unless required for ownership split.
- No operator-visible key renaming in first rollout phase.

## Design principles

1. **Single owner per key**: each key has one canonical package owner (`nano` or `host`).
2. **Standalone nano operability**: `nano.yml` is sufficient for pure `soothe-nano` runtimes.
3. **Host as overlay, not fork**: `soothe.yml` adds host behavior, not a second core schema.
4. **Fail-fast misplacement**: wrong-file keys produce actionable validation errors.
5. **Shared schema, bounded overlays**: host overlays should be small and intentionally scoped.
6. **Compatibility-first rollout**: transition paths stay available until strict phase.

## Target file layout

### `nano.yml` (nano-owned, required for nano and soothe)

Primary CoreAgent configuration surface:

- Model/provider and routing:
  - `providers`, `router_profiles`, `embedding_profile`, `active_router_profile`
- Core agent baseline:
  - `agent.name`
  - `agent.system_prompt`
  - `agent.agent_instructions_max_chars`
  - `agent.protocols`
  - `agent.code_interpreter`
  - `agent.runtime`
  - `agent.middleware`
- Tooling/subagent/platform:
  - `tools`, `subagents`, `mcp_servers`, `mcp_builtins`, `progressive_mcp`
  - `plugins`, `skills`, `progressive_skills`, `progressive_tools`, `memory`
- Shared runtime foundations:
  - `persistence`, `observability`, `security`, `filesystem_middleware`,
    `workspace_mount`, `optimization`, `vector_stores`, `vector_store_router`
- UX/debug basics:
  - `debug`, `activity_max_lines`, `tui_debug`, `ui`, `update`

### `soothe.yml` (host-owned, optional for nano-only, required for full soothe host)

Host-only orchestration overlay:

- Agent orchestration behavior:
  - `agent.goal_completion_mode`
  - `agent.final_response`
  - `agent.autopilot`
  - `agent.loop`
  - `agent.clarification`
  - `agent.veritas`
- Host services:
  - `cron`
  - `skillify`

### `daemon.yml` (daemon-owned)

Daemon runtime and transport configuration remains separate, and points to both
agent config files explicitly (or a compatibility fallback).

## Target Python module organization

### `packages/soothe-nano/src/soothe_nano/config` (core/shared)

Keep nano package as the canonical home for shared config primitives:

- `env.py`:
  - env expansion and `SOOTHE_HOME`.
- `constants.py`:
  - core tool/runtime constants only.
- `models.py`:
  - shared primitives and nano-owned sections (`AgentConfig` with `agent.middleware` shape).
- `settings.py`:
  - loads and validates `nano.yml` only.
  - must not know host-only top-level keys (`cron`, `skillify`) or host orchestration sections.
- `reload.py`:
  - generic watcher/notification machinery, no host-specific imports.
- `models_catalog.py`:
  - shared model catalog payload helpers.
- `__init__.py`:
  - nano-oriented public exports only.

### `packages/soothe/src/soothe/config` (host overlays and composition)

Host package becomes the composition and overlay layer:

- `models.py`:
  - host-only models (`agent.loop`, `agent.autopilot`, `agent.clarification`, `agent.veritas`, `cron`, `skillify`).
- `settings.py`:
  - `SootheConfig` composition entrypoint:
    1. load nano base config
    2. load host overlay
    3. validate ownership
    4. apply env overrides
- `ownership.py` (new):
  - allow/deny ownership maps and key-path validation helpers.
- `composition.py` (new):
  - deterministic merge semantics (`nano` base + `soothe` overlay).
- `compat.py` (new):
  - temporary legacy folding/adaptation logic for migration phases only.
- `reload.py` and `models_catalog.py`:
  - thin wrappers or aliases over shared implementations from nano.
- `__init__.py`:
  - host public API exports.

## Ownership contract

### Placement rules

- `nano.yml` rejects host-only sections:
  - top-level `cron`, top-level `skillify`
  - `agent.loop`, `agent.autopilot`, `agent.clarification`, `agent.veritas`
- `soothe.yml` rejects nano/shared sections:
  - provider/router/embedding sections
  - core tool and MCP sections
  - persistence/security/observability/vector/foundation sections
  - `agent.protocols`, `agent.runtime`, `agent.middleware`, `agent.code_interpreter`

### Composition semantics

Effective host configuration:

1. Resolve defaults.
2. Parse and validate `nano.yml` against nano schema.
3. Parse and validate `soothe.yml` against host overlay schema.
4. Merge (`nano` base, then `soothe` overlay on owned keys only).
5. Apply env overrides.

Cross-ownership writes are terminal errors with relocation guidance.

## Leakage cleanup targets in current code

The following current patterns should be removed from `soothe_nano/config`:

1. Host-key stripping in nano validators:
   - top-level `cron`
   - top-level `skillify`
   - host `strange_loop` compatibility blocks
2. Host fallback in nano middleware access:
   - `agent.middleware` fallback to `agent.loop`
3. Host-loop wording in nano docs where semantics are now CoreAgent middleware.

These compatibility behaviors should move to `soothe/config/compat.py` and
`soothe/config/composition.py`.

## Compatibility and migration

### Phase 1: compatible split support

- Support legacy monolithic `config.yml`.
- Add first-class split loading (`nano.yml`, `soothe.yml`).
- Keep legacy adapters in host package only; emit deprecation warnings with key paths.

### Phase 2: split-by-default

- New scaffolds emit split files.
- Docs and examples switch to split layout.
- Compatibility adapters remain, but warnings become stronger and aggregated.

### Phase 3: strict ownership enforcement

- Remove host compatibility adapters for monolithic and misplaced keys.
- Enforce ownership contract strictly in both loaders.
- Nano loader errors on host keys instead of silently dropping them.

## Recommended implementation sequence (code reorg)

1. **Introduce host composition modules**
   - add `soothe/config/ownership.py`, `composition.py`, `compat.py`.
2. **Move compatibility out of nano**
   - remove host-key stripping and host fallback logic from nano config modules.
3. **Alias shared utility modules**
   - host `reload.py` and `models_catalog.py` delegate to nano shared implementation.
4. **Stabilize public API**
   - ensure `soothe.config.__init__` and `soothe_nano.config.__init__` export clean, non-overlapping surfaces.
5. **Flip defaults**
   - switch templates/scaffolds to split files.
6. **Enforce strict mode**
   - remove compatibility adapters after migration window.

## Validation and operator experience

- Validation errors include:
  - offending key path
  - source file
  - owning file
  - relocation hint
- Startup logs clearly print:
  - loaded config files
  - composition order
  - whether compatibility adapters were applied

## Acceptance criteria

- `soothe_nano.config.settings.SootheConfig` validates nano-owned keys only.
- No host-only key handling logic remains in `soothe_nano/config/*`.
- Host `soothe.config.settings.SootheConfig` composes nano + host configs deterministically.
- Legacy monolithic config works only through host compatibility layer during migration phases.
- Docs/templates use split config layout by default.

## Open questions

- Should `soothe.yml` allow a tiny explicit override allowlist for emergency operations?
- Should daemon support one pointer that expands to both split files for managed deploys?
- Do we ship an automatic split tool (`config split`) for existing monolithic files?

## Implementation status

Design polished and ready for phased implementation.

Execution checklist and sequencing live in:
`docs/impl/IG-632-config-separation-execution-checklist.md`.
