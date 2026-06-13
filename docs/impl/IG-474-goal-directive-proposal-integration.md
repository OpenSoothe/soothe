# IG-XXX: Goal Directive and Proposal Queue Integration

**Status**: In Progress
**Created**: 2026-06-07
**RFC**: RFC-204 Group C (updated 2026-06-07)
**Scope**: Wire GoalDirective → GoalEngine + ProposalQueue → Layer 2 tools

---

## Summary

Implement RFC-204 Group C's dual-path integration for dynamic subgoal creation:
- **Reactive path**: Reflection → GoalCompletionChunk.goal_directives → GoalEngine.apply_directives()
- **Proactive path**: Layer 2 tools → ProposalQueue → Runner drain → GoalDirective → GoalEngine

---

## Phase C.1: GoalCompletionChunk Extension + apply_directives (Reactive Path)

### Files to Modify

| File | Change |
|------|--------|
| `core/goal_engine/engine.py:1243` | Implement `apply_directives()` method |
| `core/runner/_runner_autopilot_worker.py` | Add `directives` parameter to `_goal_completion_chunk`, extract from PlanResult |
| `daemon/autopilot/service.py` | Extend `_route_chunk` to call `apply_directives` |

### Step 1: GoalEngine.apply_directives()

**Location**: Replace TODO at `engine.py:1243`

**Implementation**:

```python
from soothe.protocols.planner import GoalDirective

async def apply_directives(
    self,
    directives: list[GoalDirective],
    source_goal_id: str,
) -> list[str]:
    """Apply goal directives from GoalCompletionChunk (RFC-204 Group C).

    Args:
        directives: List of GoalDirective to apply.
        source_goal_id: Goal that emitted these directives (for parent_id default).

    Returns:
        List of newly created goal IDs.
    """
    created_ids: list[str] = []

    for d in directives:
        try:
            if d.action == "create":
                # Parent defaults to source goal if not specified
                parent = d.parent_id or source_goal_id
                priority = d.priority or 50
                # Clamp priority to valid range
                priority = max(0, min(100, priority))

                new_goal = await self.create_goal(
                    description=d.description,
                    priority=priority,
                    parent_id=parent,
                    depends_on=list(d.depends_on) if d.depends_on else [],
                )
                created_ids.append(new_goal.id)
                logger.info(
                    "Directive created goal %s (parent=%s, priority=%d): %s",
                    new_goal.id,
                    parent,
                    priority,
                    preview_first(d.description, 50),
                )

            elif d.action == "adjust_priority":
                goal = self._goals.get(d.goal_id)
                if goal and d.priority is not None:
                    old_priority = goal.priority
                    goal.priority = max(0, min(100, d.priority))
                    goal.updated_at = datetime.now(UTC)
                    logger.info(
                        "Directive adjusted goal %s priority: %d → %d",
                        d.goal_id,
                        old_priority,
                        goal.priority,
                    )

            elif d.action == "add_dependency":
                goal = self._goals.get(d.goal_id)
                if goal and d.depends_on:
                    for dep_id in d.depends_on:
                        if dep_id not in goal.depends_on:
                            goal.depends_on.append(dep_id)
                    goal.updated_at = datetime.now(UTC)
                    logger.info(
                        "Directive added dependencies to goal %s: %s",
                        d.goal_id,
                        d.depends_on,
                    )

            elif d.action == "fail":
                if d.goal_id:
                    await self.fail_goal(
                        d.goal_id,
                        evidence=EvidenceBundle(narrative=d.rationale or "Directive-fail"),
                        allow_retry=False,
                    )
                    logger.info("Directive marked goal %s as failed", d.goal_id)

            elif d.action == "complete":
                if d.goal_id:
                    await self.complete_goal(d.goal_id)
                    logger.info("Directive marked goal %s as completed", d.goal_id)

            elif d.action == "decompose":
                # Future work — log and skip
                logger.warning(
                    "Directive 'decompose' not implemented (goal %s): %s",
                    d.goal_id,
                    d.description,
                )

        except Exception:
            logger.warning(
                "Directive application failed (action=%s, goal_id=%s): %s",
                d.action,
                d.goal_id,
                d.description,
                exc_info=True,
            )

    return created_ids
```

**Dependencies**:
- Import `GoalDirective` from `soothe.protocols.planner`
- Import `EvidenceBundle` from `soothe.core.goal_engine.models`
- Use existing `create_goal`, `fail_goal`, `complete_goal` methods

### Step 2: _runner_autopilot_worker.py Changes

**Location**: `_runner_autopilot_worker.py`

**Changes**:

1. Add `_extract_reflection_directives()` helper:

```python
def _extract_reflection_directives(plan_result: PlanResult | None) -> list[GoalDirective]:
    """Extract goal_directives from PlanResult if Reflection populated them."""
    if plan_result is None:
        return []

    # Reflection attaches directives via planner.reflect()
    # Check decision field (from PlannerOutput)
    decision = getattr(plan_result, "decision", None)
    if decision is None:
        return []

    # GoalDirective may be on decision or directly on plan_result
    directives = getattr(decision, "goal_directives", None)
    if isinstance(directives, list):
        return directives

    return []
```

2. Modify `_goal_completion_chunk()` to accept directives:

```python
def _goal_completion_chunk(
    self,
    job: GoalDispatchEnvelope,
    *,
    outcome: str,
    plan_result: PlanResult | None,
    directives: list[GoalDirective] = [],  # NEW parameter
    error_text: str | None = None,
) -> StreamChunk:
    """Build the single terminal GoalCompletionChunk for job."""
    contribution = self._build_contribution(plan_result)
    payload: dict[str, Any] = {
        "type": _GOAL_COMPLETION_TYPE,
        "goal_id": job.goal_id,
        "outcome": outcome,
        "attempt": job.attempt,
        "context_contribution": contribution.model_dump(mode="json"),
        "goal_directives": [d.model_dump(mode="json") for d in directives],  # NEW
    }
    if plan_result is not None:
        payload["plan_result_status"] = getattr(plan_result, "status", None)
        payload["evidence_summary"] = getattr(plan_result, "evidence_summary", "")
    if error_text is not None:
        payload["error_text"] = error_text
    return _custom(payload)
```

3. Update `_run_single_autopilot_goal()` to extract and pass directives:

```python
# After StrangeLoop completes, before emitting completion chunk:
reflection_directives = _extract_reflection_directives(plan_result)

# Merge with proposal_directives (Phase C.3 will add this)
all_directives = reflection_directives

yield self._goal_completion_chunk(
    job,
    outcome=outcome,
    plan_result=plan_result,
    directives=all_directives,  # NEW parameter
)
```

### Step 3: Daemon-side Consumer

**Location**: `daemon/autopilot/service.py` or equivalent AutopilotService stream consumer

**Add to `_route_chunk()` or equivalent**:

```python
from soothe.protocols.planner import GoalDirective

# In chunk handling for goal_completion:
if chunk_type == "soothe.internal.autopilot.goal_completion":
    # Apply directives BEFORE outcome handling
    directives_data = payload.get("goal_directives", [])
    if directives_data:
        try:
            directives = [GoalDirective(**d) for d in directives_data]
            created_ids = await goal_engine.apply_directives(
                directives,
                source_goal_id=goal_id,
            )
            logger.info(
                "Applied %d directives from goal %s, created: %s",
                len(directives),
                goal_id,
                created_ids,
            )
        except Exception:
            logger.warning(
                "Failed to apply directives for goal %s",
                goal_id,
                exc_info=True,
            )

    # Then handle outcome (existing logic unchanged)
    ...
```

### Tests for Phase C.1

**File**: `tests/unit/core/goal_engine/test_apply_directives.py`

```python
@pytest.mark.asyncio
async def test_apply_directives_create():
    engine = GoalEngine()
    await engine.create_goal("parent goal", goal_id="g1")

    directives = [GoalDirective(action="create", description="subgoal", priority=60)]
    created = await engine.apply_directives(directives, source_goal_id="g1")

    assert len(created) == 1
    child = await engine.get_goal(created[0])
    assert child.parent_id == "g1"
    assert child.priority == 60

@pytest.mark.asyncio
async def test_apply_directives_adjust_priority():
    engine = GoalEngine()
    await engine.create_goal("test", goal_id="g1", priority=50)

    directives = [GoalDirective(action="adjust_priority", goal_id="g1", priority=80)]
    await engine.apply_directives(directives, source_goal_id="g1")

    goal = await engine.get_goal("g1")
    assert goal.priority == 80

@pytest.mark.asyncio
async def test_apply_directives_add_dependency():
    engine = GoalEngine()
    await engine.create_goal("dep", goal_id="dep1")
    await engine.create_goal("target", goal_id="g1")

    directives = [GoalDirective(action="add_dependency", goal_id="g1", depends_on=["dep1"])]
    await engine.apply_directives(directives, source_goal_id="g1")

    goal = await engine.get_goal("g1")
    assert "dep1" in goal.depends_on
```

---

## Phase C.2: Reflection Directive Extraction

Already covered in Step 2 of Phase C.1. No separate implementation needed.

---

## Phase C.3: Layer 2 Tools + ProposalQueue Wiring (Proactive Path)

### Files to Create

| File | Purpose |
|------|---------|
| `toolkits/proposal/__init__.py` | Package init |
| `toolkits/proposal/suggest_goal.py` | `suggest_goal` tool |
| `toolkits/proposal/add_finding.py` | `add_finding` tool |

### Files to Modify

| File | Change |
|------|--------|
| `core/loop/orchestrator/runtime_context.py` | Add `proposal_queue: ProposalQueue | None` field |
| `core/loop/engine/strange_loop.py` | Accept `proposal_queue` parameter, pass to LoopRuntimeContext |
| `core/runner/_runner_autopilot_worker.py` | Create queue, drain, convert proposals to directives |

### Step 1: Proposal Toolkit Package

**File**: `toolkits/proposal/suggest_goal.py`

```python
"""suggest_goal tool for proactive subgoal creation (RFC-204 Group C)."""

from __future__ import annotations

from typing import Any

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field


class SuggestGoalInput(BaseModel):
    """Input schema for suggest_goal tool."""

    description: str = Field(description="What the suggested goal should accomplish")
    priority: int = Field(default=50, ge=0, le=100, description="0-100, higher = more urgent")
    depends_on: list[str] = Field(default_factory=list, description="Goal IDs this depends on")
    rationale: str = Field(default="", description="Why this goal is needed")


class SuggestGoalTool(BaseTool):
    """Tool for suggesting new subgoals mid-execution."""

    name: str = "suggest_goal"
    description: str = "Suggest a new subgoal for the current goal's DAG. Use when you identify a prerequisite."
    args_schema: type[BaseModel] = SuggestGoalInput

    proposal_queue: Any = None  # ProposalQueue injected at runtime

    def _run(self, description: str, priority: int = 50, depends_on: list[str] = [], rationale: str = "") -> str:
        """Suggest a new subgoal."""
        if self.proposal_queue is None:
            return "Error: proposal_queue not available"

        from soothe.core.goal_engine.proposal_queue import Proposal

        self.proposal_queue.enqueue(
            Proposal(
                type="suggest_goal",
                goal_id="",  # Will be filled by runner with source goal
                payload={
                    "description": description,
                    "priority": priority,
                    "depends_on": depends_on,
                    "rationale": rationale,
                },
            )
        )
        return f"Suggested goal queued: '{description[:50]}...' (priority={priority})"

    async def _arun(self, description: str, priority: int = 50, depends_on: list[str] = [], rationale: str = "") -> str:
        """Async variant."""
        return self._run(description, priority, depends_on, rationale)
```

**File**: `toolkits/proposal/add_finding.py`

```python
"""add_finding tool for context projection (RFC-204 Group C)."""

from __future__ import annotations

from typing import Any

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field


class AddFindingInput(BaseModel):
    """Input schema for add_finding tool."""

    summary: str = Field(description="Brief description of the finding", max_length=2000)
    relevance_score: float = Field(default=0.7, ge=0.0, le=1.0, description="Relevance to goal")
    tags: list[str] = Field(default_factory=list, description="Categorization tags")


class AddFindingTool(BaseTool):
    """Tool for recording findings for context projection."""

    name: str = "add_finding"
    description: str = "Record a finding for context projection to child goals."
    args_schema: type[BaseModel] = AddFindingInput

    proposal_queue: Any = None  # ProposalQueue injected at runtime

    def _run(self, summary: str, relevance_score: float = 0.7, tags: list[str] = []) -> str:
        """Record a finding."""
        if self.proposal_queue is None:
            return "Error: proposal_queue not available"

        from soothe.core.goal_engine.proposal_queue import Proposal

        self.proposal_queue.enqueue(
            Proposal(
                type="add_finding",
                goal_id="",  # Will be filled by runner
                payload={
                    "summary": summary[:2000],
                    "relevance_score": relevance_score,
                    "tags": tags,
                },
            )
        )
        return f"Finding queued: '{summary[:50]}...' (relevance={relevance_score})"

    async def _arun(self, summary: str, relevance_score: float = 0.7, tags: list[str] = []) -> str:
        """Async variant."""
        return self._run(summary, relevance_score, tags)
```

### Step 2: LoopRuntimeContext Extension

**File**: `core/loop/orchestrator/runtime_context.py`

Add field:

```python
if TYPE_CHECKING:
    from soothe.core.goal_engine.proposal_queue import ProposalQueue

@dataclass
class LoopRuntimeContext:
    # ... existing fields ...
    proposal_queue: ProposalQueue | None = None  # RFC-204 Group C
```

### Step 3: StrangeLoop.run_with_progress() Parameter

**File**: `core/loop/engine/strange_loop.py`

Add parameter and pass through:

```python
async def run_with_progress(
    self,
    goal: str,
    thread_id: str,
    workspace: str | None = None,
    # ... existing parameters ...
    proposal_queue: ProposalQueue | None = None,  # NEW
) -> AsyncGenerator[tuple[str, Any], None]:
```

And in LoopRuntimeContext construction (line ~395):

```python
ctx = LoopRuntimeContext(
    # ... existing fields ...
    proposal_queue=proposal_queue,  # NEW
)
```

### Step 4: Runner Wiring

**File**: `core/runner/_runner_autopilot_worker.py`

1. Create queue at start of `_run_single_autopilot_goal`:

```python
from soothe.core.goal_engine.proposal_queue import ProposalQueue

async def _run_single_autopilot_goal(...) -> AsyncGenerator[StreamChunk, None]:
    proposal_queue = ProposalQueue()  # NEW

    # Pass to StrangeLoop
    async for event_type, event_data in strange_loop.run_with_progress(
        ...,
        proposal_queue=proposal_queue,  # NEW
    ):
        ...
```

2. Drain and convert after StrangeLoop completes:

```python
# Drain proposals and convert to directives
proposals = proposal_queue.drain()
proposal_directives = _proposals_to_directives(proposals, source_goal_id=job.goal_id)

# Merge with reflection directives
reflection_directives = _extract_reflection_directives(plan_result)
all_directives = reflection_directives + proposal_directives
```

3. Add helper:

```python
def _proposals_to_directives(
    proposals: list[Proposal],
    source_goal_id: str,
) -> list[GoalDirective]:
    """Convert ProposalQueue proposals to GoalDirectives."""
    from soothe.protocols.planner import GoalDirective

    directives = []
    for p in proposals:
        if p.type == "suggest_goal":
            directives.append(
                GoalDirective(
                    action="create",
                    description=p.payload.get("description", ""),
                    priority=p.payload.get("priority", 50),
                    parent_id=None,  # Defaults to source_goal_id in apply_directives
                    depends_on=p.payload.get("depends_on", []),
                    rationale=p.payload.get("rationale", ""),
                )
            )
        elif p.type == "add_finding":
            # Findings enrich context_contribution, not goal_directives
            # Phase C.4 can add extraction to contribution
            pass
    return directives
```

### Tests for Phase C.3

**File**: `tests/unit/toolkits/proposal/test_suggest_goal.py`

```python
import pytest
from soothe.toolkits.proposal.suggest_goal import SuggestGoalTool
from soothe.core.goal_engine.proposal_queue import ProposalQueue


def test_suggest_goal_enqueues():
    queue = ProposalQueue()
    tool = SuggestGoalTool(proposal_queue=queue)

    result = tool._run("Analyze dataset", priority=80)
    assert "Suggested goal queued" in result

    proposals = queue.drain()
    assert len(proposals) == 1
    assert proposals[0].type == "suggest_goal"
    assert proposals[0].payload["description"] == "Analyze dataset"
```

---

## Verification

Run `./scripts/verify_finally.sh` after each phase.

---

## Success Criteria

1. `GoalEngine.apply_directives()` handles all six actions
2. `GoalCompletionChunk.goal_directives` populated from Reflection
3. `suggest_goal` tool available in StrangeLoop execution
4. Integration test: tool → queue → chunk → apply → DAG shows subgoal

---

## Dependencies

- None beyond existing GoalEngine, Runner, StrangeLoop code

---

## Risks

| Risk | Mitigation |
|------|------------|
| Directive explosion | Cap at 10 per chunk; log warning |
| Tool can't access queue | Return error string; log warning |
| Circular deps created | `create_goal` already validates cycles |