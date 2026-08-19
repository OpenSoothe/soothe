---
title: Subagents
parent: User Guides
nav_order: 4
description: >-
  Built-in specialized subagents: usage, configuration, and architecture.
audience: user
---

# Subagents

Subagents are specialized autonomous agents that perform multi-step, stateful workflows. They extend Soothe's capabilities beyond simple tool invocations, enabling complex operations like structured planning, deep research, and browser automation.

Core Soothe ships five built-in subagents: **planner**, **deep_research**, **academic_research**, **browser_use**, and **veritas**. Semantic skill discovery uses the daemon-shared **Skillify** service via the `search_skills` tool (see `skillify` in config). Additional optional delegated agents (e.g. **weaver**) are maintained in the external **`soothe-plugins`** package.

> Source: `packages/soothe/src/soothe/subagents/`

---

## Overview

| Subagent | Slash Command | Best For |
|----------|---------------|----------|
| Deep Research | `/deep_research <query>` | Public web research, comparisons, how-tos |
| Academic Research | `/academic_research <query>` | Papers, literature reviews, citations |
| Planner | `/plan` or `/plan <prompt>` | Plan-mode routing |
| Browser Use | `/browser_use <url>` | Browser automation and web interaction |
| Veritas | (auto-invoked) | Clarification auto-answerer in autonomous mode |

Semantic skill search is **not** a subagent — use the `search_skills` tool or ask the agent to search deferred skills. Configure via top-level `skillify:` (see [YAML reference](configuration-guide/yaml-reference.md)).

**Local codebase analysis** uses the main agent's file tools (`read_file`, `grep`, `glob`) — not the research subagents.

---

## Subagent vs Tool

The distinction is architectural. Tools are stateless, single-shot, and immediate. Subagents are stateful, multi-step, and long-running. A subagent uses the LLM to decide *which* tool to call *next*, based on what it has learned so far.

| Dimension | Tool | Subagent |
|-----------|------|----------|
| LLM calls | Zero or one | Multiple, orchestrated |
| State | Stateless | Stateful (accumulates findings) |
| Duration | Milliseconds to seconds | Seconds to minutes |
| Output | Direct result | Structured report |

Use a subagent when the *path* to the answer is unknown and must be discovered iteratively.

---

## Architecture Pattern

All subagents follow a consistent pattern (RFC-600/601): a `@plugin` + `@subagent` decorated factory function that returns a compiled LangGraph `StateGraph`. The graph has a typed state schema, LLM-driven nodes, tool nodes, conditional edges for flow control, and a structured output schema.

The critical contract: **state must include `messages: Annotated[list, add_messages]`** and the final node must return a single `AIMessage`. This is the `CompiledSubAgent` contract that allows subagents to be invoked by the main agent's `task` tool.

---

## Deep Research (`deep_research`)

Iterative **public web** research: plan → search → crawl top URLs → summarize → reflect → adaptive report.

**Capabilities**:
- Web search (wizsearch / configured engines)
- Crawl-on-discovery for top result URLs (shared `url_crawl` toolkit)
- Adaptive report sections (comparison, how-to, landscape, …)
- Mandatory **Scope** banner (web sources only; no local repo files)

**Usage**:
```bash
/deep_research Compare vector databases for RAG workloads
/deep_research What are the latest LangGraph checkpoint patterns?
```

**Effort levels** (default: `normal`):

| Level | Reflection loops | Crawl per search | Use when |
|-------|------------------|------------------|----------|
| `normal` | 2 | top 3 URLs | Faster lookup |
| `thorough` | 4 | top 5 URLs | Deeper investigation |

Set in config (`effort: thorough`) or in the task description (`effort: thorough` on the first line).

**Report delivery** (`save_reports`, default `false`):

| Value | Behavior |
|-------|----------|
| `false` | Full report returned inline as the subagent answer (no file write) |
| `true` | Full markdown saved under `.soothe/agents/deep_research/`; answer is a short summary plus the file path |

**Configuration**:
```yaml
subagents:
  deep_research:
    enabled: true
    config:
      effort: normal       # normal | thorough
      save_reports: false  # false: full report inline; true: save to file + short summary
```

For academic papers and literature reviews, use **`academic_research`** instead.

---

## Academic Research (`academic_research`)

Iterative **academic literature** research via DeepXiv search, with the same crawl-on-discovery and adaptive report pattern.

**Capabilities**:
- Academic paper / preprint search (DeepXiv)
- URL crawl for paper pages (shared `url_crawl` toolkit)
- Academic report scenarios (literature review, paper comparison, method survey, …)
- Mandatory **Scope** banner (academic sources only; no local repo files)

**Usage**:
```bash
/academic_research Literature review on retrieval-augmented generation 2024-2026
/academic_research Compare BERT vs modern embedding models for code search
```

**Effort levels**: same `normal` | `thorough` profiles as `deep_research`.

**Report delivery**: same `save_reports` knob as `deep_research` (default `false` returns the report inline; set `true` to write under `.soothe/agents/academic_research/`).

**Configuration**:
```yaml
subagents:
  academic_research:
    enabled: true
    config:
      effort: normal
      save_reports: false
```

Requires DeepXiv credentials (`DEEPXIV_API_KEY` / `DEEPXIV_TOKEN`) when configured.

---

## Browser Use (`browser_use`)

Browser automation specialist for web navigation and interaction (navigate, click, fill, extract, screenshot). Ships with base `soothe` dependencies but `on_load` verifies runtime deps.

**Usage**:
```bash
/browser_use Navigate to https://example.com and extract the main heading
```

**Configuration**:
```yaml
subagents:
  browser_use:
    enabled: true
```

---

## Veritas (`veritas`)

Intent-grounded clarification auto-answerer for autonomous mode. Not a general-purpose subagent — it's a **single structured-output LLM call** invoked by `AutoClarificationPolicy` when the StrangeLoop pauses on an `ask_user` interrupt. It produces a best-effort answer from the goal's first-principles context.

If veritas cannot answer with sufficient confidence, it sets `defer=True` and the loop transitions the goal to `awaiting_clarification` for out-of-band human resolution. This is the autonomous-mode safety valve: the system attempts self-resolution before blocking on human input.

---

## Planner (`planner`)

Multi-round planning subagent: iteratively refines a markdown execution plan until the model declares it complete, then returns a single structured report. The design separates plan design from execution, giving the main agent a stable blueprint to follow.

**Usage**:
```bash
/plan
/plan Create a REST API with authentication and rate limiting
```

**Key design decisions**:
- **Agentic refinement loop** — planning runs multiple refinement rounds until the model declares "done."
- **Configurable model role** — the resolver uses `subagents.planner.model_role` (default `think`) for plan-design loops.
- **Bounded cost** — explicit cap on `max_plan_rounds` prevents runaway refinement loops.
- Registered as `name="planner"`; triggers include `planner`, `decompose`, `roadmap`, `break down`.

---

## Model Role Resolution

Subagents use specific model roles, not the main agent's model. This is a cost optimization:

| Subagent | Model Role | Config | Rationale |
|----------|------------|--------|-----------|
| planner | `think` (default) | `model` or `model_role` | Explicit `provider:model` wins over role |
| deep_research | `fast` | `model` or router default | Optional explicit `provider:model` override |
| academic_research | `fast` | `model` or router default | Same resolution as deep_research |
| browser_use | `default` | `subagents.browser_use.model_role` | Browser step planning uses the default model |

Built-in subagents ignore `subagents.<name>.model_role` when `model` (explicit `provider:model`) is set. Use `model_role` for router-based selection; use `model` to pin a specific provider/model.

---

## Workspace Isolation

Subagents inherit workspace boundaries from the invoking context. The resolver provides a static workspace (daemon workspace) as a fallback, but thread-level workspace is injected at runtime via `state.workspace`. This means subagent operations are always scoped — a subagent invoked in thread A cannot access thread B's workspace.

---

## Optional Plugin Subagents

The `soothe-plugins` package provides additional delegate subagents (e.g. **weaver**, **claude**). Install `soothe-plugins` and follow its README for configuration.

---

## Related Guides

- [TUI Guide](tui-guide.md) — Slash commands and routing
- [Configuration Guide](configuration-guide/index.md) — Subagent configuration
- [Troubleshooting](troubleshooting/index.md) — Common subagent issues
- [Capabilities Overview](capabilities/index.md) — Tools, MCP, and plugin system
