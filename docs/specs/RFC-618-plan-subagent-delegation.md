# RFC-618: Plan Subagent — Structured Planning with Explore Delegation

**RFC**: 618  
**Title**: Plan Subagent — Structured Planning with Explore Delegation  
**Status**: Draft  
**Kind**: Architecture Design  
**Created**: 2026-05-11  
**Updated**: 2026-05-11  
**Authors**: Soothe Team  
**Depends on**: RFC-000, RFC-001, RFC-100, RFC-600, RFC-601, RFC-613  
**Related**: RFC-201 (AgentLoop plan-execute loop), RFC-214 (plan context)

## Abstract

This RFC specifies a built-in **plan** subagent: a `CompiledSubAgent` implemented as a **compiled LangGraph** that runs two **agentic** phases—**(1) information collection** and **(2) plan design**—then returns a single markdown report to the parent.

In the collection phase, an LLM may request **multiple readonly explore invocations per round** (several natural-language search directives in one structured response) and may repeat **multiple collection rounds** until it declares enough evidence or caps are hit. Each directive is executed by **direct `invoke`** on the same explore runnable used by the standalone explore subagent (no nested `task` tool).

In the plan-design phase, a separate structured loop refines a **full markdown plan** over one or more iterations before the delegate emits one final `AIMessage`.

This subagent is **not** the AgentLoop planner (RFC-201); it is an optional **delegation capability** the main agent may call with `task(subagent_type="plan", ...)`.

## 1. Problem Statement

1. The main deep agent exposes one `task` tool listing all subagents; **child** compiled subagents do not automatically receive a nested `task` roster (see deepagents `CompiledSubAgent` handling).
2. Teams want a **planning-oriented delegate** that can **iteratively** gather workspace context via **multiple explore runs** (same engine as RFC-613), then **iteratively** shape a plan—mirroring agentic “collect → reflect → plan” workflows without bloating the main thread.
3. Nesting a full second `SubAgentMiddleware` inside the plan graph is heavier than explicit programmatic invokes of the explore runnable.

## 2. Design Goals

1. **Explicit explore integration** — call the same explore engine as `create_explore_subagent` / compiled runnable.
2. **No nested `task` tool** — use direct `invoke` on the explore runnable with parent `RunnableConfig` from `langgraph.config.get_config()` so workspace injection (Soothe patch) stays consistent.
3. **Agentic collection** — multiple collection rounds; each round may schedule **several** explore tasks (bounded per round and in total).
4. **Agentic plan design** — multiple planner rounds that rewrite a full markdown plan until the model sets “done” or a round cap applies.
5. **Read-only recon by default** — explore stays readonly; the plan graph does not attach mutating tools in v1 (extensible later to other readonly tools).
6. **Bounded cost** — YAML-tunable caps on collection rounds, plan rounds, tasks per collection round, and total explore invocations.
7. **Plugin-compliant** — `@plugin` / `@subagent` on `soothe.subagents.plan`.

## 3. Non-Goals

- Replacing or merging with AgentLoop `LLMPlanner` / PlanManager.
- Nested `task` tools or general-purpose subagent inside plan.
- Parallel `Send` fan-out for explore in v1 (explore invocations within a round are **sequential**; multiple directives per round are still supported).

## 4. Architecture

### 4.1 High-level flow

```
START → ingest_task
      → [enable_explore?] collection_iteration ⟲  else → plan_iteration
      → plan_iteration ⟲
      → emit_final → END
```

- **ingest_task**: Reads the delegated task from the initial `HumanMessage`.
- **collection_iteration** (optional): Structured `CollectorDecision` — `explore_tasks` (0..N strings), `finish_collection`, `rationale`. Runs up to `max_explore_tasks_per_round` explores **sequentially**, appends markdown snippets to `findings` (reducer), enforces `max_explore_passes` **total** across all rounds. Loops until `finish_collection` or `max_collection_rounds`.
- **plan_iteration**: Structured `PlanRefinement` — full `plan_markdown`, `finish_planning`, `rationale`. Loops until `finish_planning` or `max_plan_rounds`.
- **emit_final**: Writes the last `plan_markdown` as the sole new `AIMessage` for the parent `task` tool.

If `enable_explore` is false, the graph skips **collection_iteration** entirely and starts at **plan_iteration**.

### 4.2 State schema

The compiled graph state **must** include `messages` with `add_messages` for the `CompiledSubAgent` contract. Additional channels include `findings` (list, `operator.add` reducer), round counters, `plan_markdown`, flags, and `explores_used`.

### 4.3 Configuration (`PlanSubagentConfig`)

| Field | Type | Default | Meaning |
|-------|------|---------|---------|
| `enable_explore` | bool | `true` | Run the collection phase; when false, go straight to plan design. |
| `max_explore_passes` | int | `24` | **Total** explore sub-invocations allowed for the whole delegate. |
| `max_collection_rounds` | int | `6` | Max collection LLM rounds. |
| `max_explore_tasks_per_round` | int | `8` | Cap on `explore_tasks` executed in one collection round. |
| `max_plan_rounds` | int | `5` | Max plan-design LLM rounds. |

### 4.4 Model roles

- **Plan** subagent primary model: **always** the router **`think`** role via `SootheConfig.create_chat_model("think")`. The top-level YAML field `subagents.plan.model` is **not** consulted (reserved shape only; same as other subagents).
- **Explore** invocations (including those spawned from plan): **`fast`** model inside `create_explore_subagent` from the plan factory; the standalone explore subagent default remains **`fast`** in `resolve_subagents`.

### 4.5 Future: additional readonly tools

The same **collection** loop pattern can later bind other readonly tools (e.g. bounded file reads) alongside explore; v1 uses explore only.

## 5. Security and Policy

- Plan subagent inherits workspace boundaries like other `task` children.
- Explore obeys `ExploreSubagentConfig` and global security flags.

## 6. Observability

Structured logging in the engine; optional wire events in a follow-up.

## 7. Acceptance Criteria

1. With `subagents.plan.enabled: true`, `resolve_subagents` returns a `CompiledSubAgent` dict named `plan`.
2. A typical invoke ends with one `AIMessage` in `messages`.
3. With `enable_explore` true, the explore runnable may be invoked **multiple times** across one delegate (unit tests cover multi-round collection).
4. With `enable_explore` false, explore is never invoked.

## 8. References

- RFC-613 — Explore agent.
- RFC-601 — Built-in plugin agents.
- `soothe/core/agent/_patch.py` — `task` tool config propagation.

## 9. Implementation

`docs/impl/IG-413-plan-subagent-rfc-618.md` — `soothe.subagents.plan` (`engine.py`, `schemas.py`, `implementation.py`).
