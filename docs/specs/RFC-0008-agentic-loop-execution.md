# RFC-0008: Agentic Loop Execution Architecture

**RFC**: 0008
**Title**: Agentic Loop Execution Architecture
**Status**: Draft
**Created**: 2026-03-16
**Updated**: 2026-03-29
**Related**: RFC-0001, RFC-0002, RFC-0003, RFC-0007, RFC-0009, RFC-0010, RFC-0012, RFC-0015

## Abstract

This RFC documents Soothe's current default non-autonomous execution architecture. Today, Soothe routes non-chitchat queries into an **agentic loop** in `SootheRunner`, but the active runtime is still primarily an **observe → act → verify** loop backed by planning, step execution, planner reflection, and heuristic continuation checks. In parallel, the codebase now contains partial scaffolding for the intended **PLAN → ACT → JUDGE** architecture: structured loop schemas, cognition-scoped loop events, a judge engine, and integration adapters. Those pieces are not yet the primary execution path.

The result is a transitional implementation: the runtime already has adaptive planning, iterative execution, and a chitchat fast path, but RFC-0008's fuller Layer-2 `LoopAgent` design is only partially wired.

## Motivation

### Problem Statement

Soothe originally executed most work in a single pass. As the runtime evolved, it needed a lighter-weight iterative mode than RFC-0007 autonomous goal management:

1. **Standard tasks still need iteration**: many non-autonomous requests benefit from plan creation, execution, reflection, and possible revision.
2. **Chitchat should stay fast**: greetings and other trivial requests should bypass the heavier loop.
3. **Default mode should remain lighter than autonomous mode**: standard requests should not pay for goal DAG management, retries, and goal persistence.
4. **Longer-term direction needed**: the codebase began introducing a more explicit PLAN → ACT → JUDGE architecture with structured schemas and dedicated loop modules.

### Design Goals

1. **Default iterative execution** for non-chitchat queries
2. **Sub-second chitchat** through direct fast-path routing
3. **Adaptive planning** based on task complexity
4. **Lighter than autonomous mode** while still supporting iteration
5. **A migration path** from observe → act → verify toward the fuller PLAN → ACT → JUDGE architecture

### Relationship to RFC-0007 (Autonomous Mode)

**Two complementary execution modes**:

| Aspect | Agentic Loop (This RFC) | Autonomous Mode (RFC-0007) |
|--------|-------------------------|----------------------------|
| **Trigger** | Default for non-chitchat queries | Explicit autonomous mode |
| **Current loop sequence** | Observe → Act → Verify | Goal → Plan → Reflect |
| **Goal management** | Implicit thread-scoped execution | Explicit GoalEngine with DAG |
| **Planning** | Adaptive, complexity-driven | Goal-driven, comprehensive |
| **Iteration control** | Verification-based continuation | Reflection-based goal completion |
| **Use case** | Standard tasks | Multi-goal autonomous workflows |

Current implementation note: RFC-0008 also describes a more explicit Layer-2 PLAN → ACT → JUDGE design. Parts of that design exist in the codebase, but the active default runner still uses observe → act → verify.

## Current Runtime Architecture

### Three-layer model

Soothe currently operates with three conceptual layers:

```text
Layer 3: Autonomous Loop (runner, RFC-0007)
  └─ Goal-driven iteration with GoalEngine

Layer 2: Agentic Loop (runner, this RFC)
  └─ Observe → Act → Verify loop for default non-autonomous execution

Layer 1: deepagents Tool Loop (graph, langchain)
  └─ Model → Tools → Model tool-calling loop
```

deepagents provides the underlying tool-calling loop. Soothe adds higher-level planning, reflection, and optional autonomous goal management on top.

### Default execution flow

Current default non-autonomous execution in `SootheRunner.astream()`:

```text
User Request
    |
    v
If subagent was specified:
    direct subagent routing
else:
    UnifiedClassifier routing
        |
        +-- if chitchat:
        |      _run_chitchat()
        |
        +-- else:
               _run_agentic_loop()
                    |
                    +-- pre-stream independent work
                    |      (thread, policy, memory, context)
                    |
                    +-- determine planning strategy
                    |
                    +-- loop while iteration < max_iterations:
                           |
                           +-- Observe
                           |      optional context/memory recall
                           |      reuse cached routing classification
                           |
                           +-- Act
                           |      optional PlannerProtocol.create_plan()
                           |      if multi-step plan: step loop
                           |      else: direct stream phase
                           |
                           +-- Verify
                                  PlannerProtocol.reflect()
                                  continuation heuristics
                                  optional revise_plan()
```

### Chitchat fast path

The chitchat fast path is implemented and active. When tier-1 routing classifies a request as `chitchat`, the runner bypasses the agentic loop and routes directly into `_run_chitchat()`.

### Agentic loop behavior

The live `_run_agentic_loop()` path currently performs:

1. Tier-1 routing classification
2. Chitchat bypass when appropriate
3. Pre-stream protocol work
4. Planning-strategy selection: `none`, `lightweight`, or `comprehensive`
5. Iterative **observe → act → verify** execution
6. Optional plan revision when reflection indicates more work is needed
7. Post-stream persistence and checkpointing
8. Final loop-completed event emission

## Current Components

### 1. Runner agentic loop (`core/runner/_runner_agentic.py`)

The live default loop is implemented in `AgenticMixin._run_agentic_loop()`.

**Current behavior**:
- emits `soothe.agentic.*` lifecycle and observation/verification events
- stores lightweight `AgenticIterationRecord` entries on runner state
- uses planning strategy selection before each iteration
- uses planner-created plans during ACT
- uses planner reflection plus `_evaluate_continuation()` during VERIFY

Current implementation note: the active loop does **not** call `_agentic_plan()` or `_agentic_judge()` as its main path.

### 2. Planning integration (`PlannerProtocol` + step loop)

Planning is fully integrated into the current agentic loop, but not in the RFC's original AgentDecision-centric form.

**Current behavior**:
- strategy `none` → direct stream execution
- strategy `lightweight` / `comprehensive` → `PlannerProtocol.create_plan()`
- multi-step plans → `StepLoopMixin._run_step_loop()`
- single-step or no plan → `_stream_phase()`
- post-execution verification → `PlannerProtocol.reflect()`
- if continuation is needed and reflection requests revision → `PlannerProtocol.revise_plan()`

### 3. Verification path

The current VERIFY phase is planner/reflection driven.

**Current behavior**:
- build `StepResult` objects from completed/failed plan steps
- call `PlannerProtocol.reflect(plan, step_results)`
- emit `soothe.cognition.plan.reflected`
- use `_evaluate_continuation()` to decide whether to continue
- continuation logic is heuristic and considers:
  - `reflection.should_revise`
  - configured completion signals
  - response-text indicators like `missing`, `incomplete`, `need to verify`
  - response length thresholds

Current implementation note: this is not yet the RFC's intended JudgeEngine-driven `JudgeResult` runtime.

### 4. LoopAgent scaffolding (`cognition/loop_agent/*`)

The codebase now contains partial scaffolding for the intended PLAN → ACT → JUDGE architecture.

**Implemented modules**:
- `core/schemas.py` — `AgentDecision`, `JudgeResult`, `ToolOutput`
- `core/state.py` — `LoopState`, `StepRecord`
- `core/events.py` — `soothe.cognition.loop.*` event models
- `execution/judge.py` — `JudgeEngine`
- `execution/failure_detector.py` — guardrail helpers
- `integration/context_borrower.py` — borrowed-context summarization
- `integration/tool_loop_adapter.py` — Layer-1 execution adapter skeleton
- `integration/goal_adapter.py` — autonomous/goal integration scaffolding

Current implementation note: these modules are only partially integrated. In particular, `ToolLoopAdapter.execute_tool()` still returns a permanent "not fully implemented yet" failure, and the live runner does not currently route through `ContextBorrower`, `GoalAdapter`, or `FailureDetector`.

### 5. PLAN/JUDGE helper path

`_runner_agentic.py` also contains `_agentic_plan()` and `_agentic_judge()` helpers that use:
- `AgentDecision`
- `JudgeEngine`
- `soothe.cognition.loop.phase.*` events

Current implementation note: these helpers are present but are not yet the active default execution path.

## Interfaces & Data Models

### Active runtime state: `RunnerState` + `AgenticIterationRecord`

The live loop primarily tracks state through `RunnerState` and a lightweight `AgenticIterationRecord` journal.

```python
class AgenticIterationRecord(BaseModel):
    iteration: int
    planning_strategy: Literal["none", "lightweight", "comprehensive"]
    observation_summary: str
    actions_taken: str
    verification_result: str
    should_continue: bool
    duration_ms: int
```

This lightweight record is currently runner-local state, not a richer persisted LoopState history model.

### Partial structured-loop schemas

The following schemas exist in `cognition/loop_agent/core/schemas.py` and represent the intended fuller architecture:
- `AgentDecision`
- `JudgeResult`
- `ToolOutput`
- `LoopState`
- `StepRecord`

Current implementation note: these schemas are not yet the primary contract for the live default loop.

## Control Flow

### Active loop pseudocode

```python
state = RunnerState()
planning_strategy = determine_planning_strategy(complexity, user_input)

while iteration < max_iterations and should_continue:
    observe()

    if planning_strategy != "none":
        plan = planner.create_plan(user_input, context)

    if plan has multiple steps:
        run_step_loop(plan)
    else:
        stream_phase(user_input)

    reflection = planner.reflect(plan, completed_step_results)
    should_continue = evaluate_continuation(reflection, response_text, strictness)

    if should_continue and reflection.should_revise:
        plan = planner.revise_plan(plan, reflection.feedback)
```

### Intended future helper path

The codebase also contains a partial PLAN → ACT → JUDGE helper flow:

```python
decision = await _agentic_plan(...)
result = await tool_loop_adapter.execute_tool(...)
judgment = await _agentic_judge(...)
```

Current implementation note: this path is not yet wired into `_run_agentic_loop()`.

## Guardrails & Failure Modes

### Currently active behavior

The active runtime does **not** yet fully enforce the RFC's richer structured guardrail model.

What is currently active:
- `max_iterations`
- planner reflection and plan revision
- heuristic completion/continuation detection via `_evaluate_continuation()`
- chitchat bypass

What currently exists mostly as scaffolding:
- repeated-action detection via `FailureDetector`
- tool hallucination enforcement in the Layer-2 loop
- silent-failure detection in the Layer-2 loop
- structured retry/replan/done judgment as the primary runtime contract

## Tool Interface Status

RFC-0008's intended direction is for tool execution to flow through structured `ToolOutput` values. The current codebase includes `ToolOutput` and tool-output formatting support, but the default runner does not yet require all tools to execute through the Layer-2 `ToolLoopAdapter` contract.

Current implementation note: `ToolLoopAdapter` exists but is not fully implemented or used as the active ACT path.

## Memory and Persistence

### Current memory behavior

Memory and context handling in agentic mode currently reuse the runner's standard pre-stream and post-stream protocol flows:
- pre-stream memory recall and context projection
- optional extra observation-phase context/memory gathering in later iterations
- post-stream response/context persistence

This is lighter and more generic than the richer loop-native episodic/semantic memory model originally described in this RFC.

### Current persistence behavior

Agentic mode currently runs through the same post-stream checkpoint path used by non-autonomous execution, and checkpoint state is still recorded with `mode="single_pass"` rather than a distinct `agentic` mode.

## Event System

### Active runtime event taxonomy

The live runner currently emits **`soothe.agentic.*`** events for agentic-loop lifecycle and observation/verification progress.

**Lifecycle events**:
- `soothe.agentic.loop.started`
- `soothe.agentic.loop.completed`
- `soothe.agentic.iteration.started` *(defined, but not currently emitted by the main loop)*
- `soothe.agentic.iteration.completed`

**Observation / verification events**:
- `soothe.agentic.observation.started`
- `soothe.agentic.observation.completed`
- `soothe.agentic.verification.started`
- `soothe.agentic.verification.completed`
- `soothe.agentic.planning.strategy_determined`

**Related plan events used by the live loop**:
- `soothe.cognition.plan.created`
- `soothe.cognition.plan.reflected`
- standard step-loop events from RFC-0009
- `soothe.output.final_report` when a multi-step final report is synthesized

### Partial cognition-loop event surface

`cognition/loop_agent/core/events.py` defines a richer `soothe.cognition.loop.*` taxonomy including PLAN/ACT/JUDGE phase events, retry/replan events, and error events.

Current implementation note: these cognition-loop events represent partial/future architecture and are not yet the main event surface emitted by `_run_agentic_loop()`.

## Module Structure

### Implemented module layout

The following pieces exist today:

```text
core/runner/
├── _runner_agentic.py      # active default non-autonomous loop
├── _runner_autonomous.py   # autonomous goal loop
├── _runner_steps.py        # DAG step execution
└── _runner_phases.py       # pre/post-stream orchestration

cognition/loop_agent/
├── core/                   # schemas, state, cognition-loop events
├── execution/              # judge engine, failure detector
└── integration/            # context borrower, goal adapter, tool adapter
```

### Responsibility split today

- `core/runner/_runner_agentic.py` owns the live default loop
- `PlannerProtocol` and planning backends own plan creation/reflection/revision
- `StepLoopMixin` owns multi-step execution
- `cognition/loop_agent/*` provides partial scaffolding for a more explicit future Layer-2 loop architecture

## Performance Optimization

### Chitchat fast path

This is active and implemented:
- chitchat requests bypass the default loop
- direct `_run_chitchat()` execution keeps trivial responses fast

### Adaptive planning

This is active and implemented:
- `simple` → `none`
- `medium` → `lightweight`
- `complex` → `comprehensive`
- configured force-keywords can escalate directly to `comprehensive`

Current implementation note: adaptive escalation is based on planner feedback text, not the RFC's intended JudgeResult-driven loop decisions.

### Query execution tiers

Daemon-served queries are routed into one of three execution tiers:

| Tier | Use Case | Properties |
|------|----------|------------|
| **Fast Path** | No tool use, multi-step, or iterative verification needed | Single-pass, minimal observation, no multi-iteration loop |
| **Light-Agentic** | One PLAN → ACT → JUDGE cycle likely sufficient | One iteration default, minimal refresh, smaller evidence budget |
| **Full-Agentic** | Complex tasks, failure recovery, replan conditions | Multiple iterations, broader refresh when justified |

**Routing Principle**: Prefer the cheapest path that can still produce a reliable answer. Escalation requires evidence; early completion does not.

### Query-scoped observation reuse

Observation work (classification, memory recall, context projection) should not be repeated across iterations or steps unless the active problem meaning changes.

**Snapshot Contents**:
- normalized query key
- classification result
- recalled memories
- context projection
- version/freshness metadata
- invalidation reason when refreshed

**Reuse Semantics**: Reuse observation snapshot across:
- subsequent iterations for the same query
- retries that keep the same intent
- plan steps semantically close to parent query

**Refresh Triggers** (MUST refresh when):
1. judge returns `replan`
2. active step or query meaning materially changes
3. tool results introduce new retrieval target not covered by current snapshot
4. observation mode explicitly escalated
5. no valid snapshot exists

**Step-Level Inheritance**: Step execution inherits parent query snapshot by default. If a step introduces distinct retrieval target, create small step-local delta rather than full recomputation.

### Token-count planning strategy

Planning strategy is determined by token-count heuristics:

| Token Count | Strategy | Behavior |
|-------------|----------|----------|
| ≤ threshold (default ~50) | `none` | Direct stream, no plan creation |
| > threshold | `lightweight`/`comprehensive` | Create plan, execute step loop |

**Threshold Configuration**: `agentic.planning.simple_max_tokens` in config.

**Fast-verifiable step bias**: Plans should prefer steps that:
1. target one concrete subproblem
2. produce one strong completion signal when successful
3. are easy to classify as `done`, `retry`, or `replan`
4. limit evidence ambiguity during judgment

**Why this improves loops**: Small fast-verifiable steps make PLAN → ACT → JUDGE cheaper:
- PLAN emits narrower actions
- ACT produces clearer evidence
- JUDGE needs less context to decide status
- retries and replans become more targeted

### Early termination optimization

First-iteration completion should be default for light-agentic requests when evidence is sufficient:
- judgment input smaller for first-pass evaluation than full-agentic
- escalate only when evidence is weak, contradictory, or indicates scope change
- do not pay full verification overhead when first action already produced strong completion evidence

### Query timing instrumentation

The query execution path SHOULD record timings for:
- classification
- memory recall
- context projection
- plan creation
- act execution
- judge/verification
- total latency
- iteration count
- observation snapshot cache hit/miss

## Configuration

Current agentic configuration surface:

```yaml
agentic:
  enabled: true
  use_judge_engine: true
  max_iterations: 3
  observation_strategy: "adaptive"
  verification_strictness: "moderate"
  planning:
    simple_max_tokens: 50
    medium_max_steps: 3
    complexity_threshold: 160
    force_keywords: ["plan for", "create a plan", "steps to"]
    adaptive_escalation: true
  early_termination:
    enabled: true
    completion_signals: ["task complete", "done", "finished successfully"]
    error_threshold: 3
```

Current implementation note:
- `use_judge_engine` exists on the config surface but is not yet wired into the live `_run_agentic_loop()` path
- earlier RFC drafts described extra judge/guardrail/retry/tool-timeout settings that are not part of the current runtime config

## Example of Current Runtime Behavior

For a non-chitchat debugging request, the current path is typically:

1. classify as non-chitchat
2. run pre-stream memory/context/policy work
3. choose a planning strategy
4. create a plan if needed
5. execute either a step loop or a direct stream pass
6. reflect on results
7. continue or revise if reflection and heuristics indicate more work
8. persist and emit loop-completed event

This is iterative and agentic, but it is still not the fully structured PLAN → ACT → JUDGE runtime described in the earlier RFC text.

## Migration & Compatibility

### Current migration status

RFC-0008 is in a transitional state:

| Area | Current Status |
|------|----------------|
| Default iterative execution | Implemented |
| Chitchat fast path | Implemented |
| Adaptive planning | Implemented |
| Planner reflection-based verification | Implemented |
| PLAN → ACT → JUDGE helper scaffolding | Partial |
| Structured LoopAgent integration | Partial |
| `soothe.cognition.loop.*` as active runtime namespace | Not yet primary |
| Structured judge engine as active runtime verifier | Not yet primary |

### Backward compatibility

The external `runner.astream()` interface is unchanged. The main differences are internal execution semantics, observability, and the gradual introduction of LoopAgent-specific modules and schemas.

## Future Enhancements

1. Wire `use_judge_engine` into the live loop
2. Promote `_agentic_plan()` / `_agentic_judge()` from scaffolding to active path
3. Integrate `ToolLoopAdapter` into ACT execution
4. Integrate `FailureDetector` into the main loop
5. Decide whether to migrate the live event namespace from `soothe.agentic.*` to `soothe.cognition.loop.*`
6. Give agentic mode a first-class checkpoint mode distinct from `single_pass`
7. Revisit richer loop-native episodic memory integration

## References

- RFC-0001: System Conceptual Design
- RFC-0007: Autonomous Iteration Loop
- RFC-0009: DAG-Based Execution and Unified Concurrency
- RFC-0010: Failure Recovery Persistence
- RFC-0012: Unified LLM-Based Classification System
- RFC-0015: Progress Event Protocol
- IG-045: Agentic Loop Implementation Guide
- Draft Document: `docs/drafts/004-rfc-0008-polish-agentic-loop.md`

## Changelog

### 2026-03-29
- Merged RFC-0023 query execution performance content
- Added query execution tiers (fast, light-agentic, full-agentic)
- Added query-scoped observation reuse semantics
- Added token-count planning strategy heuristics
- Added early termination optimization and timing instrumentation

### 2026-03-28
- Aligned RFC-0008 with the current runtime instead of the intended end state
- Documented the active default loop as observe → act → verify
- Clarified that PLAN → ACT → JUDGE modules and helpers exist but are only partially wired
- Updated event taxonomy to match the currently emitted `soothe.agentic.*` surface
- Updated configuration to match the real `agentic.*` settings
- Corrected memory, persistence, and autonomous-integration wording to reflect current implementation

### 2026-03-27
- Major rewrite toward a fuller PLAN → ACT → JUDGE architecture
- Added Layer Integration Architecture section
- Added cognition-loop event taxonomy
- Added LoopAgent module structure and structured schemas

### 2026-03-22
- Rewrote RFC-0008 to focus on Agentic Loop architecture
- Replaced single-pass execution model with agentic loop as default
- Added observe → act → verify three-phase loop
- Introduced adaptive planning strategies
- Preserved chitchat fast path

### 2026-03-19 (Original RFC-0008)
- Initial draft with unified classification system
- Single-pass execution model
- Performance optimization strategies
- Parallel execution and template matching
