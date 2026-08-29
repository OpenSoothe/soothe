# Changelog

All notable changes to the Soothe project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [v1.0.0] - 2026-08-29

### Changed
- **Major version release (1.0.0)** — Soothe reaches its first stable release. All monorepo-owned packages (`soothe`, `soothe-autopilot`, `soothe-daemon`, `soothe-cli`) bump to 1.0.0 and mark `Development Status :: 5 - Production/Stable`. The `soothe-sdk` package remains on its independent 1.x version line (currently 1.0.12).
- Raise upper bounds on first-party dependencies from `<1.0.0` to `<2.0.0` (`soothe`, `soothe-autopilot`) so downstream packages resolve the new 1.0.0 release.

### Added
- StrangeLoop now carries pre-interrupt elapsed time into the resume step duration, so paused-then-resumed steps report accurate wall-clock timing.

### Fixed
- Harden fatal-error routing and the grounding critic in the TUI: the app module is split for clarity, and legacy docstrings/dead comments are cleansed from routing, grounding, and decomposition paths.

[Compare with previous version]: https://github.com/mirasoth/soothe/compare/v0.11.0...v1.0.0

## [v0.11.0] - 2026-08-29

### Changed
- Minor version bump to 0.11.0 across all monorepo-owned packages (`soothe`, `soothe-autopilot`, `soothe-daemon`, `soothe-cli`). The `soothe-sdk` package remains on its independent 1.x version line.

### Fixed
- Fix import ordering in `soothe-cli` TUI message helpers (`_helpers.py`).

[Compare with previous version]: https://github.com/mirasoth/soothe/compare/v0.10.40...v0.11.0

## [v0.10.40] - 2026-08-29

### Fixed
- `ask_user` tool now coerces invalid LLM output instead of crashing the loop: over-long headers are truncated, wrong option counts are padded/trimmed, empty/duplicate labels are de-duplicated, and whitespace-only questions are replaced with a placeholder. Markdown-list-prefixed JSON option strings (e.g. `- [{"label": ...}]`) are now parsed instead of rejected by Pydantic.
- Decomposition proposals no longer reject out-of-range or self-referential `depends_on_local` deps — they are dropped, so a single bad subtask no longer kills the whole proposal. Empty subtask descriptions are coerced to a placeholder.
- Eval coverage-audit prompt now constrains the thread to assessment only: run at most one decisive verification command, never implement/edit/explore. Stops Eval rounds from burning a full loop on exploratory tool calls.
- TUI clarification picker shows an inline "Enter to submit" hint on the selected option row so the user knows their choice is captured.

[Compare with previous version]: https://github.com/mirasoth/soothe/compare/v0.10.39...v0.10.40

## [v0.10.39] - 2026-08-28

### Changed
- Default `agent.clarification.default_mode` to `manual`: interactive runs now route clarifications through the TUI relay unless `auto` is set. Autopilot (headless) still forces auto.
- Bump `soothe-nano` dependency floor to v1.2.14 across `soothe` and `soothe-autopilot` packages.

### Removed
- Remove dead config keys with no runtime reader: `agent.goal_completion_mode`/`agent.final_response` (agent-level duplicates of the live `agent.loop.*` keys), autopilot `checkpoint_interval`/`max_total_goals`/`max_goal_depth`/`dreaming_interval`, loop `goal_completion_mode`/`context_compaction_target_pct`/`step_context_check_enabled`/`strange_loop_output_contract_enabled`/`prior_conversation_limit`/`goal_context`/`decompose.max_recompose`/`decompose.reconcile_model_role`, clarification `auto_policy`/`max_defer_age_hours`/`tool_approval.veritas_fallback.inline_project_instructions`, and daemon `memory_profiling.snapshot_interval_seconds`/`log_growth_interval_seconds`.
- Fix SLA template keys to match `SlaConfig` field names: `warning_seconds`/`critical_seconds`/`breach_seconds` (were `*_after_seconds`, silently ignored); drop never-existing `track_root_goals_only`. Re-remove the no-op `loop_orchestrator_evidence_validate` line that a template sync had reintroduced.

### Fixed
- Veritas no longer auto-answers questions that solicit the user's own preference or input when no preference is stated: a "(Recommended)" option label is treated as a UI default, not evidence of user intent, so such questions defer to the human instead of fabricating the answer.
- Stop leaking tool output and raw tool-error text (e.g. "Error invoking tool ...") into the user-visible assistant message: the end-of-turn assistant row is now composed from AI-message text only.

[Compare with previous version]: https://github.com/mirasoth/soothe/compare/v0.10.38...v0.10.39

## [v0.10.38] - 2026-08-26

### Changed
- Auto clarification now auto-approves safe tool actions: remove `tool_approval` from the default `force_manual_origins` so veritas's security-approver prompt evaluates each `edit_file`/`run_command` call. Risky or low-confidence calls still degrade to a manual prompt (interactive) or park (headless). Re-add `tool_approval` to `agent.clarification.force_manual_origins` to force a human on every tool action.
- Remove `thread_ids` from loop metadata (IG-764): the loop registry no longer indexes fork threads. The main thread id equals the loop id (RFC-223); fork threads (execute-step, synth, intake) use random opaque ids and are reachable via the shared checkpointer, not indexed in loop metadata. GC now scans the durability layer (`runner.list_threads()`) to find fork threads for deletion instead of reading a stale `thread_ids` list. The vestigial SQLite `thread_ids` column stays as `NOT NULL DEFAULT '[]'` for legacy compatibility but is never read back.
- Bump client submodules: go v0.4.16, rust v0.3.9, typescript v0.5.10, python v1.0.19.

### Fixed
- Fix clarification focus bug: the tool-approval/plan-review comments input can no longer steal cursor focus — it is enabled only while the Refine/Edit action is selected, so the cursor stays on the selected action button by default.
- Fix tool-approval popup focusing the chat input instead of the Approve action: `_active_plan_review_action_focus` now also matches the `tool_approval` origin so the app-level focus resolution prefers the popup's Approve button rather than falling through to `ChatInput`.
- Remove the redundant `[approve / edit / reject]` suffix from tool-approval questions — the option buttons already convey the choices.
- Fix fatal "Record iteration without plan/decision" after an `ask_user` answer resume: the synth path now populates scratch and routes through `record_iteration`. Steps that captured an ask_user interrupt score as awaiting-user instead of failed, and `ask_user` raises structured errors for whitespace-only questions.
- Fix silent dead-end after submitting a clarification answer: save the Context Engine (step DAG) both before the interactive clarification pause and on the defer park — the resume previously loaded an empty DAG and root_eval killed the goal. The resume synth also recreates a lost CE step, and `ask_user` accepts a `query` alias.
- Deliver clarification answers in-thread: both `ask_user` answers and tool approvals resume the interrupted agent via `Command(resume=...)` on the original step thread — the ask_user tool returns the Q&A (or the approved tool executes) and the agent continues its turn with full context. The execute stream config no longer inherits the parent graph's checkpoint namespace (which made interrupts unreachable); the config-injected checkpointer is preserved.

## [v0.10.37] - 2026-08-26

### Added
- Add `ask_user` LLM-callable tool (RFC-622 relay) that emits a structured `ask_user` LangGraph interrupt; wire into `AgentBuilder`. Add `WorkspaceSyncBackend` protocol with `Resource`, `Manifest`, `Artifact`, `CheckpointPayload` wire contracts for workspace-to-storage sync in `soothe-sdk`.
- Route `deepagents` `HumanInTheLoopMiddleware` `action_requests` interrupts through the clarification relay instead of auto-approving them. The executor detects both `ask_user` and `action_requests` shapes and routes either to `await_clarification`. Add veritas tool-approval system prompt (approve/reject/defer decisions) and `build_tool_approval_resume_payload` for `Command(resume=...)` shape. Default `force_manual_origins` now includes `tool_approval`.
- Add `AskUserPromptMiddleware` that appends an `<ASK_USER_GATE_DIRECTIVE>` to the system prompt so the LLM calls the `ask_user` tool (not plain prose) at every clarification/approval gate. Wire `interrupt_on` (approve/reject) for write/exec tools in agent mode so their `action_requests` interrupts surface to the clarification relay (`tool_approval` origin) instead of being silently auto-approved. Read-only plan/ask modes keep deny-based permissions.

### Changed
- Decouple `thread_id` from `step_id` in thread selection: random 5-hex `thread_id`, linear reuse (single parent + single child), and interrupt resume reusing `loop_state.resume_thread_id`. Remove the `EXECUTE->DISPATCH` edge (no longer needed) from routing and builder. Resume path rebuilds `AgentDecision` from CE root step and falls through to `Executor` with `Command(resume=...)` on the original thread; no `DISPATCH`, no synthesis workaround.
- Bump `soothe-nano` to v1.2.11.
- Add §14.5 to `AGENTS.md`: before tagging any owned package release, verify that `soothe-nano` and `soothe-deepagents` have their latest versions published on PyPI and that monorepo pinned floors do not exceed the live PyPI version.

### Fixed
- Add async `awrap_model_call` to `AskUserPromptMiddleware`; the sync `wrap_model_call` never fires in production (`astream`/`ainvoke` dispatches the async override), so the directive was silently dropped on every hop.
- Catch `GraphInterrupt` during stream to avoid step crash; `HumanInTheLoopMiddleware` raises it mid-stream when a tool call matches an `interrupt_on` rule. Now caught and routed into the clarification relay instead of propagating.
- Extract interrupts from the `GraphInterrupt` exception (`exc.args[0]`) instead of re-reading from graph state, which could miss the clarification capture.
- Persist `resume_thread_id` through the graph checkpoint so the `ask_user` clarification resume path survives the pause/resume round-trip; previously it was only on the in-memory `LoopState` and the loop fell through to a fatal error after the user answered. Handle CE step loss on resume by synthesizing a minimal `StepAction` and creating a root `StepNode` in the CE so `record_progress` can complete it.

[Compare with previous version]: https://github.com/mirasoth/soothe/compare/v0.10.36...v0.10.37

## [v0.10.36] - 2026-08-25

### Changed
- Default `agent.clarification.default_mode` to `manual` so unqualified clarification turns route through the TUI relay instead of veritas auto-answer; autopilot still forces `auto`.

### Fixed
- Replace the single-buffer `_pending_submit_text` with a token→payload map in `ChatInput` so edits around `[Pasted text #N]` tokens preserve the full paste; modified or removed tokens no longer expand to stale payloads.
- Raise `plan_prompt_ledger` char limits (24000/3000 → 200000/200000) so large plan artifacts are not truncated before review.

[Compare with previous version]: https://github.com/mirasoth/soothe/compare/v0.10.35...v0.10.36

## [v0.10.35] - 2026-08-24

### Fixed
- Drop the stale 50 ms `set_timer` fallback in `ClarificationInputMessage._schedule_focus`. The timer was added to win a focus race against `ChatInput`'s app-level `on_click` / `on_app_focus` handlers, but those handlers now guard against stealing focus from focusable widgets (`_click_landed_on_focusable` and the `focused is not None` check in `on_app_focus`), so the race no longer exists. Removing the timer also eliminates stale callbacks that re-focused the previously-selected menu item (block flash). Focus now relies on `call_after_refresh` alone, which Textual fires exactly once after the next render cycle when layout has settled.

[Compare with previous version]: https://github.com/mirasoth/soothe/compare/v0.10.34...v0.10.35

## [v0.10.34] - 2026-08-24

### Added
- Split plan-mode review into a three-way action: Approve (stash follow-on exec signal, finalize plan-mode goal, daemon enqueues the approved plan as a fresh exec goal), Reject (mark the plan artifact rejected, record a terminal goal completion, finalize the current goal without creating a follow-on execution goal), and Refine (store comments as plan review feedback, re-emit the review clarification so the goal stays in plan mode for the operator to iterate). Previously Reject served two roles — terminate and refine — which conflated intent. Untagged free-text answers now default to Refine instead of Reject.
- Skip Eval StepNode insertion and the eval-decision LLM call for read-only interaction modes (plan, ask) at ROOT_EVAL; routing still sends plan mode to PLAN_REVIEW and ask mode to FINALIZE.

### Fixed
- Rejecting a plan now ends the goal outright with no synthesis, no goal-completion ledger pair, and no user-facing output — `handle_plan_mode_review_answer` sets a `plan_rejected` scratch flag and `node_goal_completion` branches to a reject finalize path that runs only Context Engine goal cancellation and the terminal wire event.
- Toggle the plan-review answered card expand/collapse via an `is-expanded` class (Enter and click) instead of fighting submitted-state CSS with display assignments; give the answered view a single aligned tree branch (action, comments, expand toggle) matching the goal→step tree; make `ClarificationInputMessage` focusable so the Enter binding lands on the submitted card where Approve/Reject are disabled.

### Changed
- Align the `soothe-sdk` floor pin to `>=1.0.12` across `soothe`, `soothe-cli`, `soothe-autopilot`, and `soothe-daemon` (was inconsistent `>=1.0.8`/`>=1.0.11`). Bump the `soothe-client-python` floor to `>=1.0.18` in CLI and daemon dev deps, and the daemon `soothe-cli` dev pin to `>=0.10.33`.
- Drop legacy `planner_subagent_review` origin handling from the host routing and the CLI textual adapter.

[Compare with previous version]: https://github.com/mirasoth/soothe/compare/v0.10.33...v0.10.34

## [v0.10.33] - 2026-08-24

### Added
- Veritas clarification answering now retries transient infrastructure failures (rate limit, timeout, connection error) with exponential backoff instead of immediately deferring; `StructuredOutputError` (malformed model output) still defers immediately. Resolved Q&A is appended to `LoopState.clarification_history` so veritas can reference prior answers when answering subsequent clarifications for the same goal run (RFC-622), capped at 20 entries. New `VeritasConfig` fields: `max_retries`, `retry_backoff_seconds`, `coerced_confidence`.

### Fixed
- Replace the rigid path-existence `decompose_task` grounding guard with an async FAST-model LLM critic (`check_proposal_grounded`) that judges whether the proposal's concrete claims (paths, modules, functions, quantities, behavioral assertions) are supported by the gathered evidence — without touching the filesystem. The old guard spuriously rejected proposals whose cited paths existed under nested monorepo source roots but not at the workspace root, and was unusable in sandboxes with no real project paths. Evidence is accumulated in a new `_evidence_corpus` `ContextVar` (same mutable-list copy_context-safe pattern as `_evidence_calls`), captured by `DecomposeTaskMiddleware.awrap_tool_call` after each grounding tool runs.
- Restore the evidence-counter increment that was accidentally dropped when the grounding-guard output-capture was inlined during the LLM-critic rewrite; without it `current_evidence_calls()` stayed at `0` and the zero-evidence gate fired falsely. Add regression tests for both counter and corpus capture.
- Break read-only evidence-gathering loops (loop a85d: 666 read-only tool calls without ever calling `decompose_task` or a mutating tool, then cancelled). Four-direction fix: (1) WestWorld addendum convergence/escalation — after 10 evidence calls with no decompose proposal queued, replace the fan-out addendum with a new `WESTWORLD_ESCALATION_ADDENDUM` that forces a decision (decompose now OR execute directly); (2) executor read-only-streak circuit breaker in `_ActStreamBudget` tracking consecutive read-only tools (grep/glob/read_file/ls/file_info); (3) tool-budget default lowered from 999; (4) no-progress watchdog now also measures decompose-proposal absence, not just chunk-interval inactivity.
- Keep the TUI "Submitting" spinner alive through the plan→exec re-attach round-trip: track the pending follow-on via `_plan_approve_follow_on_pending` so the thinking row does not go blank while the daemon enqueues the follow-on exec goal after the plan-mode goal terminates; clear it on the exec goal's `STRANGE_LOOP_STARTED` or when re-attach gives up.
- Mount the plan Approve/Reject confirmation line before the adapter `None` early return so the user's decision is recorded even when the adapter was torn down (app closing); guard the `_plan_approve_follow_on_pending` read in `_cleanup_agent_task` against `AttributeError` on `None`.

### Changed
- Restructure the `soothe-cli` package and module layout: slim `tui/` to only Textual app/widget code; lift shared modules (`_version`, `_env_vars`, `_cli_context`, `project_utils`, `model_config`, `update_check`, `card_wire`) to package root; split the ~1140-line `tui/config.py` god module into a new `settings/` subpackage (`bootstrap`, `glyphs`, `shell_allow`, `skills_dirs`, `stream_config`, `provider`, `core`, `_console_impl`); create a `display/` subpackage; lift slash-command system to package-level `commands/`; move `sessions.py` to `loops/`. Dependency direction is now one-way: `cli → runtime → settings/display/commands → sdk`.
- Remove the no-op `loop_orchestrator_evidence_validate` config field (RFC-220; never read in src/tests, only its own `Field()` definition referenced it) and the matching `soothe.yml` template line.
- Remove the dead `display_policy` module from the CLI (108 lines, zero references).
- Cleanse five production-dead functions identified in the CFB-01 legacy/dead code scan — all defined in `src/` with zero production callers, referenced only from tests: `soothe/identity/credentials.is_valid_secret_key_format`, `soothe/persistence/checkpoint_split.is_persist_degraded`, `soothe-daemon/event/bus.get_event_bus_drop_counts`, and `soothe-sdk/observability/langfuse/system_hint` outer API wrappers (`publish_/clear_langfuse_system_prompt_hint`, `push_/reset_` helpers). Tests adjusted to read raw state / `_drop_counters` directly.

[Compare with previous version]: https://github.com/mirasoth/soothe/compare/v0.10.31...v0.10.33

## [v0.10.32] - 2026-08-23

### Fixed
- Make the decompose evidence-gathering counter survive LangGraph Pregel `copy_context()` snapshots. The counter was a plain `int` `ContextVar`, whose copy-on-write semantics meant increments made inside a ToolNode turn never reached the later `decompose_task` turn — the grounding gate always saw `0` and rejected every `decompose_task` as "no prior evidence" despite dozens of `ls`/`grep`/`read_file` calls. Store the counter as a single-element list (a mutable container referenced, not copied, by `copy_context()`) bound lazily by `_evidence_counter()`, so in-place mutation is visible across every snapshot sharing the reference bound at `bind_decompose_runtime`.

## [v0.10.31] - 2026-08-23

### Changed
- `SIMPLE` tasks now use an LLM decision (`decide_eval_required`) at ROOT_EVAL to dynamically determine whether a coverage Eval is warranted, replacing the deterministic skip. `COMPLEX` tasks continue using the structural `eval_required()` predicate; `MINIMAL` tasks still skip Eval without an LLM call. Fail-safe: when the fast model is unavailable or the call errors, Eval is required rather than silently skipped.

[Compare with previous version]: https://github.com/mirasoth/soothe/compare/v0.10.30...v0.10.31

## [v0.10.30] - 2026-08-22

### Added
- Introduce `interaction_mode` (`ask` / `plan`) prompt addenda and wire the mode through the executor, replacing the old planner wired-subagent delegate with a first-class plan-mode review station in the StrangeLoop graph.
- Plan-mode approve now enqueues a follow-on exec goal (the approved plan) and drops the "More comments" affordance — approve means "execute this plan."

### Fixed
- Plan-mode approve no longer runs the goal-completion synthesis summary; the approved plan proceeds directly to execution.
- Strip `None`/`N/A` plan sections so the rendered plan card never shows empty placeholder sections; the TUI submit feedback and badge are now theme-aware.
- Accept a blank `revision-comments` field on plan-mode review instead of erroring.
- Swallow planner progress events on orphan SubAgent cards in the TUI.
- Use the daemon default clarification mode on plan approval and show the submitting spinner before the mode-resolution RPC.
- Allow `awaiting_clarification` to re-park from `pending`/`active` Context Engine goals idempotently.
- Persist chitchat Context Engine goal finalization to disk instead of leaving it in-memory.

### Changed
- Remove dead plan-mode approve graph channels (`approved_plan_markdown` / `approved_plan_path`) and the routing branches that read them; the approve path is driven by `plan_approved_follow_on` + `follow_on_exec` only. The `LoopState` attributes of the same name remain live (used by grounding/dispatch for operator-approved intake plans).

[Compare with previous version]: https://github.com/mirasoth/soothe/compare/v0.10.29...v0.10.30

## [v0.10.29] - 2026-08-21

### Fixed
- Allow a fresh chitchat goal (a `running` checkpoint with `duration_ms == 0`) to finalize via the chitchat fast-path. The fast-path skips the FINALIZE station, so such goals previously stayed stuck in `running` because `chitchat_may_finalize_checkpoint` rejected all non-idle checkpoints. In-flight task goals (`duration_ms > 0`) are still blocked — their completion belongs to the normal graph FINALIZE.
- Quiet the clipboard fallthrough over SSH/tmux: `pbcopy` exits rc=1 with empty stderr when no pasteboard server is reachable, so surface a useful "no pasteboard server" detail instead of an empty message and stop logging a full traceback for expected native-clipboard failures (the OSC 52 backend is tried next).

### Changed
- Centralize the chitchat fast-path bypass decision in `enter_loop` via `should_bypass_chitchat_fast_path` (loop-control phrase + intra-loop checkpoint work); routing now trusts that decision and ENDs unconditionally. Drop the `new_goal_created` routing guard from `route_after_preprocess` and the `LoopGraphState`/`enter_loop` plumbing that fed it. Bump the `soothe-client-python` floor to `1.0.17` in CLI and daemon.
- Remove the legacy `route_by_intent` backward-compat alias; callers now use the canonical `route_after_preprocess` name. Drop unused intake-derived fields from `LoopGraphState` and `enter_loop` (`is_continuation`, `is_fresh_goal`, `is_task`, `scope`, `has_deliverable`) — routing is driven by `intake_label` + `intent_route` only. Rename `test_route_by_intent.py` → `test_route_after_preprocess.py`.
- Harden the Docker release workflow to retry the first-party PyPI resolve up to 5× (15s backoff) to ride out CDN propagation lag before the multi-arch build.

[Compare with previous version]: https://github.com/mirasoth/soothe/compare/v0.10.28...v0.10.29

## [v0.10.28] - 2026-08-21

### Changed
- Require `soothe-nano>=1.2.7`; ship the `_StructuredOutputRunnable` callback-manager flattening fix from nano 1.2.7. A leaked LangGraph `AsyncCallbackManager` in a structured-output `RunnableConfig` no longer crashes intake classification with `TypeError: 'AsyncCallbackManager' object is not iterable` (which had routed every query, including chitchat, as a complex task when Langfuse was off).
- Bump `soothe-autopilot` `soothe-nano` floor to `1.2.7` to match.

[Compare with previous version]: https://github.com/mirasoth/soothe/compare/v0.10.27...v0.10.28

## [v0.10.27] - 2026-08-21

### Fixed
- Simple tasks now skip the coverage Eval gate and finalize directly from the CoreAgent execute result via the `root_eval` short-circuit, matching the trivial-task path; only `complex` goals run the full coverage Eval gate.

### Changed
- Drop the `medium` task-complexity tier so routing collapses to three levels: `minimal`, `simple`, and `complex`. Update `IntakeLabel`/`IntentClassification` docstrings and intake prompts accordingly.
- Rename the `trivial` intake label to `minimal` across the StrangeLoop engine, Autopilot rails, daemon protocol schemas, and TUI widgets.
- Require `soothe-sdk>=1.0.10`; ship the `TaskComplexity` `medium`-tier removal from the SDK.

[Compare with previous version]: https://github.com/mirasoth/soothe/compare/v0.10.26...v0.10.27

## [v0.10.26] - 2026-08-21

### Changed
- Remove the pre-graph social gate; the in-graph `intent_classify` node is now the sole intake classification call site. It projects the full CE ledger (prior-goal completion + preamble) so the second goal's intake sees the first goal's context instead of "No prior context provided." Chitchat flows through the graph INTAKE node → `enter_loop` fast-path → END; the structural continuation bypass (`should_bypass_chitchat_fast_path`) is checkpoint-based and lives in `enter_loop`.
- Delete `IntakeLangfuseSpan` / `open_intake_langfuse_span` module; the graph node inherits the LangGraph RunnableConfig for tracing. Remove `with_intake_parent_span` / `intake_parent_span_id` / `nest_under_intake_span` / `_intake_parent_handler` from `GoalLoopTrace`. Drop the `intake_langfuse_run_display_name` fallback (never reached since `intake_invoke_config` defaults to `phase="intake_classify"`).
- Rename `should_bypass_social_gate_fast_path` to `should_bypass_chitchat_fast_path` (the social gate is gone).

[Compare with previous version]: https://github.com/mirasoth/soothe/compare/v0.10.25...v0.10.26

## [v0.10.25] - 2026-08-21

### Fixed
- Trivial intake tasks now skip the coverage Eval phase and finalize directly from the CoreAgent execute result; the goal-completion ledger uses the synthesis prompt for all complexities (drop the trivial-only submission shortcut).
- Bound prior goal-completion report projection with new constants (`GOAL_COMPLETION_REPORT_MAX_CHARS` / `_MESSAGES` / `_PER_MESSAGE_CHARS`) and head+tail truncation (40% head + 60% tail) so conclusions/recommendations survive instead of front-only clipping.

### Changed
- Rename `trivial_plan.py` to `wired_subagent_plan.py` (wired-subagent delegate path plan builder); update imports and tests.
- Change `prior_goal_tail` and `cross_goal_completion_tail` defaults from `3` to `0` (unlimited — project all prior-goal terminal units); widen the upper bound to `1000`.
- Only upgrade `CHITCHAT`/`None` intake labels to `COMPLEX` on interrupt-resume keywords; `simple` already routes to DISPATCH under the unified workflow and `trivial` skips Eval via the root_eval short-circuit.

[Compare with previous version]: https://github.com/mirasoth/soothe/compare/v0.10.24...v0.10.25

## [v0.10.24] - 2026-08-20

### Added
- Accept common typos of TUI plain-text commands (`exit`/`quit`/`clear`) as exact single-word aliases.

### Fixed
- Keep intake social replies for `continue`/`retry` when this loop has no checkpoint work to resume.
- Finalize TUI goal-completion reports reliably so the prefix stops blinking and Markdown renders after every synthesis.
- Require an intra-loop checkpoint before allowing a continuation bypass; harden the Eval thread against stale continuations.

### Changed
- Require `soothe-sdk>=1.0.9`; ship the Langfuse callback-manager flattening fix and `TraceBody` import-path compatibility shim from the SDK.
- Bump `soothe-client-python` to v1.0.17 (SDK floor alignment).
- Split the StrangeLoop engine into `execute` and `completion` sub-packages and rename the `stages` layout to `stations`.

[Compare with previous version]: https://github.com/mirasoth/soothe/compare/v0.10.23...v0.10.24

## [v0.10.23] - 2026-08-20

### Fixed
- Prevent LangGraph node-level callback handlers from leaking into nano structured-output invokes; pin empty callbacks on the goal-loop trace config and give step reports distinct Langfuse display names.
- Remove the duplicate "Wait for soothe-sdk on PyPI" step in `deploy-core` that read the wrong VERSION file and timed out, blocking core publish.

### Changed
- Require `soothe-nano>=1.2.5`; route host, Autopilot, and daemon chat-model calls through nano's unified traced invocation so Langfuse spans attach consistently for plain and structured calls.
- Unify the StrangeLoop intake classifier into a single pass; drop the two-pass coordinator so tasks enter do-or-decompose directly.
- Reuse the graph node's `RunnableConfig` for intent classification so model generation nests under the graph intake span instead of opening a pinned parent span.
- Reuse the pre-graph intake verdict as the loop intent, skipping the duplicate structured LLM call after task confirmation.
- Rename `cognition` to `plans` and derive `intake_label` from the real `task_complexity` field; switch intake reasoning to first-person prose so the TUI cognition card reads as the agent's own intent.
- Unify loop-context projection into a single `LoopContextProjector`; remove the parallel projection adapters and dead fields; add `preamble_max_turns` / `prior_goal_tail` config knobs.
- Consolidate host prompts into `soothe.prompts`; collapse nano prompt wrappers into re-exports.
- Scope the `/resume` loop picker to the current workspace by default (press W to toggle all-workspaces); drop the dead column-toggle panel.
- Render the full scoped step id (e.g. `KFA-07:`) as the plan panel row prefix so operators can correlate rows with logs.
- Propagate `task_complexity` through `IntentClassifiedEvent` and `StrangeLoopPlanDecisionEvent` so clients show execute-phase complexity, not just the routing label.

[Compare with previous version]: https://github.com/mirasoth/soothe/compare/v0.10.22...v0.10.23

## [v0.10.22] - 2026-08-19

### Fixed
- Fix a timestamp race in the Pass 1 prompt test where `build_intake_pass1_system_prompt` and `build_prompt_timestamp_block` fetched time independently; both now accept an optional `ctx` for a single shared context.

### Changed
- Make recursive step decomposition always-on for step THREADS; remove the `agent.loop.decompose.enabled` flag and the legacy plan-generation spine (planner, `PromptBuilder`, ledger projectors). Ground operator-approved intake plans directly onto the root THREAD at DISPATCH.
- Add goal GC and stale-runtime reconciliation to Autopilot: a periodic watchdog cancels orphaned non-terminal goals, releases stranded workspace reservations and worker slots, and re-queues stranded goals. Gated by `AutopilotConfig.gc_enabled`.
- Add an SLA monitor for the alert pipeline and harden the notify router and webhook sink against alert drift.
- Strip `ContextBundle` to fields prompt consumers actually read; make char-budget trim loops single-pass O(N); fix the `trace_context` property and `TraceBody` import path; drop unused cli/sdk helpers.
- Simplify wiki structure and compress root docs: fix broken goal-engine→context-engine links, consolidate the subagents page, update the module map to the real monorepo DAG, and tighten verbose prose across methodology/history/index guides.

[Compare with previous version]: https://github.com/mirasoth/soothe/compare/v0.10.21...v0.10.22

## [v0.10.21] - 2026-08-19

### Fixed
- Harden the clarification relay: park hard-defers via the Context Engine and make them resumable; fail orphaned interrupt-resume closed instead of spinning; capture empty `ask_user`/questions as failures so they no longer trigger auto-resume spin; skip `send_back` when a goal is parked awaiting clarification; add a TUI clarification-mode badge.

### Changed
- Migrate `soothe-sdk` from an independent PyPI repository into the monorepo as `packages/soothe-sdk`, keeping its own `VERSION` file (1.x line); CI now builds and publishes the SDK from this repo, and module boundary checks enforce the leaf constraint.

[Compare with previous version]: https://github.com/mirasoth/soothe/compare/v0.10.20...v0.10.21

## [v0.10.20] - 2026-08-18

### Changed
- Overhaul the StrangeLoop v2 graph topology: introduce a `LoopNode` base class with a `pre`/`project`/`prompt`/`process`/`post` lifecycle, replace the route-key bag with a typed `RouteDecision`, and fold `validate_plan`→`commit_plan` and `begin_iteration`→`check_limits` (14→12 nodes, 11→8 routers).
- Suppress Pass 1 task reasoning from the resume topic so task results fall back to the user's own request text; social chitchat handling is unchanged.
- Add bare command alias support in the TUI.

### Fixed
- Fix RFC archive path references (`docs/specs/archive/` → `docs/archive/specs/`) across the README, RFC-900, and rfc templates.

### Removed
- Drop the redundant early `_subscribed` init, unused `snapshot_for_job` method, and unused `_max_audit_entries`/`_thread` fields from the autopilot config reload path.
- Scrub internal IG identifiers from comments and docstrings across all owned packages; archive 11 completed design drafts. No behavior changes.

[Compare with previous version]: https://github.com/mirasoth/soothe/compare/v0.10.19...v0.10.20

## [v0.10.19] - 2026-08-18

### Fixed
- Force-kill stuck workers on goal cancel: add `is_idle`/`force_kill` to `LoopRunnerProtocol` and mirror the query engine's cancel ladder (`cancel()` → poll with backoff → `force_kill()`) across pool, thread, and ray runners.
- Fix the `uv_sync_with_fallback` make macro that dropped its `$(1)` argument so `make sync-no-cache` now passes `--no-cache --refresh` to `uv sync`.

### Changed
- Replace the prod daemon's named volume + three bind mounts with a single `~/.soothe-prod` bind mount as the full `SOOTHE_HOME` workdir, isolating prod state from dev and making the full workdir host-inspectable.

### Removed
- Complete the AsyncAPI drift-detection pipeline removal: drop the drift detector script, the `/drift` TUI dashboard, the weekly historical-data-refresh cron job, the CI drift step, and the `verify_finally.sh` drift phase.
- Delete the obsolete manual-branch `docker.yml` workflow (release builds use `release-docker.yml`).

[Compare with previous version]: https://github.com/mirasoth/soothe/compare/v0.10.18...v0.10.19

## [v0.10.18] - 2026-08-17

### Fixed
- Add the first versioned migration (`001_add_checkpoint_index_column.sql`) so deployed `agentloop_checkpoints` tables bootstrapped before the `checkpoint_index` column get it via idempotent `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` on the next pool open.

### Changed
- Bump the `soothe-nano` floor from 1.2.2 to 1.2.3 in `soothe` and `soothe-autopilot`.
- Ship `fd-find` and `git` alongside `ripgrep` in the runtime Docker image so `soothed doctor` reports all expected host tools.

### Removed
- Revert the quarterly RFC audit cycle and inter-rater reliability reviewer pool along with their implementation guide, config, and Q3 2026 audit report; strip cross-references so the RFC corpus stays internally consistent at 90 RFCs.

[Compare with previous version]: https://github.com/mirasoth/soothe/compare/v0.10.17...v0.10.18

## [v0.10.17] - 2026-08-17

### Fixed
- Add a `deploy-autopilot` job to the release workflow so `soothe-autopilot` publishes to PyPI alongside the other packages; `deploy-daemon` now waits for both core and autopilot to be available before syncing.

[Compare with previous version]: https://github.com/mirasoth/soothe/compare/v0.10.16...v0.10.17

## [v0.10.16] - 2026-08-17

### Fixed
- Stop the host `cron` check from returning ERROR when `soothe-daemon` is absent in an isolated core venv; surface the import failure as a non-blocking OK note while the config-presence check still runs.

[Compare with previous version]: https://github.com/mirasoth/soothe/compare/v0.10.15...v0.10.16

## [v0.10.15] - 2026-08-17

### Fixed
- Stop the host `autopilot` check from returning ERROR when `soothe-autopilot` is absent and autopilot is disabled; surface the import failure as ERROR only when autopilot is actually enabled.

[Compare with previous version]: https://github.com/mirasoth/soothe/compare/v0.10.14...v0.10.15

## [v0.10.14] - 2026-08-17

### Added
- Extract the autopilot orchestration layer out of the `soothe` host into a standalone `soothe-autopilot` package (AutopilotService, monitor, rails, verify, intake, dispatch, notify), enforcing the one-way dependency DAG.
- Seed project goal-DAG pairs into the Context Engine ledger as a real multi-turn transcript before the current goal's user turn so the executing LLM begins with a genuine conversation leading up to the ask.
- Add a master switch `agent.autopilot.verify_periodic_enabled` (default false) gating the periodic DAG health tick; raise `verify_interval` 30s → 120s.

### Changed
- Migrate to `soothe-nano` 1.2.x unified `soothe_nano.llm` module (litellm-backed, fixing the tool-calling regression where bound `tools=` was dropped on the way to OpenAI-compatible endpoints like DashScope); bump the floor to `>=1.2.2`.
- Require both a live PID file and the configured WS port accepting connections for daemon start readiness, so startup crashes surface loudly instead of masking as success.
- Stop emitting Pass 1 intake reasoning as a TUI cognition card; only the Pass 2 scope reasoning card is surfaced. Remove the `pass1_reasoning` field and the structural bypass-prefix heuristic.
- Reconcile per-RFC status headers and index/history tables (82 active / 9 archived / 7 reclassified / 2 process).

### Fixed
- Bump Docker actions to Node 24 (setup-qemu v3→v4, login v3→v4, metadata v5→v6, build-push v6→v7) and add `actions:write` so buildx cache writes succeed.

### Removed
- Drop the dead dreaming-distillation stub and its symbols (autopilot dreaming loops, `DreamingModeConfig`, episodic memory, event triggers).
- Delete the obsolete `.platonic.yml` (superseded by `AGENTS.md` and the `docs/` RFC/IG workflow).

[Compare with previous version]: https://github.com/mirasoth/soothe/compare/v0.10.13...v0.10.14

## [v0.10.13] - 2026-08-15

### Fixed
- Close the loop-0041 race where `SharedPostgreSQLPool.reset_pool` nulled `_pool` before reopening and deadlocked re-entering the non-reentrant lock; extract the open+schema body into `_open_locked()` and add `await_pool()` so callers block through the reopen window instead of observing `None`.

### Changed
- Make notify severity drift-aware, add TTL-based dedup, and make email rate-limiting configurable; add `suspend_escalation_multiplier`, `dedup_ttl_seconds`, and `rate_limit_seconds` fields synced across config templates.
- Add a `BuiltinJobSpec` registry with idempotent `seed_builtin_jobs()` on daemon startup; add `enable_builtin_jobs` flag (default true).
- Synthesize a reusable RFC methodology guide from the existing RFC/IG corpus into `docs/rfc-methodology-guide.md` and wire it into rfc-standard, rfc-template, rfc-index, and rfc-history.
- Remove the obsolete drift-detection pipeline (detector script, drift GitHub workflow, webhook test, and `check_asyncapi_drift()` call sites in `verify_finally.sh`).

[Compare with previous version]: https://github.com/mirasoth/soothe/compare/v0.10.12...v0.10.13

## [v0.10.9] - 2026-08-13

### Fixed
- Retry transient SQLite checkpointer errors (WAL contention, file-lock races) with exponential backoff, mirroring the PostgreSQL path; ensure the parent directory exists before connecting and close the aiosqlite connection on setup failure to prevent leaked threads and `ResourceWarning`.
- Drop the unused `render_markdown=False` argument from the instant-loop assistant message.

### Changed
- Switch default `final_response` from `auto` to `always_synthesize` for both the agent and StrangeLoop so a final CoreAgent report is always produced on goal completion; sync across template, develop config, packaged daemon template, and config models.
- Fold the goal line into the TUI plan panel overlay title row (`Orchestrating [8d26] · complex · 37s`) leaving the panel body for step rows only.
- Upgrade `soothe-nano` 1.1.15 → 1.1.16: adds a vLLM provider (streaming disabled; vLLM-Metal ignores `stream=True`) and replaces the muse-glimmer router profile with a vllm profile.

[Compare with previous version]: https://github.com/mirasoth/soothe/compare/v0.10.8...v0.10.9

## [v0.10.8] - 2026-08-12

### Fixed
- Stop goal cancel from orphaning in-flight `run_command` shells; `drain_goal_runtime` now reaps both foreground and background process groups on `user_cancelled` and daemon cancel (SIGTERM → grace → SIGKILL).

### Changed
- Upgrade `soothe-nano` 1.1.13 → 1.1.14; drop the host re-export of `PolicyCheckedEvent` (nano no longer emits the policy-checked wire type; denials still use `PolicyDeniedEvent`). TUI plan panel is off by default (`--plan-panel` to auto-show).
- Generate the GitHub Pages CHANGELOG from the repository root `CHANGELOG.md` via `scripts/sync_wiki_changelog.sh` (no more hand-maintained wiki copy).

[Compare with previous version]: https://github.com/mirasoth/soothe/compare/v0.10.7...v0.10.8

## [v0.10.7] - 2026-08-12

### Fixed
- Stop TUI dynamic themes from crashing the synthesis card with `TypeError`; supply the missing `card_running`/`card_running_muted` colors and add a static AST guard over every `ThemeColors()` constructor site.
- Feed the Autopilot job-maturity assessor full contract context instead of truncated fragments; remove tight char caps on `verification_rules`, `GOAL.md`, DAG summary, workspace inventory, and QA response inputs.
- Render inline `code` spans in a dedicated warm amber so literals read as literals in assistant prose.
- Align stream card prefixes via a single 1-column inset so every card type's prefix dot lines up.
- Start clipboard copy with the native OS backend and drop the opportunistic `pyperclip` import that duplicated `pbcopy`/`xclip`/`xsel`.

### Changed
- Centralize scattered `*_MAX_CHARS` sentinels into a single Character-Cap Registry in `soothe/config/constants.py` so truncation budgets are auditable in one place.
- Remove the unused `hooks.py` stub and its `dispatch_hook` call sites.

[Compare with previous version]: https://github.com/mirasoth/soothe/compare/v0.10.6...v0.10.7

## [v0.10.6] - 2026-08-12

### Changed
- Upgrade `soothe-nano` 1.1.11 → 1.1.12; nano excised several host-owned helpers back to the host packages (persistence metrics, unified persistence validation, model catalog payload, daemon error-format). Add `hide_thinking_tokens` config field for the new thinking-token stripping feature.

[Compare with previous version]: https://github.com/mirasoth/soothe/compare/v0.10.5...v0.10.6

## [v0.10.5] - 2026-08-11

### Fixed
- Set `cancel_event` on busy in-flight workers before the join wait on runner ThreadPool shutdown so daemon restart/stop unwinds dying `astream()` runs through the cooperative-cancel pipeline instead of leaking a spurious "unexpected cancellation" RuntimeError.
- Resolve workspace-local skills (`.agents/skills`) on freshly created loops before the first `loop_input` by falling back to the `current_workspace` stored at `loop_new` time.
- Stop `soothe ap top` from ticking an elapsed clock for queued goals; anchor elapsed on `started_at` so pending work shows no running timer.

### Added
- Add a resumable interrupted-goal cursor for cancel-then-retry: a mid-Execute cancel now marks the goal `interrupted` (distinct from terminal `cancelled`) and persists the iteration cursor so retry resumes in place with one grace iteration at the budget boundary.
- Add an autoresearch loop rail with native exec and 15 prompt fragments: an iterative autonomous research loop that decomposes questions, gathers web evidence, reflects on sufficiency, and synthesizes an adaptive report via find→optimize→verify.
- Add CE goal DAG analysis and digraph to the `inspect-autopilot-job` skill.

### Changed
- Always resume `continue` via the launcher gate (single resume path) instead of the legacy direct-continue path.
- Condense plan prompt fragments to telegraphic wording; remove the unused structured plan parser, fatal-error transition, and step-alignment helpers.
- Drop the `iter<=N` suffix from the TUI goal-tree header; slim packaged daemon/soothe config template defaults.

[Compare with previous version]: https://github.com/mirasoth/soothe/compare/v0.10.4...v0.10.5

## [v0.10.4] - 2026-08-10

### Fixed
- Stop WebSocket 1009 (message too big) crashes on large autopilot command-RPC replies; client and daemon now set `max_size=10 MiB` to match the daemon's `transport.websocket.max_frame_size` default.
- Stop the TUI from hanging on a stale "live" loop probe after a turn completes; require the daemon's authoritative `active_runner` signal and raise after 45s with no real content on the attach-only turn read.

### Added
- Add Autopilot streaming slice DAG spawn and host worktree lifecycle.
- Add Veritas auto-clarify for rail `pause_for_user`; encode Superpowers discipline into rail maker briefs.
- Add the cognition intake module and CLI guide.
- Add WavePlan continue short-circuit and dispatch intake scope.
- Add LLM-based rail auto-pick.
- Add Autopilot report-commit judgment with bounded DAG ops.
- Add TUI auto-show/hide plan panel during goal execution, one-stage vs two-stage Enter for slash autocomplete, and a clarification mode badge in the status bar.

### Changed
- Convert `soothe-sdk` from workspace submodule to PyPI dependency (`soothe-sdk>=1.0.8,<2.0.0`); release workflow waits for the pinned floor on PyPI.
- Remove the `packages/soothe-nano` git submodule; consume Coding CoreAgent from PyPI (`soothe-nano>=1.1.6`) only.
- Upgrade `soothe-nano` 1.1.8 → 1.1.10.
- Raise `soothe-client-python` floor to `>=1.0.15` in soothe-cli and soothe-daemon (WebSocket max_frame_size fix).
- Raise packaged `llm_rate_limit` globals for Autopilot + CLI coexistence: `rpm_limit=180`, `concurrent_limit=4`, `global_concurrent_limit=18`.
- Default LLM rate-limit / loop concurrency to develop-safe caps: `autopilot.max_parallel_goals=3`, `max_parallel_steps/subagents=3`, `global_max_llm_calls=8` (requires `soothe-nano>=1.1.7`).
- Rename autopilot `cognition` → `intake` module; collapse redundant bugfix/migration builtins and raise auto-pick timeout.
- Rename `wave_below_max` → `below_slice_budget`; decouple budget from `job_complete`.

### Removed
- Drop `agent.loop.concurrency.max_parallel_goals` (dead after single-goal StrangeLoop workers); use `agent.autopilot.max_parallel_goals` for Autopilot goal fan-out. Stale YAML keys are ignored on load.
- Drop `ConcurrencyPolicy.max_parallel_goals` (soothe-sdk 1.0.8); persisted plans with the legacy key still load via `extra="ignore"`.
- Drop Autopilot evidence turns; trust the StrangeLoop completion signal instead.

[Compare with previous version]: https://github.com/mirasoth/soothe/compare/v0.10.2...v0.10.4

## [v0.10.2] - 2026-08-07

### Changed
- Release fix versions for all clients: Python 1.0.12, TypeScript 0.5.8, Go 0.4.14, Rust 0.3.7.
- Raise `soothe-client-python` floor to `>=1.0.12` in soothe-cli and soothe-daemon.

## [v0.10.1] - 2026-08-07

### Added
- Add the Rail Exec system with YAML verb bodies and migration waves.
- Add structure-driven builtin rails with a review closeout workflow.
- Add Autopilot top `steps_mode` with active/pending filter for the StepDAG view.
- Add a CLI `ap` alias for the `autopilot` command and rail/goal display in commands.
- Add multi-channel job lifecycle notify push (email, WebSocket, webhook).
- Enrich Autopilot job notify emails with compact DAG progress.
- Persist job descriptions as `data/jobs/{id}/GOAL.md`.
- Persist WavePlan via Context Engine findings (no file artifact).

### Fixed
- Freeze elapsed time for terminal jobs/goals/loops to avoid live drift.
- Make Autopilot consensus trust use StrangeLoop response signals.
- Replace consensus suspend with fail for automatic recovery.
- Rename notify target `address` to `to_address` for clarity.

### Changed
- Raise `soothe-client-python` floor to `>=1.0.11` (120s `autopilot_submit` timeout).
- Remove the unused `suggest_goal`/`ProposalQueue` mechanism; DAG growth stays via LoopRail, monitor, intake, and reflection `GoalDirective`s.
- Make Autopilot consensus judge goal text vs StrangeLoop response only; drop host workspace evidence grounding and pytest hard-accept.
- Refactor autopilot/rails to one-level subpackages with workflow tracing.
- Make sensitive config dual-mode: plain YAML or `${ENV_VAR}` placeholders.
- Replace `files_touched` with domain-agnostic `GoalEffect` for job artifacts.
- Move `plan_contribution` to the dispatch module for cleaner separation.

[Compare with previous version]: https://github.com/mirasoth/soothe/compare/v0.10.0...v0.10.1

## [v0.10.0] - 2026-08-06

### Added
- Add an Autopilot live top dashboard with htop-style Jobs/Goals/Loops stats, interactive keymaps (`a` all/active, `s`/`l` steps/loops, `d` density, `+/-` delay, vim-style scroll), and a pair-column layout.
- Add greenfield rails with LLM-determined fanout width, consensus pass with full evidence, thrash rail tag loss detection, and subgoal consensus exhaustion recovery.
- Add an Autopilot job maturity assessment system, enable the scheduling loop by default, and add deadlocked failed-goal recovery.
- Track job token usage in the Context Engine and display it in the CLI autopilot.
- Add a `--file` flag for `autopilot submit` to load GOAL.md from a file.
- Split diagnose tools into `diagnose-loop` and `inspect-autopilot-job` workflows.
- Migrate the web search/crawl backend from wizsearch to tarzi via `soothe-nano>=1.1.4`.

### Fixed
- Fix the Autopilot greenfield rail feedback cycle, guards, and wave idle deadlock resolution.
- Preserve the StepDAG under live goals in Autopilot top when `steps=on`.
- Mirror worker steps onto the Context Engine for top display.
- Color Autopilot top progress meters as success green.
- Validate CLI autopilot help flags on ANSI-stripped output.
- Prevent premature `job_complete` on greenfield without an acceptance latch.

### Changed
- Align Autopilot config with shared StrangeLoop budgets and always-on dynamic goals.
- Share `max_iterations` between StrangeLoop and Autopilot instead of a duplicate budget.
- Shorten the Autopilot top header title to "Autopilot".
- Remove the soothe-desktop submodule and archive desktop docs.
- Increase default Autopilot concurrency limits for better throughput.
- Require `soothe-nano>=1.1.4` / `tarzi>=0.2.3` for web search/crawl. Default engines: `tavily` → `google_serper` → `duckduckgo` → `bing` → `brave`.

[Compare with previous version]: https://github.com/mirasoth/soothe/compare/v0.9.16...v0.10.0

## [v0.9.16] - 2026-08-05

### Added
- Add `soothe autopilot top` interactive linux-`top` keymaps (`a` all/active goals, `s`/`l` steps/loops, `d` density, `+/-` delay, scroll, help) plus `include_terminal` on `autopilot_top`.
- Add the Autopilot live top dashboard, JobLoopIndex loop-id assignment, LoopRails wiring, greenfield-system rail, and job-scoped artifacts under `data/jobs/` with full-screen StepDAG nesting.
- Add consensus evidence grounding and DAG health guardrails for Autopilot.
- Add tool-aware dispatch timeout, resume from successful checkpoint, and assess keep/reject for failed StrangeLoop steps.
- Add TUI sticky Plan composer mode (Shift+Tab) and equivalent `-h` / `--help` / `help` everywhere.

### Fixed
- Include `parent_id` children in Autopilot `dag_snapshot` for correct top trees.
- Collapse multiline descriptions to single-line previews in Autopilot top/status.
- Make CLI help tests tolerate ANSI styling; run pytest from workspace root for editable installs.
- Remove the duplicate force-include that broke wheel packaging.
- Dock the TUI bottom chrome so the thinking row is not clipped; show intake complexity on the plan panel goal header.

### Changed
- Streamline autopilot CLI submit/run; remove manual dream/wake commands.
- Pin language clients to python 1.0.10 / typescript 0.5.7 / go 0.4.13; require `soothe-nano>=1.1.2`.

[Compare with previous version]: https://github.com/mirasoth/soothe/compare/v0.9.15...v0.9.16

## [v0.9.15] - 2026-08-03

### Changed
- Route simple fresh-loop StrangeLoop tasks through the same trivial pseudo-plan path as TRIVIAL, bypassing the plan_assess/plan_generate cycle entirely; fold SIMPLE into the COMMIT_PLAN branch with a pre-built 1-step plan and remove the standalone SIMPLE → GENERATE_PLAN branch.
- Unify continuation intake at route_after_preprocess so all non-fresh goals enter gather_evidence with intake-tiered work handled inside the mid-loop spine; skip the continuation-assess LLM for continuation+simple and coerce goal_progress prose to none to avoid burning a schema-repair retry.

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
