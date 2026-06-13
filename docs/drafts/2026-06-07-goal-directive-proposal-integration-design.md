# Design Draft: Goal Directive and Proposal Queue Integration

**Date:** 2026-06-07
**Author:** Claude (via Platonic Brainstorming)
**Status:** Draft for user review
**Related RFCs:** RFC-222, RFC-204, RFC-200, RFC-225

---

## Problem Statement

Job `43caba4a` has a single goal in GoalEngine's DAG because two key integration points are not wired:

**Gap #1:** `GoalDirective` generation exists (Reflection, Planner) but `GoalEngine.apply_directives()` is a TODO at `engine.py:1243`. Directives never reach the DAG.

**Gap #2:** `ProposalQueue` class exists with tests, but Layer 2 tools (`suggest_goal`, `add_finding`) are not implemented and Runner never drains/processes proposals.

Both reactive (failure → prerequisite) and proactive (agent decides to decompose) subgoal creation pathways are blocked.

---

## Design Goals

1. Wire the reactive path: Reflection → GoalCompletionChunk → GoalEngine.apply_directives()
2. Wire the proactive path: Layer 2 tools → ProposalQueue → Runner drain → GoalDirective → GoalEngine
3. Unify both paths at `GoalCompletionChunk.goal_directives` for single daemon-side consumer
4. Preserve existing wire contract (extend, not replace)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                    AGENTLOOP WORKER (Subprocess)                    │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  Mid-iteration (Proactive Path):                                    │
│    suggest_goal tool ──► ProposalQueue.enqueue()                    │
│    add_finding tool ──► ProposalQueue.enqueue()                     │
│                                                                     │
│  End-of-goal (Reactive Path):                                       │
│    Planner.reflect() ──► Reflection.goal_directives                 │
│                                                                     │
│  Runner merges both:                                                │
│    proposals = ProposalQueue.drain()                                │
│    proposal_directives = _proposals_to_directives(proposals)        │
│    all_directives = reflection_directives + proposal_directives     │
│                                                                     │
│  Emit:                                                              │
│    GoalCompletionChunk(goal_directives=all_directives)              │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    DAEMON AUTOPILOTSERVICE                          │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  _route_chunk(GoalCompletionChunk):                                 │
│    goal_engine.apply_directives(chunk.goal_directives)              │
│      ──► create_goal() for "create" actions                         │
│      ──► update priority/deps for "adjust_*" actions                │
│      ──► transition for "fail"/"complete" actions                   │
│                                                                     │
│    DAG now has subgoals → scheduling loop picks them up             │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Component Changes

### 1. GoalCompletionChunk Extension (Worker Side)

**Current location:** `_runner_autopilot_worker.py:260-279`

**Current payload:**

```python
payload: dict[str, Any] = {
    "type": "soothe.internal.autopilot.goal_completion",
    "goal_id": job.goal_id,
    "outcome": outcome,
    "attempt": job.attempt,
    "context_contribution": contribution.model_dump(mode="json"),
}
```

**Extended payload:**

```python
payload: dict[str, Any] = {
    "type": "soothe.internal.autopilot.goal_completion",
    "goal_id": job.goal_id,
    "outcome": outcome,
    "attempt": job.attempt,
    "context_contribution": contribution.model_dump(mode="json"),
    "goal_directives": [d.model_dump(mode="json") for d in directives],  # NEW
}
```

**Directive sources in worker:**

| Source | When populated | Type of directives |
|--------|----------------|-------------------|
| Reflection | End of goal execution | Prerequisite creation, decomposition |
| ProposalQueue drain | End of goal execution | Proactive subgoal suggestions |

**Semantics:**

- `goal_directives` populated on all outcomes (`completed`, `failed`, `needs_replan`)
- Empty list when no directives generated
- Merged order: reflection directives first, then proposal-derived directives

---

### 2. GoalEngine.apply_directives() (Daemon Side)

**Location:** `engine.py:1243` (TODO comment)

**Signature:**

```python
async def apply_directives(
    self,
    directives: list[GoalDirective],
    source_goal_id: str,
) -> list[str]:
    """Apply goal directives from GoalCompletionChunk.

    Args:
        directives: List of GoalDirective to apply.
        source_goal_id: Goal that emitted these directives (for parent_id default).

    Returns:
        List of newly created goal IDs.
    """
```

**Action handlers:**

| Action | Implementation |
|--------|----------------|
| `create` | `create_goal(description, priority, parent_id=parent_id or source_goal_id, depends_on)` |
| `decompose` | Log warning + skip (future work) |
| `adjust_priority` | `goal.priority = d.priority` |
| `add_dependency` | `goal.depends_on.extend(d.depends_on)` |
| `fail` | `fail_goal(d.goal_id, evidence=d.rationale)` |
| `complete` | `complete_goal(d.goal_id)` |

**Parent_id defaulting:**

- If `d.parent_id` is None, use `source_goal_id`
- This creates natural subgoal hierarchy without explicit parent_id required

**Error handling:**

- Missing `goal_id` for non-create actions → log warning, skip directive
- Invalid `priority` → clamp to [0, 100]
- Duplicate dependency → silently dedupe

---

### 3. Layer 2 Tools: suggest_goal and add_finding

**Location:** New package `tools/proposal/`

#### suggest_goal tool

```python
@tool
def suggest_goal(
    description: str,
    priority: int = 50,
    depends_on: list[str] = [],
    rationale: str = "",
) -> str:
    """Suggest a new subgoal for the current goal's DAG.

    Use when you identify a prerequisite or subtask that should be
    handled separately before continuing the current goal.

    Args:
        description: What the suggested goal should accomplish.
        priority: 0-100, higher = more urgent. Default 50.
        depends_on: Goal IDs this suggestion depends on (optional).
        rationale: Why this goal is needed.

    Returns:
        Confirmation string that suggestion was queued.
    """
```

**Access to ProposalQueue:**

- Via `LoopRuntimeContext.proposal_queue` injected by Runner
- Tool reads context from CoreAgent's execution context

#### add_finding tool

```python
@tool
def add_finding(
    summary: str,
    relevance_score: float = 0.7,
    tags: list[str] = [],
) -> str:
    """Record a finding for context projection to child goals.

    Use when you discover information that may be useful for downstream
    goals (e.g., file locations, key insights, partial results).

    Args:
        summary: Brief description of the finding (max 2000 chars).
        relevance_score: 0.0-1.0, how relevant to the overall goal.
        tags: Optional categorization tags.

    Returns:
        Confirmation string that finding was queued.
    """
```

**Proposal payload:**

```python
{
    "summary": summary,
    "relevance_score": relevance_score,
    "tags": tags,
}
```

---

### 4. Runner Wiring: ProposalQueue Lifecycle

**Location:** `_runner_autopilot_worker.py`

**Changes to `_run_single_autopilot_goal`:**

```python
async def _run_single_autopilot_goal(...) -> AsyncGenerator[StreamChunk, None]:
    # Create per-goal proposal queue
    proposal_queue = ProposalQueue()

    # Inject into StrangeLoop via runtime context
    async for event_type, event_data in strange_loop.run_with_progress(
        goal=job.goal_description,
        thread_id=tid,
        workspace=workspace,
        max_iterations=max_iterations,
        loop_id=tid,
        clarification_policy=clarification_policy,
        proposal_queue=proposal_queue,  # NEW parameter
    ):
        # ... existing event handling ...

    # After StrangeLoop completes, drain proposals
    proposals = proposal_queue.drain()

    # Convert proposals to directives
    proposal_directives = _proposals_to_directives(proposals, source_goal_id=job.goal_id)

    # Extract reflection directives from PlanResult (if available)
    reflection_directives = _extract_reflection_directives(plan_result)

    # Merge
    all_directives = reflection_directives + proposal_directives

    # Emit completion chunk with directives
    yield self._goal_completion_chunk(
        job,
        outcome=outcome,
        plan_result=plan_result,
        directives=all_directives,  # NEW parameter
    )
```

**Helper: `_proposals_to_directives`**

```python
def _proposals_to_directives(
    proposals: list[Proposal],
    source_goal_id: str,
) -> list[GoalDirective]:
    """Convert ProposalQueue proposals to GoalDirectives."""
    directives = []
    for p in proposals:
        if p.type == "suggest_goal":
            directives.append(GoalDirective(
                action="create",
                description=p.payload.get("description", ""),
                priority=p.payload.get("priority", 50),
                parent_id=None,  # Defaults to source_goal_id in apply_directives
                depends_on=p.payload.get("depends_on", []),
                rationale=p.payload.get("rationale", ""),
            ))
        elif p.type == "add_finding":
            # Findings don't create goals; they enrich context_contribution
            # Handled separately in _build_contribution
            pass
    return directives
```

**Helper: `_extract_reflection_directives`**

```python
def _extract_reflection_directives(plan_result: PlanResult | None) -> list[GoalDirective]:
    """Extract goal_directives from PlanResult if Reflection populated them."""
    if plan_result is None:
        return []

    # Reflection attaches directives to PlanResult.decision
    decision = getattr(plan_result, "decision", None)
    if decision is None:
        return []

    directives = getattr(decision, "goal_directives", None)
    if isinstance(directives, list):
        return directives
    return []
```

---

### 5. StrangeLoop Injection: proposal_queue Parameter

**Location:** `core/loop/__init__.py` (StrangeLoop.run_with_progress)

**Parameter addition:**

```python
async def run_with_progress(
    self,
    goal: str,
    thread_id: str | None = None,
    workspace: str | None = None,
    max_iterations: int | None = None,
    loop_id: str | None = None,
    clarification_policy: Any | None = None,
    proposal_queue: ProposalQueue | None = None,  # NEW
) -> AsyncGenerator[tuple[str, Any], None]:
```

**Storage in LoopRuntimeContext:**

```python
class LoopRuntimeContext:
    # ... existing fields ...
    proposal_queue: ProposalQueue | None = None  # NEW
```

**Tool access pattern:**

Tools access via CoreAgent's context injection mechanism (existing pattern used by other context-aware tools).

---

### 6. Daemon-side Consumer: _route_chunk Extension

**Location:** `daemon/autopilot/service.py` (AutopilotService._route_chunk)

**Current handling:**

```python
if chunk_type == "soothe.internal.autopilot.goal_completion":
    if outcome == "completed":
        goal_engine.complete_goal(goal_id)
        context_store.put(goal_id, contribution)
    elif outcome == "failed":
        goal_engine.fail_goal(goal_id, evidence=...)
```

**Extension:**

```python
if chunk_type == "soothe.internal.autopilot.goal_completion":
    # Apply directives FIRST (creates subgoals before state transitions)
    directives = payload.get("goal_directives", [])
    if directives:
        await goal_engine.apply_directives(
            [GoalDirective(**d) for d in directives],
            source_goal_id=goal_id,
        )

    # Then handle outcome
    if outcome == "completed":
        goal_engine.complete_goal(goal_id)
        context_store.put(goal_id, contribution)
    elif outcome == "failed":
        goal_engine.fail_goal(goal_id, evidence=...)
    elif outcome == "needs_replan":
        # Goal stays active; directives may have created prerequisites
        pass
```

**Ordering rationale:**

- Apply directives before state transition so created subgoals can inherit from active goal
- Subgoals created on `failed` outcome will be ready when backoff target resumes

---

## Implementation Phases

### Phase 1: GoalCompletionChunk extension + apply_directives (Gap #1)

**Files modified:**

1. `core/goal_engine/engine.py` — implement `apply_directives()`
2. `core/runner/_runner_autopilot_worker.py` — add `directives` parameter to `_goal_completion_chunk`
3. `daemon/autopilot/service.py` — extend `_route_chunk` to consume directives

**Tests:**

- `test_goal_engine_apply_directives.py` — unit tests for each action type
- Update existing autopilot integration tests

### Phase 2: Reflection directive extraction

**Files modified:**

1. `core/runner/_runner_autopilot_worker.py` — add `_extract_reflection_directives`

**Tests:**

- Test Reflection → PlanResult → GoalDirective extraction chain

### Phase 3: Layer 2 tools + ProposalQueue wiring (Gap #2)

**Files created:**

1. `tools/proposal/__init__.py`
2. `tools/proposal/suggest_goal.py`
3. `tools/proposal/add_finding.py`

**Files modified:**

1. `core/loop/__init__.py` — add `proposal_queue` parameter
2. `core/loop/state/schemas.py` — add `proposal_queue` to `LoopRuntimeContext`
3. `core/runner/_runner_autopilot_worker.py` — create queue, drain, convert

**Tests:**

- `test_suggest_goal_tool.py`
- `test_add_finding_tool.py`
- Integration test: tool → queue → directive → DAG

---

## Deferred Work

1. **`report_progress` tool** — lower priority, useful for observability but not DAG construction
2. **`flag_blocker` tool** — lower priority, maps to existing backoff mechanism
3. **`decompose` action** — requires explicit multi-child creation logic; future work
4. **Finding extraction to GoalDispatchContextContribution** — `add_finding` proposals should enrich contribution, not just queue

---

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| Directive explosion (too many subgoals created) | Cap `max_directives_per_chunk` in config; log warning on excess |
| Duplicate goals (reflection + proposal both create same) | Dedupe by description similarity before apply |
| Race: directive creates goal that depends on source, but source fails | `apply_directives` runs before `fail_goal`; dependencies still valid |
| Tool can't access ProposalQueue (context not injected) | Fail gracefully: return error string, log warning |

---

## Success Criteria

1. Job with prerequisite failure creates subgoal via Reflection → GoalCompletionChunk → apply_directives
2. StrangeLoop can call `suggest_goal` mid-execution and see subgoal in next scheduling tick
3. `GoalEngine._format_goal_dag()` shows parent→child relationships for dynamically created goals
4. Integration test covers full flow: tool → queue → chunk → apply → DAG

---

## Open Questions

1. **Should `suggest_goal` return a goal_id for depends_on chaining?** Current design queues asynchronously; no ID until daemon applies. Could return placeholder `proposal_id` for intra-iteration chaining.
2. **Priority inheritance:** Should subgoals inherit parent priority + 10 by default, or use explicit value only?
3. **Finding propagation:** Should `add_finding` proposals flow to `GoalDispatchContextContribution.findings` or stay separate?