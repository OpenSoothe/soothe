# Changelog

All notable changes to the Soothe project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed
- Require `soothe-nano>=1.1.4` / `tarzi>=0.2.3` for web search/crawl (replaces
  `wizsearch`). Tool names and `tools.wizsearch` config keys unchanged. Default
  engines: `tavily` → `google_serper` → `duckduckgo` → `bing` → `brave`.

## [v0.9.16] - 2026-08-05

### Added
- `soothe autopilot top` interactive linux-`top` keymaps (`a` all/active goals,
  `s`/`l` steps/loops, `d` density, `+/-` delay, scroll, help) plus
  `include_terminal` on `autopilot_top` (IG-688).
- Autopilot live top dashboard, JobLoopIndex assignment loop ids, LoopRails
  wiring, greenfield-system rail, and job-scoped artifacts under `data/jobs/`
  with full-screen StepDAG nesting (IG-677 / IG-679 / IG-686 / IG-687).
- Consensus evidence grounding and DAG health guardrails for autopilot
  (IG-685 / IG-680).
- StrangeLoop: tool-aware dispatch timeout, resume from successful checkpoint,
  assess keep/reject for failed steps (IG-681 / IG-683 / IG-684).
- TUI sticky Plan composer mode (Shift+Tab) and equivalent `-h` / `--help` /
  `help` everywhere (IG-682).

### Fixed
- Autopilot `dag_snapshot` includes `parent_id` children for correct top trees.
- Autopilot top/status collapses multiline descriptions to single-line previews.
- CLI help tests tolerate ANSI styling; pytest runs from workspace root for
  editable installs.
- Build: remove duplicate force-include that broke wheel packaging.
- TUI: dock bottom chrome so the thinking row is not clipped; show intake
  complexity on the plan panel goal header.

### Changed
- Streamline autopilot CLI submit/run; remove manual dream/wake commands.
- Pin language clients to python 1.0.10 / typescript 0.5.7 / go 0.4.13;
  require `soothe-nano>=1.1.2`.

[Compare with previous version]: https://github.com/mirasoth/soothe/compare/v0.9.15...v0.9.16

## [v0.9.15] - 2026-08-03

### Changed
- StrangeLoop now routes simple fresh-loop tasks through the same trivial
  pseudo-plan path as TRIVIAL, bypassing the plan_assess/plan_generate cycle
  entirely. SIMPLE is folded into the COMMIT_PLAN branch with a pre-built
  1-step plan; the standalone SIMPLE → GENERATE_PLAN branch is removed.
- Continuation intake is unified at route_after_preprocess: all non-fresh
  goals now enter gather_evidence, with intake-tiered work
  (trivial/simple/complex) handled inside the mid-loop spine. The
  continuation-assess LLM is skipped for continuation+simple (it could never
  change the route), and goal_progress prose is coerced to none to avoid
  burning a schema-repair retry. Unused ENTER_LOOP targets are pruned and
  synthetic StatusAssessment factories are unified.

### Added
- TUI highlights the leading slash-command token (e.g. `/skill:foo`) in the
  live chat input box and in submitted user cards, with the command accent
  color following the mode glyph. A shared `command_token_span` helper
  replaces the combined @mention+/command regex.

[Compare with previous version]: https://github.com/mirasoth/soothe/compare/v0.9.14...v0.9.15

## [v0.9.14] - 2026-08-03

### Fixed
- TUI plan panel now hides by default (Orchestrate view) and adds a step-id
  formatter so step rows render stable identifiers instead of raw node names.
- `/clear` wipes the live plan/turn panel so the Orchestrate view does not
  stale out after clearing a turn.
- Success footer on stream-end is preserved after goal completion, instead of
  being overwritten by the closing frame (loop 2973).
- Autopilot in-memory goal context store is now bounded with an LRU and
  retention policy, preventing unbounded growth across long-running sessions.

### Added
- StrangeLoop execute-step prompts now carry vision context, so image-bearing
  turns keep their visual attachments through to the execution subgraph.
- TUI paste: clipboard images are pasted as `[image N]` attachments, turning a
  pasted screenshot into a first-class turn attachment without a file path.
- StrangeLoop unifies plan gap analysis and assess into a single `evaluate`
  subgraph, reducing redundant graph hops between plan review and assessment.
- Plan-phase adaptive cost: the planner scales token/cost budgets per phase
  based on goal complexity instead of a flat budget for every plan.

### Changed
- Bump `soothe-nano` floor to `>=1.1.1` (drops the `CodingCoreAgent` alias).
- Raise daemon `soothe` floor pin to `>=0.9.14`.
- Remove card emojis and cleanse legacy/dead code across the CLI (config,
  input, media_utils, prepare).

[Compare with previous version]: https://github.com/mirasoth/soothe/compare/v0.9.13...v0.9.14

## [v0.9.12] - 2026-07-31

### Fixed
- Plan approve / clarification resume no longer silently no-ops when CoreAgent
  or intake specialists advance the shared checkpointer past a parked
  `await_user` interrupt. StrangeLoop checkpoints use an isolated
  `thread_id={loop_id}__strange_loop`, intake-only invokes get their own
  thread, and orphaned pending clarifications recover via `Command(goto=…)`
  instead of a no-op `Command(resume=…)`.
- StrangeLoop graph compile now materializes CoreAgent and attaches a durable
  checkpointer before parking on planner review / `ask_user` / `await_user`,
  so `Command(resume=…)` can resume instead of being a no-op.
- Card broadcasts stamp `turn_id` from the active turn generation so the CLI
  no longer drops mid-turn frames; plan gap analysis hardens wire salvage,
  prefers `json_schema`, and soft-fails on timeout instead of thrashing for
  minutes.
- Planner structured output prefers `json_schema` methods and clips Pass 2
  prior/reasoning projection to reduce function-call thrash.

### Added
- CLI `--plan-panel` / `--no-plan-panel` flag to control whether the in-flow
  plan panel is expanded on TUI launch (Ctrl+t still toggles afterward).

### Changed
- TUI plan panel header label is now `Orchestrate`
- Orphan wired SubAgent cards reuse the cognition step widget (header meta /
  activity tree / footers) instead of a separate card surface
- Bump client submodule pins (python 1.0.9, typescript 0.5.6, rust 0.3.6,
  go 0.4.12)
- Raise daemon `soothe` floor pin to `>=0.9.12`

[Compare with previous version]: https://github.com/mirasoth/soothe/compare/v0.9.11...v0.9.12

## [v0.9.11] - 2026-07-31

### Fixed
- Intake Pass 2 structured output now resolves in one shot via
  `soothe-nano>=1.0.13`; intake classifiers prefer `json_schema`, clip the
  Pass 2 prior projection, and the redundant outer structured retries were
  dropped. Previously the outer retry wrapper could re-trigger a second
  structured call after Pass 1, producing flaky classification and extra
  latency.
- Goal-completion reports now focus on the current goal rather than echoing
  the whole goal stack, so terminal summaries stay scoped to what actually
  finished.

### Changed
- Raise daemon `soothe` floor pin to `>=0.9.11`
- Require `soothe-nano>=1.0.13` (Pass 2 json_schema support)

[Compare with previous version]: https://github.com/mirasoth/soothe/compare/v0.9.10...v0.9.11

## [v0.9.10] - 2026-07-30

### Fixed
- CLI reconnect retry after a mid-turn WebSocket drop no longer resends an empty
  `loop_input` for slash-skill turns; the queued `/skill:…` selector line is
  resent, and contentless turns are not retried (avoids
  "loop_id and non-empty content required")
- Require `soothe-nano>=1.0.12` / `wizsearch>=1.1.9` / `tarzi>=0.1.11` so
  blocking web search releases the Python GIL; previously tarzi held the GIL
  across headless-browser I/O and froze the daemon event loop / heartbeats
  during `deep_research` / wizsearch fan-out

### Changed
- Raise daemon `soothe` floor pin to `>=0.9.10`

[Compare with previous version]: https://github.com/mirasoth/soothe/compare/v0.9.9...v0.9.10

## [v0.9.9] - 2026-07-30

### Fixed
- SQLite loop flush coordinator no longer binds its `asyncio.Event` to the first
  worker loop in `__init__`; the durable Event is created lazily on the bound
  main loop, fixing "bound to a different event loop" hangs when a later worker
  awaited it (loop b648)
- Coordinator now marshals caller work onto the bound main loop via
  `run_coroutine_threadsafe` (`submit_enqueue` / `submit_flush_loop` /
  `submit_release_loop`), mirroring `LoopPersistenceWriter`
- Daemon pins the SQLite flush coordinator to the main loop at startup before
  any worker thread starts
- `get_shared_instance` self-gates on `default_backend=sqlite` so a
  Postgres-configured process never constructs the SQLite singleton
- Stale (closed) bound loop is handled in `_run_on_main` for test/restart safety

### Changed
- Raise daemon `soothe` floor pin to `>=0.9.9`

[Compare with previous version]: https://github.com/mirasoth/soothe/compare/v0.9.8...v0.9.9

## [v0.9.8] - 2026-07-30

### Fixed
- Internal `asyncio.CancelledError` (no user `/cancel`) no longer interrupts a
  running loop: workers retry once, emit an error terminal instead of cancel,
  and StrangeLoop skips `goal_interrupted` unless the task was cooperatively
  cancelled
- Stream-end UX: honor `soothe.stream.end` cancel reasons; avoid misleading
  "Query cancelled by user" / "Stream ended unexpectedly" for cancel terminals
- Interrupted loops set metadata `status=idle` so resume is not stuck on
  `running` until reconciliation

### Changed
- Require `soothe-client-python>=1.0.8` (CLI runtime + daemon dev):
  `aupdate_loop_state`, shared stream-end cancel-reason helpers
- Raise daemon `soothe` floor pin to `>=0.9.8`

[Compare with previous version]: https://github.com/mirasoth/soothe/compare/v0.9.7...v0.9.8

## [v0.9.7] - 2026-07-29

### Added
- Planner plan artifact with human review gate: plan-review clarification card
  with draft preview, action buttons, and arrow-key stage navigation
- Planner "Approve" action hands off to StrangeLoop `plan_generate`; clarification
  resume reuses the Context Engine goal
- Server-owned display card ledger via `card_wire` — live source-of-truth for
  planner intake-only cards
- Loop resume gate with execution-state fetch RPC (daemon + CLI)
- Canonical loop token field and MS Teams ref migration marker
- Mermaid diagram rendering in goal-completion TUI reports
- Session tips rotate in the CLI status footer on interval
- Daemon started time exposed in status output

### Changed
- Require `soothe-nano>=1.0.11` (browser_use eventbus fix, operation_guard
  protected-kill hooks, RunBackgroundTool args_schema, planner recon tools,
  solution-report output)
- Raise daemon `soothe` floor pin to `>=0.9.7`
- Planner reframed as solution report (goal-completion proposal) instead of an
  investigation roadmap; expanded plan-review body
- StrangeLoop prefers single CoreAgent execute over trivial plan steps; disables
  general-purpose subagent by default
- Mid-loop plan phase uses fast gap/assess roles for speed
- LLM owns goal-completion report outline (synthesis)
- Relocated prompts package into the sloop namespace

### Fixed
- Orphan-stop reliability and intake-only plan wiring (daemon, sloop, TUI)
- Diagnose/doctor: polish daemon and providers diagnose UX

### Removed
- Legacy `loop_cards_fetch` compat shim and stale migration notes (daemon, CLI)

[Compare with previous version]: https://github.com/mirasoth/soothe/compare/v0.9.6...v0.9.7

## [v0.9.6] - 2026-07-25

### Added
- Vital progressive `soothed doctor` (tool deps, gated persistence/providers/observability, `--deep` / `--live-llm`)
- Package diagnose APIs: `soothe_nano.diagnose` / `soothe.diagnose`, called by daemon `HealthChecker`
- `soothed setup` for nano/soothe/daemon config scaffolding
- TUI: bare `exit`/`quit` words and `/exit` alias

### Changed
- Require `soothe-nano>=1.0.8` (diagnose API); bump nano submodule pin
- Unify SQLite under process-scoped runtime; tighten host→nano re-export facades
- Rename CodingCoreAgent → SootheNanoAgent; scope monorepo tooling to owned packages

### Fixed
- Honor LangGraph durability kwargs only when a checkpointer is present
- IdentityService sync close / SQLite registry teardown in tests
- Daemon setup templates packaging and ANSI stripping in setup help tests
- Diagnose `CheckStatus` aggregation no longer prefers lexicographic `"ok"` over `"error"`

[Compare with previous version]: https://github.com/mirasoth/soothe/compare/v0.9.5...v0.9.6

## [v0.9.5] - 2026-07-23

### Changed
- Simplify `soothe-daemon` first-party deps: declare `soothe` + `soothe-sdk` only (drop `soothe-nano` re-pin and runtime `soothe-client-python`); channels stay hard deps; admin RPCs use `soothe_daemon.admin_rpc` (sdk wire)
- Raise daemon `dev` pin for WS tests to `soothe-client-python>=1.0.2,<2.0.0` (was `<1.0.0`)
- Package-boundary docs and gates: daemon must not import `soothe_client` in runtime source; pin alignment rejects nano/client re-pins on daemon

### Added
- `soothe_daemon.admin_rpc` for one-shot `soothed` admin RPCs over protocol-1 wire without the Python client package

[Compare with previous version]: https://github.com/mirasoth/soothe/compare/v0.9.4...v0.9.5

## [v0.9.4] - 2026-07-23

### Changed
- Package-boundary excision: remove host/daemon-only concepts that leaked into `soothe-nano` — dead-duplicate `ThreadLogger`/`ConfigWatcher`/`PersistenceDirectoryManager`/workspace-policy functions (host already owns canonical copies), dead `soothe_checkpoints` DDL (host-owned), `cron_jobs`+`identity_*` DDL from nano's metadata bootstrap (host applies at runtime), `DisplayCardStore` moved to the daemon, dead `set_step_context`/`log_exception_simplified` helpers. Standalone nano unaffected (the moved symbols were never called by nano).
- Align `soothe-daemon` first-party pins with `soothe`: `soothe-nano>=1.0.0,<2.0.0`, `soothe-sdk>=1.0.5,<2.0.0`, and `soothe>=0.9.4,<1.0.0`

### Added
- `scripts/check_nano_duplicate_symbols.py` — CI gate (run by `verify_finally.sh`) that detects dead-duplicate public symbols defined in both `soothe-nano` and `soothe`/`soothe-daemon`, catching the renamed-leak pattern the literal-name boundary ban misses.
- `scripts/check_first_party_pin_alignment.py` — CI gate that fails when `soothe` and `soothe-daemon` declare disjoint ranges for shared deps (`soothe-nano`, `soothe-sdk`)
- Release Docker workflow dry-runs `uv pip install soothe==V soothe-daemon==V` before the multi-arch image build

### Fixed
- Docker image install of `soothe` + `soothe-daemon` failed on 0.9.2 because daemon still required `soothe-nano<1.0.0` while soothe required `soothe-nano>=1.0.0`

[Compare with previous version]: https://github.com/mirasoth/soothe/compare/v0.9.2...v0.9.4

## [v0.9.2] - 2026-07-22

### Changed
- Bump `soothe-nano` pin to `>=1.0.0,<2.0.0` (nano 1.0.0 is now on PyPI) and `soothe-sdk` pin to `>=1.0.5,<2.0.0`
- Remove stale `soothe-plugins` path from the dead-code scan config (plugins now ship from their own repo)

[Compare with previous version]: https://github.com/mirasoth/soothe/compare/v0.9.0...v0.9.2

## [v0.9.0] - 2026-07-20

### Added
- Coding CoreAgent lives in standalone `soothe-nano` (batteries-included deepagents stack); host composes StrangeLoop, Autopilot, and daemon around it
- Split develop/runtime config into `nano.yml` (nano-owned) and `soothe.yml` (host-owned) with composition

### Changed
- Require `soothe-nano>=0.9.2` and `soothe-deepagents>=0.7.24` for the host Coding CoreAgent path
- Host package depends only on orchestration-owned libraries; nano owns Coding CoreAgent transitive deps
- Shared protocols, identity errors, and Langfuse helpers move to `soothe-sdk`; drop nano re-export shims
- Default `save_reports` to `false` for `deep_research` and `academic_research` (full report inline; set `true` to write under `.soothe/agents/`)
- Strip attachment bodies from research topics and goal logs (keep attachment metadata only)

### Removed
- In-tree Coding CoreAgent / nano module ownership from the host package (use `soothe-nano` instead)

[Compare with previous version]: https://github.com/mirasoth/soothe/compare/v0.8.5...v0.9.0

## [v0.8.5] - 2026-07-19

### Added
- Unified PostgreSQL backend for display card ledger, cron, and identity when `persistence.default_backend: postgresql`

### Changed
- Display card ledger uses PostgreSQL `soothe_metadata` in Postgres mode instead of always writing `$SOOTHE_HOME/data/display.db`
- Cron and identity follow `persistence.default_backend`; mixed durability overrides raise; SQLite WAL housekeeping skipped in Postgres mode
- Increase default recursion limit from 99 to 200
- Align research source timeouts with wizsearch
- Promote FAQ, CHANGELOG, and API Reference to top-level docs nav

### Fixed
- Remove duplicate classmethod on `set_current_workspace`

[Compare with previous version]: https://github.com/mirasoth/soothe/compare/v0.8.4...v0.8.5

## [v0.8.4] - 2026-07-19

### Changed
- Rename daemon intent-hint service (`direct_llm_turn` → `intent_hint_turn`) and reject legacy `intent_hint` values (`direct_llm`, `quiz`, `direct_model`)
- Remove docker-daemon Makefile targets in favor of the production compose workflow

### Added
- Document `save_reports` for research subagent config
- Language clients guide

[Compare with previous version]: https://github.com/mirasoth/soothe/compare/v0.8.3...v0.8.4

## [soothe-sdk 1.0.1] - 2026-07-19

### Removed
- Legacy loop assistant phase `direct_model` from `LOOP_ASSISTANT_OUTPUT_PHASES`

## [v0.8.3] - 2026-07-18

### Changed
- Require `soothe-sdk>=1.0.0,<2.0.0` across core packages after the SDK stable major

### Fixed
- Daemon port isolation so integration tests never bind the production WebSocket port
- Agent `kill_process` / shell kill guards that refuse daemon, self, and production-port PIDs
- Operation security bans for `pkill`/`killall`/`soothed stop|restart` patterns targeting Soothe

[Compare with previous version]: https://github.com/mirasoth/soothe/compare/v0.8.2...v0.8.3

## [soothe-sdk 1.0.0] - 2026-07-17

### Removed
- `soothe_sdk.client.*` and `soothe_sdk.langchain_wire` compatibility shims
- Root-package re-exports of plugin API, paths, protocols, and events
- Short plugin type aliases (`Manifest`, `Context`, `Health`, `Depends`)

### Changed
- First stable major: import from subpackages only (`soothe_sdk.plugin`, `.wire`, `.paths`, `.core`, …)
- Plugin package exports full type names (`PluginManifest`, `PluginContext`, `PluginHealth`, `library`)
- Dependent packages require `soothe-sdk>=1.0.0,<2.0.0`

## [v0.8.2] - 2026-07-17

### Added
- Protocol-1 `autopilot_*` request RPCs so CLI and clients work against envelope-only daemons
- Autopilot cascade goal cancel and `cancel --all` to clear leftover pending children
- Loop stream `turn_id` / monotonic `seq` boundaries; turns end with `stream.end` + idle

### Changed
- Thin CLI daemon I/O onto `soothe_client` (`DaemonSession`, shared protocol-1 helpers)
- Require `soothe-client-python>=0.10.0` and adopt `AsyncCommandClient` / `CommandClient`
- Disable explorer subagent by default (opt-in)
- Raise assess execute-AI preview default to 2048 chars with head+tail compaction

### Fixed
- Omit `turn_id` on pre-admit `running` so TUI does not lock onto the prior turn
- Keep deliverable openings when compacting oversized execute AI rows for assess
- Workspace path normalize when the daemon cwd has been deleted

[Compare with previous version]: https://github.com/mirasoth/soothe/compare/v0.8.1...v0.8.2

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
