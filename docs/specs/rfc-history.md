# RFC History

This document tracks the change history of all RFCs in this project.

## Change Log

| Date | RFC | Status | Description |
|------|-----|--------|-------------|
| 2026-06-01 | RFC-227 | Draft | Plan-Assess Prior-Progress Digest — executor-owned `PriorProgressDigest` (new typed value + `ToolCallHead`) refreshed at the end of every wave and stashed on `LoopState.prior_progress`; rendered as a ≤600-char `<PRIOR_PROGRESS>` XML block by `build_plan_context_envelope` for both `plan_assess` and `plan_generate`; new `assessment_reasoning` contract in `plan_assess_instructions.xml` (anchor on `<PRIOR_PROGRESS>`, do not restate the user query); deterministic `derived_progress_hint` shown verbatim (no code-side override); telemetry log on digest/LLM `goal_progress` disagreement; no graph topology change; root-caused from Langfuse trace `279a91c70f73f5b71fb31a5b61370f45` where plan-assess `assessment_reasoning` repeatedly restated the goal across iterations 1-3 despite 13 prior `run_command` results in the ledger |
| 2026-05-29 | RFC-105 | Draft | Progressive Skill Loading — three-stage progressive disclosure replacing deepagents' always-emit-all skill listing: budgeted turn-0 `<AVAILABLE_SKILLS>` (delta-only, ≤1% of context window), path-driven conditional activation via new `SkillActivationMiddleware` on file-op tool calls (`pathspec` gitignore matching), lazy `<SKILL_CONTEXT>` body injection on `/skill:<name>` invocation; new `ProgressiveSkillRegistry`, `format_skills_within_budget`, `ProgressiveSkillsConfig`; new events `soothe.skill.activated` / `soothe.skill.body.loaded`; `LoopState` snapshot of agent-state activation dict at iteration boundaries; deepagents' `SkillsMiddleware` suppressed via `skills=None` |
| 2026-05-29 | RFC-226 | Draft | Continuation-Aware plan_assess and Post-Execute Fast Exit — `plan_assess` on iter=0 of continuation queries becomes a single LLM-driven discriminator (new `ContinuationAssessment` schema + `LOOP_CONTINUATION_ASSESS_PROMPT`) that routes to bootstrap or `plan_generate`; new `PlanResult.terminal_after_execute: bool`; one new conditional edge `record_iteration → goal_completion`; removes structural `continue_loop_plan_bootstrap_allowed()` heuristic; multi-step continuations correctly escalate to `plan_generate` |
| 2026-05-29 | RFC-225 | Draft | Loop Continuity and Goal Record Enrichment — `IntentClassification.intent_type` collapses to `quiz \| agentic`; `continue_loop_mode` (renamed from `continue_thread_mode`) derived structurally in `AgentLoop` from checkpoint (replaces broken `GoalEngine` check in solo runner); status `ready_for_next_goal` → `idle`; `GoalExecutionRecord` enriched with `current_plan`, `step_results`, `evidence_ledger`, `completed_step_ids`, `plan_revision_count`; schema bump `3.1` → `3.2` |
| 2026-05-11 | RFC-618 | Draft | Plan subagent — compiled LangGraph delegate for structured multi-step plans; optional sequential invokes of the explore runnable (no nested `task` tool); YAML `subagents.plan.config` (`enable_explore`, `max_explore_passes`); default model role `think` |
| 2026-05-09 | RFC-221 | Draft | LoopRunnerProtocol: Unified Subprocess-Isolated Agent Loop Execution — one subprocess per loop_id via Python multiprocessing (local) or Ray actor (distributed); fixes SootheRunner singleton data race on `_current_thread_id`, `_current_plan`, `_interrupt_resolver`, `_artifact_store`; removes `daemon._runner` singleton; `QueryEngine` migrated to `LoopRunnerFactory`; renumbered into 2xx AgentLoop series |
| 2026-05-05 | RFC-220 | Draft | LangGraph Agent Loop Orchestrator — Layer 2 as Loop Graph (`loop_id` checkpoint key), mandatory evidence-bound steps, cut-over (supersedes RFC-201 imperative driver); **RFC id**: was RFC-620, renumbered into AgentLoop 2xx series |
| 2026-05-04 | Multiple specs | — | Path migration: `soothe/cognition/*` Python sources documented as `packages/soothe/src/soothe/core/*` (AgentLoop, goal_engine, prompts, events); wire event types `soothe.cognition.*` unchanged (RFC-403) |
| 2026-05-04 | RFC-603, RFC-604, RFC-214 | Draft / Implemented / Draft | IG-376: `goal_progress` is assess-model output only (remove evidence blend); confidence blend remains in `LLMPlanner`; plan-context human uses `Goal` + `Execute iteration` lines; abstract and §3 updated |
| 2026-05-03 | RFC-409 → RFC-215 | Renumbered | AgentLoop Persistence Backend moved to 2xx series (architecture alignment) |
| 2026-05-03 | RFC-608 → RFC-216 | Renumbered | AgentLoop Multi-Thread Lifecycle moved to 2xx series |
| 2026-05-03 | RFC-609 → RFC-217 | Renumbered | Goal Context Management moved to 2xx series |
| 2026-05-03 | RFC-611 → RFC-218 | Renumbered | Checkpoint Tree Architecture moved to 2xx series |
| 2026-05-03 | RFC-615 → RFC-219 | Renumbered | Goal Completion Module moved to 2xx series |
| 2026-05-03 | RFC-214 | Draft | AgentLoop Loop Message Surface and Plan Context — unified ledger of LoopHumanMessage/LoopAIMessage per step as sole Plan context; checkpoint persistence for loop_messages; gap analysis vs combined-wave Execute, StepResult evidence, derive_plan_conversation, LangGraph transcript |
| 2026-04-13 | RFC-605 | Draft | Explore Subagent and Parallel Spawning — targeted filesystem search with wave-based strategy, LLM-driven search planning, match validation; parallel subagent spawning via StepAction.subagents list field; breaking schema migration (no backward compatibility) |
| 2026-04-10 | RFC-211 | Draft | Layer 2 Tool Result Optimization — minimal data contract with outcome metadata, tool_call_id uniqueness, file system cache for large results, final report generation shifted to Layer 1 |
| 2026-04-09 | RFC-207 | Draft | Executor Thread Isolation Simplification — remove manual thread ID generation, leverage langgraph concurrency and task tool automatic isolation, ~80 lines simplified |
| 2026-04-08 | RFC-206 | Draft | Hierarchical Prompt Architecture with System/User Separation — three-layer XML structure (SYSTEM_CONTEXT, USER_TASK, INSTRUCTIONS), PromptBuilder API, modular fragment composition |
| 2026-04-08 | RFC-203 | Draft | Layer 2 Unified State Model and Independent Checkpoint — step I/O semantics, independent persistence, recovery without Layer 1 dependency |
| 2026-04-07 | RFC-200 | Implemented | Added Layer 2 Context Isolation and Execution Bounds — thread isolation for delegation steps, subagent task cap, wave metrics, output contract enforcement |
| 2026-04-03 | RFC-203 | Active | Autopilot Mode — consensus loop, dreaming mode, channel protocol, scheduler, UX surfaces; gap analysis identifying 12 remaining gaps |
| 2026-04-03 | IG-125 | New | Implementation Guide for RFC-203 gap closure |
| 2026-03-31 | Multiple | Reclassified | **RFC Reclassification** — Consolidated 23 RFCs into 16 with new numbering scheme |
| 2026-03-31 | RFC-101 | New | Created from merger of RFC-0016 (Tool Interface) + RFC-0025 (Event Naming) |
| 2026-03-31 | RFC-200 | New | Created from merger of RFC-0009 (DAG Execution) + RFC-0010 (Failure Recovery) |
| 2026-03-31 | RFC-301 | New | Created: Protocol Registry for remaining 6 protocols |
| 2026-03-31 | RFC-400 | New | Created from merger of RFC-0015 + RFC-0019 + RFC-0022 (Event Processing) |
| 2026-03-31 | RFC-501 | New | Created from merger of RFC-0020 + RFC-0024 (Display & Verbosity) |
| 2026-03-31 | RFC-601 | New | Created from merger of RFC-0004 + RFC-0005 + RFC-0021 (Built-in Agents) |
| 2026-03-31 | RFC-0001 | Renamed | Renumbered to RFC-000 (System Conceptual Design) |
| 2026-03-31 | RFC-0002 | Renamed | Renumbered to RFC-001 (Core Modules Architecture) |
| 2026-03-31 | RFC-0023 | Renamed | Renumbered to RFC-100 (CoreAgent Runtime) |
| 2026-03-31 | RFC-0012 | Renamed | Renumbered to RFC-102 (Security & Filesystem Policy) |
| 2026-03-31 | RFC-0007 | Renamed | Renumbered to RFC-200 (Autonomous Goal Management) |
| 2026-03-31 | RFC-0008 | Renamed | Renumbered to RFC-200 (Agentic Goal Execution) |
| 2026-03-31 | RFC-0006 | Renamed | Renumbered to RFC-300 (Context & Memory Protocols) |
| 2026-03-31 | RFC-0013 | Renamed | Renumbered to RFC-400 (Daemon Communication) |
| 2026-03-31 | RFC-0003 | Renamed | Renumbered to RFC-500 (CLI/TUI Architecture) |
| 2026-03-31 | RFC-0018 | Renamed | Renumbered to RFC-600 (Plugin Extension System) |
| 2026-03-30 | RFC-0020 | Draft | Added CLI Stream Display Pipeline section with goal/step/tool narrative format |
| 2026-03-29 | RFC-0024 | Draft | VerbosityTier Unification - replaces two-layer classification with unified enum |
| 2026-03-29 | RFC-0022 | Implemented | Updated to use VerbosityTier, changed VerbosityLevel from `minimal` to `quiet` |
| 2026-03-29 | RFC-0020 | Draft | Updated to use VerbosityTier classification throughout |
| 2026-03-29 | RFC-0019 | Implemented | Added RFC-0024 reference for VerbosityTier |
| 2026-03-29 | RFC-0015 | Implemented | Updated EventMeta.verbosity to use VerbosityTier enum |
| 2026-03-29 | event-catalog.md | Reference | Updated all verbosity columns to use VerbosityTier |
| 2026-03-27 | RFC-0002 | Implemented | Status updated to reflect complete implementation of all 8 core protocols |
| 2026-03-27 | RFC-0003 | Implemented | Status updated to reflect full CLI/TUI implementation |
| 2026-03-27 | RFC-0004 | Implemented | Status updated to reflect Skillify subagent implementation |
| 2026-03-27 | RFC-0005 | Implemented | Status updated to reflect Weaver subagent implementation |
| 2026-03-27 | RFC-0006 | Implemented | Status updated to reflect Context and Memory backends implementation |
| 2026-03-27 | RFC-0013 | Implemented | Status updated to reflect multi-transport daemon implementation |
| 2026-03-27 | RFC-0015 | Implemented | Status updated to reflect progress event system implementation |
| 2026-03-27 | RFC-0018 | Implemented | Status updated to reflect plugin system with decorator API implementation |
| 2026-03-27 | RFC-0021 | Implemented | Status updated to reflect research subagent implementation |
| 2026-03-24 | RFC-0018 | Draft | Updated: Renamed to "Plugin Extension Specification", simplified scope |
| 2026-04-14 | RFC-606 | Implemented | DeepAgents CLI TUI Migration — full copy of deepagents-cli TUI (~30 files), backend adapters created, ProtocolEventWidget implemented (commit 945cc2e) |
| 2026-04-14 | RFC-607 | Implemented | Progressive Display Refinements Post-Migration — newline separators for goal/step/reasoning/completion events, backend adapter integration, protocol event rendering (commit 37c2b09) |
| 2026-03-23 | RFC-0018 | Draft | Initial Plugin Extension Specification |
| 2026-03-18 | RFC-0009 | Draft | DAG-Based Execution and Unified Concurrency |
| 2026-03-18 | RFC-0010 | Draft | Failure Recovery, Progressive Persistence |
| 2026-03-13 | RFC-0004 | Draft | Skillify Agent Architecture Design |
| 2026-03-13 | RFC-0005 | Draft | Weaver Agent Architecture Design |
| 2026-03-12 | RFC-0001 | Draft | Initial Conceptual Design (Platonic Init) |
| 2026-03-12 | RFC-0003 | Draft | CLI TUI Architecture Design |
| 2026-03-20 | RFC-0015 | Draft | Progress Event Protocol |

## Reclassification Summary (2026-03-31)

### New Numbering Scheme

| Prefix | Category |
|--------|----------|
| 0xx | Foundation |
| 1xx | Core Agent |
| 2xx | Cognition Loop |
| 3xx | Protocols |
| 4xx | Daemon |
| 5xx | CLI/TUI |
| 6xx | Plugin System |

### Merges

| New RFC | Source RFCs |
|---------|-------------|
| RFC-101 | RFC-0016 + RFC-0025 |
| RFC-200 | RFC-0009 + RFC-0010 |
| RFC-400 | RFC-0015 + RFC-0019 + RFC-0022 |
| RFC-501 | RFC-0020 + RFC-0024 |
| RFC-601 | RFC-0004 + RFC-0005 + RFC-0021 |

### Renumbered

| Old | New |
|-----|-----|
| RFC-0001 | RFC-000 |
| RFC-0002 | RFC-001 |
| RFC-0023 | RFC-100 |
| RFC-0012 | RFC-102 |
| RFC-0007 | RFC-200 |
| RFC-0008 | RFC-200 |
| RFC-0006 | RFC-300 |
| RFC-0013 | RFC-400 |
| RFC-0003 | RFC-500 |
| RFC-0018 | RFC-600 |

## Notes

- All RFCs start in **Draft** status when generated
- Use `specs-refine` to validate and refine RFCs
- Reclassification maintains all content, only changes organization