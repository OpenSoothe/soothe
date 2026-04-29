# Changelog

All notable changes to Soothe are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.3.4] - 2026-04-19

### Added
- Dockerfile for Soothe daemon with full extras and Playwright support
- IG-300: per-loop daemon workspace under ``$SOOTHE_HOME/Workspace/<loop_id>/``; unified tool metadata helpers for policy path extraction; ``PolicyContext.workspace`` for stream-scoped filesystem checks

### Changed
- Migrated soothe-community to standalone project ([github.com/OpenSoothe/soothe-community](https://github.com/OpenSoothe/soothe-community))
- Removed soothe-community from monorepo workspace
- Centralized version management across monorepo packages
- Simplified version extraction logic
- Use Chinese Docker registry mirror for builds
- Move config files to `config/` directory
- IG-300: default ``security.allow_paths_outside_workspace`` to false (template + dev overlay); ``ConfigDrivenPolicy`` applies filesystem deny/allow/workspace rules to real deepagents tool names; workspace backend expands ``~`` in normalized paths; explore/research/claude subagents align with the security flag

### Fixed
- Version mismatch in packaging
- IG-301: adaptive per-call LLM timeout for large prompts (goal-completion synthesis no longer cut off at the 60s floor when the provider needs longer)
- IG-302: goal-completion synthesis runs under an ephemeral LangGraph ``thread_id`` so the checkpointer does not replay the full AgentLoop conversation; stream tags still use the parent thread id

## [0.3.3] - 2026-04-19

### Added
- Tool card arg/output placeholder hints in TUI and CLI (IG-216)
- Tool-call logging, display, and card mount fixes (IG-213, IG-214, IG-215)
- Claude DEBUG logging and goal tree sync (IG-212)
- Canonical tool-call resolution and logging config (IG-211)
- Unified CLI config and tool display cleanup (IG-209, IG-210)
- Tool-call UI gated by logging verbosity (IG-208)
- Cognition goal→steps tree card for AgentLoop (IG-207)
- Unified cognition plan card with phased reasoning (IG-206)
- Step ID correlation and cognition step cards (IG-205)

### Fixed
- PyPI publish: add `--native-tls` flag (IG-203)

## [0.3.2] - 2026-04-18

### Added
- Claude session bridge for subagent integration (IG-202)
- Dynamic workspace for Claude `cwd` (IG-201)
- Adaptive final response and daemon envelope (IG-199, IG-200, RFC-201)
- Subagent stream propagation and browser `max_steps` routing UX

### Changed
- Makefile build fixes (IG-203)

### Fixed
- AgentLoop/Runner: merge prior thread excerpts for Plan phase (IG-198)
- TUI: preserve progress line hierarchy indent
- Runner stream poll, plugin metadata, and event classification (IG-193, IG-194, IG-195)

## [0.3.1] - 2026-04-18

### Added
- Subagent progress events exposed via SDK with CLI/TUI display (IG-192)
- Multi-threaded loop lifecycle with goal thread management (RFC-608, IG-135)
- Goal context injection for Plan/Execute phases (RFC-609, IG-168)
- System message caching for prompt efficiency (IG-183)
- CLI/TUI step tree display polish (IG-182)
- Built-in skills restoration

### Changed
- Clean up deprecation references from soothe-sdk (IG-191)
- Separate CLI verbosity from daemon config (RFC-401)
- Remove iteration tracking from prompt construction
- Consolidate 16 RFCs into 10 (IG-188)
- Final RFC refinement and naming normalization (IG-185, IG-186, IG-187)

### Removed
- Deprecated `types` module from soothe-sdk

## [0.3.0] - 2026-04-16

### Added
- `soothe-sdk` package with WebSocket client and protocol primitives
- Multi-package monorepo structure (soothe, soothe-cli, soothe-sdk, soothe-community)
- Multi-package dependency validation in `verify_finally.sh`

### Changed
- **BREAKING**: Split Soothe into CLI and daemon packages
- Migrated CLI to pure WebSocket daemon communication (IG-175 Phase 2)
- Replaced all CLI daemon imports with SDK types in three batches (IG-174 Phase 1)
- Moved Rich dependencies from daemon to CLI (IG-176)
- Established CLI-daemon architectural boundaries for slash commands (RFC-404, IG-177)
- Improved logging separation and reasoning transparency
- Unified event naming semantics with present progressive tense (RFC-403)
- Reorganized tests into package-specific directories
- Extended SDK protocols and reorganized skills system
- Fixed CLI entry points architecture (IG-173)

### Fixed
- Headless error handling for immediate exit (IG-181)
- SDK import sorting errors
- Monorepo Makefile and GitHub workflows

## [0.2.12] - 2026-04-14

### Added
- Model catalog RPC for querying available models
- Per-turn model override support
- `UIConfig` and `UpdateConfig` for persisted preferences
- Per-thread model override in TUI
- Daemon-backed skill list and invocation
- Remember built-in skill
- Unified history to shared `history.jsonl` with sticky thinking indicator
- TUI daemon client session and shared essential UX events

### Changed
- DeepAgents CLI TUI migration with enhanced features (RFC-606, RFC-607)
- Extract `DEFAULT_EXECUTE_TIMEOUT` constant for centralized management
- AgentLoop default `max_iterations` updated to 10

### Fixed
- Config path references in TUI
- History file format conflict and robustness
- LangSmith env var resolution and daemon history parsing
- AgentLoop reasoning display and event type mismatch (IG-164)
- Autopilot mode parameter in TUI entry

## [0.2.11] - 2026-04-13

### Fixed
- `/cancel` command now bypasses input queue for immediate effect (IG-161)

## [0.2.10] - 2026-04-13

### Changed
- Updated community loop agent schema tests

## [0.2.9] - 2026-04-12

### Changed
- Cleaned up agentic event handling

### Removed
- Unused utility modules

## [0.2.8] - 2026-04-12

### Added
- Global cross-thread input history system

### Changed
- Simplified documentation and reorganized config structure

### Fixed
- Model wrapper compatibility
- LMStudio compatibility for limited OpenAI-compatible providers

## [0.2.7] - 2026-04-12

### Added
- Configurable WebSocket max frame size
- Goal header display with newline before final report (IG-162)

### Changed
- Completed event type renaming for agentic step events
- Optimized TUI output for brevity and tree mode steps (IG-158, IG-159)

### Fixed
- TUI instant display: removed over-aggressive suppression
- TUI cancel and PID display issues (IG-157)
- Next action display in TUI plan phase (IG-160)
- Agentic step events added to TUI essential events whitelist (IG-161)

## [0.2.6] - 2026-04-12

_No changes from 0.2.5 — duplicate tag._

## [0.2.5] - 2026-04-12

### Added
- Autopilot goal discovery and progress reporting (RFC-200, IG-155)
- GoalEngine → AgentLoop delegation (IG-154, IG-156)

### Changed
- Renamed planner API for consistency (IG-056)
- Renamed AgentLoop design pattern: ReAct → Plan-and-Execute (IG-153)
- Refined RFCs to reflect latest implementation (IG-153, IG-150, IG-149)

### Fixed
- PyPI packaging issues (IG-056)

## [0.2.4] - 2026-04-12

### Added
- Unified text preview utility replacing ad-hoc truncation
- Progressive actions display with RFC-603 reasoning quality
- Reason phase robustness (RFC-604, IG-149)

### Changed
- Renamed `SimplePlanner` to `LLMPlanner` for clarity
- Renamed Layer 2 to AgentLoop and enhanced planner robustness
- Consolidated planning module into `agent_loop` (IG-150)
- Refactored reasoning to structured output and polished CLI display
- Optimized LoopAgent message structure (RFC-207)
- Implemented step result outcome metadata optimization (RFC-211)
- Dynamic tool/system context injection (RFC-210)
- Executor thread isolation simplification (RFC-209)
- CoreAgent message optimization (RFC-208)
- CLI display refactoring with condensed action summary (IG-143)
- Extracted shared suppression state to reusable module

### Fixed
- WebSocket keepalive timeout (IG-153)
- Accurate token tracking and action truncation (IG-151, IG-152)
- Progressive actions repetition and path extraction bugs
- Final report streaming to accumulate `AIMessageChunk` content

### Removed
- Context Protocol and user_summary field
- Layer prefixes from logging statements

## [0.2.3] - 2026-04-08

### Added
- LLM tracing support (IG-136, IG-139)
- Daemon safeguards (IG-141)
- Layer 2 unified state checkpoint support (RFC-205, IG-134)
- Autopilot mode core components (RFC-204 Phase 1-4)
  - Daemon endpoints, webhooks, dreaming mode
  - TUI autopilot screen and dreaming integration
- SQLite backend for durability, persistence, and vector store (RFC-602)
- Unified presentation engine and headless progress stream
- TUI welcome banner and WebSocket-based thread list
- Shared system prompt prefix and headless stdout replay

### Changed
- **BREAKING**: Separated `SystemMessage`/`HumanMessage` types in message handling (RFC-207, IG-142)
- Consolidated prompts architecture (IG-137, IG-138, IG-140)
- Refactored LoopAgent to ReAct pattern (Reason + Act)
- Elevate foundation modules and reorganize UX layers
- Migrated weaver and skillify subagents to community module
- Unified workspace resolution across runner, daemon, and context injection

### Fixed
- Prior conversation duplication in Reason prompts (IG-133)
- SQLite checkpointer deferred creation for async context
- Agentic loop stdout suppression and final output shaping

## [0.2.2] - 2026-04-02

### Added
- Three-layer execution architecture (CoreAgent / LoopAgent / GoalEngine) (RFC-0023)
- CLI stream display pipeline with source prefix for debug mode (IG-103)
- Three-level tree progress display (RFC-0020)
- Client disconnect query cancellation
- Daemon heartbeat to prevent client timeout during long LLM operations
- Double-press Ctrl+C to exit TUI
- Unlimited concurrency support (`0 = unlimited`)
- Initial prompt support and unified TUI/CLI event display
- Workspace resolution with `SOOTHE_WORKSPACE` support
- Startup banner with version and transport info

### Changed
- Unified daemon transport to WebSocket-only (IG-102)
- Consolidated middleware into `core/agent/middleware` package
- Split `agent.py` into modular package
- Verbosity tier unification (RFC-0024)
- Tool event naming unification (RFC-0025)
- Subagent dispatched/completed events and tool event visibility (RFC-0020)
- Standardized plan and step ID formats

### Fixed
- Daemon thread cancel bug
- WebSocket session handling and daemon startup reliability
- Loop agent output capture and continue strategy
- Duplicate events and streaming display for agentic loops
- Thread context persistence across lifecycle transitions
- ChitchatStartedEvent hidden from user display

### Removed
- soothe-community package references

## [0.2.0] - 2026-03-28

### Added
- Daemon-side event filtering
- Parallel tool execution and research subagent integration
- Multi-package monorepo with plugin SDK and community packages
- Plugin system architecture with event bus
- Soothe SDK for plugin development
- Customizable display names for tools and subagents
- Health check CLI and TUI navigation
- Final report events and progress visibility
- Thread resume history recovery (RFC-0017)
- Unified thread management architecture (RFC-0017)
- Wizsearch with config-driven engine selection
- Agentic loop execution architecture
- Multi-transport daemon (Unix socket, WebSocket, HTTP)

### Changed
- TUI polish improvements
- CLI commands refactored to consistent nested pattern, then flattened
- Unified event processing system (RFC-0019)
- Module self-containment refactoring
- Migrated memU to internal implementation and added skills system
- Migrated inquiry to research subagent (RFC-0020, RFC-0021)

### Fixed
- TUI disconnection issue
- Classifier robustness and TUI event handling
- Browser subagent hanging issue
- Step dependencies display in plan output

## [0.1.6] - 2026-03-21

### Added
- Brave search engine for development
- Thread inactivity management and lifecycle handling
- Unified planning architecture

### Changed
- Consolidated tools architecture and introduced cognition/safety modules
- RFC-0013 polish

### Fixed
- All ruff linting errors

## [0.1.5] - 2026-03-21

### Added
- Inquiry engine for iterative multi-source research
- Progress event protocol for unified progress rendering (RFC-0015)
- Capability abstraction and tool consolidation

### Changed
- Removed scout/research subagents and introduced cognition module
- Consolidated websearch backends and fixed tool resolution
- Relocated config templates and improved progress output clarity
- Split large files and modularized code structure for AI-agent processability

### Fixed
- Remove `engines` parameter from websearch tool
- Subagent errors
- ExecuteTool parameter name mismatch with LLM calls

## [0.1.4] - 2026-03-19

### Added
- System prompt optimization based on LLM classification
- Scout-then-plan skill
- Path utilities and improved code organization
- Dual-protocol daemon RFC

### Changed
- Optimized unified classifier
- Removed planner subagent and added chitchat fast path
- Simplified planning workflow architecture and removed dead code
- Modularized CLI architecture
- Replaced vector/keyword memory backends with unified MemU backend

### Fixed
- CI pipeline issues
- CLI errors

## [0.1.3] - 2026-03-18

### Added
- Dynamic goal management (RFC-0011)
- Secure filesystem path handling and security policy (RFC-0012)
- Unified complexity classification and `init` command
- Failure recovery, progressive persistence, and artifact storage (RFC-0010)

### Changed
- Renamed `DirectPlanner` to `SimplePlanner` and unified classification system
- Refactored planner subsystem and fixed `goal_context` propagation
- Refactored resolver and runner into modular components
- Renamed bash tool to cli tool
- Optimized router policy

## [0.1.2] - 2026-03-18

### Added
- DAG-based execution and unified concurrency (RFC-0009)
- Failure recovery design (RFC-0010)
- Comprehensive error handling and resilience improvements

### Changed
- Enhanced wizsearch diagnostics with debug mode integration

### Fixed
- Message size limits
- Checkpointer initialization warnings
- Browser subagent hanging issue
- Three critical bugs: TUI commands, thread list, and attach

## [0.1.1] - 2026-03-17

### Added
- Initial public release
- Core agent factory, runner, resolver, and events
- CLI with Typer and Textual TUI
- Multi-transport daemon (Unix socket, WebSocket, HTTP)
- 8 runtime-agnostic protocol definitions
- Protocol implementations: context, memory, policy, durability, persistence
- Browser and Claude subagents via deepagents
- Tool groups: execution, websearch, research, etc.
- MCP server loading and management
- Plugin SDK with decorators
- Autonomous iteration loop
- Built-in skills infrastructure
- Thread conversation logging and history recovery
- PostgreSQL persistence backend
- Health checks and browser connection handling
- Subagent progress visibility and output capture
- CI/CD workflows

### Fixed
- Pin `claude-agent-sdk` to exclude macOS-only version 0.1.49

[0.3.4]: https://github.com/mirasurf/Soothe/releases/tag/0.3.4
[0.3.3]: https://github.com/mirasurf/Soothe/releases/tag/0.3.3
[0.3.2]: https://github.com/mirasurf/Soothe/releases/tag/0.3.2
[0.3.1]: https://github.com/mirasurf/Soothe/releases/tag/0.3.1
[0.3.0]: https://github.com/mirasurf/Soothe/releases/tag/0.3.0
[0.2.12]: https://github.com/mirasurf/Soothe/releases/tag/0.2.12
[0.2.11]: https://github.com/mirasurf/Soothe/releases/tag/0.2.11
[0.2.10]: https://github.com/mirasurf/Soothe/releases/tag/0.2.10
[0.2.9]: https://github.com/mirasurf/Soothe/releases/tag/0.2.9
[0.2.8]: https://github.com/mirasurf/Soothe/releases/tag/0.2.8
[0.2.7]: https://github.com/mirasurf/Soothe/releases/tag/0.2.7
[0.2.6]: https://github.com/mirasurf/Soothe/releases/tag/0.2.6
[0.2.5]: https://github.com/mirasurf/Soothe/releases/tag/0.2.5
[0.2.4]: https://github.com/mirasurf/Soothe/releases/tag/0.2.4
[0.2.3]: https://github.com/mirasurf/Soothe/releases/tag/0.2.3
[0.2.2]: https://github.com/mirasurf/Soothe/releases/tag/0.2.2
[0.2.0]: https://github.com/mirasurf/Soothe/releases/tag/0.2.0
[0.1.6]: https://github.com/mirasurf/Soothe/releases/tag/0.1.6
[0.1.5]: https://github.com/mirasurf/Soothe/releases/tag/0.1.5
[0.1.4]: https://github.com/mirasurf/Soothe/releases/tag/0.1.4
[0.1.3]: https://github.com/mirasurf/Soothe/releases/tag/0.1.3
[0.1.2]: https://github.com/mirasurf/Soothe/releases/tag/0.1.2
[0.1.1]: https://github.com/mirasurf/Soothe/releases/tag/0.1.1
