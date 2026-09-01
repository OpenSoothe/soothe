# Persistence & Reentrant Loop State

> Rules governing storage backends and loop state durability.

## Unified Persistence Backend (MUST)
`persistence.default_backend` is **one mode for the whole process**: `postgresql` or `sqlite`. **Never mix** the two in the same daemon/runtime.
- **Postgres mode** → all daemon-owned durable stores MUST use PostgreSQL (databases under `postgres_base_dsn` / `postgres_databases`). No SQLite "for convenience" for cron, identity, display cards, checkpoints, Context Engine, durability, or autopilot.
- **SQLite mode** → use local `$SOOTHE_HOME` / `$SOOTHE_DATA_DIR` SQLite files. Do not open a parallel Postgres path for any subset of features.
- Overrides (`agent.protocols.durability.backend` / `.checkpointer`) MUST stay `"default"` unless the operator intentionally switches the **entire** process.
- Vector stores follow the same rule: Postgres → `pgvector`; SQLite → `sqlite_vec` (in-memory for tests only).
- New persistence features MUST branch on `persistence.default_backend` (or a shared factory) — never hard-code SQLite when Postgres is configured.
- Leftover SQLite files under `$SOOTHE_DATA_DIR` in Postgres mode are legacy only; do not write new runtime state to them.

## Reentrant Loop State (MUST)
Loop state is **independent of runtime workers** — pauseable and resumable across arbitrary time intervals. Workers are stateless conduits; state lives in storage, not in process.
1. **State is in storage, not in process.** Three persistent layers hold loop state: LangGraph checkpointer (graph channel values), Context Engine (goal DAG + ledger), and disk artifacts (`.soothe/plans/*.md`). A worker crash loses nothing that isn't already on disk. Never add a new in-memory-only state layer for data that must survive worker exit.
2. **The `pending_clarification` channel is the re-entry contract.** When a loop parks for user input (plan review, ask_user), everything needed to resume — plan draft, plan path, refinement comments, clarification origin — MUST be serialized into the `pending_clarification` graph channel. A fresh worker reads this channel via `aget_state` and reconstructs the context. Do not store resumption-critical data only on `LoopPhaseScratch` (in-memory) without projecting it into a graph channel.
3. **CE goal status is the source of truth for parking.** A goal in `awaiting_clarification` is intentionally parked — not crashed, not stale. The stale-loop reconciler, auto-resume, and clarification-resume paths all check this status before acting. Never demote a loop with a pending clarification to `idle` (that kills the clarification flow). Never mark a parked goal as `interrupted` on cancel — cancel the in-flight operation,
4. **Scratch is ephemeral; channels are durable.** `LoopPhaseScratch` is deliberately not serialized by LangGraph (it carries rich non-primitive models). Fields that must survive a worker exit are projected into graph channels before parking (`build_plan_mode_review_pending`). `hydrate_scratch_from_pending` is the inverse projection on resume. New scratch fields that need persistence MUST follow this project→persist→hydrate pattern.
5. **Cancel ≠ terminal.** A cancel during a long-running LLM call (synthesis, refinement, execute) cancels the in-flight operation, not the goal's clarification status. The goal's `awaiting_clarification` status is preserved so the user's next input resumes from the same parked state, not from a new goal. `resolve_clarification_resume_ce_goal` matches both `"active"` and `"awaiting_clarification"` goals.
