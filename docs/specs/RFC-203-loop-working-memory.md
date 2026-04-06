# RFC-203: Loop Working Memory

**RFC**: 0203  
**Title**: Loop Working Memory (Agentic ReAct State Bridge)  
**Status**: Draft  
**Kind**: Architecture Design / Impl Interface  
**Created**: 2026-04-02  
**Dependencies**: RFC-201, RFC-103, RFC-100

## Abstract

The agentic ReAct loop (Layer 2, RFC-201) passes progress to the next Reason call mainly via truncated step outputs. That loses structure and forces redundant exploration. This RFC defines **loop working memory**: a small, explicit store of durable facts and pointers that survives iterations, can live entirely in RAM, and **spills to the thread workspace** when content is too large for inline prompts—so Layer 1 tools can open the same files the planner references.

## Motivation

1. **Truncation**: Evidence strings are capped (hundreds of characters). Directory listings and long reads disappear from the Reason context.
2. **No deduplication key**: The LLM cannot tell “already listed `src/`” from a short “✓ …” line.
3. **Layer boundary**: Layer 1 has rich tool transcripts; Reason in the agentic loop only sees what the Act phase forwards.

Loop working memory is **not** a second context ledger (see RFC-300). It is a **bounded scratchpad** scoped to one agentic goal run, optimized for planner-facing summaries and spill artifacts.

## Design Principles

- **In-memory first**: Fast, no I/O until spill triggers.
- **Runs-local files**: Spilled bytes stay under `SOOTHE_HOME/runs/{thread_id}/loop/`; agents use normal file tools to inspect them.
- **Deterministic layout**: Paths are predictable so prompts can say `read_file("<runs>/loop/...")`.
- **Optional**: Implementations may disable working memory via config.
- **No secrets**: Do not store raw credentials; redact or omit sensitive tool output at the integration layer (future hardening).

## Data Model

### Memory entry (logical)

| Field | Description |
|-------|-------------|
| `step_id` | Loop step identifier from `StepAction.id` |
| `description` | Short copy of step description (for human scan) |
| `success` | Whether the step succeeded |
| `inline_summary` | Short text always embedded in the Reason prompt (may be truncated) |
| `spill_relpath` | Optional path relative to workspace root when body was spilled |

### Spill artifact

- **File**: UTF-8 text (`.md` or `.txt`).
- **Content**: Full or large excerpt of step output (or structured dump), written when inline budget is exceeded.
- **Index**: The in-memory entry’s `inline_summary` references the relative path (e.g. `See runs/<thread_id>/loop/step-<id>.md`).

## Filesystem Layout

Relative to **SOOTHE_HOME**:

```text
SOOTHE_HOME/
  runs/
    {thread_id}/
      loop/
        step-<step_id>-<seq>.md
```

- **`thread_id`**: The canonical durability thread identifier (same as used by `RunArtifactStore`).
- **`<seq>`**: Monotonic integer per `(thread_id, step_id)` to avoid overwrites when the same step id is retried.

Implementations **must** create parent directories before writing. Spill files co-locate with other run artifacts (manifest, checkpoints, step reports) under `runs/{thread_id}/`.

## Configuration (conceptual)

| Key | Meaning |
|-----|---------|
| `enabled` | Turn working memory on/off |
| `max_inline_chars` | Max characters for the **aggregated** working-memory block injected into Reason |
| `max_entry_chars_before_spill` | Per-step output length above which spill to disk is preferred |

Spill path is canonical: `SOOTHE_HOME/runs/{thread_id}/loop/`. No configurable subdirectory.

## Python API (modular encapsulation)

### Protocol: `LoopWorkingMemoryProtocol`

Implementations provide:

- `__init__(thread_id, *, max_inline_chars, max_entry_chars_before_spill)`  
  Construct working memory scoped to a thread. Spill path is `SOOTHE_HOME/runs/{thread_id}/loop/`.
- `record_step_result(step_id, description, output, success, *, workspace, thread_id) -> None`  
  Append/update memory from one Act step. May spill `output` when large. `thread_id` is kept for API stability (unused; set in constructor).
- `render_for_reason(*, max_chars: int | None = None) -> str`  
  Return a single prompt section (empty if disabled / no entries).
- `clear() -> None`  
  Reset for a new goal (optional; LoopAgent may create a fresh instance per run).

Concrete classes:

- **`LoopWorkingMemory`**: In-memory deque/list + spill writer (`soothe.cognition.loop_working_memory`).
- **`NullLoopWorkingMemory`**: No-op when disabled (optional).

### Integration points (RFC-201 alignment)

1. **Loop start**: Runner / `LoopAgent` constructs working memory from config.
2. **Post-Act**: After each batch of `StepResult` objects, call `record_step_result` for each.
3. **Pre-Reason**: `build_loop_reason_prompt` (or `PlanContext`) receives `working_memory_excerpt: str` from `render_for_reason()`.

`PlanContext` carries `working_memory_excerpt: str | None` so `ClaudePlanner` / `SimplePlanner` share the same surface.

## Prompt Contract

Reason prompts include a bounded block, e.g.:

```text
<SOOTHE_LOOP_WORKING_MEMORY>
... concise bullets + spill path references ...
</SOOTHE_LOOP_WORKING_MEMORY>
```

Rules stated to the model:

- Treat bullets as **authoritative** for what has already been inspected.
- Prefer `read_file` on spill paths over re-running expensive listings.
- Do not repeat successful exploration verbatim.

## Relationship to Other RFCs

- **RFC-201**: The agentic loop owns loop working memory lifecycle for that goal.
- **RFC-103**: Paths resolve inside workspace; enforce policy in tools (RFC-102).
- **RFC-300**: Context ledger remains separate; loop working memory is not a protocol backend.

## Future Work

- Structured fields (`visited_paths`, `read_files`) with deterministic merge.
- Cross-iteration persistence (durability) for resume.
- Automatic summarization LLM pass before spill.

## References

- RFC-201 Agentic Goal Execution  
- RFC-103 Thread-Aware Workspace  
- IG-122 Implementation Guide (companion)
