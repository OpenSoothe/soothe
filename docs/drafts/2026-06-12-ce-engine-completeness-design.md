# CE Engine Completeness — Sub-project 1 Design

> RFC-624 Phase 3: Harden the ContextEngine into a self-sufficient engine with complete
> public API, state machine, event callbacks, lossless persistence, bounded ledger, and
> full projection output.

## Purpose

The ContextEngine module (`soothe.context`) works for basic adapter use but has structural
gaps that block it from being a self-sufficient, replaceable engine. This sub-project fills
those gaps so that Sub-projects 2 (adapter hardening + projection wiring) and 3 (CE as
primary path) can build on a solid foundation.

## Scope

**In scope:**
- Public read API on ContextEngine (eliminate private field access)
- Missing state transitions (cancel_goal, skip_step, block/unblock_goal)
- Simple callback event mechanism
- Lossless ledger persistence (full BaseMessage round-trip)
- Ledger compaction strategy (bounded growth)
- Complete ContextBundle projection (populate ledger_messages)

**Out of scope (deferred to Sub-projects 2/3):**
- Adapter refactor to use new public API (Sub-project 2)
- Projection wiring into prompt pipeline (Sub-project 2)
- Replacing PlanManager/PlanDAG as primary state (Sub-project 3)
- Postgres persistence backend
- Token-aware bounding
- Multi-process concurrency safety

## Architecture

No new modules. All changes are internal to existing files:

```
soothe.context/
├── engine.py        # Public read API + missing transitions + callbacks
├── models.py        # cancel/block transitions on GoalStepDAG
├── ledger.py        # compact() + public entries()
├── projection.py    # Populate ledger_messages in ContextBundle
├── persistence/
│   └── file_backend.py  # Lossless ledger serialization
└── (unchanged: semantic.py, persistence/in_memory.py)
```

## Component Changes

### 1. ContextEngine Public Read API

**Problem:** Adapters access `_ce._dag` and `_ce._ledger._entries` directly, creating
tight coupling to internal representation.

**Solution:** Add read-only accessors that return copies or views:

```python
class ContextEngine:
    # New public methods
    def get_dag_snapshot(self) -> GoalStepDAGSnapshot:
        """Return a serializable snapshot of the full GoalStepDAG."""
        return self._dag.snapshot()

    def get_step_dag(self, goal_id: str) -> StepDAG | None:
        """Return the StepDAG for a goal (None if goal not found)."""
        goal = self._dag.get_goal(goal_id)
        return goal.steps if goal else None

    def get_ledger_entries(self, phases: list[str] | None = None) -> list[tuple[BaseMessage, str | None]]:
        """Return (message, phase) tuples, optionally filtered by phase."""
        return self._ledger.entries(phases)

    def get_all_goals(self) -> list[GoalNode]:
        """Return all goals in the DAG."""
        return list(self._dag.goals.values())

    def get_goal_lineage(self, goal_id: str) -> list[str]:
        """Return chain of goal descriptions from root to this goal."""
        return self._dag.goal_lineage(goal_id)
```

These are synchronous (not async) since they read from in-memory state. The existing
async methods (`get_goal`, `list_goals`) remain for API consistency.

### 2. Missing State Transitions

**GoalStepDAG** gets two new methods:

```python
class GoalStepDAG:
    def cancel_goal(self, goal_id: str) -> None:
        """Transition goal to cancelled (terminal state)."""
        goal = self.goals.get(goal_id)
        if goal is not None:
            goal.status = "cancelled"
            goal.updated_at = datetime.now(UTC)

    def block_goal(self, goal_id: str, reason: str | None = None) -> None:
        """Transition goal to blocked."""
        goal = self.goals.get(goal_id)
        if goal is not None:
            goal.status = "blocked"
            goal.updated_at = datetime.now(UTC)

    def unblock_goal(self, goal_id: str) -> None:
        """Transition goal from blocked back to pending."""
        goal = self.goals.get(goal_id)
        if goal is not None and goal.status == "blocked":
            goal.status = "pending"
            goal.updated_at = datetime.now(UTC)
```

**ContextEngine** gets corresponding async methods:

```python
class ContextEngine:
    async def cancel_goal(self, goal_id: str) -> None:
        self._dag.cancel_goal(goal_id)
        self._fire("goal_cancelled", goal_id)

    async def skip_step(self, goal_id: str, step_id: str) -> None:
        goal = self._dag.get_goal(goal_id)
        if goal is None:
            return
        goal.steps.mark_skipped(step_id)
        goal.updated_at = datetime.now(UTC)
        self._fire("step_skipped", goal_id, step_id)

    async def block_goal(self, goal_id: str, reason: str | None = None) -> None:
        self._dag.block_goal(goal_id)
        self._fire("goal_blocked", goal_id)

    async def unblock_goal(self, goal_id: str) -> None:
        self._dag.unblock_goal(goal_id)
        self._fire("goal_unblocked", goal_id)
```

### 3. Callback Event Mechanism

**Design:** Simple synchronous callbacks registered by event name. Callbacks fire
after state changes complete. Errors in callbacks are caught and logged — they never
block the state transition.

```python
# Event type
EngineEvent = Literal[
    "goal_created", "goal_activated", "goal_completed", "goal_failed",
    "goal_suspended", "goal_cancelled", "goal_blocked", "goal_unblocked",
    "step_completed", "step_failed", "step_skipped",
]

class ContextEngine:
    def __init__(self, ...):
        self._callbacks: dict[str, list[Callable]] = {}

    def on(self, event: EngineEvent, callback: Callable) -> None:
        """Register a callback for an event. Callback receives event-specific args."""
        self._callbacks.setdefault(event, []).append(callback)

    def off(self, event: EngineEvent, callback: Callable) -> None:
        """Unregister a callback."""
        callbacks = self._callbacks.get(event, [])
        if callback in callbacks:
            callbacks.remove(callback)

    def _fire(self, event: EngineEvent, *args: Any) -> None:
        """Fire all callbacks for an event, catching errors."""
        for cb in self._callbacks.get(event, []):
            try:
                cb(*args)
            except Exception:
                logger.warning("Callback error for event %s: %s", event, cb, exc_info=True)
```

Callback signatures by event:

| Event | Callback signature |
|---|---|
| `goal_created` | `(goal_id: str)` |
| `goal_activated` | `(goal_id: str)` |
| `goal_completed` | `(goal_id: str)` |
| `goal_failed` | `(goal_id: str, error: str)` |
| `goal_suspended` | `(goal_id: str, reason: str)` |
| `goal_cancelled` | `(goal_id: str)` |
| `goal_blocked` | `(goal_id: str)` |
| `goal_unblocked` | `(goal_id: str)` |
| `step_completed` | `(goal_id: str, step_id: str)` |
| `step_failed` | `(goal_id: str, step_id: str)` |
| `step_skipped` | `(goal_id: str, step_id: str)` |

Fire callbacks from existing methods too (not just new ones):

```python
async def activate_goal(self, goal_id, loop_id=None):
    # ... existing logic ...
    self._fire("goal_activated", goal_id)

async def complete_goal(self, goal_id):
    self._dag.complete_goal(goal_id)
    self._fire("goal_completed", goal_id)

async def fail_goal(self, goal_id, error):
    self._dag.fail_goal(goal_id, error)
    self._fire("goal_failed", goal_id, error)

async def suspend_goal(self, goal_id, reason):
    self._dag.suspend_goal(goal_id, reason)
    self._fire("goal_suspended", goal_id, reason)

async def create_goal(self, ...):
    # ... existing logic ...
    self._fire("goal_created", goal.id)
    return goal

async def complete_step(self, ...):
    # ... existing logic ...
    self._fire("step_completed", goal_id, step_id)

async def fail_step(self, ...):
    # ... existing logic ...
    self._fire("step_failed", goal_id, step_id)
```

### 4. Lossless Ledger Persistence

**Problem:** `engine.save()` only serializes `type + content + phase`, losing
`ToolMessage`, `tool_calls`, `response_metadata`, `usage_metadata`.

**Solution:** Use `BaseMessage.model_dump()` for serialization and
`message_type.model_validate()` for deserialization.

```python
async def save(self) -> None:
    try:
        await self._persistence.save_dag(self._dag)
        ledger_data: list[dict[str, Any]] = []
        for msg, phase in self._ledger.entries():
            dump = msg.model_dump()
            dump["_phase"] = phase
            dump["_msg_type"] = type(msg).__name__
            ledger_data.append(dump)
        await self._persistence.save_ledger(ledger_data)
    except Exception:
        logger.warning("Persistence save failed", exc_info=True)

async def load(self) -> bool:
    try:
        dag = await self._persistence.load_dag()
        if dag is not None:
            self._dag = dag
        ledger_data = await self._persistence.load_ledger()
        if ledger_data:
            self._ledger.clear()
            for entry_data in ledger_data:
                msg_type_name = entry_data.pop("_msg_type", "HumanMessage")
                phase = entry_data.pop("_phase", None)
                # Remove extra keys that BaseMessage.model_validate would reject
                # Keep only standard LangChain fields
                msg = _reconstruct_message(msg_type_name, entry_data)
                if msg is not None:
                    self._ledger.record_message(msg, phase or "")
        return dag is not None
    except Exception:
        logger.warning("Persistence load failed", exc_info=True)
        return False
```

The `_reconstruct_message` helper maps type names to LangChain classes:

```python
from langchain_core.messages import (
    AIMessage, HumanMessage, SystemMessage, ToolMessage, AIMessageChunk,
)

_MESSAGE_TYPES = {
    "AIMessage": AIMessage,
    "HumanMessage": HumanMessage,
    "SystemMessage": SystemMessage,
    "ToolMessage": ToolMessage,
    "AIMessageChunk": AIMessageChunk,
    # LoopMessage subtypes
    "LoopAIMessage": AIMessage,  # fallback — content preserved
    "LoopHumanMessage": HumanMessage,
}

def _reconstruct_message(type_name: str, data: dict) -> BaseMessage | None:
    cls = _MESSAGE_TYPES.get(type_name)
    if cls is None:
        logger.warning("Unknown message type %s, skipping", type_name)
        return None
    try:
        return cls.model_validate(data)
    except Exception:
        # Fallback: at minimum preserve content
        content = data.get("content", "")
        logger.warning("Failed to reconstruct %s, using content-only fallback", type_name)
        return cls(content=content)
```

**Backward compatibility:** Old persisted files (with `type + content + phase` only)
continue to load — the `load()` method handles both formats by checking for `_msg_type`.

### 5. Ledger Compaction

**Design:** Configurable compaction function passed to `LedgerManager.__init__`.
When entries exceed `max_entries`, the oldest entries are compacted into a summary.

```python
class LedgerManager:
    def __init__(
        self,
        max_inline_chars: int = 4000,
        max_entry_chars_before_spill: int = 1500,
        max_entries: int = 200,
        compact_fn: Callable[[list[_LedgerEntry]], str | None] | None = None,
    ) -> None:
        self.max_inline_chars = max_inline_chars
        self.max_entry_chars_before_spill = max_entry_chars_before_spill
        self._max_entries = max_entries
        self._compact_fn = compact_fn
        self._entries: list[_LedgerEntry] = []
        self._step_lines: list[str] = []

    def compact(self) -> None:
        """Compact old entries when count exceeds max_entries.

        If a compact_fn is provided, it receives the oldest entries and returns
        a summary string (or None to skip compaction). The summary replaces
        those entries as a single SystemMessage.

        If no compact_fn is set, entries beyond max_entries are dropped.
        """
        if len(self._entries) <= self._max_entries:
            return

        excess = len(self._entries) - self._max_entries
        old_entries = self._entries[:excess]

        if self._compact_fn is not None:
            summary = self._compact_fn(old_entries)
            if summary:
                from langchain_core.messages import SystemMessage
                self._entries = [
                    _LedgerEntry(message=SystemMessage(content=summary), phase="compacted"),
                    *self._entries[excess:],
                ]
                return

        # No compaction function — drop oldest entries
        self._entries = self._entries[excess:]
```

The `compact()` call should be triggered automatically after each `record_message`:

```python
def record_message(self, message: BaseMessage, phase: str) -> None:
    self._entries.append(_LedgerEntry(message=message, phase=phase))
    if len(self._entries) > self._max_entries:
        self.compact()
```

**Default `max_entries=200`**: sufficient for typical multi-hour AgentLoop sessions
(~50 iterations x 4 ledger pairs). The compaction function is not set by default —
without it, old entries are dropped. This matches the current behavior where
`loop_messages` grows unbounded but is bounded by the projection layer.

### 6. Complete ContextBundle Projection

**Problem:** `ContextBundle.ledger_messages` is always empty.

**Solution:** Populate it in `ProjectionEngine.project()`:

```python
# In ProjectionEngine.project(), before building ContextBundle:
ledger_messages: list[dict] = []
for msg, phase in ledger.entries():
    ledger_messages.append({
        "type": type(msg).__name__,
        "phase": phase,
        "content": _truncate(
            getattr(msg, "content", "") if isinstance(getattr(msg, "content", ""), str) else "",
            500,  # per-message cap
        ),
    })
ledger_messages = ledger_messages[-cfg.max_ledger_messages:]
```

This provides structured access to the ledger (message type, phase, bounded content)
without the full BaseMessage objects, which would be too heavy for the ContextBundle.

### 7. LedgerManager Public entries() Method

```python
class LedgerManager:
    def entries(self, phases: list[str] | None = None) -> list[tuple[BaseMessage, str | None]]:
        """Return (message, phase) tuples for all entries, optionally filtered."""
        if phases is None:
            return [(e.message, e.phase) for e in self._entries]
        phase_set = set(phases)
        return [(e.message, e.phase) for e in self._entries if e.phase in phase_set]
```

## Data Flow

### Callback Flow

```
AgentLoop → ContextEngine.complete_goal(goal_id)
                ↓
            GoalStepDAG.complete_goal() [state change]
                ↓
            _fire("goal_completed", goal_id) [callback dispatch]
                ↓
            AgentLoop handler (if registered)
                → e.g., activate next ready goal
```

### Persistence Flow

```
ContextEngine.save()
    → persistence.save_dag(dag_snapshot)         [GoalStepDAG — Pydantic model_dump]
    → persistence.save_ledger(ledger_data)       [BaseMessage.model_dump + _phase + _msg_type]

ContextEngine.load()
    → persistence.load_dag() → self._dag         [Pydantic model_validate]
    → persistence.load_ledger() → _reconstruct_message() → self._ledger.record_message()
```

### Projection Flow

```
ContextEngine.project(goal_id)
    → ProjectionEngine.project(dag, ledger, semantic)
        → resolve target goal
        → build step lists (pending/completed/failed)
        → build ledger_summary (text) + ledger_messages (structured)
        → load semantic context
        → return ContextBundle
```

## Error Handling

| Scenario | Handling |
|---|---|
| Invalid state transition | Raise `ValueError` with clear message (e.g., "Goal X is failed, cannot cancel") |
| Callback error | Catch, log warning, continue — never block the state transition |
| Persistence save failure | Catch, log warning, continue with in-memory state |
| Persistence load failure | Catch, log warning, return False (empty state) |
| Message reconstruction failure | Fallback to content-only `HumanMessage`/`AIMessage` |
| Compaction failure | Catch, log warning, leave entries un-compacted |

## Testing

### Unit Tests (`tests/unit/context/`)

| Test | Description |
|---|---|
| `test_public_read_api` | `get_dag_snapshot`, `get_step_dag`, `get_ledger_entries`, `get_all_goals`, `get_goal_lineage` return correct data |
| `test_cancel_goal` | Cancel transitions goal to "cancelled" |
| `test_skip_step` | Skip transitions step to "skipped" |
| `test_block_unblock_goal` | Block → "blocked", unblock → "pending" |
| `test_callbacks_fire` | Register callback, verify it fires on state change |
| `test_callbacks_error_handling` | Callback raises, state still changes, error logged |
| `test_callback_off` | Unregister callback, verify it doesn't fire |
| `test_lossless_persistence` | Save/load round-trip with Human, AI, Tool, System messages |
| `test_backward_compat_persistence` | Load old-format (type+content+phase) files |
| `test_ledger_compact_no_fn` | Entries dropped when exceeding max_entries without compact_fn |
| `test_ledger_compact_with_fn` | Entries summarized into SystemMessage with compact_fn |
| `test_context_bundle_ledger_messages` | ledger_messages populated with type, phase, bounded content |
| `test_ledger_entries_public` | entries() returns (message, phase) tuples with phase filtering |

### Existing Tests

All existing tests (22 adapter + 9 integration) must continue to pass without modification.
The public API additions are backward-compatible — no existing method signatures change.

## Migration Path

This sub-project is backward-compatible:
- New public methods are additive — no existing signatures change
- Callbacks are opt-in — no behavioral change unless registered
- Lossless persistence handles old-format files on load
- Ledger compaction is auto-triggered but only when exceeding `max_entries=200`
- `ContextBundle.ledger_messages` was always empty before — populating it is additive

After this sub-project, the engine is ready for Sub-project 2 (adapter hardening +
projection wiring) which will:
- Refactor adapters to use public read API instead of `_dag`/`_ledger`
- Wire `ContextBundle` into the prompt pipeline
- Make `GoalContextAdapter` read from CE's DAG instead of old state_manager
