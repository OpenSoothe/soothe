---
title: CHANGELOG
layout: default
nav_order: 4
description: All notable changes to Soothe are documented in this file, following the Keep a Changelog format.
permalink: /changelog/
---

# Changelog

All notable changes to Soothe are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## Version Overview

| Version | Release Date | Summary |
|---------|-------------|---------|
| **0.7.x** | 2026-06-30+ | Current — router profiles, skill runtime discovery, sloop refactor, explore removal, config hot-reload |
| **0.6.x** | 2025-Q2+ | HTTP REST removed, soothe-plugins package, 15 channels, unified autonomous config |
| **0.5.x** | 2025-01+ | RFC-220 loop orchestrator, deployment guides |
| **0.4.x** | 2024-Q4 | Protocol consolidation, multi-package monorepo, RFC-802 PostgreSQL |
| **0.3.x** | 2024-Q3 | Daemon multi-transport (WebSocket, Unix Socket), event system |
| **0.2.x** | 2024-Q2 | CoreAgent + StrangeLoop, autonomous goal execution |
| **0.1.x** | 2024-Q1 | Initial prototype - basic agent runtime |

---

## [Unreleased]

### Changed - Deep Research subagents (RFC-619, 2026-07-07)

- Replaced the monolithic research subagent with **`deep_research`** (public web) and **`academic_research`** (academic literature)
- Slash routes: `/deep_research`, `/academic_research`
- Effort levels: `normal` | `thorough` (replaces `normal` / `high` / `xhigh`)
- Shared `url_crawl` toolkit; crawl-on-discovery after each search
- Adaptive research reports with mandatory Scope banner

---

## [0.7.0] - 2026-06-30

### Added - Router Profiles

Replaced flat `router:` config with named router profiles (RFC-450, IG-530):

```yaml
router_profiles:
  - name: default
    router:
      default: openai:gpt-4o-mini
      think: null
      fast: null
      image: null
      ocr: null
active_router_profile: default
embedding_profile:
  - model_role: openai:text-embedding-3-small
    embedding_dims: 1536
```

### Added - Environment-First Provider Bootstrap

Providers can now be configured via environment variables without YAML (IG-530). SQLite with `sqlite_vec` is the default vector store for local development.

### Added - Daemon WebSocket Protocol Standardization

Daemon WebSocket standardized on protocol-1 (RFC-450). All clients use the same protocol layer.

### Added - Start-Phase LLM Intake Routing

RFC-630 Phase A: LLM-based intake routing with 4-class label (IG-528). Phase B+C completed: legacy simple-bypass removed.

### Changed - SOOTHE_HOME Persistence Consolidation

Consolidated SOOTHE_HOME persistence into shared SQLite stores (IG-529). MemU memory backend disabled pending redesign.

### Changed - Checkpoint Async Writes

Async checkpoint writes with periodic flush (RFC-803 Phase 6, IG-523) for lower latency.

### Changed - Goal Completion Synthesis

Improved goal-synthesis prompt design (IG-524).

### Fixed

- Graceful detach on closed connection with CE persistence fallback
- Premature stream abort when concurrent daemon queries run
- Direct LLM streaming + structured parse on local OMLX

---

## [0.7.1] - 2026-07-01

### Added - Daemon-TUI Performance Isolation

Performance isolation Phases 2–3 (IG-535 opt 3): daemon and TUI run independently with planning consolidation. TUI shows daemon startup status in thinking row.

### Changed - foundation.loop → foundation.sloop

Renamed `foundation.loop` package to `foundation.sloop` for terminology clarity. All import paths updated.

### Fixed

- Goal-completion stream tail preservation and worker lifecycle hardening
- TUI startup race, cancel resubmit poison, drift checker strict mode
- Durability thread metadata recovery on daemon restart

---

## [0.7.2] - 2026-07-03

### Added - Skill Runtime Discovery

Skill runtime discovery (IG-543, RFC-105 P1): skills are discovered and bound at turn 0 with tag-based matching.

### Added - Cross-Wave Step DAG Planning

Cross-wave step DAG planning (IG-539) and intent-classify prompt with ledger optimization (IG-540, RFC-214).

### Added - Execute-Step Ledger Projection

Execute-step ledger projection (IG-542) for predecessor context.

### Changed - General-Purpose Subagent Gate

Removed deprecated autopilot internals; added general-purpose subagent gate.

### Changed - System Prompt Handling

Refactored agent system prompt handling with builtin/default detection. Removed `git_status` from prompt injection system.

### Fixed

- Duplicate ledger messages when Slice A fallback overlaps Slice B
- LangGraph checkpointer serialization under PostgreSQL advisory lock

---

## [0.7.3] - 2026-07-05

### Added - Skill Auto-Invoke

Core skill auto-invoke with corpus matching and intake heuristics. Skills auto-invoke based on tag matching with word-boundary enforcement for short tags.

### Added - Cron Job APIs

Cron job APIs optimized; cron enabled by default. `agent.autonomous` renamed to `agent.autopilot`.

### Added - RFC-621 Workspace Mount Mapping

Workspace mount mapping for container deployments (RFC-621).

### Changed - Intake Routing Simplification

Collapsed quiz intake into trivial 3-class routing (RFC-630). Spinner labels centralized; event stats converted to structured JSON.

### Changed - Persistence I/O Deferral

Persistence I/O deferred to background tasks for lower latency.

### Fixed

- Test isolation issues and workspace validation logic
- Dead foundation code removed; vulture dead-code checks added

---

## [0.7.4] - 2026-07-06

### Added - Config Hot-Reload

Hot-reload for config changes with watchdog (IG-552). Config file changes are detected and applied without daemon restart.

### Added - Goal-Bound Display Snapshots

Goal-bound display snapshots and hardened worker lifecycle for TUI.

### Changed - Explore Subagent Removed

Removed `explore` subagent and all related dead code. General-purpose subagent gate retained.

### Changed - LLM Rate Limiting

Unified LLM rate limiting with shorter 429 retry timeouts to prevent agent hangs. Simplified rate limiting middleware.

### Changed - Assistant Identity

Unified assistant identity handling with inventor attribution. Hardened `browser_use` subagent.

### Fixed

- Execute-step tool budget raised to 999; edit coalescing hardened on stream teardown
- TUI streaming regression; skill discovery tools bound on turn 0

---

## [0.7.5] - 2026-07-06

### Added - High-Performance Persistence

High-performance persistence with mid-loop continuation routing fixes.

### Changed - Database Bootstrap

Replaced `sql_migrations` with `db_init` for idempotent bootstrap + migrations. Removed `init-db.sql`; relies on auto-provisioning for Soothe databases.

### Fixed

- Execute-step stream fan-out to avoid duplicate events and forward heartbeats
- Multi-goal loop ledger growth bounded to keep planner context scalable
- GitHub Pages deployment via gh-pages branch; Jekyll build hardened
- StrangeLoop checkpoint shutdown hardening

---

## [0.7.6] - 2026-07-06 (Current)

### Added - CLI Report Formatting

Goal-completion synthesis instructs GFM tables, bullets, and optional Mermaid blocks via per-scenario format hints (IG-552). Removed unused `synthesis_format.xml`.

### Changed - TUI File-Change Cards

TUI file-change cards use single-word action prefixes (Writing, Editing, Created) with labels consolidated in `file_tracker`. Dead preview-widget/CSS paths removed.

### Fixed

- File-change previews shown for all surgical write tools
- Plan=keep remount of successful steps prevented; secondary text style unified
- Docker build from source when PyPI packages unavailable

---

## [0.6.x] - 2025-Q2+

### Added - soothe-plugins Package

**Major change**: The monorepo now ships **5 packages** (previously 4).

| Package | Purpose |
|---------|---------|
| `soothe-sdk` | Shared SDK (protocol types, decorators, WebSocket client) |
| `soothe-cli` | CLI + TUI (`soothe` command) |
| `soothe` | Agent core (library) |
| `soothe-daemon` | Daemon server (`soothed` command) |
| `soothe-plugins` | Optional delegate subagents and community plugins |

### Added - Channel System

15 built-in channels for messaging platform integration:

- WebSocket, Slack, Feishu/Lark, Matrix, WhatsApp, Telegram, Signal, Email
- Discord, Microsoft Teams, Personal WeChat, Enterprise WeChat, DingTalk
- QQ, Mochat (Socket.IO)

### Added - Core Subagents

Six built-in subagents ship with the core `soothe` package:

- `planner`: Structured planning delegate
- `deep_research`: Public web research
- `academic_research`: Academic literature research
- `browser_use`: Browser automation specialist
- `skillify`: Skill discovery and invocation
- `veritas`: Intent-grounded clarification auto-answerer

### Changed - HTTP REST Transport Removed

HTTP REST transport has been removed. WebSocket is the supported transport. All daemon communication is via WebSocket RPC.

### Changed - Unified Autonomous Configuration

Autonomous settings are now nested under `agent.autonomous`:

```yaml
agent:
  autonomous:
    enabled: false
    max_iterations: 10
    max_retries: 2
```

### Changed - Thread Commands

Thread management uses the `loop` subcommand group:

- `soothe loop continue` — continue an existing loop
- `soothe loop list` — list loops
- `soothe loop new` — create a new loop

### Changed - Autopilot Command

`soothe autopilot run "..."` is the production autopilot path (was `soothe autopilot "..."`).

### Changed - Health Checks

`HealthChecker` class with `run_all_checks()` replaces the standalone `health_check()` function. Health check modules renamed (`protocols_check`, `config_check`, etc.).

---

## [Unreleased]

### Added

- RFC-220: LangGraph Agent Loop Orchestrator (IG-394, IG-396)
- Deployment Guide: Production setup, monitoring, security, scaling, backup/recovery
- Configuration Guide: Complete YAML reference, environment variables, common patterns
- Testing Guide: Comprehensive testing workflow and best practices
- Contributing Guide: Development workflow, code standards, PR process
- FAQ: Frequently asked questions organized by topic

### Changed

- RFC-224: Automatic context window management for StrangeLoop
- RFC-621: Workspace host convention for container deployments
- IG-434: Unified autonomous + autopilot configuration in `agent.autonomous`
- IG-407: Unified strange_loop configuration under `agent.loop`
- IG-052: Event system optimization with `register_event()` public API

### Fixed

- Various bug fixes and performance improvements

---

## [0.5.0] - 2025-01-XX

### Added - RFC-220 Loop Orchestrator

**Major feature**: LangGraph-based StrangeLoop orchestrator with evidence validation.

- **Loop Graph topology**: Plan → Execute → Assess → Adapt cycles
- **Evidence validation**: Plan-assess validates execution evidence
- **Langfuse bridge**: Loop-level LLM traces and token accounting
- **Output streaming**: RFC-614 multi-mode delivery (batch, adaptive, streaming)
- **Clarification relay**: RFC-622 auto-answerer via veritas subagent

**Configuration changes**:
```yaml
agent:
  loop:
    loop_orchestrator_evidence_validate: true
    goal_completion_mode: llm_only  # llm_only | heuristic_only | hybrid
    final_response: auto            # auto | always_synthesize
```

### Added - Deployment Infrastructure

- **Docker Compose**: Production stack with PostgreSQL + pgvector
- **Multi-database architecture**: RFC-802 separate databases for checkpoints, metadata, vectors, memory
- **Workspace host convention**: RFC-621 path mapping for container deployments
- **Health checks**: Daemon status, PostgreSQL connectivity
- **Backup strategies**: pg_dump, WAL streaming, Barman

### Changed - Configuration Consolidation

**IG-434**: Unified autonomous + autopilot configuration.

Previously separate sections merged into `agent.autonomous`:
```yaml
# Before (separate sections)
autonomous:
  enabled: false
autopilot:
  max_loops: 4

# After (unified)
agent:
  autonomous:
    enabled: false
    max_iterations: 10
    max_retries: 2
    max_parallel_goals: 3
```

**IG-407**: Unified strange_loop configuration under `agent.loop`.

All loop-related fields moved to nested structure:
```yaml
agent:
  loop:
    max_iterations: 10
    context_window_limit: 200000
    output_streaming:
      mode: adaptive
    llm_rate_limit:
      concurrent_limit: 10
```

### Changed - Event System

**IG-052**: Event system optimization.

- `register_event()` public API for module-level event registration
- Third-party plugins can register custom events without modifying core
- Reduced `event_catalog.py` by 12% (105 lines)
- Self-registration pattern for tool/subagent events

### Fixed

- Context projection bounds for GoalDispatchContextBundle (RFC-222 revised)
- Workspace reservation conflict gate (RFC-222 revised)
- Tool batch debouncing in output streaming
- Adaptive timeout scaling for large prompts (IG-295)

---

## [0.4.0] - 2024-Q4

### Added - Multi-Package Monorepo

**Major refactoring**: Consolidated into 5 packages.

| Package | Purpose |
|---------|---------|
| `soothe-sdk` | Shared SDK (protocol types, decorators, WebSocket client) |
| `soothe-cli` | CLI + TUI (`soothe` command) |
| `soothe` | Agent core (library) |
| `soothe-daemon` | Daemon server (`soothed` command) |
| `soothe-plugins` | Optional delegate subagents and community plugins |

**Dependency order**: `soothe-sdk` → `soothe-cli` → `soothe` → `soothe-daemon`

**Migration**:
- Previously: Single package `soothe` with all components
- Now: Separate packages with clear boundaries

### Added - PostgreSQL Multi-Database Architecture

**RFC-802**: Separate databases for lifecycle isolation.

```
PostgreSQL Cluster:
├── soothe_checkpoints  (LangGraph + StrangeLoop)
├── soothe_metadata     (Durability metadata)
├── soothe_vectors      (pgvector embeddings)
└── soothe_memory       (MemU long-term memory)
```

**Benefits**:
- Backup granularity
- Schema isolation
- pgvector extension requirements
- Performance optimization per workload

### Added - Protocol Resolver

Automatic protocol wiring from configuration:

```yaml
protocols:
  memory:
    enabled: true
    llm_chat_role: fast
    llm_embed_role: embedding
  planner:
    model: think
    routing: auto
  policy:
    profile: standard
  durability:
    backend: postgresql
```

Resolver maps config to backend implementations.

### Changed - Module Self-Containment (IG-047)

**Refactoring pattern**: Tests moved close to code they test.

```
packages/soothe/src/soothe/core/strange_loop/
├── graph.py
├── nodes.py

packages/soothe/tests/unit/core/strange_loop/
├── test_graph.py
├── test_nodes.py
```

**Benefits**:
- Easier test maintenance
- Clear source-to-test mapping
- Modular development

### Changed - Verification Script

`./scripts/verify_finally.sh` for pre-commit verification:

- Workspace integrity (`uv sync`)
- Dependency validation (SDK independence, CLI no daemon imports)
- Format + lint + unit tests
- Auto-fix mode (`--fix`)
- Quick mode (`--quick`)

**MANDATORY**: Run before every commit.

---

## [0.3.0] - 2024-Q3

### Added - Daemon Multi-Transport

**RFC-302**: Multi-transport daemon server.

| Transport | Use Case |
|-----------|----------|
| Unix Socket | Local CLI/TUI (filesystem permissions) |
| WebSocket | Remote clients (TLS via reverse proxy) |

**Configuration**:
```yaml
daemon:
  transports:
    unix_socket:
      enabled: true
      path: "~/.soothe/soothe.sock"
    websocket:
      enabled: true
      host: "0.0.0.0"
      port: 8765
```

### Added - External Authentication

**RFC-303**: Security by delegation model.

- **No built-in auth**: Soothe daemon trusts connections from reverse proxy
- **Reverse proxy handles**: TLS, authentication, authorization, rate limiting
- **Recommended**: nginx, Traefik, Kong, Envoy

See [Authentication Guide](authentication.md).

### Added - Event System

Event-driven architecture with protocol events:

- Memory events (injection, extraction)
- Planner events (plan created, step completed)
- Durability events (checkpoint saved, thread suspended)
- Subagent events (started, completed)

**Event registration**:
```python
register_event(MyCustomEvent, summary_template="Custom: {data}")
```

### Added - Thread Management

Persistent conversation threads:

- Thread directory: `~/.soothe/data/threads/<thread-id>/`
- Thread metadata: `thread_metadata.json`
- Thread continuation: `soothe loop continue`

See [Thread Management Guide](thread-management.md).

### Changed - CLI Architecture

- Typer CLI framework
- Textual TUI with split panels
- Headless mode (stdout/stderr)
- Daemon connection mode

---

## [0.2.0] - 2024-Q2

### Added - StrangeLoop

**RFC-201**: Agentic goal execution with Plan → Execute iterations.

```
User Query → StrangeLoop
  ↓
PLAN phase
  - Decompose goal
  - Generate plan steps
  ↓
EXECUTE phase
  - Execute steps
  - Collect results
  - Check completion
  ↓
If incomplete → PLAN again
If complete → Final response
```

**Max iterations**: 10 (configurable)

### Added - CoreAgent

**RFC-100**: LangGraph native agent runtime.

- `create_soothe_agent()` → `CompiledStateGraph`
- Model → Tools → Model loop
- Checkpointer integration
- Tool middleware (retry, limits)

### Added - Autonomous Mode

Multi-step autonomous task execution:

```yaml
agent:
  autonomous:
    enabled: false
    max_iterations: 10
    max_retries: 2
    max_total_goals: 50
    max_goal_depth: 5
```

See [Autonomous Mode Guide](autonomous-mode.md).

### Added - Subagents

Built-in specialized agents:

- `planner`: Planning delegate
- `deep_research`: Public web research (split from legacy monolithic research subagent in 0.7.x)
- `academic_research`: Academic literature research (0.7.x+)
- `browser_use`: Browser automation (added in 0.6.x)
- `veritas`: Clarification auto-answerer (added in 0.6.x)

### Changed - Configuration System

Pydantic v2 configuration:

- `SootheConfig` with `SOOTHE_` env prefix
- YAML config file support
- `${ENV_VAR}` interpolation
- Model router with purpose roles

---

## [0.1.0] - 2024-Q1

### Added - Initial Prototype

Basic agent runtime:

- LangGraph agent foundation
- Simple tool execution
- Basic memory integration
- Initial protocol definitions

**Limitations**:
- No multi-step planning
- No autonomous execution
- No daemon server
- Single package structure

---

## Release Notes

### Version Naming

- **MAJOR**: Breaking changes (API, configuration, architecture)
- **MINOR**: New features, enhancements (backward compatible)
- **PATCH**: Bug fixes, minor improvements

### Breaking Changes Policy

Breaking changes documented with:
- Migration guide
- Configuration changes
- Deprecation timeline (2 minor versions)

### RFC References

Major features reference RFCs:
- RFC-100: CoreAgent runtime
- RFC-201: StrangeLoop execution
- RFC-220: Loop orchestrator
- RFC-302: Daemon multi-transport
- RFC-802: PostgreSQL multi-database

See [RFC Index](../specs/).

---

## Upgrade Guides

### Upgrading from 0.4.x to 0.5.x

**Configuration changes**:

1. **Unified autonomous config**:
```yaml
# Before (0.4.x)
autonomous:
  enabled_by_default: false
autopilot:
  max_loops: 4

# After (0.5.x)
agent:
  autonomous:
    enabled_by_default: false
    max_loops: 4
```

2. **Unified strange_loop config**:
```yaml
# Before (0.4.x)
strange_loop:
  max_iterations: 10

# After (0.5.x)
agent:
  loop:
    max_iterations: 10
```

3. **Output streaming**:
```yaml
# New in 0.5.x
agent:
  loop:
    output_streaming:
      mode: adaptive  # batch | adaptive | streaming
```

**No breaking changes**: Old config still works (mapped automatically).

### Upgrading from 0.3.x to 0.4.x

**Multi-package monorepo**:

```bash
# Before (0.3.x)
pip install soothe

# After (0.4.x+)
pip install soothe soothe-cli soothe-daemon
```

**PostgreSQL multi-database** (RFC-802):
- Run `init-db.sql` to create 4 databases
- Update connection strings

---

## Future Roadmap

### Planned Features

1. **Benchmark reproduction**: [Compiler experiment](https://github.com/anthropics/claudes-c-compiler)
2. **Multi-agent collaboration**: Cross-daemon goal delegation
3. **Web UI**: Browser-based interface
4. **Plugin marketplace**: Community plugin registry
5. **Performance dashboard**: Real-time metrics UI

### RFC Pipeline

- RFC-700: Desktop app product redesign
- Web UI architecture (RFC number TBD — 8xx series is used by persistence backends)
- Plugin marketplace specification (RFC-900 series is used by deprecation/security)

---

## See Also

- **[Architecture Overview](architecture/index.md)** - System design
- **[Contributing Guide](contributing-guide.md)** - Development workflow
- **[FAQ](faq.md)** - Frequently asked questions
- **[RFC Index](../specs/)** - Specification documents
- **[GitHub Releases](https://github.com/mirasoth/soothe/releases)** - Release downloads