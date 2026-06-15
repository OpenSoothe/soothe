# IG-625: ContextEngine and AutopilotMonitor Unification

**RFC**: 625
**Title**: AutopilotMonitor as ContextEngine Monitor Submodule — GoalEngine Deletion
**Created**: 2026-06-15
**Updated**: 2026-06-15
**Status**: In Progress

---

## Overview

This IG tracks implementation of RFC-625: unifying goal management under ContextEngine, deleting GoalEngine, and introducing AutopilotMonitor as a proactive DAG monitoring submodule.

---

## Implementation Phases

| Phase | Scope | Status | Estimated |
|-------|-------|--------|-----------|
| 1 | Relocate `soothe.context` → `soothe.foundation.context` | Done | 2 days |
| 2 | Enhance GoalNode with Goal fields, add CE API methods | Done | 2 days |
| 3 | Delete GoalEngine, migrate BackoffReasoner | Done | 3 days |
| 4 | Implement AutopilotMonitor (Verifier, Intake, Dreaming) | Pending | 5 days |
| 5 | Implement TUI GoalDAGCard, mode switch logic | Pending | 3 days |
| 6 | Integration tests, verify_finally.sh | In Progress | 2 days |

### Phase 1 Completion Summary

**Completed:** 2026-06-15

**Files created:**
- `foundation/context/__init__.py`, `models.py`, `engine.py`, `ledger.py`, `projection.py`, `semantic.py`
- `foundation/context/persistence/__init__.py`, `base.py`, `file_backend.py`, `sqlite_backend.py`, `pgsql_backend.py`
- `foundation/context/planning/__init__.py`, `models.py`, `completion.py`, `step_planner.py`, `goal_planner.py`, `scheduling.py`

**Import updates:**
- All internal imports in foundation/context updated to self-referential paths
- All external imports updated (config, foundation/loop/*)
- All test imports updated (unit + integration)

**Old location:** `soothe.context` directory deleted (user requested removal).

**Tests:** 278 passed (252 unit + 26 integration), lint passes.

### Phase 2 Completion Summary

**Completed:** 2026-06-15

**GoalNode enhancement (RFC-625):**

Added fields migrated from Goal model (`autopilot/engine/models.py`):
- `retry_count`, `max_retries`, `send_back_count`, `max_send_backs` (RFC-204)
- `attempts_after_crash` (RFC-222 H4)
- `source_file`, `workspace` (RFC-222)
- `report` (serialized GoalReport)
- `pending_clarification` (RFC-622)
- `guidance_accumulated` (RFC-228)

Added new dreaming fields:
- `topic` — Topic tag for cross-loop dreaming
- `findings` — Key findings from goal execution
- `distilled` — Whether goal has been distilled

Added `BLOCKED_STATES` constant.

**GoalStepDAG new methods:**
- `remove_goal(goal_id)` — Remove goal with dependent validation
- `merge_goals(goal_ids, merged_description)` — Merge multiple goals
- `is_dag_complete()` — Check if all goals in terminal states
- `get_goals_by_status(status)` — Filter by status
- `get_goal_dependents(goal_id)` — Get dependent goal IDs
- `update_dependencies(goal_id, depends_on)` — Update deps for mode switch

**ContextEngine new methods:**
- `remove_goal()`, `merge_goals()`, `is_dag_complete()`, `get_goals_by_status()`, `get_goal_dependents()`, `update_dependencies()`
- `record_episodic_memory()`, `get_episodic_memory()` — Dreaming support

**New model:**
- `EpisodeSummary` — Distilled episodic memory from goal execution

**Tests:** 278 passed, lint passes.

### Phase 3 Completion Summary

**Completed:** 2026-06-15

**Files deleted:**
- `foundation/autopilot/engine/engine.py` (1821 lines) — GoalEngine deleted
- `foundation/autopilot/engine/file_lock_registry.py` (270 lines) — FileLockRegistry deleted
- `foundation/autopilot/engine/backoff_reasoner.py` (232 lines) — Migrated to monitor/

**Goal class deleted from models.py:**
- Removed Goal class entirely
- Fields migrated to GoalNode in `foundation/context/models.py`

**ContextEngine enhanced with GoalEngine methods:**
- `peek_ready_goals(limit)` — Scheduler read-only query (renamed from `ready_goals`)
- `claim_goal(goal_id, loop_id)` — Atomic dispatch claim (sync, not async)
- `send_back_goal(goal_id, reason)` — RFC-204 consensus send-back
- `validate_goal(goal_id)` — RFC-204 acceptance
- `reactivate_goal(goal_id)` — RFC-204 resume
- `check_reactivated_goals()` — Auto-reactivate on deps resolved
- `apply_directives(directives, source_goal_id)` — RFC-204 Group C
- `mark_awaiting_clarification()` — RFC-622 pause
- `answer_clarification()` — RFC-622 resume
- `absorb_guidance()` — RFC-228 LOR guidance

**AutopilotService migrated:**
- Constructor signature changed: `_goal_engine: GoalEngine` → `_ce: ContextEngine`
- Added `_monitor: AutopilotMonitor | None` parameter
- Removed FileLockRegistry code (`_release_goal_locks`, loop file release)
- All `_goal_engine` calls replaced with `_ce` calls
- Return types changed from `Goal` to `GoalNode`

**Daemon core.py migrated:**
- Imports ContextEngine, AutopilotMonitor instead of GoalEngine
- Creates ContextEngine + AutopilotMonitor instead of GoalEngine

**Runner references removed:**
- Deleted `resolve_goal_engine()` from `_resolver_tools.py`
- Removed `_goal_engine` field from SootheRunner

**Test files deleted:**
- `tests/unit/core/goal_engine/` directory (10 files)
- `tests/integration/core/goal_engine/` directory (1 file)
- `tests/unit/middleware/test_file_lock.py`

**Test files updated:**
- `test_submit_task.py` — Uses ContextEngine
- `test_cancel_goal.py` — Uses ContextEngine
- `test_real_dispatch.py` — Uses ContextEngine
- `test_subscribe_to_bus.py` — Uses ContextEngine
- `test_deadline_monitor.py` — Uses ContextEngine
- `test_consensus_dispatch.py` — Uses ContextEngine
- `test_worker_pool.py` — Uses GoalNode
- `test_context_projector.py` — Uses GoalNode
- `test_relationship_detector.py` — Uses GoalNode

**relationship_detector.py updated:**
- Import changed from `Goal` (engine/models) to `GoalNode` (context/models)
- Function signatures updated: `GoalNode` instead of `Goal`

**Export updates:**
- `foundation/autopilot/__init__.py` — Removed GoalEngine, Goal exports; added AutopilotMonitor
- `foundation/__init__.py` — Removed GoalEngine export; added AutopilotMonitor (lazy)
- `foundation/autopilot/engine/__init__.py` — Removed GoalEngine, FileLockRegistry, Goal exports

**Status:** Core migration complete. Tests require additional fixes:
- `test_goal_step_dag.py`, `test_ig624_3_planning_submodule.py` — `ready_goals` → `peek_ready_goals` renaming
- GoalNode validation errors — `submit_task()` kwargs mapping to GoalNode fields
- `claim_goal` async/sync signature change in GoalScheduler tests

---

## Phase 1: Module Relocation

### Files to move

Source: `packages/soothe/src/soothe/context/`
Destination: `packages/soothe/src/soothe/foundation/context/`

| File | Action |
|------|--------|
| `__init__.py` | Move + update imports |
| `models.py` | Move |
| `engine.py` | Move + update internal imports |
| `ledger.py` | Move |
| `projection.py` | Move + update internal imports |
| `semantic.py` | Move |
| `persistence/__init__.py` | Move + update imports |
| `persistence/base.py` | Move + update imports |
| `persistence/file_backend.py` | Move + update imports |
| `persistence/sqlite_backend.py` | Move + update imports |
| `persistence/pgsql_backend.py` | Move + update imports |
| `planning/__init__.py` | Move + update imports |
| `planning/models.py` | Move |
| `planning/completion.py` | Move |
| `planning/step_planner.py` | Move + update imports |
| `planning/goal_planner.py` | Move + update imports |
| `planning/scheduling.py` | Move + update imports |

### External import updates

Files with `from soothe.context import` (move to `soothe.foundation.context`):

| File | Current import | New import |
|------|---------------|------------|
| `config/models.py` | `from soothe.context.projection import ProjectionConfig` | `from soothe.foundation.context.projection import ProjectionConfig` |
| `foundation/loop/planning/planner.py` | `from soothe.context.planning.completion import` | `from soothe.foundation.context.planning.completion import` |
| `foundation/loop/planning/manager.py` | `from soothe.context.planning.completion import` | `from soothe.foundation.context.planning.completion import` |
| `foundation/loop/prompts/user_message.py` | `from soothe.context.projection import ContextBundle` | `from soothe.foundation.context.projection import ContextBundle` |
| `foundation/loop/prompts/builder.py` | `from soothe.context.projection import ContextBundle` | `from soothe.foundation.context.projection import ContextBundle` |
| `foundation/loop/engine/strange_loop.py` | `from soothe.context.engine import ContextEngine` | `from soothe.foundation.context.engine import ContextEngine` |
| `foundation/loop/engine/context_adapters.py` | `from soothe.context.engine import ContextEngine` | `from soothe.foundation.context.engine import ContextEngine` |
| `foundation/loop/orchestrator/nodes/record_iteration.py` | `from soothe.context.models import StepExecution` | `from soothe.foundation.context.models import StepExecution` |
| `foundation/loop/orchestrator/nodes/goal_completion.py` | `from soothe.context.planning.models import` | `from soothe.foundation.context.planning.models import` |

### Test imports

Update all test files in `packages/soothe/tests/unit/context/` and `packages/soothe/tests/integration/context/` to use new import path.

### Deprecation shim

Create `packages/soothe/src/soothe/context/__init__.py` with deprecation warning:

```python
"""Deprecated: use soothe.foundation.context instead."""
import warnings
warnings.warn(
    "soothe.context is deprecated. Use soothe.foundation.context instead.",
    DeprecationWarning,
    stacklevel=2,
)
from soothe.foundation.context import *  # noqa: F401, F403
```

---

## Phase 2: GoalNode Enhancement

### Fields to add to GoalNode (from Goal model)

In `foundation/context/models.py`:

```python
# Retry/backoff (from Goal)
retry_count: int = 0
max_retries: int = 2
send_back_count: int = 0
max_send_backs: int = 3
attempts_after_crash: int = 0

# Workspace/source (from Goal)
source_file: str | None = None
workspace: str | None = None
report: GoalReport | None = None
pending_clarification: dict[str, Any] | None = None
guidance_accumulated: list[dict[str, Any]] = []

# Dreaming (NEW)
topic: str | None = None
findings: list[str] = []
distilled: bool = False
```

### CE API additions

In `foundation/context/engine.py`:

- `remove_goal(goal_id) -> bool`
- `merge_goals(goal_ids, merged_description) -> GoalNode`
- `is_dag_complete() -> bool`
- `get_goals_by_status(status) -> list[GoalNode]`
- `get_goal_dependents(goal_id) -> list[str]`
- `update_dependencies(goal_id, depends_on) -> None`
- `record_episodic_memory(episodes) -> None`
- `get_episodic_memory(limit) -> list[EpisodeSummary]`

---

## Phase 3: GoalEngine Deletion

### Files to delete

- `foundation/autopilot/engine/engine.py` (~1821 lines)
- `foundation/autopilot/engine/file_lock_registry.py`

### Files to migrate

- `foundation/autopilot/engine/backoff_reasoner.py` → `foundation/autopilot/monitor/backoff_reasoner.py`

### Files to keep (other components)

- `foundation/autopilot/engine/models.py` — Keep `Goal` temporarily for migration reference
- `foundation/autopilot/engine/discovery.py`
- `foundation/autopilot/engine/scheduled_tasks.py`
- `foundation/autopilot/engine/proposal_queue.py`
- `foundation/autopilot/engine/dreaming.py` — Will be superseded by DreamingCoordinator
- `foundation/autopilot/engine/webhooks.py`

---

## Phase 4: AutopilotMonitor Implementation

### New files

| File | Purpose |
|------|---------|
| `foundation/autopilot/monitor/__init__.py` | Public API |
| `foundation/autopilot/monitor/monitor.py` | AutopilotMonitor class |
| `foundation/autopilot/monitor/goal_dag_verifier.py` | GoalDAGVerifier coordinator |
| `foundation/autopilot/monitor/verifier_reasoner.py` | DagVerificationReasoner (LLM) |
| `foundation/autopilot/monitor/verifier_prompts.py` | LLM prompt templates |
| `foundation/autopilot/monitor/goal_intake_handler.py` | GoalIntakeHandler |
| `foundation/autopilot/monitor/dreaming_coordinator.py` | DreamingCoordinator |
| `foundation/autopilot/monitor/dreaming_reasoner.py` | DreamingDistillationReasoner (LLM) |
| `foundation/autopilot/monitor/dreaming_prompts.py` | LLM prompt templates |
| `foundation/autopilot/monitor/dreaming_handlers/__init__.py` | Handler exports |
| `foundation/autopilot/monitor/dreaming_handlers/episodic_handler.py` | Episodic mode |
| `foundation/autopilot/monitor/dreaming_handlers/procedure_handler.py` | Procedure mode |
| `foundation/autopilot/monitor/dreaming_handlers/semantic_handler.py` | Semantic mode |
| `foundation/autopilot/monitor/dreaming_handlers/profile_handler.py` | Profile mode |
| `foundation/autopilot/monitor/backoff_reasoner.py` | Migrated from GoalEngine |
| `foundation/autopilot/monitor/models.py` | Monitor-specific models |

---

## Phase 5: TUI and Mode Switch

### TUI GoalDAGCard

File: `packages/soothe-cli/src/soothe_cli/tui/widgets/goal_dag_card.py`

### Mode switch logic

File: `foundation/autopilot/service.py` — Update for toggle_autopilot()

---

## Verification

Run `./scripts/verify_finally.sh` after each phase.

---

## Notes

- All CE mutations go through public APIs (no direct `_dag` access)
- StrangeLoop remains pure execution unit (no DAG knowledge)
- RFC-222 components (WorkerPool, WorkspaceReservation) unchanged