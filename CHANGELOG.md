# Changelog

All notable changes to the Soothe project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [v0.7.16] - 2026-07-13

### Changed
- Scripts/VERSION synchronization for release consistency

## [v0.7.15] - 2026-07-12

### Added
- Configurable model roles for planner, monitor, and consensus paths
- Optional extras to core soothe dependencies
- Log retention and `tail_background_log` for execution tools
- Streaming stdout cap for execution tools

### Changed
- Merged `create_chat_model_with_fallback` into `create_chat_model` for automatic retry
- Subagent models now resolve from explicit `provider:model` config, taking precedence over `model_role`
- Removed deepagents execute tool in favor of host execution tools
- Improved background log lifecycle with immediate headers and kill footers
- Loop token usage tracking across StrangeLoop lifecycle

### Fixed
- Goal completion display showing planning text instead of deliverables

## [v0.7.14] - 2026-07-12

### Added
- Cancel/queued-goal guards
- Token usage tracking in daemon stream and TUI

### Changed
- Dropped Claude core agent + fastembed

### Fixed
- Fixed release-docker validation failures on push to main by using step outputs instead of secrets in if expressions
- Fixed goal completion display showing planning text instead of deliverables
- Tame completed step footer tone
- CLI version resolution on editable installs

## [v0.7.13] - 2026-07-11

### Added
- Declarative tool-call/step-count limits (replacing content heuristics)
- Loop token usage tracking across StrangeLoop lifecycle
- Opt-in MCP builtins with progressive tool loading

### Changed
- Replaced content heuristics with declarative tool-call/step-count limits (RFC-631)
- Tool-heavy goals now synthesize instead of replaying truncated execute monologue
- Raised execute AI ledger cap to 64K
- Merged `/tokens` into `/context` modal
- Detected response language in Pass 1 and injected explicit prose directives

## [v0.7.12] - 2026-07-11

### Added
- MCP progressive tool loading with search-promote-bind runtime

### Changed
- CI workflow updates
- Updated deploy to install grep backends and wire TAVILY_API_KEY

### Fixed
- TUI chat input focus issues

## [v0.7.11] - 2026-07-10

### Added
- Debug env to deploy
- Reduced step card tool call preview from 3 to 2 lines

### Changed
- Centralized daemon metadata merge for checkpoint writes
- Consolidated workspace mount resolution and checkpoint merge
- Dropped redundant host_root/container_root kwargs

### Fixed
- Fixed mount-aware source labeling
- Fixed force-kill admission release and removed legacy cancel path
- Preserved loop workspace mount metadata after `/clear` and checkpoint save

## [v0.7.10] - 2026-07-09

### Added
- IG-572 subagent wire display guide

### Changed
- Ran `make format` across all 1,522 files in all packages

### Fixed
- Forwarded subagent wire progress to TUI and unified builtin activity protocol
- Fixed LoopPersistenceWriter cross-event-loop failures
- Fixed filesystem tools resolving against daemon temp workspace

## [v0.7.8] - 2026-07-08

### Added
- Ctrl+T plan tree with deps, live stats, single-line rows
- Execute AI ledger cap

### Changed
- Hardened execute-step scope and replan-wave ledger projection
- Wired RFC-214 `core_agent_message_id` dedup for execute-step projection

### Fixed
- Hardened Pass 1 intake prompts against vendor identity leaks
- Emit Pass 1 social replies verbatim
- Replaced `## Result` execute retry with Step Deliverable Gate

## [v0.7.7] - 2026-07-07

### Added
- IG-557 Plan Gap Analysis (Phases A-G):
  - Assess-only projection and v2 task envelope
  - Guard premature goal_progress=complete at mid-goal
  - Inject PREVIOUS ASSESSMENT from CE last_assessment
  - Feed remaining_gaps into plan-generate
  - Persist assess audit on GoalNode
  - Stop plan_assess ledger pairs
- deep_research and academic_research subagents (replaced tacitus)

### Fixed
- Removed dead code from assess compaction and unused config

## [v0.7.6] - 2026-07-06

### Added
- Goal completion synthesis with GFM tables, bullets, Mermaid blocks format hints (IG-552)
- File-change previews for all surgical write tools

### Changed
- TUI file-change cards use single-word action prefixes (Writing, Editing, Created)

### Fixed
- Fixed step failure caused by tool error
- Prevented plan=keep remount of successful steps

## [v0.7.5] - 2026-07-06

### Added
- Idempotent database bootstrap + migrations (replacing sql_migrations)

### Changed
- High-performance persistence + mid-loop continuation routing
- Bound multi-goal loop ledger growth to keep planner context scalable

### Fixed
- Fixed execute-step stream fan-out to avoid duplicate events
- Removed init-db.sql, rely on auto-provisioning

## [v0.7.4] - 2026-07-06

### Added
- Execute-step tool budget raised to 999
- Edit coalescing on stream teardown
- Log retention and background tool logs

### Changed
- Replaced `## Result` execute retry with Step Deliverable Gate

### Fixed
- Fixed edit coalescing on stream teardown
- Added inventor attribution to assistant identity responses
- Unified assistant identity handling
- Added hot-reload for config changes with watchdog
- Unified LLM rate limiting, shortened 429 retry timeouts

## [v0.7.3] - 2026-07-05

### Added
- Skill auto-invoke with improved matching and tool generation
- invoke_tools method to skill registry

### Changed
- Refined skill auto-invoke with improved matching and tool generation
- Enhanced skill_activation middleware with better context handling
- Wired auto-invoke tools into system prompt

## [v0.6.17] - 2026-06-28

### Added
- Same-file edit concurrency optimization (RFC-902)
- EditCoalescingMiddleware and async file I/O (IG-517)
- IntentClassifiedEvent for agentic intents (IG-518)
- 24h timeout for task tool invoking subagents (IG-516)

### Changed
- Perf: ungate `ag`, gate Python fallback, honor .gitignore (IG-520)
- Cached SkillIndex, fixed skill snapshot

### Fixed
- Reasoning field handling

## [v0.6.16] - 2026-06-26

### Changed
- Removed unused code from CLI package
- Extracted step card activity module
- Split message widgets package
- Fixed tool stats display

## [v0.6.15] - 2026-06-26

### Added
- Tool timeout middleware and grep fallback hang recovery (IG-511, IG-512)
- Full_description for enhanced step execution context (IG-510)
- Reusable SootheRunner per daemon worker (IG-506)

### Changed
- Speed up TUI connect by deferring card replay and empty-loop derivation
- Streamlined config templates
- Lazy CoreAgent materialization

### Fixed
- Handled paths outside workspace

## [v0.6.14] - 2026-06-26

### Added
- IdentityProtocol for AKSK auth and JWT token management (RFC-307)

### Changed
- Removed chunk-level timeout, unified with LLMRateLimitMiddleware (IG-506)
- Removed HTTP REST protocol remnants, WebSocket-only transport (IG-504)

### Fixed
- Fixed timeout errors misclassified as rate-limit

## [v0.6.13] - 2026-06-25

### Added
- Natural language scheduling via CLI and TUI (RFC-229)

### Changed
- Removed HTTP REST channel, WebSocket-only transport (IG-504)
- Enhanced config env var resolution

## [v0.6.12] - 2026-06-25

### Added
- goal_unblocked event for responsive scheduling (RFC-622, RFC-625)
- Cron service for scheduled task management
- Clear loop archival (IG-500)
- HTTP 429 rate limit retry with exponential backoff (IG-499)
- daemon_version and core_version to daemon status

### Fixed
- Fixed file descriptor leak and added network resilience for LLM calls (IG-503)

## [v0.6.11] - 2026-06-18

### Added
- SQLite as default persistence backend with concurrent loop support
- PostgreSQL connection retry with exponential backoff
- Wrapped checkpointer initialization with retry for DB restart resilience

### Changed
- Removed dead code and deprecated workspace functions
- Flattened managers and entities modules

## [v0.6.10] - 2026-06-17

### Added
- Job entity, JobManager, ExecutionCheckpoint for state management
- Trace documentation
- Consolidated SOOTHHE_HOME usage

### Changed
- Modularized executor and consolidated IG numbering
- Raised parallelism defaults
- Unified LLM utilities into soothe.utils.llm package (RFC-627)
- Flattened loop.limits into categorized config sections

## [v0.6.9] - 2026-06-16

### Changed
- Reduced STEP_CARD_TOOL_ACTIVITY_PREVIEW_COUNT to 3

## [v0.6.8] - 2026-06-14

### Changed
- Routine version increment

## [v0.6.7] - 2026-06-13

### Changed
- Routine version increment with bypass test assertion fix

## [v0.6.6] - 2026-06-12

### Fixed
- Fixed loop evidence fallback and show subgraph tool activity

## [v0.6.5] - 2026-06-12

### Changed
- Routine version increment

## [v0.6.4] - 2026-06-11

### Fixed
- Fixed CI test-unit failure when package lacks tests/unit directory

## [v0.6.3] - 2026-06-10

### Changed
- Routine version increment

## [v0.6.2] - 2026-06-10

### Added
- Progressive tools and output caps (IG-478)

## [v0.6.1] - 2026-06-09

### Changed
- Routine version increment

## [v0.6.0] - 2026-06-09

### Added
- Major baseline release

---

## Release Notes Summary

### Key Themes in v0.7.x

- **Model Configuration**: Role fallback consolidation, subagent model spec overrides, configurable model roles
- **Ledger/Gates (RFC-631)**: Structural tool-call/step-count limits replacing content heuristics
- **Skill Auto-Invoke**: Improved matching and tool generation
- **CLI/TUI Polish**: Report formatting, file-change cards, format hints for goal completion, token tracking
- **Execution Hardening**: Tool budgets, edit coalescing, checkpoint/workspace handling, background tool logs
- **Workspace/Checkpoint**: Mount resolution, metadata preservation, daemon metadata merge
- **MCP Progressive Loading**: Opt-in MCP builtins with search-promote-bind runtime
- **Plan Gap Analysis (IG-557)**: Phase A-G for assess-only projection, remaining_gaps feeding
- **CI/CD**: Docker release workflow fixes, cancel/queued-goal guards
- **Code Quality**: System-wide formatting pass (1,522 files)

### Key Themes in v0.6.x

- **WebSocket-Only Transport**: Removed HTTP REST channel (IG-504)
- **Persistence Backends**: SQLite default, PostgreSQL retry with exponential backoff
- **Rate Limiting**: Unified LLM rate limiting, chunk-level timeout removal (IG-506)
- **Identity Protocol**: AKSK auth and JWT token management (RFC-307)
- **Scheduling**: Natural language scheduling (RFC-229), cron service, goal_unblocked events
- **Filesystem Concurrency**: Same-file edit optimization (RFC-902), EditCoalescingMiddleware (IG-517)
- **Intent Classification**: IntentClassifiedEvent for agentic intents (IG-518)
- **Modularization**: Executor modularization, LLM utilities consolidation (RFC-627)
- **Progressive Tools**: Progressive tools and output caps (IG-478)

[Unreleased]: https://github.com/mirasoth/soothe/compare/v0.7.15...HEAD
[v0.7.15]: https://github.com/mirasoth/soothe/releases/tag/v0.7.15
[v0.7.14]: https://github.com/mirasoth/soothe/releases/tag/v0.7.14
[v0.7.13]: https://github.com/mirasoth/soothe/releases/tag/v0.7.13
[v0.7.12]: https://github.com/mirasoth/soothe/releases/tag/v0.7.12
[v0.7.11]: https://github.com/mirasoth/soothe/releases/tag/v0.7.11
[v0.7.10]: https://github.com/mirasoth/soothe/releases/tag/v0.7.10
[v0.7.9]: https://github.com/mirasoth/soothe/releases/tag/v0.7.9
[v0.7.8]: https://github.com/mirasoth/soothe/releases/tag/v0.7.8
[v0.7.7]: https://github.com/mirasoth/soothe/releases/tag/v0.7.7
[v0.7.6]: https://github.com/mirasoth/soothe/releases/tag/v0.7.6
[v0.7.5]: https://github.com/mirasoth/soothe/releases/tag/v0.7.5
[v0.7.4]: https://github.com/mirasoth/soothe/releases/tag/v0.7.4
[v0.7.3]: https://github.com/mirasoth/soothe/releases/tag/v0.7.3
[v0.6.17]: https://github.com/mirasoth/soothe/releases/tag/v0.6.17
[v0.6.16]: https://github.com/mirasoth/soothe/releases/tag/v0.6.16
[v0.6.15]: https://github.com/mirasoth/soothe/releases/tag/v0.6.15
[v0.6.14]: https://github.com/mirasoth/soothe/releases/tag/v0.6.14
[v0.6.13]: https://github.com/mirasoth/soothe/releases/tag/v0.6.13
[v0.6.12]: https://github.com/mirasoth/soothe/releases/tag/v0.6.12
[v0.6.11]: https://github.com/mirasoth/soothe/releases/tag/v0.6.11
[v0.6.10]: https://github.com/mirasoth/soothe/releases/tag/v0.6.10
[v0.6.9]: https://github.com/mirasoth/soothe/releases/tag/v0.6.9
[v0.6.8]: https://github.com/mirasoth/soothe/releases/tag/v0.6.8
[v0.6.7]: https://github.com/mirasoth/soothe/releases/tag/v0.6.7
[v0.6.6]: https://github.com/mirasoth/soothe/releases/tag/v0.6.6
[v0.6.5]: https://github.com/mirasoth/soothe/releases/tag/v0.6.5
[v0.6.4]: https://github.com/mirasoth/soothe/releases/tag/v0.6.4
[v0.6.3]: https://github.com/mirasoth/soothe/releases/tag/v0.6.3
[v0.6.2]: https://github.com/mirasoth/soothe/releases/tag/v0.6.2
[v0.6.1]: https://github.com/mirasoth/soothe/releases/tag/v0.6.1
[v0.6.0]: https://github.com/mirasoth/soothe/releases/tag/v0.6.0
