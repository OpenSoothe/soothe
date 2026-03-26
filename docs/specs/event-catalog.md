# Event Catalog Reference

**Purpose**: Complete catalog of Soothe progress event types (RFC-0015)
**Status**: Reference Document
**Last Updated**: 2026-03-27

This document provides the complete catalog of all Soothe progress event types. For event naming conventions, architecture, and design principles, see [RFC-0015](RFC-0015.md).

## Event Naming Pattern

All events follow the 4-segment pattern:
```
soothe.<domain>.<component>.<action>
```

Domains: `lifecycle`, `protocol`, `tool`, `subagent`, `output`, `error`

---

## Lifecycle Events

| Type | Fields | Verbosity |
|------|--------|-----------|
| `soothe.lifecycle.thread.created` | `thread_id: str` | protocol |
| `soothe.lifecycle.thread.started` | `thread_id: str`, `protocols: dict` | protocol |
| `soothe.lifecycle.thread.resumed` | `thread_id: str` | protocol |
| `soothe.lifecycle.thread.saved` | `thread_id: str` | protocol |
| `soothe.lifecycle.thread.ended` | `thread_id: str` | protocol |
| `soothe.lifecycle.iteration.started` | `iteration: int`, `goal_id: str`, `goal_description: str`, `parallel_goals: int` | protocol |
| `soothe.lifecycle.iteration.completed` | `iteration: int`, `goal_id: str`, `outcome: str`, `duration_ms: int` | protocol |
| `soothe.lifecycle.checkpoint.saved` | `thread_id: str`, `completed_steps: int`, `completed_goals: int` | protocol |
| `soothe.lifecycle.recovery.resumed` | `thread_id: str`, `completed_steps: list[str]`, `completed_goals: list[str]`, `mode: str` | protocol |

---

## Protocol Events

### Context Protocol

| Type | Fields | Verbosity |
|------|--------|-----------|
| `soothe.protocol.context.projected` | `entries: int`, `tokens: int` | protocol |
| `soothe.protocol.context.ingested` | `source: str`, `content_preview: str` | protocol |

### Memory Protocol

| Type | Fields | Verbosity |
|------|--------|-----------|
| `soothe.protocol.memory.recalled` | `count: int`, `query: str` | protocol |
| `soothe.protocol.memory.stored` | `id: str`, `source_thread: str` | protocol |

### Plan Protocol

| Type | Fields | Verbosity |
|------|--------|-----------|
| `soothe.protocol.plan.created` | `goal: str`, `steps: list[StepDict]` | protocol |
| `soothe.protocol.plan.step_started` | `step_id: str`, `description: str`, `depends_on: list[str]`, `batch_index: int?` | protocol |
| `soothe.protocol.plan.step_completed` | `step_id: str`, `success: bool`, `result_preview: str?`, `duration_ms: int?` | protocol |
| `soothe.protocol.plan.step_failed` | `step_id: str`, `error: str`, `blocked_steps: list[str]?`, `duration_ms: int?` | protocol |
| `soothe.protocol.plan.batch_started` | `batch_index: int`, `step_ids: list[str]`, `parallel_count: int` | protocol |
| `soothe.protocol.plan.reflected` | `should_revise: bool`, `assessment: str` | protocol |
| `soothe.protocol.plan.dag_snapshot` | `steps: list[StepDepDict]` | debug |
| `soothe.protocol.plan.plan_only` | `thread_id: str`, `goal: str`, `step_count: int` | protocol |

### Policy Protocol

| Type | Fields | Verbosity |
|------|--------|-----------|
| `soothe.protocol.policy.checked` | `action: str`, `verdict: str`, `profile: str` | protocol |
| `soothe.protocol.policy.denied` | `action: str`, `reason: str`, `profile: str` | protocol |

### Goal Protocol

| Type | Fields | Verbosity |
|------|--------|-----------|
| `soothe.protocol.goal.created` | `goal_id: str`, `description: str`, `priority: int\|str` | protocol |
| `soothe.protocol.goal.completed` | `goal_id: str` | protocol |
| `soothe.protocol.goal.failed` | `goal_id: str`, `error: str`, `retry_count: int` | protocol |
| `soothe.protocol.goal.batch_started` | `goal_ids: list[str]`, `parallel_count: int` | protocol |
| `soothe.protocol.goal.report` | `goal_id: str`, `step_count: int`, `completed: int`, `failed: int`, `summary: str` | protocol |
| `soothe.protocol.goal.directives_applied` | `goal_id: str`, `directives_count: int`, `changes: list` | protocol |
| `soothe.protocol.goal.deferred` | `goal_id: str`, `reason: str`, `plan_preserved: bool` | protocol |

---

## Tool Events

### Generic Tool Events

| Type | Fields | Verbosity |
|------|--------|-----------|
| `soothe.tool.{name}.started` | `tool: str`, `args: str?`, `kwargs: str?` | tool_activity |
| `soothe.tool.{name}.completed` | `tool: str`, `result_preview: str?` | tool_activity |
| `soothe.tool.{name}.failed` | `tool: str`, `error: str` | tool_activity |

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

## Subagent Events

### Browser Subagent

| Type | Fields | Verbosity |
|------|--------|-----------|
| `soothe.subagent.browser.step` | `step: int\|str`, `url: str`, `action: str`, `title: str`, `is_done: bool` | subagent_progress |
| `soothe.subagent.browser.cdp` | `status: str`, `cdp_url: str?` | subagent_progress |

### Claude Subagent

| Type | Fields | Verbosity |
|------|--------|-----------|
| `soothe.subagent.claude.text` | `text: str` | subagent_custom |
| `soothe.subagent.claude.tool_use` | `tool: str` | subagent_custom |
| `soothe.subagent.claude.result` | `cost_usd: float`, `duration_ms: int` | subagent_custom |

### Research Subagent

| Type | Fields | Verbosity |
|------|--------|-----------|
| `soothe.subagent.research.web_search` | `query: str`, `engines: list[str]` | subagent_custom |
| `soothe.subagent.research.search_done` | `result_count: int` | subagent_custom |
| `soothe.subagent.research.queries_generated` | `count: int`, `queries: list[str]` | subagent_custom |
| `soothe.subagent.research.completed` | *(none)* | subagent_custom |

### Skillify Subagent

| Type | Fields | Verbosity |
|------|--------|-----------|
| `soothe.subagent.skillify.indexing_pending` | `query: str` | subagent_custom |
| `soothe.subagent.skillify.retrieve_started` | `query: str` | subagent_custom |
| `soothe.subagent.skillify.retrieve_completed` | `query: str`, `result_count: int`, `top_score: float` | subagent_custom |
| `soothe.subagent.skillify.retrieve_not_ready` | `message: str` | subagent_custom |
| `soothe.subagent.skillify.index_started` | `collection: str` | subagent_custom |
| `soothe.subagent.skillify.index_updated` | `new: int`, `changed: int`, `deleted: int`, `total: int` | subagent_custom |
| `soothe.subagent.skillify.index_unchanged` | `total: int` | subagent_custom |
| `soothe.subagent.skillify.index_failed` | *(none)* | subagent_custom |

### Weaver Subagent

| Type | Fields | Verbosity |
|------|--------|-----------|
| `soothe.subagent.weaver.analysis_started` | `task_preview: str` | subagent_custom |
| `soothe.subagent.weaver.analysis_completed` | `capabilities: list`, `constraints: list` | subagent_custom |
| `soothe.subagent.weaver.reuse_hit` | `agent_name: str`, `confidence: float` | subagent_custom |
| `soothe.subagent.weaver.reuse_miss` | `best_confidence: float` | subagent_custom |
| `soothe.subagent.weaver.skillify_pending` | *(none)* | subagent_custom |
| `soothe.subagent.weaver.harmonize_started` | `skill_count: int` | subagent_custom |
| `soothe.subagent.weaver.harmonize_completed` | `retained: int`, `dropped: int`, `bridge_length: int` | subagent_custom |
| `soothe.subagent.weaver.generate_started` | `agent_name: str` | subagent_custom |
| `soothe.subagent.weaver.generate_completed` | `agent_name: str`, `path: str` | subagent_custom |
| `soothe.subagent.weaver.validate_started` | `agent_name: str` | subagent_custom |
| `soothe.subagent.weaver.validate_completed` | `agent_name: str` | subagent_custom |
| `soothe.subagent.weaver.registry_updated` | `agent_name: str`, `version: str` | subagent_custom |
| `soothe.subagent.weaver.execute_started` | `agent_name: str`, `task_preview: str` | subagent_custom |
| `soothe.subagent.weaver.execute_completed` | `agent_name: str`, `result_length: int` | subagent_custom |

### Inquiry Subagent

| Type | Fields | Verbosity |
|------|--------|-----------|
| `soothe.subagent.inquiry.analyze` | `topic: str` | subagent_custom |
| `soothe.subagent.inquiry.sub_questions` | `count: int` | subagent_custom |
| `soothe.subagent.inquiry.queries_generated` | `queries: list[str]` | subagent_custom |
| `soothe.subagent.inquiry.gather` | `query: str`, `domain: str` | subagent_custom |
| `soothe.subagent.inquiry.gather_done` | `query: str`, `result_count: int`, `sources_used: list[str]` | subagent_custom |
| `soothe.subagent.inquiry.summarize` | `total_summaries: int` | subagent_custom |
| `soothe.subagent.inquiry.reflect` | `loop: int` | subagent_custom |
| `soothe.subagent.inquiry.reflection_done` | `loop: int`, `is_sufficient: bool`, `follow_up_count: int` | subagent_custom |
| `soothe.subagent.inquiry.synthesize` | `topic: str`, `total_sources: int` | subagent_custom |
| `soothe.subagent.inquiry.completed` | `answer_length: int` | subagent_custom |

### Generic Subagent Tool Events

| Type | Fields | Verbosity |
|------|--------|-----------|
| `soothe.subagent.{agent}.tool_started` | `tool: str`, `args: str?`, `kwargs: str?` | subagent_custom |
| `soothe.subagent.{agent}.tool_completed` | `tool: str`, `result_preview: str?` | subagent_custom |
| `soothe.subagent.{agent}.tool_failed` | `tool: str`, `error: str` | subagent_custom |

---

## Output Events

| Type | Fields | Verbosity |
|------|--------|-----------|
| `soothe.output.chitchat.started` | `query: str` | protocol |
| `soothe.output.chitchat.response` | `content: str` | assistant_text |
| `soothe.output.autonomous.final_report` | `goal_id: str`, `description: str`, `status: str`, `summary: str` | assistant_text |

---

## Error Events

| Type | Fields | Verbosity |
|------|--------|-----------|
| `soothe.error.general` | `error: str` | error |

---

## Verbosity Classification

Events are classified into verbosity categories that determine visibility:

| Domain | Default Verbosity | Description |
|--------|-------------------|-------------|
| `lifecycle` | protocol | Thread and session lifecycle events |
| `protocol` | protocol | Core protocol activity events |
| `tool` | tool_activity | Main agent tool execution events |
| `subagent` | subagent_custom | Subagent activity (promoted events use `subagent_progress`) |
| `output` | assistant_text | Content destined for user display |
| `error` | error | Error events (always shown) |

**Note**: Some subagent events (e.g., browser step events) are promoted to `subagent_progress` verbosity for visibility at normal verbosity level.

---

**See Also**: [RFC-0015](RFC-0015.md) for event architecture and design principles.