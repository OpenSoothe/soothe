# IG-125: RFC-204 Autopilot Mode — Gap Closure

**Guide**: IG-125
**Title**: RFC-204 Autopilot Mode — Gap Closure
**Kind**: Gap Closure / Completion
**RFC**: [RFC-204](../specs/RFC-204-autopilot-mode.md) (Section 12: Gap Analysis)
**Created**: 2026-04-03
**Status**: Draft

---

## Summary

Closes all 12 remaining gaps in RFC-204 Autopilot Mode implementation. Gaps span across all 4 RFC phases: broken code, missing tools, missing logic, and missing integration.

## Gap Inventory

| # | Gap | Group | Phase | File(s) to Create/Modify |
|---|-----|-------|-------|--------------------------|
| 1 | `_send_autopilot_webhook()` undefined | A | 4 | Fix: `_runner_autonomous.py` |
| 12 | Autopilot config schema missing | F | 4 | Fix: `config.py` |
| 5 | Proposal queuing not implemented | C | 1 | New: `cognition/proposal_queue.py`, Modify: `implementation.py`, `_runner_autonomous.py` |
| 10 | WebSocket events not emitted | F | 3 | Modify: `_runner_autonomous.py`, daemon event filter |
| 2 | `get_world_info()` tool missing | B | 1 | New: `GetWorldInfoTool` in `tools/goals/implementation.py` |
| 3 | `search_memory()` tool missing | B | 1 | New: `SearchMemoryTool` in `tools/goals/implementation.py` |
| 4 | `add_finding()` tool missing | B | 1 | New: `AddFindingTool` in `tools/goals/implementation.py` |
| 6 | LLM-judged criticality placeholder | D | 2 | Modify: `cognition/criticality.py` |
| 7 | MUST confirmation not wired | D | 2 | Modify: `_runner_autonomous.py`, `autopilot_cmd.py` |
| 9 | File-based progress incomplete | E | 2 | Modify: `cognition/goal_engine.py` |
| 8 | Relationship auto-detection missing | D | 2 | New: `cognition/relationship_detector.py` |
| 11 | Dreaming goal anticipation missing | F | 4 | Modify: `cognition/dreaming.py` |

## Implementation Tasks

### Task 1: Add Autopilot Config Schema (Gap 12)

**Why first**: Unblocks webhook wiring (Gap 1) and provides config-driven values throughout.

**File**: `src/soothe/config.py`

Add `AutopilotConfig` Pydantic model:
```python
class AutopilotConfig(BaseModel):
    max_iterations: int = 50
    max_send_backs: int = 3
    max_parallel_goals: int = 3
    dreaming_enabled: bool = True
    dreaming_consolidation_interval: int = 300
    dreaming_health_check_interval: int = 60
    checkpoint_interval: int = 10
    scheduler_enabled: bool = True
    max_scheduled_tasks: int = 100
    webhooks: dict[str, str | None] = Field(default_factory=dict)
```

Add to `SootheConfig`:
```python
autopilot: AutopilotConfig = Field(default_factory=AutopilotConfig)
```

**Verification**: `config.autopilot` accessible, defaults work, YAML config overrides work.

### Task 2: Fix `_send_autopilot_webhook()` (Gap 1)

**File**: `src/soothe/core/runner/_runner_autonomous.py`

Add method to `AutonomousMixin`:
```python
async def _send_autopilot_webhook(self, event_type: str, payload: dict) -> None:
    """Send autopilot webhook notification."""
    try:
        from soothe.cognition.webhooks import WebhookService
        from soothe.config import SOOTHE_HOME

        webhook_url = None
        if self._config and hasattr(self._config, "autopilot"):
            webhook_url = self._config.autopilot.webhooks.get(f"on_{event_type}")

        if not webhook_url:
            return

        service = WebhookService(soothe_home=str(SOOTHE_HOME))
        await service.send_webhook(event_type, payload)
    except Exception:
        logger.debug("Webhook failed for %s", event_type, exc_info=True)
```

Add call sites:
- `goal_failed` event (after `fail_goal` in exception handler)
- `dreaming_entered` (before `dreaming.run()`)
- `dreaming_exited` (after dreaming exits, before returning)

**Verification**: Method exists, all 4 call sites wired, no-op when webhook URL is null.

### Task 3: Implement Proposal Queue (Gap 5)

**New file**: `src/soothe/cognition/proposal_queue.py`

```python
@dataclass
class Proposal:
    type: str  # "report_progress" | "suggest_goal" | "add_finding" | "flag_blocker"
    goal_id: str
    payload: dict
    timestamp: datetime

class ProposalQueue:
    def enqueue(self, proposal: Proposal) -> None
    def drain(self) -> list[Proposal]
    def is_empty(self) -> bool
```

**Modify**: `src/soothe/tools/goals/implementation.py`

Update `ReportProgressTool`, `SuggestGoalTool`, `FlagBlockerTool` to accept an optional `proposal_queue` parameter and write to it instead of just logging. Add `AddFindingTool` (Gap 4).

**Modify**: `src/soothe/core/runner/_runner_autonomous.py`

- Add `_proposal_queue: ProposalQueue` to `AutonomousMixin`
- Initialize queue at start of each goal execution
- Add `_process_proposals()` method called before `complete_goal`:
  - `report_progress` → update goal progress
  - `suggest_goal` → run through criticality check (see Task 6)
  - `add_finding` → append to goal's findings
  - `flag_blocker` → transition goal to blocked state
- Clear queue after processing

### Task 4: Add Missing Layer 2 Tools (Gaps 2, 3, 4)

**File**: `src/soothe/tools/goals/implementation.py`

Add three new tool classes:

1. `GetWorldInfoTool`: Returns current workspace state (active goal, iteration count, subagents, workspace path)
2. `SearchMemoryTool`: Delegates to `self.memory.recall(query, limit)` — requires `memory_protocol` parameter
3. `AddFindingTool`: Writes finding to proposal queue — requires `proposal_queue` parameter

Update `create_layer2_tools()` to return the new tools.

### Task 5: Wire WebSocket Events (Gap 10)

**File**: `src/soothe/core/runner/_runner_autonomous.py`

Add `_custom()` calls for missing events at appropriate points:
- `soothe.autopilot.status_changed` — on state transitions
- `soothe.autopilot.goal_created` — when goal created (may already exist)
- `soothe.autopilot.goal_progress` — when progress reported
- `soothe.autopilot.goal_completed` — when goal completed (may already exist)
- `soothe.autopilot.dreaming_entered` — before `dreaming.run()`
- `soothe.autopilot.dreaming_exited` — after dreaming exits

**File**: Daemon WebSocket broadcast — verify autopilot event types are in whitelist.

### Task 6: LLM-Judged Criticality (Gap 6)

**File**: `src/soothe/cognition/criticality.py`

Add async function `_evaluate_with_llm(description, priority, model)`:
- Build prompt asking LLM to evaluate goal description for risk
- Criteria: external systems, security, cost, data modification, irreversibility, dependency breadth
- Parse JSON response for `risk_level` and `reasons`
- Update `evaluate_criticality()` to accept optional `model` parameter and call `_evaluate_with_llm`

### Task 7: Wire MUST Confirmation (Gap 7)

**File**: `src/soothe/core/runner/_runner_autonomous.py`

In `_process_proposals()`, when handling `suggest_goal`:
1. Call `evaluate_criticality(description, priority, use_llm=True, model=self._model)`
2. If "must": write to pending confirmations JSON file, send via channel outbox
3. If "should"/"nice": create goal via `goal_engine.create_goal()`

**New file**: `SOOTHE_HOME/autopilot/pending_confirmations.json` (created on first MUST goal)

**Modify**: `src/soothe/ux/cli/commands/autopilot_cmd.py`

Update `approve` and `reject` commands to read/write the pending confirmations file.

### Task 8: File-Based Progress Tracking (Gap 9)

**File**: `src/soothe/cognition/goal_engine.py`

Add `_append_goal_progress(goal_id, entry: str)`:
- Open goal's GOAL.md file
- Find or create `## Progress` section
- Append `[{timestamp}] {entry}` line

Call from:
- When `ReportProgressTool` processes a proposal
- When goal state changes (status updates)

### Task 9: Relationship Auto-Detection (Gap 8)

**New file**: `src/soothe/cognition/relationship_detector.py`

```python
def detect_relationships(completed_goal: Goal, all_goals: list[Goal]) -> list[Relationship]
```

Detection logic:
- **`informs`**: Text overlap in descriptions/findings, shared tags
- **`conflicts_with`**: Both reference same resource paths with write intent
- **`depends_on`**: Goal B description references goal A's output artifacts

Confidence scoring: 0.0-1.0, >=0.8 auto-apply, 0.5-0.8 flag for review.

**Modify**: `src/soothe/core/runner/_runner_autonomous.py`

Call `detect_relationships()` after goal completion, before marking complete. Apply high-confidence relationships automatically, emit `relationship_detected` events.

### Task 10: Dreaming Goal Anticipation (Gap 11)

**File**: `src/soothe/cognition/dreaming.py`

Add `_anticipate_goals()` method:
- Read recently completed goals from goal engine
- Analyze patterns (text similarity, recurring themes)
- If LLM model available, generate candidate future tasks
- Write markdown files to `SOOTHE_HOME/autopilot/draft_goals/`
- If no LLM, use simple template based on completed goal patterns

Call during dreaming mode loop.

## Verification

After all tasks:
1. Run `./scripts/verify_finally.sh` — all checks must pass
2. Test autopilot mode end-to-end: submit goal, observe execution, verify tools work
3. Test dreaming mode: complete all goals, verify dreaming enters and goal anticipation runs
4. Test webhook: configure test webhook URL, verify notifications sent
5. Test MUST confirmation: propose a high-risk goal, verify confirmation flow

## Dependencies

- Tasks 1+2 unblock webhook wiring
- Task 3 unblocks Tasks 4, 7 (tools need queue, confirmation needs queue processing)
- Task 5 is independent
- Tasks 6+7 are coupled (LLM criticality used by MUST confirmation)
- Task 8 is independent
- Task 9 is independent
- Task 10 is independent
