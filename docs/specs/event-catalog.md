# Event Catalog Reference

**Purpose**: Complete catalog of Soothe progress event types (RFC-400, RFC-403)
**Status**: Reference document (incrementally migrated naming)
**Last Updated**: 2026-05-01

This document provides the complete catalog of all Soothe progress event types. For event naming semantics, grammar rules, and domain taxonomy, see [RFC-403](RFC-403-unified-event-naming.md). For event processing architecture, see [RFC-400](RFC-400-event-processing.md). For verbosity classification, see [RFC-501](RFC-501-display-verbosity.md).

## Event Naming Pattern

All events follow the 4-segment pattern defined in RFC-403:
```
soothe.<domain>.<component>.<action_or_state>
```

**Domains**: See RFC-403 for the domain taxonomy with functional scope definitions.

**Grammar**: All actions use present progressive tense; state nouns for reports. See RFC-403 for approved verb and state noun lists.

**Note**: Built-in **delegated subagent** progress on the WebSocket `custom` stream uses the **IG-339** allowlist in `soothe_sdk.core.subagent_wire`, not the long granular lists in older drafts.

---

## RFC-403 migration notes

Granular rename tables in older RFC drafts are partially superseded: built-in subagents emit only **curated** `soothe.subagent.*` types (see § Subagent Events below and RFC-403 §8.4).

---

## Lifecycle Events

| Type | Fields | VerbosityTier |
|------|--------|---------------|
| `soothe.lifecycle.thread.created` | `thread_id: str` | DETAILED |
| `soothe.lifecycle.thread.started` | `thread_id: str`, `protocols: dict` | DETAILED |
| `soothe.lifecycle.thread.resumed` | `thread_id: str` | DETAILED |
| `soothe.lifecycle.thread.saved` | `thread_id: str` | DETAILED |
| `soothe.lifecycle.thread.ended` | `thread_id: str` | DETAILED |
| `soothe.lifecycle.iteration.started` | `iteration: int`, `goal_id: str`, `goal_description: str`, `parallel_goals: int` | DETAILED |
| `soothe.lifecycle.iteration.completed` | `iteration: int`, `goal_id: str`, `outcome: str`, `duration_ms: int` | DETAILED |
| `soothe.lifecycle.checkpoint.saved` | `thread_id: str`, `completed_steps: int`, `completed_goals: int` | DETAILED |
| `soothe.lifecycle.recovery.resumed` | `thread_id: str`, `completed_steps: list[str]`, `completed_goals: list[str]`, `mode: str` | DETAILED |

---

## Protocol Events

### Context Protocol

| Type | Fields | VerbosityTier |
|------|--------|---------------|
| `soothe.protocol.context.projected` | `entries: int`, `tokens: int` | DETAILED |
| `soothe.protocol.context.ingested` | `source: str`, `content_preview: str` | DETAILED |

### Memory Protocol

| Type | Fields | VerbosityTier |
|------|--------|---------------|
| `soothe.protocol.memory.recalled` | `count: int`, `query: str` | DETAILED |
| `soothe.protocol.memory.stored` | `id: str`, `source_thread: str` | DETAILED |

### Plan Cognition

| Type | Fields | VerbosityTier |
|------|--------|---------------|
| `soothe.cognition.plan.created` | `goal: str`, `steps: list[StepDict]` | NORMAL |
| `soothe.cognition.plan.step_started` | `step_id: str`, `description: str`, `depends_on: list[str]`, `batch_index: int?` | NORMAL |
| `soothe.cognition.plan.step_completed` | `step_id: str`, `success: bool`, `result_preview: str?`, `duration_ms: int?` | NORMAL |
| `soothe.cognition.plan.step_failed` | `step_id: str`, `error: str`, `blocked_steps: list[str]?`, `duration_ms: int?` | NORMAL |
| `soothe.cognition.plan.batch_started` | `batch_index: int`, `step_ids: list[str]`, `parallel_count: int` | NORMAL |
| `soothe.cognition.plan.reflected` | `should_revise: bool`, `assessment: str` | DETAILED |
| `soothe.cognition.plan.dag_snapshot` | `steps: list[StepDepDict]` | DEBUG |
| `soothe.cognition.plan.plan_only` | `thread_id: str`, `goal: str`, `step_count: int` | NORMAL |

### Policy Protocol

| Type | Fields | VerbosityTier |
|------|--------|---------------|
| `soothe.protocol.policy.checked` | `action: str`, `verdict: str`, `profile: str` | DETAILED |
| `soothe.protocol.policy.denied` | `action: str`, `reason: str`, `profile: str` | QUIET |

### Goal Cognition

| Type | Fields | VerbosityTier |
|------|--------|---------------|
| `soothe.cognition.goal.created` | `goal_id: str`, `description: str`, `priority: int\|str` | NORMAL |
| `soothe.cognition.goal.completed` | `goal_id: str` | QUIET |
| `soothe.cognition.goal.failed` | `goal_id: str`, `error: str`, `retry_count: int` | QUIET |
| `soothe.cognition.goal.batch_started` | `goal_ids: list[str]`, `parallel_count: int` | NORMAL |
| `soothe.cognition.goal.report` | `goal_id: str`, `step_count: int`, `completed: int`, `failed: int`, `summary: str` | NORMAL |
| `soothe.cognition.goal.directives_applied` | `goal_id: str`, `directives_count: int`, `changes: list` | DETAILED |
| `soothe.cognition.goal.deferred` | `goal_id: str`, `reason: str`, `plan_preserved: bool` | DETAILED |

---

## Tool Events

### Generic Tool Events

| Type | Fields | VerbosityTier |
|------|--------|---------------|
| `soothe.tool.{name}.started` | `tool: str`, `args: str?`, `kwargs: str?` | DETAILED |
| `soothe.tool.{name}.completed` | `tool: str`, `result_preview: str?` | DETAILED |
| `soothe.tool.{name}.failed` | `tool: str`, `error: str` | QUIET |

Where `{name}` is the concrete tool name (e.g., `search`, `crawl`, `read_file`, `execute`).

### Wizsearch Tool Events

| Type | Additional Fields |
|------|-------------------|
| `soothe.tool.search.started` | `query: str`, `engines: list[str]` |
| `soothe.tool.search.completed` | `query: str`, `result_count: int`, `response_time: float?` |
| `soothe.tool.search.failed` | `query: str`, `engines: list[str]`, `engine_status: dict?`, `debug_mode: bool?` |
| `soothe.tool.crawl.started` | `url: str`, `content_format: str?` |
| `soothe.tool.crawl.completed` | `url: str`, `content_length: int` |
| `soothe.tool.crawl.failed` | `url: str`, `error_type: str?` |

---

## Subagent Events (built-in wire, IG-339)

Sparse **`soothe.subagent.*`** events are emitted on the LangGraph **`custom`** stream for CLI/TUI progress. Payloads are **metadata-only** (bounded strings, counts). Full assistant prose and native tool loops use **`messages`** where applicable.

**Authoritative allowlist**: `soothe_sdk.core.subagent_wire.get_allowlisted_subagent_event_types()`.

| Type | Fields (representative) | CLI/TUI tier |
|------|-------------------------|--------------|
| `soothe.subagent.explore.started` | `search_target`, `thoroughness` | NORMAL |
| `soothe.subagent.explore.milestone` | `decision`, `findings_count`, `iterations_used` | DETAILED |
| `soothe.subagent.explore.step.completed` | `tool_name`, `args_preview`, `result_preview` | NORMAL |
| `soothe.subagent.explore.completed` | `total_findings`, `thoroughness`, `iterations_used`, `duration_ms` | NORMAL |
| `soothe.subagent.tacitus.started` | `topic_preview` | NORMAL |
| `soothe.subagent.tacitus.gather.summary` | `query_preview`, `result_count`, `sources_touched` | NORMAL |
| `soothe.subagent.tacitus.completed` | `duration_ms`, `answer_length`, `summary` | NORMAL |

**Removed / not emitted (core)**: `soothe.capability.*` (hard cut). Browser, Claude, and Research subagents moved to [soothe-community](https://github.com/OpenSoothe/soothe-community); their wire types are not part of the core daemon contract. Historical per-phase names such as `soothe.subagent.claude.text` or `soothe.subagent.research.gather` are **not** emitted unless reintroduced under IG-339-style review.

### Skillify Subagent

| Type | Fields | VerbosityTier |
|------|--------|---------------|
| `soothe.subagent.skillify.indexing_pending` | `query: str` | DETAILED |
| `soothe.subagent.skillify.retrieve_started` | `query: str` | DETAILED |
| `soothe.subagent.skillify.retrieve_completed` | `query: str`, `result_count: int`, `top_score: float` | DETAILED |
| `soothe.subagent.skillify.retrieve_not_ready` | `message: str` | DETAILED |
| `soothe.subagent.skillify.index_started` | `collection: str` | DETAILED |
| `soothe.subagent.skillify.index_updated` | `new: int`, `changed: int`, `deleted: int`, `total: int` | DETAILED |
| `soothe.subagent.skillify.index_unchanged` | `total: int` | DETAILED |
| `soothe.subagent.skillify.index_failed` | *(none)* | QUIET |

### Weaver Subagent

| Type | Fields | VerbosityTier |
|------|--------|---------------|
| `soothe.subagent.weaver.analysis_started` | `task_preview: str` | DETAILED |
| `soothe.subagent.weaver.analysis_completed` | `capabilities: list`, `constraints: list` | DETAILED |
| `soothe.subagent.weaver.reuse_hit` | `agent_name: str`, `confidence: float` | DETAILED |
| `soothe.subagent.weaver.reuse_miss` | `best_confidence: float` | DETAILED |
| `soothe.subagent.weaver.skillify_pending` | *(none)* | DETAILED |
| `soothe.subagent.weaver.harmonize_started` | `skill_count: int` | DETAILED |
| `soothe.subagent.weaver.harmonize_completed` | `retained: int`, `dropped: int`, `bridge_length: int` | DETAILED |
| `soothe.subagent.weaver.generate_started` | `agent_name: str` | DETAILED |
| `soothe.subagent.weaver.generate_completed` | `agent_name: str`, `path: str` | DETAILED |
| `soothe.subagent.weaver.validate_started` | `agent_name: str` | DETAILED |
| `soothe.subagent.weaver.validate_completed` | `agent_name: str` | DETAILED |
| `soothe.subagent.weaver.registry_updated` | `agent_name: str`, `version: str` | DETAILED |
| `soothe.subagent.weaver.execute_started` | `agent_name: str`, `task_preview: str` | DETAILED |
| `soothe.subagent.weaver.execute_completed` | `agent_name: str`, `result_length: int` | DETAILED |

### Generic Subagent Tool Events

| Type | Fields | VerbosityTier |
|------|--------|---------------|
| `soothe.subagent.{agent}.tool_started` | `tool: str`, `args: str?`, `kwargs: str?` | DETAILED |
| `soothe.subagent.{agent}.tool_completed` | `tool: str`, `result_preview: str?` | DETAILED |
| `soothe.subagent.{agent}.tool_failed` | `tool: str`, `error: str` | QUIET |

---

## Output domain (`soothe.output.*`)

**IG-317 / RFC-614:** User-visible **assistant answer text** for the main agent loop is **not** cataloged here as `soothe.output.*` events. It is streamed on **`mode="messages"`** as loop-tagged AI payloads with a **`phase`** field (`goal_completion`, `quiz`, `autonomous_goal`, `direct_model`). Clients should use `soothe_sdk.ux.loop_stream` helpers to recognize those phases. **Headless CLI** treats unphased namespaced subgraph assistant prose as non-output (IG-343). The runner emits **`phase=goal_completion`** after `completed` unless AgentLoop set `skip_goal_completion_wire_duplicate=True` (streamed **synthesize** already delivered the body; RFC-500 / RFC-219).

Optional **ancillary** progress may still use the `soothe.output.*` domain (verbosity default: **QUIET** via domain `output`), for example dynamic types emitted by `soothe.utils.output_capture.OutputCapture` when `emit_progress=True` (`soothe.output.{source}`).

| Type | Fields | VerbosityTier |
|------|--------|---------------|
| `soothe.output.*` (dynamic / ancillary) | Event-specific | QUIET (domain default) |

---

## Autopilot Events (RFC-203)

| Type | Fields | VerbosityTier |
|------|--------|---------------|
| `soothe.autopilot.dreaming_entered` | `timestamp: datetime` | NORMAL |
| `soothe.autopilot.dreaming_exited` | `timestamp: datetime`, `trigger: str` | NORMAL |
| `soothe.autopilot.goal_validated` | `goal_id: str`, `confidence: float` | DETAILED |
| `soothe.autopilot.goal_suspended` | `goal_id: str`, `reason: str` | NORMAL |
| `soothe.autopilot.send_back` | `goal_id: str`, `remaining_budget: int`, `feedback: str` | DETAILED |
| `soothe.autopilot.relationship_detected` | `from_goal: str`, `to_goal: str`, `type: str`, `confidence: float` | DETAILED |
| `soothe.autopilot.checkpoint.saved` | `thread_id: str`, `trigger: str` | DETAILED |

---

## Error Events

| Type | Fields | VerbosityTier |
|------|--------|---------------|
| `soothe.error.general` | `error: str` | QUIET |

---

## Verbosity Classification

Events are classified into VerbosityTier values (RFC-0024) that determine visibility:

| Domain | Default VerbosityTier | Description |
|--------|----------------------|-------------|
| `lifecycle` | DETAILED | Thread and session lifecycle events |
| `protocol` | DETAILED | Core protocol activity events |
| `cognition` | NORMAL | Plan and goal cognition events |
| `tool` | DETAILED | Main agent tool execution events |
| `subagent` | DETAILED (registry default) | Curated **`soothe.subagent.*`** overrides to **NORMAL** in `classify_event_to_tier` (IG-339); see RFC-501 §6.1 |
| `output` | QUIET | Content destined for user display |
| `error` | QUIET | Error events (always shown) |

**Note (IG-339)**: All allowlisted **`soothe.subagent.*`** wire events classify to **`NORMAL`** for CLI/TUI (`soothe_sdk.ux.classification`). Third-party subgraphs may still emit non-curated types—those fall back to domain defaults or **DEBUG**.

---

**See Also**: [RFC-400](RFC-400-event-processing.md) for event architecture, [RFC-403](RFC-403-unified-event-naming.md) §8.4 for delegated subagent naming, [RFC-501](RFC-501-display-verbosity.md) for VerbosityTier specification.