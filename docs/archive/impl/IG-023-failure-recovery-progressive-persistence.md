# IG-023: Failure Recovery, Progressive Persistence, and Artifact Storage

**Implements**: RFC-202
**Status**: Draft
**Created**: 2026-03-18

## Overview

Implements progressive checkpointing after each step/goal, structured
artifact storage in `$SOOTHE_HOME/runs/`, crash recovery via
`RunArtifactStore.load_checkpoint()` + `GoalEngine.restore_from_snapshot()`,
daemon restart detection, cross-validated final report synthesis, and
enhanced reflection with dependency awareness.

Hard-cut changes: `save_state`/`load_state` removed from DurabilityProtocol,
`threads/` directory removed, no backward compatibility code.

## Phase 1: DurabilityProtocol Cleanup

Remove `save_state` and `load_state` from:

- `protocols/durability.py` -- remove method definitions
- `backends/durability/base.py` -- remove implementations
- `core/runner.py` lines 615-622, 1587-1592 -- delete these blocks (replaced later)

## Phase 2: RunArtifactStore

New file: `src/soothe/core/artifact_store.py`

### Data Models

```python
class ArtifactEntry(BaseModel):
    """A single artifact tracked in the run manifest."""
    path: str
    source: Literal["produced", "reference"]
    original_path: str = ""
    tool_name: str = ""
    step_id: str = ""
    goal_id: str = ""
    size_bytes: int = 0

class RunManifest(BaseModel):
    """Index of all artifacts and metadata for a run."""
    version: int = 1
    thread_id: str
    created_at: str
    updated_at: str
    query: str = ""
    mode: Literal["single_pass", "autonomous"] = "single_pass"
    status: Literal["in_progress", "completed", "failed"] = "in_progress"
    goals: list[str] = Field(default_factory=list)
    artifacts: list[ArtifactEntry] = Field(default_factory=list)
```

### RunArtifactStore Class

```python
class RunArtifactStore:
    """Manages $SOOTHE_HOME/runs/{thread_id}/ directory."""

    def __init__(self, thread_id: str, soothe_home: str = SOOTHE_HOME) -> None:
        self._thread_id = thread_id
        self._run_dir = Path(soothe_home).expanduser() / "runs" / thread_id
        self._run_dir.mkdir(parents=True, exist_ok=True)
        self._manifest = RunManifest(
            thread_id=thread_id,
            created_at=datetime.now(UTC).isoformat(),
            updated_at=datetime.now(UTC).isoformat(),
        )

    @property
    def run_dir(self) -> Path: ...

    @property
    def conversation_log_path(self) -> Path:
        return self._run_dir / "conversation.jsonl"

    def ensure_step_dir(self, goal_id: str, step_id: str) -> Path:
        d = self._run_dir / "goals" / goal_id / "steps" / step_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def write_step_report(self, goal_id: str, step: PlanStep, duration_ms: int) -> None:
        step_dir = self.ensure_step_dir(goal_id, step.id)
        report = StepReport(
            step_id=step.id, description=step.description,
            status=step.status if step.status in ("completed","failed") else "skipped",
            result=step.result or "", duration_ms=duration_ms,
            depends_on=step.depends_on,
        )
        (step_dir / "report.json").write_text(report.model_dump_json(indent=2))
        md = f"# Step: {step.description}\n\n"
        md += f"**Status**: {report.status}  \n**Duration**: {duration_ms}ms\n\n"
        if report.depends_on:
            md += f"**Depends on**: {', '.join(report.depends_on)}\n\n"
        md += f"## Result\n\n{report.result}\n"
        (step_dir / "report.md").write_text(md)

    def write_goal_report(self, report: GoalReport) -> None:
        goal_dir = self._run_dir / "goals" / report.goal_id
        goal_dir.mkdir(parents=True, exist_ok=True)
        (goal_dir / "report.json").write_text(report.model_dump_json(indent=2))
        md = f"# Goal: {report.description}\n\n"
        md += f"**Status**: {report.status}  \n**Duration**: {report.duration_ms}ms\n\n"
        md += f"## Summary\n\n{report.summary}\n"
        if report.reflection_assessment:
            md += f"\n## Reflection\n\n{report.reflection_assessment}\n"
        if report.cross_validation_notes:
            md += f"\n## Cross-Validation\n\n{report.cross_validation_notes}\n"
        if report.step_reports:
            md += "\n## Steps\n\n"
            for sr in report.step_reports:
                icon = "+" if sr.status == "completed" else "x"
                md += f"- [{icon}] **{sr.step_id}**: {sr.description} ({sr.status})\n"
        (goal_dir / "report.md").write_text(md)

    def record_artifact(self, entry: ArtifactEntry) -> None:
        self._manifest.artifacts.append(entry)
        self.save_manifest()

    def save_checkpoint(self, envelope: dict[str, Any]) -> None:
        """Write checkpoint atomically (tmp + rename)."""
        target = self._run_dir / "checkpoint.json"
        tmp = target.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(envelope, default=str, indent=2))
        tmp.rename(target)

    def load_checkpoint(self) -> dict[str, Any] | None:
        target = self._run_dir / "checkpoint.json"
        if not target.exists():
            return None
        return json.loads(target.read_text())

    def save_manifest(self) -> None:
        self._manifest.updated_at = datetime.now(UTC).isoformat()
        target = self._run_dir / "manifest.json"
        target.write_text(self._manifest.model_dump_json(indent=2))

    def load_manifest(self) -> RunManifest | None:
        target = self._run_dir / "manifest.json"
        if not target.exists():
            return None
        return RunManifest.model_validate_json(target.read_text())
```

## Phase 3: Protocol Model Updates (`protocols/planner.py`)

- Add `CheckpointEnvelope` model
- `StepReport`: add `depends_on: list[str]`
- `GoalReport`: add `reflection_assessment: str`, `cross_validation_notes: str`
- `Reflection`: add `blocked_steps: list[str]`, `failed_details: dict[str, str]`

## Phase 4: Runner Integration (`core/runner.py`)

### 4.1 Artifact store initialization

Create `RunArtifactStore` lazily in `_pre_stream` when `thread_id` is
resolved.  Store as `self._artifact_store`.

### 4.2 `_save_checkpoint()` helper

```python
async def _save_checkpoint(
    self, state: RunnerState, *, user_input: str,
    mode: str = "single_pass", status: str = "in_progress",
) -> None:
    if not self._artifact_store:
        return
    plan_data = state.plan.model_dump(mode="json") if state.plan else None
    completed = [
        s.id for s in (state.plan.steps if state.plan else [])
        if s.status == "completed"
    ]
    goals_data = self._goal_engine.snapshot() if self._goal_engine else []
    envelope = {
        "version": 1,
        "timestamp": datetime.now(UTC).isoformat(),
        "mode": mode, "last_query": user_input,
        "thread_id": state.thread_id,
        "goals": goals_data, "active_goal_id": None,
        "plan": plan_data, "completed_step_ids": completed,
        "total_iterations": 0, "status": status,
    }
    try:
        self._artifact_store.save_checkpoint(envelope)
    except Exception:
        logger.debug("Checkpoint save failed", exc_info=True)
```

### 4.3 Insert checkpoints

- After each step in `_run_step_loop`: call `_save_checkpoint` + `write_step_report`
- After each goal in `_execute_autonomous_goal`: call `_save_checkpoint` + `write_goal_report`
- At end of `_run_autonomous` and `_post_stream`: `_save_checkpoint(status="completed")`

### 4.4 Remove old `save_state` calls

Delete the `durability.save_state(...)` blocks at runner.py:615-622 and 1587-1592.

## Phase 5: Recovery on Resume (`core/runner.py`)

### `_try_recover_checkpoint()`

```python
async def _try_recover_checkpoint(self, state: RunnerState) -> bool:
    if not self._artifact_store:
        return False
    loaded = self._artifact_store.load_checkpoint()
    if not loaded or loaded.get("status") != "in_progress":
        return False
    if loaded.get("version", 0) < 1:
        return False

    goals_data = loaded.get("goals", [])
    if goals_data and self._goal_engine:
        self._goal_engine.restore_from_snapshot(goals_data)

    plan_data = loaded.get("plan")
    completed_ids = set(loaded.get("completed_step_ids", []))
    if plan_data:
        plan = Plan.model_validate(plan_data)
        for step in plan.steps:
            if step.id in completed_ids:
                step.status = "completed"
        state.plan = plan
        self._current_plan = plan

    return True
```

Called in `_pre_stream` after `context.restore()`.

## Phase 6: CLI Hard-Cut

### 6.1 `cli/main.py`

- Delete `migrate_sessions_to_threads()` function and its call
- Thread deletion: remove `runs/{thread_id}/` directory instead of JSONL file

### 6.2 `cli/tui_app.py`

- Remove `sessions/threads` fallback logic
- ThreadLogger uses `runs/{thread_id}/` (from `artifact_store.conversation_log_path`)

### 6.3 `cli/daemon.py`

- ThreadLogger dir passed from `RunArtifactStore.conversation_log_path`
- Add `_detect_incomplete_threads()`: scan `runs/*/checkpoint.json`

### 6.4 `cli/thread_logger.py`

- Default `thread_dir` parameter accepts explicit path from RunArtifactStore

## Phase 7: Cross-Validated Final Report

`_synthesize_root_goal_report()` in `runner.py`:

```python
async def _synthesize_root_goal_report(
    self, goal: Goal, step_reports: list[StepReport],
    child_goal_reports: list[GoalReport],
) -> str:
    parts = [f"Goal: {goal.description}\n"]
    if step_reports:
        parts.append("Step results:")
        for r in step_reports:
            icon = "+" if r.status == "completed" else "x"
            parts.append(f"  [{icon}] {r.step_id}: {r.description}\n      Result: {r.result[:400]}")
    if child_goal_reports:
        parts.append("\nChild goal reports:")
        for cr in child_goal_reports:
            parts.append(f"  Goal {cr.goal_id}: {cr.description}\n    Summary: {cr.summary[:300]}")
    synthesis_prompt = "\n".join(parts) + """

Produce a brief synthesis (3-5 sentences):
1. Summarize what was accomplished across all steps/goals.
2. Cross-validate: note any contradictions or conflicting information.
3. Identify gaps: what information is missing or incomplete?
4. State confidence level: high/medium/low based on source agreement.
"""
    try:
        if self._planner and hasattr(self._planner, "_invoke"):
            return (await self._planner._invoke(synthesis_prompt))[:2000]
    except Exception:
        logger.debug("LLM synthesis failed, using heuristic", exc_info=True)

    completed = [r for r in step_reports if r.status == "completed"]
    failed = [r for r in step_reports if r.status == "failed"]
    lines = [f"Completed {len(completed)}/{len(step_reports)} steps."]
    if failed:
        lines.append(f"Failed: {', '.join(r.step_id for r in failed)}.")
    if completed:
        lines.append("Results: " + "; ".join(r.description[:50] for r in completed[:5]))
    return " ".join(lines)
```

## Phase 8: Enhanced Reflection

All planners (Direct, Claude, Subagent):

```python
async def reflect(self, plan: Plan, step_results: list[StepResult]) -> Reflection:
    completed = sum(1 for r in step_results if r.success)
    failed_list = [r for r in step_results if not r.success]
    total = len(plan.steps)

    failed_ids = {r.step_id for r in failed_list}
    blocked, direct_failed = [], []
    for r in failed_list:
        step = next((s for s in plan.steps if s.id == r.step_id), None)
        if step and any(dep in failed_ids for dep in step.depends_on):
            blocked.append(r.step_id)
        else:
            direct_failed.append(r.step_id)

    failed_details = {r.step_id: (r.output[:200] if r.output else "no output") for r in failed_list}

    if failed_list:
        parts = [f"{completed}/{total} steps completed, {len(failed_list)} failed"]
        if direct_failed:
            parts.append(f"Directly failed: {direct_failed}")
        if blocked:
            parts.append(f"Blocked by dependencies: {blocked}")
        return Reflection(
            assessment=". ".join(parts), should_revise=True,
            feedback=f"Failed steps: {direct_failed}. Blocked: {blocked}.",
            blocked_steps=blocked, failed_details=failed_details,
        )
    return Reflection(
        assessment=f"{completed}/{total} steps completed successfully",
        should_revise=False, feedback="",
    )
```

## Phase 9: Configuration

Add `RecoveryConfig` to `config.py`, add to `ExecutionConfig`:

```python
class RecoveryConfig(BaseModel):
    progressive_checkpoints: bool = True
    auto_resume_on_start: bool = False
```

Update `config/config.yml`.

## Testing Checklist

- [ ] RunArtifactStore: create, write reports, save/load checkpoint, manifest
- [ ] Checkpoint round-trip: save envelope, load, verify fields
- [ ] Recovery: pre-completed steps restored, StepScheduler skips them
- [ ] Goal DAG recovery: restore_from_snapshot with depends_on preserved
- [ ] Enhanced reflection: blocked vs direct failed distinction
- [ ] Model fields: StepReport.depends_on, GoalReport.reflection_assessment, etc.
- [ ] CLI: ThreadLogger uses runs/ path, thread deletion removes run dir

## Files to Modify

| File | Changes |
|------|---------|
| `protocols/durability.py` | Remove `save_state`, `load_state` |
| `backends/durability/base.py` | Remove `save_state`, `load_state` |
| `core/artifact_store.py` | NEW: RunArtifactStore, RunManifest, ArtifactEntry |
| `protocols/planner.py` | CheckpointEnvelope, StepReport.depends_on, GoalReport fields, Reflection fields |
| `core/runner.py` | Artifact store integration, checkpoints, recovery, synthesis |
| `cli/daemon.py` | Incomplete thread detection, ThreadLogger path |
| `cli/main.py` | Delete migration, update thread deletion |
| `cli/tui_app.py` | Remove sessions/threads fallback |
| `cli/thread_logger.py` | Accept explicit log path |
| `cognition/planning/direct.py` | Enhanced `reflect()` |
| `cognition/planning/claude.py` | Enhanced `reflect()` |
| `cognition/planning/subagent.py` | Enhanced `reflect()` |
| `config.py` | RecoveryConfig |
| `config/config.yml` | execution.recovery section |
