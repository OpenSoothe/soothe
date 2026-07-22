# IG-494: RFC-625 Completion — LLM Reasoners, TUI, Config

**RFC**: 625 — AutopilotMonitor and ContextEngine Unification
**IG**: 494-rfc625-completion
**Status**: Complete
**Created**: 2026-06-15
**Owner**: Claude

---

## Scope

Complete remaining RFC-625 implementation work:

1. **LLM Verification Reasoner** — structured LLM calls for DAG health, placement analysis
2. **LLM Dreaming Reasoner** — structured LLM calls for 4 distillation modes
3. **TUI GoalDAGCard** — autopilot DAG visualization widget
4. **Config additions** — `verify_interval`, `dreaming_modes.*` fields

---

## Dependencies

- RFC-625 §4 (LLM verification/dreaming spec) — design complete
- RFC-625 §13 (config additions) — schema defined
- `BackoffReasoner` pattern (`autopilot/backoff_reasoner.py`) — reference for LLM integration
- `InternalEventBus` — event routing for GoalDAGCard

---

## Phase 1: Config Additions (0.5 day)

**Goal**: Add RFC-625 §13 config fields to `AutonomousConfig`.

### Changes

**File**: `packages/soothe/src/soothe/config/models.py`

Add to `AutonomousConfig`:

```python
class DreamingModeConfig(BaseModel):
    """Per-mode dreaming configuration (RFC-625 §13)."""
    enabled: bool = True
    max_episodes: int = 10  # episodic only
    min_success_rate: float = 0.8  # procedure only


class DreamingModesConfig(BaseModel):
    """Dreaming modes configuration container (RFC-625 §13)."""
    episodic: DreamingModeConfig = Field(default_factory=DreamingModeConfig)
    procedure: DreamingModeConfig = Field(default_factory=DreamingModeConfig)
    semantic: DreamingModeConfig = Field(default_factory=DreamingModeConfig)
    profile: DreamingModeConfig = Field(default_factory=DreamingModeConfig)


class AutonomousConfig(BaseModel):
    # Existing fields...
    dreaming_enabled: bool = True
    dreaming_poll_interval: int = Field(default=300, ge=10)

    # RFC-625 additions
    verify_interval: int = Field(default=30, ge=5, description="Background verification loop interval (seconds)")
    dreaming_interval: int = Field(default=300, ge=60, description="Time-based dreaming trigger (seconds)")
    dreaming_scope: Literal["loop", "workspace", "topic"] = Field(default="workspace", description="Cross-loop dreaming scope")
    dreaming_modes: DreamingModesConfig = Field(default_factory=DreamingModesConfig)
```

**Files**: `config/config.template.yml`, `config/develop/config.yml`

Add corresponding YAML structure:

```yaml
agent:
  autonomous:
    verify_interval: 30
    dreaming_interval: 300
    dreaming_scope: workspace
    dreaming_modes:
      episodic:
        enabled: true
        max_episodes: 10
      procedure:
        enabled: true
        min_success_rate: 0.8
      semantic:
        enabled: true
      profile:
        enabled: true
```

### Tests

- `tests/unit/config/test_autonomous_config.py`: verify new fields parse correctly
- Verify backward compatibility (missing fields use defaults)

---

## Phase 2: DagVerificationReasoner (1 day)

**Goal**: Implement LLM calls for DAG verification with structured output.

### Files to Create

**`packages/soothe/src/soothe/autopilot/verifier_reasoner.py`** (~150 lines)

```python
class DagVerificationReasoner:
    """LLM-based reasoning for DAG verification (RFC-625 §4)."""

    def __init__(self, config: SootheConfig) -> None:
        self._model = config.create_chat_model("think")  # Use think router

    async def verify_health(self, snapshot: DagSnapshot) -> DagHealthResponse:
        """Call LLM for health verification."""
        prompt = DAG_HEALTH_VERIFICATION_PROMPT.format(...)
        response = await self._model.ainvoke([SystemMessage(prompt)])
        return DagHealthResponse.model_validate_json(response.content)

    async def verify_post_completion(self, context: CompletionVerificationContext) -> CompletionVerificationResponse:
        """Call LLM for post-completion analysis."""
        prompt = POST_COMPLETION_VERIFICATION_PROMPT.format(...)
        response = await self._model.ainvoke([SystemMessage(prompt)])
        return CompletionVerificationResponse.model_validate_json(response.content)

    async def analyze_placement(self, context: GoalPlacementContext) -> GoalPlacementResponse:
        """Call LLM for placement analysis."""
        prompt = GOAL_PLACEMENT_PROMPT.format(...)
        response = await self._model.ainvoke([SystemMessage(prompt)])
        return GoalPlacementResponse.model_validate_json(response.content)
```

**`packages/soothe/src/soothe/autopilot/verifier_prompts.py`** (~80 lines)

```python
DAG_HEALTH_VERIFICATION_PROMPT = """Analyze the goal DAG for health issues.

DAG Summary:
{dag_summary}

Goals Detail:
{goals_detail}

Step Progress:
{step_progress}

Respond in JSON format:
{
  "reset_goals": ["goal_id1", ...],  // Goals to reset to pending
  "remove_goals": ["goal_id1", ...],  // Goals to remove entirely
  "merge_goals": [{"goals": [...], "merged_description": "..."}],
  "decompose_goals": [{"goal_id": "...", "subgoals": [...]}],
  "priority_adjustments": {"goal_id": new_priority},
  "reasoning": "explanation"
}
"""

POST_COMPLETION_VERIFICATION_PROMPT = """..."""
GOAL_PLACEMENT_PROMPT = """..."""
```

### Wire into GoalDAGVerifier

**`goal_dag_verifier.py`**:

```python
class GoalDAGVerifier:
    def __init__(self, ce: ContextEngine, config: SootheConfig) -> None:
        self._ce = ce
        self._config = config
        self._reasoner = DagVerificationReasoner(config)  # NEW

    async def verify_dag_health(self) -> DagHealthReport:
        snapshot = self._build_dag_snapshot()
        response = await self._reasoner.verify_health(snapshot)
        return DagHealthReport(
            suggest_reset=response.reset_goals,
            suggest_remove=response.remove_goals,
            suggest_merge=response.merge_goals,
            reasoning=response.reasoning,
        )
```

### Tests

- `tests/unit/autopilot/test_verifier_reasoner.py`:
  - Mock LLM responses, verify structured parsing
  - Test error handling (invalid JSON, timeout)

---

## Phase 3: DreamingDistillationReasoner (1 day)

**Goal**: Implement LLM calls for 4 dreaming distillation modes.

### Files to Create

**`packages/soothe/src/soothe/autopilot/dreaming_reasoner.py`** (~150 lines)

```python
class DreamingDistillationReasoner:
    """LLM-based reasoning for memory distillation (RFC-625 §6)."""

    def __init__(self, config: SootheConfig) -> None:
        self._model = config.create_chat_model("think")

    async def distill_episodic(self, context: EpisodicDistillationContext) -> EpisodicDistillationResponse:
        prompt = EPISODIC_DISTILLATION_PROMPT.format(...)
        response = await self._model.ainvoke([SystemMessage(prompt)])
        return EpisodicDistillationResponse.model_validate_json(response.content)

    async def distill_procedure(self, context: ProcedureDistillationContext) -> ProcedureDistillationResponse:
        prompt = PROCEDURE_DISTILLATION_PROMPT.format(...)
        response = await self._model.ainvoke([SystemMessage(prompt)])
        return ProcedureDistillationResponse.model_validate_json(response.content)

    async def distill_semantic(self, context: SemanticDistillationContext) -> SemanticDistillationResponse:
        prompt = SEMANTIC_DISTILLATION_PROMPT.format(...)
        response = await self._model.ainvoke([SystemMessage(prompt)])
        return SemanticDistillationResponse.model_validate_json(response.content)

    async def distill_profile(self, context: ProfileDistillationContext) -> ProfileDistillationResponse:
        prompt = PROFILE_DISTILLATION_PROMPT.format(...)
        response = await self._model.ainvoke([SystemMessage(prompt)])
        return ProfileDistillationResponse.model_validate_json(response.content)
```

**`packages/soothe/src/soothe/autopilot/dreaming_prompts.py`** (~80 lines)

Prompts for each mode as defined in RFC-625 §6.

### Wire into DreamingCoordinator

**`dreaming_coordinator.py`**:

```python
class DreamingCoordinator:
    def __init__(self, ce: ContextEngine, config: SootheConfig, bus: InternalEventBus | None = None) -> None:
        self._ce = ce
        self._config = config
        self._bus = bus
        self._reasoner = DreamingDistillationReasoner(config)  # NEW

    async def _run_mode(self, mode: DreamingMode, context: DreamingContext) -> Any:
        if mode == "episodic":
            response = await self._reasoner.distill_episodic(context)
            return response.episodes
        elif mode == "procedure":
            response = await self._reasoner.distill_procedure(context)
            return response.procedures
        # ... etc
```

### Tests

- `tests/unit/autopilot/test_dreaming_reasoner.py`:
  - Mock LLM responses for each mode
  - Verify structured output parsing
  - Test handler application (episodic → CE store, procedure → skill)

---

## Phase 4: TUI GoalDAGCard (2 days)

**Goal**: Create Textual widget for autopilot DAG visualization.

### File to Create

**`packages/soothe-cli/src/soothe_cli/tui/widgets/goal_dag_card.py`** (~200 lines)

```python
class GoalDagCard(Widget):
    """TUI card displaying DAG updates (delta view, RFC-625 §9)."""

    def __init__(self, ce: ContextEngine, bus: InternalEventBus) -> None:
        self._ce = ce
        self._updates: list[DagUpdateEntry] = []
        self._expanded = False
        bus.subscribe("goal_created", self._on_goal_created)
        bus.subscribe("goal_completed", self._on_goal_completed)
        bus.subscribe("goal_failed", self._on_goal_failed)
        bus.subscribe("goal_removed", self._on_goal_removed)

    def render(self) -> Panel:
        if self._expanded:
            return self._render_expanded()  # Mini-DAG tree
        return self._render_compact()  # Recent updates list

    def _render_compact(self) -> Panel:
        # Show last 5 updates with timestamps
        ...

    def _render_expanded(self) -> Panel:
        # Show goal tree with status icons
        ...

    def toggle_expand(self) -> None:
        self._expanded = not self._expanded
        self.refresh()

    # Event handlers update self._updates and refresh()
```

### Integration

Wire into main TUI layout when autopilot mode is active.

### Tests

- `tests/unit/tui/test_goal_dag_card.py`:
  - Test event handling
  - Test compact/expanded rendering
  - Test update list management

---

## Phase 5: Integration Tests (1 day)

**Goal**: Verify end-to-end flows work.

### Integration Tests

1. **Solo → Autopilot mode switch**:
   - Create linear chain in solo
   - Toggle autopilot
   - Verify DAG preserved, pending goals analyzed for restructuring

2. **Goal intake with placement**:
   - Submit goal via monitor
   - Verify LLM placement analysis called
   - Verify priority adjusted

3. **Dreaming trigger**:
   - Complete all goals
   - Verify dreaming mode entered
   - Verify LLM distillation called
   - Verify episodic memory stored

4. **DAG health verification**:
   - Create stuck goal (pending > verify_interval)
   - Run verification cycle
   - Verify LLM suggests reset/remove

---

## Execution Plan

| Phase | Scope | Days | Depends On |
|-------|-------|------|------------|
| 1 | Config additions | 0.5 | None |
| 2 | DagVerificationReasoner | 1 | Phase 1 |
| 3 | DreamingDistillationReasoner | 1 | Phase 1 |
| 4 | TUI GoalDAGCard | 2 | None |
| 5 | Integration tests | 1 | Phases 2, 3, 4 |

**Total: ~5.5 days**

---

## Verification

Run `./scripts/verify_finally.sh` after each phase. All unit tests must pass.

---

## Completion Criteria

- [x] Config fields added to AutonomousConfig
- [x] DagVerificationReasoner with 3 LLM methods
- [x] DreamingDistillationReasoner with 4 LLM methods
- [x] TUI GoalDagUpdatesCard widget functional
- [x] Unit tests passing
- [x] RFC-625 status updated to "Implemented"