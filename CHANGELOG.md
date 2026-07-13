# Changelog

All notable changes to the Soothe project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [v0.7.15] - 2026-07-12

### Changed
- Merged `create_chat_model_with_fallback` into `create_chat_model` for automatic retry
- Subagent models now resolve from explicit `provider:model` config, taking precedence over `model_role`

## [v0.7.14] - 2026-07-12

### Fixed
- Fixed release-docker validation failures on push to main by using step outputs instead of secrets in if expressions

## [v0.7.13] - 2026-07-11

### Changed
- Replaced content heuristics with declarative tool-call/step-count limits
- Tool-heavy goals now synthesize instead of replaying truncated execute monologue
- Raised execute AI ledger cap to 64K

## [v0.7.12] - 2026-07-11

### Changed
- CI workflow update

## [v0.7.11] - 2026-07-10

### Changed
- Centralized daemon metadata merge for checkpoint writes
- Dropped redundant host_root/container_root kwargs
- Fixed mount-aware source labeling

## [v0.7.10] - 2026-07-09

### Changed
- Ran `make format` across all 1,522 files in all packages

## [v0.7.8] - 2026-07-08

### Changed
- Version bump

## [v0.7.7] - 2026-07-07

### Changed
- Version bump

## [v0.7.6] - 2026-07-06

### Changed
- Goal completion synthesis now instructs GFM tables, bullets, Mermaid blocks via format hints
- TUI file-change cards use single-word action prefixes (Writing, Editing, Created)

## [v0.7.5] - 2026-07-06

### Changed
- LLM wrapper update

## [v0.7.4] - 2026-07-06

### Changed
- Raised tool budget to 999 to prevent cleanup step cancellation

### Fixed
- Fixed edit coalescing on stream teardown to skip resolved futures instead of raising InvalidStateError

## [v0.7.3] - 2026-07-05

### Changed
- Enhanced skill_activation middleware with better context handling
- Added invoke_tools method to skill registry
- Wired auto-invoke tools into system prompt

---

## Release Notes Summary

### Key Themes in v0.7.x

- **Model configuration**: Role fallback consolidation and subagent model spec overrides
- **CLI/TUI polish**: Report formatting, file-change cards, format hints for goal completion
- **Execution hardening**: Tool budgets, edit coalescing, checkpoint/workspace handling
- **Ledger/gates**: Structural tool-call limits replacing content heuristics
- **CI/CD**: Docker release workflow fixes
- **Code quality**: System-wide formatting pass

[Unreleased]: https://github.com/mirasurf/soothe/compare/v0.7.15...HEAD
[v0.7.15]: https://github.com/mirasurf/soothe/releases/tag/v0.7.15
[v0.7.14]: https://github.com/mirasurf/soothe/releases/tag/v0.7.14
[v0.7.13]: https://github.com/mirasurf/soothe/releases/tag/v0.7.13
[v0.7.12]: https://github.com/mirasurf/soothe/releases/tag/v0.7.12
[v0.7.11]: https://github.com/mirasurf/soothe/releases/tag/v0.7.11
[v0.7.10]: https://github.com/mirasurf/soothe/releases/tag/v0.7.10
[v0.7.9]: https://github.com/mirasurf/soothe/releases/tag/v0.7.9
[v0.7.8]: https://github.com/mirasurf/soothe/releases/tag/v0.7.8
[v0.7.7]: https://github.com/mirasurf/soothe/releases/tag/v0.7.7
[v0.7.6]: https://github.com/mirasurf/soothe/releases/tag/v0.7.6
[v0.7.5]: https://github.com/mirasurf/soothe/releases/tag/v0.7.5
[v0.7.4]: https://github.com/mirasurf/soothe/releases/tag/v0.7.4
[v0.7.3]: https://github.com/mirasurf/soothe/releases/tag/v0.7.3
