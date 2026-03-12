# Configuration and Documentation Revision Guide

**Guide**: IG-008
**Title**: Configuration Examples, Documentation, and AI Agent Rules
**Created**: 2026-03-12
**Related RFCs**: RFC-0001, RFC-0002, RFC-0003

## Overview

This guide covers the creation of configuration reference files, a comprehensive user guide,
an updated README, and revised AI agent development rules (AGENTS.md). The goal is to
provide complete onboarding documentation for both human users and AI agents working on
the Soothe codebase.

## Prerequisites

- [x] RFC-0001 accepted (System Conceptual Design)
- [x] RFC-0002 accepted (Core Modules Architecture Design)
- [x] RFC-0003 accepted (CLI TUI Architecture Design)
- [x] IG-005 completed (Core Protocols Implementation)
- [x] IG-007 completed (CLI TUI Implementation)

## Deliverables

| File | Purpose |
|------|---------|
| `config/env.example` | All environment variables with descriptions |
| `config/config.yml` | Fully-commented YAML config example |
| `README.md` | Project overview, architecture, quick start, doc links |
| `docs/user_guide.md` | End-user guide (CLI, TUI, configuration, subagents) |
| `AGENTS.md` | AI agent development rules with full module map |

## Implementation Plan

### Phase 1: Configuration Examples

**config/env.example** -- Three categories of env vars:
1. `SOOTHE_*` vars (pydantic-settings auto-mapped from `SootheConfig`)
2. LLM provider keys (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`)
3. Tool-specific keys (`SERPER_API_KEY`, `JINA_API_KEY`, `TAVILY_API_KEY`)

**config/config.yml** -- Mirrors every field in `SootheConfig`:
- providers, router, subagents, tools, mcp_servers
- context_backend, memory_backend, planner_routing, policy_profile
- concurrency, vector_store, persistence settings

### Phase 2: README Rewrite

Replace the current README with:
- Vision statement from RFC-0001
- Architecture stack diagram
- Quick start (install, configure, run)
- Configuration pointers to `config/`
- CLI command overview
- Project structure tree
- Doc links (RFCs, impl guides, user guide)
- Privacy, development, license

### Phase 3: User Guide

Write `docs/user_guide.md` covering:
- Installation with optional extras
- Configuration (YAML + env vars)
- CLI usage (TUI mode, headless mode, thread management)
- TUI interface (slash commands, subagent routing)
- Subagent descriptions
- Protocol overview (user-facing)
- MCP integration
- Tool groups
- Troubleshooting

### Phase 4: AGENTS.md Revision

Expand AGENTS.md with:
- Updated architecture overview (CLI TUI layer, protocols, implementations)
- Complete module map with all packages
- Configuration system documentation
- RFC and impl guide references
- Design principles from RFC-0001

## Verification

- [ ] `config/env.example` lists all env vars from config.py, tools, and subagents
- [ ] `config/config.yml` has valid YAML matching every SootheConfig field
- [ ] README links all docs and has correct project structure
- [ ] User guide covers all CLI commands and TUI features
- [ ] AGENTS.md lists all source modules
- [ ] No broken internal doc links

## Related Documents

- [RFC-0001](../specs/RFC-0001.md) - System Conceptual Design
- [RFC-0002](../specs/RFC-0002.md) - Core Modules Architecture Design
- [RFC-0003](../specs/RFC-0003.md) - CLI TUI Architecture Design
- [IG-005](./005-core-protocols-implementation.md) - Core Protocols Implementation
- [IG-007](./007-cli-tui-implementation.md) - CLI TUI Implementation
