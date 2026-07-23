# IG-645 Loop 088c Tool-Call Performance

## Goal

Reduce execute-step wall time and wasted tool hops observed in loop `088c`
(dead-code cleanup): wrong filesystem workspace root, open-ended `task`
searches, rediscovery after predecessor evidence, empty `write_todos`, and
chunked `read_file` thrash.

## Incident Baseline

Loop `019f89de-59d9-71c0-aade-3ff9cf6a088c` (suffix `088c`):

- `glob` / nested `task` tools rooted at ephemeral `.../soothe-workspace`
  while stream workspace was the project tree → empty matches and
  `outside workspace` errors, then shell/`find` workarounds.
- SOR-02: `task` ~248s with ~83 SubagentTool calls; parent then re-grepped.
- SOR-03: similar `task` + overlapping patterns with SOR-02.
- Plan wave: Recon → Search → Confirm unused → Edit (serialized rediscovery).
- Empty `write_todos` (0 items) inside subagents; 11× small `read_file` on one file.

Prior art: [IG-609](IG-609-loop-146e-tool-execution-optimization.md),
[IG-610](IG-610-tool-optimization-middleware-architecture.md) (exact-signature
reuse / native-vs-shell consolidation). This guide does not reopen the
middleware split.

## Scope

1. **Workspace binding** — execute + nested `task` children use stream
   project root for filesystem tools (not process `temp/soothe-workspace`).
2. **Prompts** — no `task` for mechanical multi-pattern search; merge
   discovery steps; no rediscovery after predecessor/`task` evidence;
   prefer wider `read_file`.
3. **Deterministic middleware guards** — empty `write_todos` short-circuit;
   same-path `read_file` thrash guidance; metrics counters.

## Non-Goals

- Keyword/regex intent heuristics for “is this a search?” (RFC-630).
- Hard silent caps that drop legitimate large `task` work.
- Changing `verify_finally.sh` semantics.

## Design

### 1) Workspace root (P0) — independent of host ``soothe_config``

- Forward parent ``configurable.workspace`` (and ``thread_id``) into ``task``
  subagent invoke config — **never** inject host config objects.
- ``FilesystemMiddleware`` duck-types ``backend.bind_workspace(path)`` from tool
  runtime on every FS call (works for nested GP ``task`` children).
- ``WorkspaceAwareBackend.bind_workspace`` + ContextVar / langgraph fallback.
- GP inherits parent middleware that sets ``propagate_to_general_purpose=True``
  (generic deepagents opt-in; nano sets this on its workspace/optimization
  middleware).
- Virtual mode comes from the filesystem backend construction settings, not
  from a runtime host-config blob.

### 2) Prompt tightening (P0)

- Subagent / tool orchestration: mechanical repo search → batched `grep` /
  one `rg` via `run_command`; `task` only for multi-hop reasoning.
- Execution policies + plan_generate: prefer a single discovery wave when
  scopes overlap; do not split enumerate/search/confirm across steps when the
  goal or prior evidence already scopes the work; do not re-search after
  predecessor evidence except disputed spot-checks.
- File ops: prefer one wider `read_file` over many tiny slices.

### 3) Middleware guards (P1)

Extend `ToolOptimizationMiddleware`:

- Empty `write_todos` → ToolMessage “todo list unchanged” (short-circuit).
- Same-path `read_file` thrash guidance (hardcoded threshold of 3 consecutive
  same-path reads per step scope).
- Counters: `empty_write_todos_short_circuited`, `read_file_thrash_guided`
  (plus existing IG-609 metrics).

## Cleanse Plan

- No parallel workspace-binding paths after the ContextVar + task-config
  fix is authoritative.
- Do not leave duplicate conflicting subagent guidance in prompt fragments.

## Verification Plan

1. Unit: workspace resolve on execute/task; empty todos; read thrash.
2. Relative `glob` with project workspace must not mention `soothe-workspace`.
3. `./scripts/verify_finally.sh` green.

## Acceptance Criteria

- Nested `task` filesystem tools use parent stream workspace.
- Prompts discourage `task`-for-search and rediscovery.
- Empty `write_todos` and read thrash are short-circuited with metrics.
- Full repository verification passes.
