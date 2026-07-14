# Changelog

All notable changes to the Soothe project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [v0.7.16] - 2026-07-13

### Added
- Skillify embedding resilience with automatic retry and fallback
- Cancelled goal persistence to disk for audit and resumption
- Queue interaction tips with actionable cues in UI
- Skill root prioritization for runtime discovery
- IG-589 structural gating for agent lifecycle

### Changed
- Scripts/VERSION synchronization for release consistency
- Pass 1 continuation routing fixes with response-language detection
- TUI context viewer polish for improved readability

### Fixed
- Token tracking in daemon/TUI streams
- Streaming log capture and management

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
- Release-docker validation failures on push to main by using step outputs instead of secrets in if expressions
- Goal completion display showing planning text instead of deliverables
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
- Ctrl+T plan tree view for visual goal breakdown
- Execute AI ledger cap (64K) for long-running operations

### Changed
- Improved TUI progress forwarding from daemon

## [v0.7.7] - 2026-07-07

### Added
- Plan Gap Analysis framework (IG-557 Phases A-G)
- Assess-only projection mode for dry-run evaluations
- Remaining gaps injection for targeted goal completion
- Built-in `deep_research` and `academic_research` subagents

### Changed
- Enhanced goal completion synthesis with GFM, bullets, and Mermaid diagrams
- File-change previews before apply phase

## [v0.7.6] - 2026-07-06

### Added
- Goal completion synthesis with GFM format, bullet points, and Mermaid diagrams
- File-change previews in execute workflow
- Single-word action prefixes for compact action display

### Fixed
- Execute step budget raised to 999 for complex goals

## [v0.7.5] - 2026-07-06

### Added
- Idempotent database bootstrap for reliable initialization
- High-performance persistence layer with batch writes
- Multi-goal ledger scaling for parallel operations

### Changed
- Optimized database operations for concurrent access
- Improved checkpoint reliability

## [v0.7.4] - 2026-07-06

### Added
- Execute-step budget set to 999 for extended operation windows
- Edit coalescing for batched file modifications
- Log retention configuration
- Hot-reload config support

### Fixed
- File change tracking and preview generation

## [v0.7.3] - 2026-07-05

### Added
- Skill auto-invoke improvements for seamless tool discovery
- `invoke_tools` method for explicit tool execution

### Changed
- Enhanced skill runtime discovery

## [v0.7.2] - 2026-07-03

### Added
- Skill runtime discovery (IG-543, RFC-105 Phase 1)
- Dynamic skill loading at runtime

## [v0.7.1] - 2026-07-01

### Added
- Performance isolation Phases 2–3 (IG-535)
- Memory optimization for concurrent goals

## [v0.7.0] - 2026-06-30

### Added
- Post-paint initialization gating for smoother startup
- Enhanced agent lifecycle management

## [v0.6.17] - 2026-06-28

### Added
- Same-file edit concurrency handling (RFC-902)
- EditCoalescingMiddleware for batched modifications
- IntentClassifiedEvent for enhanced event tracking
- 24-hour subagent timeout for long-running tasks

### Changed
- Improved concurrent edit safety

### Fixed
- Release-docker validation failures on push to main
