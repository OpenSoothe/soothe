---
title: Subagents
parent: User Guides
nav_order: 4
description: >-
  User-facing guide to built-in specialized subagents and community plugin agents.
audience: user
---

# Specialized Subagents

> **User guide.** For the architectural design, protocol contracts, and model
> role resolution of subagents, see
> **[Subagents Architecture](capabilities/subagents.md)**.

Core Soothe ships five built-in subagents: **planner**, **deep_research**, **academic_research**, **browser_use**, and **veritas**. Semantic skill discovery uses the daemon-shared **Skillify** service via the `search_skills` tool (see `skillify` in config). Additional optional delegated agents (e.g. **weaver** and other community plugins) are maintained in the **`soothe-plugins`** package—see that project's README and docs.

## Overview

| Subagent | Slash Command | Best For |
|----------|--------------|----------|
| Deep Research | `/deep_research <query>` | Public web research, comparisons, how-tos |
| Academic Research | `/academic_research <query>` | Papers, literature reviews, citations |
| Planner | `/plan` or `/plan <prompt>` | Plan-mode routing |
| Browser Use | `/browser_use <url>` | Browser automation and web interaction |
| Veritas | (auto-invoked) | Clarification auto-answerer in autonomous mode |

Semantic skill search is **not** a subagent — use the `search_skills` tool or ask the agent to search deferred skills. Configure via top-level `skillify:` (see [YAML reference](configuration-guide/yaml-reference.md)).

**Local codebase analysis** uses the main agent's file tools (`read_file`, `grep`, `glob`) — not the research subagents.

## Deep Research (`deep_research`)

Iterative **public web** research: search → crawl top URLs → reflect → adaptive report.

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

**Configuration**:
```yaml
subagents:
  deep_research:
    enabled: true
    config:
      effort: normal  # normal | thorough
```

For academic papers and literature reviews, use **`academic_research`** instead.

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

**Configuration**:
```yaml
subagents:
  academic_research:
    enabled: true
    config:
      effort: normal
```

Requires DeepXiv credentials (`DEEPXIV_API_KEY` / `DEEPXIV_TOKEN`) when configured.

## Browser Use Agent

Browser automation specialist for web navigation and interaction.

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

## Veritas Agent

Intent-grounded clarification auto-answerer for autonomous mode. Invoked automatically by `AutoClarificationPolicy` when the loop pauses on `ask_user`.

## Planner Agent

Planning and task decomposition for complex multi-step tasks.

**Usage**:
```bash
/plan
/plan Create a REST API with authentication and rate limiting
```

## Subagent Routing

### Slash Commands

```bash
/deep_research <query>      # Public web research
/academic_research <query>  # Academic literature research
/plan <prompt>              # Planner
/browser_use <url>          # Browser automation
```

Without a slash command, queries go to the main agent.

## Examples

```bash
/deep_research Compare Redis vs Memcached for session caching
/academic_research Survey papers on agent memory architectures
/browser_use Navigate to https://news.ycombinator.com and list the top 5 stories
```

## Optional Plugin Subagents

The `soothe-plugins` package provides additional delegate subagents (e.g. **weaver**, **claude**). Install `soothe-plugins` and follow its README for configuration.

## Related Guides

- [TUI Guide](tui-guide.md) - Slash commands and routing
- [Configuration Guide](configuration-guide/index.md) - Subagent configuration
- [Troubleshooting](troubleshooting/index.md) - Common subagent issues
- [Subagents Architecture](capabilities/subagents.md) - Architecture and protocol design
