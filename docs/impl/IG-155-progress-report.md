# IG-155 Progress Report: Autopilot Goal Discovery Implementation

**ID**: IG-155  
**Status**: 🔄 IN PROGRESS (Phase 1 Complete)  
**Date**: 2026-04-12  
**Priority**: P1 (High - Missing Feature)

---

## ✅ **Phase 1: Core Discovery Modules COMPLETE**

### 1. Goal Discovery Module (`src/soothe/cognition/goal_engine/discovery.py`)
**CREATED**: 304 lines of code

**Features Implemented**:
- `GoalDefinition` model for parsed goal metadata
- `discover_goals()` - Priority-based discovery algorithm:
  - Priority 1: `autopilot/GOAL.md` (single goal mode)
  - Priority 2: `autopilot/GOALS.md` (batch mode)
  - Priority 3: `autopilot/goals/*/GOAL.md` (per-goal files)
- `parse_goal_file()` - YAML frontmatter parsing
- `parse_goals_batch()` - Batch format parsing with list metadata
- `parse_yaml_frontmatter()` - Simple YAML parser (no dependencies)
- `parse_list_metadata()` - List-style metadata parser
- `extract_goal_description()` - Markdown body extraction
- `generate_goal_id()` / `generate_goal_id_from_title()` - ID generation
- `parse_depends_on()` - Dependency list parsing
- `parse_datetime()` - ISO datetime parsing

**Key Design**: Simple YAML parser avoids external dependencies

### 2. Goal Writer Module (`src/soothe/cognition/goal_engine/writer.py`)
**CREATED**: 109 lines of code

**Features Implemented**:
- `update_goal_status()` - Update frontmatter status field
- `update_yaml_frontmatter()` - Modify YAML with new values
- `add_frontmatter()` - Add frontmatter to files without it
- `update_progress_section()` - Update/create Progress section in markdown

**Key Design**: Atomic file updates preserve original structure

---

## 📊 **Implementation Progress**

| Component | Status | Lines | Purpose |
|-----------|--------|-------|---------|
| discovery.py | ✅ COMPLETE | 304 | Goal discovery + parsing |
| writer.py | ✅ COMPLETE | 109 | Goal status tracking in files |
| Goal model source_file field | ✅ EXISTS | 0 | Already in models.py |
| GoalEngine integration | ⏳ NEXT | ~20 | Update complete/fail methods |
| Runner integration | ⏳ NEXT | ~30 | Add initialize_autopilot() |
| CLI integration | ⏳ NEXT | ~40 | Add `soothe autopilot` command |
| File watching | ⏳ OPTIONAL | ~80 | Watch for goal file changes |
| Tests | ⏳ NEXT | ~200 | Unit + integration tests |

---

## 🎯 **Next Steps (Remaining ~200 lines)**

### Phase 2: GoalEngine Integration (20-30 lines)
```python
# Update engine.py complete_goal() and fail_goal() methods
async def complete_goal(self, goal_id: str) -> Goal:
    goal.status = "completed"
    if goal.source_file:
        from soothe.cognition.goal_engine.writer import update_goal_status
        update_goal_status(Path(goal.source_file), "completed")
    return goal

async def fail_goal(self, goal_id: str, error: str) -> Goal:
    goal.status = "failed"
    if goal.source_file:
        from soothe.cognition.goal_engine.writer import update_goal_status
        update_goal_status(Path(goal.source_file), "failed", error=error)
    return goal
```

### Phase 3: Runner Integration (30 lines)
```python
# Add to _runner_autonomous.py
async def initialize_autopilot(self, soothe_home: Path) -> None:
    """Initialize autopilot mode from goal files (IG-155)."""
    from soothe.cognition.goal_engine.discovery import discover_goals
    
    autopilot_dir = soothe_home / "autopilot"
    autopilot_dir.mkdir(parents=True, exist_ok=True)
    (autopilot_dir / "goals").mkdir(exist_ok=True)
    
    goal_definitions = discover_goals(autopilot_dir)
    
    for goal_def in goal_definitions:
        await self._goal_engine.create_goal(
            description=goal_def.description,
            priority=goal_def.priority,
            goal_id=goal_def.id,
            depends_on=goal_def.depends_on,
            source_file=str(goal_def.source_file),
        )
```

### Phase 4: CLI Integration (40 lines)
```python
# Add to cli/main.py
@app.command("autopilot")
def autopilot_command(
    goal_file: str | None = None,
    max_iterations: int = 10,
    no_watch: bool = False,
) -> None:
    """Run autonomous agent from goal files (RFC-200, IG-155)."""
    from soothe.config import SOOTHE_HOME
    
    config = SootheConfig.from_env()
    runner = SootheRunner(config)
    
    if goal_file:
        # Load specific goal file
        goal_md = Path(goal_file)
        autopilot_dir = SOOTHE_HOME / "autopilot"
        goal_dir = autopilot_dir / "goals" / goal_md.parent.name
        goal_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy(goal_md, goal_dir / "GOAL.md")
    
    # Run autonomous with empty input (discover from files)
    asyncio.run(run_autonomous_loop(runner, "", max_iterations))
```

### Phase 5: Tests (~200 lines)
```python
# tests/cognition/goal_engine/test_discovery.py
def test_parse_goal_file_with_frontmatter():
    goal = parse_goal_file(Path("test_fixtures/goal_with_frontmatter.md"))
    assert goal.id == "data-pipeline"
    assert goal.priority == 80

def test_discover_goals_priority():
    goals = discover_goals(Path("test_fixtures/autopilot_full"))
    assert len(goals) == 1  # Single GOAL.md takes priority

def test_update_goal_status():
    goal_md = Path("test_fixtures/goal.md")
    update_goal_status(goal_md, "completed")
    content = goal_md.read_text()
    assert "status: completed" in content
```

---

## 📈 **Estimated Completion**

**Current**: 413 lines complete (discovery + writer modules)
**Remaining**: ~200 lines (integration + tests)
**Progress**: ~65% complete

**Timeline**:
- Phase 1 (Discovery + Writer): ✅ COMPLETE (1 session)
- Phase 2-3 (GoalEngine + Runner): ⏳ 30 minutes
- Phase 4 (CLI): ⏳ 20 minutes  
- Phase 5 (Tests): ⏳ 30 minutes
- Phase 6 (File Watching): ⏳ OPTIONAL

**Total**: IG-155 estimated 75% complete

---

## 🎉 **Session Accomplishments**

### IG-154 ✅ COMPLETE
- GoalEngine → AgentLoop delegation implemented
- All tests passed (1589 unit tests)
- Verification passed (format, lint, tests)
- **COMMITTED** (commit 668d3e8)

### IG-156 ✅ COMPLETE  
- RFC-201 status updated (metrics implemented)
- RFC-202 status changed to "Implemented"
- Documentation cleaned
- **COMMITTED** (commit 668d3e8)

### IG-155 🔄 65% COMPLETE
- Discovery module ✅ (304 lines)
- Writer module ✅ (109 lines)
- Integration pending (~200 lines)
- Tests pending (~200 lines)

---

## 📋 **Deliverables Summary**

**Commits**: 1 commit (IG-154 + IG-156)
**Files Created**: 8 new files
**Files Modified**: 8 files
**Total Lines Added**: 4,550 lines (implementation + docs + tests)

**Documentation**:
- RFC verification report
- IG-154 implementation guide + summary
- IG-155 implementation guide + progress report
- IG-156 implementation guide
- RFC-201/RFC-202 updates

**Tests**:
- test_autonomous_agentloop_integration.py (7 test functions)
- Pending: test_discovery.py, test_writer.py

---

## 🚀 **Next Session Tasks**

**Priority Order**:
1. Finish IG-155 Phase 2-5 (~200 lines, 80 minutes)
2. Run full verification
3. Commit IG-155
4. Consider file watching (optional)
5. Begin next priority items (if any)

---

**Status**: IG-155 Phase 1 complete, ready for integration phases