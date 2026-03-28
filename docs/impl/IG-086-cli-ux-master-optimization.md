# IG-086: CLI UX Master Optimization - Unified Implementation

**Status**: Proposed
**Created**: 2026-03-28
**Scope**: Consolidated CLI UX improvements merging IG-084, IG-085, and new optimizations
**Priority**: CRITICAL
**Estimated Effort**: 3 weeks (15 days)

---

## Executive Summary

This implementation guide consolidates all CLI UX improvements into a unified implementation plan:

1. **IG-084**: UX fixes (verbosity filtering, config crash, checkhealth exit codes, thread list)
2. **IG-085**: Daemon lifecycle semantics (client detachment, persistence, messaging)
3. **New Optimizations**: Display policy layer, event classification, standardized lifecycle messages

**Key Insight**: Daemon lifecycle stability (IG-085) is prerequisite for reliable UX testing. Display policy layer provides robust output filtering beyond IG-084's event filtering approach.

---

## Problems Identified (Consolidated)

### Priority 1: Foundation Issues (Week 1)

#### 1. Daemon Lifecycle Instability
**Severity**: BLOCKER
**Evidence**: Daemon restart required SIGKILL after 8s timeout
**Impact**: Unstable daemon prevents reliable UX testing
**Fix**: Implement IG-085 daemon lifecycle semantics + shutdown timeout handling

#### 2. Config Command Crash
**Severity**: BLOCKER
**Evidence**: `soothe config show` crashes with AttributeError
**Impact**: Users cannot view configuration
**Fix**: IG-084 Phase 1 Step 1 (attribute checking)

#### 3. Checkhealth Exit Code Logic
**Severity**: HIGH
**Evidence**: Exit code 2 (critical) for optional component warnings
**Impact**: Users think system is broken when healthy
**Fix**: IG-084 Phase 1 Step 2 (exit code categorization)

### Priority 2: Display Quality Issues (Week 2)

#### 4. Minimal Verbosity Too Verbose
**Severity**: HIGH
**Evidence**: `--verbosity minimal` shows plan details, reasoning, lifecycle messages
**Expected**: Only final answer
**Actual**: Full internal protocol details
**Impact**: Cannot get clean output for automation/pipes
**Fix**: Display policy layer + event classification (NEW)

#### 5. Plan Visualization Leakage
**Severity**: HIGH
**Evidence**: Plan reasoning and step breakdown appear in minimal mode
**Impact**: Internal details leak into user output
**Fix**: Event classification + display policy enforcement

#### 6. Headless Stream Clutter
**Severity**: MEDIUM
**Evidence**: Pydantic warnings, protocol events, lifecycle metadata
**Impact**: Unprofessional output, obscures results
**Fix**: Verbosity-based suppression + warning filtering

### Priority 3: Consistency Issues (Week 3)

#### 7. Inconsistent Lifecycle Messages
**Severity**: MEDIUM
**Evidence**: Different formats across TUI/non-TUI, verbosity levels
**Impact**: Inconsistent UX, confusing messaging
**Fix**: Unified lifecycle message templates (NEW)

#### 8. Thread List Information Overload
**Severity**: MEDIUM
**Evidence**: Shows 113 threads unpaginated, tool warnings, empty columns
**Impact**: Users can't find relevant threads
**Fix**: IG-084 Phase 2 Step 4 (pagination, filtering)

#### 9. No First-Time User Guidance
**Severity**: MEDIUM
**Evidence**: `checkhealth` says "run config init" without explanation
**Impact**: New users don't know where to start
**Fix**: IG-084 Phase 3 Step 5 (quickstart command)

---

## Architecture: Two-Layer Filtering Approach

### Layer 1: Event Classification (Stream Level)

Classify events early in pipeline for routing decisions.

**Location**: `src/soothe/ux/cli/stream_classifier.py` (new file)

```python
from typing import Literal
from langchain_core.messages import AIMessage, ToolMessage

StreamEventClass = Literal[
    "assistant_response",  # Final output text
    "tool_call",           # Tool invocation
    "tool_result",         # Tool execution result
    "plan",                # Plan creation event
    "step",                # Plan step event
    "protocol",            # Protocol orchestration (context, memory, policy)
    "lifecycle",           # Daemon/thread lifecycle
    "error",               # Error event
    "debug",               # Internal debug info
]

def classify_stream_event(namespace: list[str], mode: str, data: any) -> StreamEventClass:
    """Classify stream event for filtering and routing.

    Args:
        namespace: LangGraph namespace tuple
        mode: Stream mode (messages, updates, custom)
        data: Event data payload

    Returns:
        Event classification string
    """
    # Assistant response (main graph, messages mode, AIMessage)
    if mode == "messages" and not namespace:
        if isinstance(data, tuple) and len(data) >= 1:
            if isinstance(data[0], AIMessage):
                # Check if it's a tool call or text response
                if data[0].tool_calls:
                    return "tool_call"
                return "assistant_response"

    # Tool result (main graph, messages mode, ToolMessage)
    if mode == "messages" and not namespace:
        if isinstance(data, tuple) and len(data) >= 1:
            if isinstance(data[0], ToolMessage):
                return "tool_result"

    # Custom events (soothe.* namespace)
    if mode == "custom" and isinstance(data, dict):
        event_type = data.get("type", "")

        # Plan events
        if event_type == "soothe.plan.created":
            return "plan"
        if event_type.startswith("soothe.plan.step"):
            return "step"

        # Protocol events
        if event_type.startswith("soothe.context"):
            return "protocol"
        if event_type.startswith("soothe.memory"):
            return "protocol"
        if event_type.startswith("soothe.policy"):
            return "protocol"

        # Lifecycle events
        if event_type.startswith("soothe.thread"):
            return "lifecycle"
        if event_type.startswith("soothe.daemon"):
            return "lifecycle"

        # Error events
        if event_type.startswith("soothe.error"):
            return "error"

        # Subagent progress (research, browser, etc.)
        if event_type.startswith("soothe.research"):
            return "protocol"
        if event_type.startswith("soothe.browser"):
            return "protocol"

        return "debug"

    # HITL interrupts
    if mode == "updates" and isinstance(data, dict):
        if "__interrupt__" in data:
            return "lifecycle"

    return "debug"
```

### Layer 2: Display Policy (Output Level)

Enforce verbosity filtering at final display layer (most robust).

**Location**: `src/soothe/ux/cli/display_policy.py` (new file)

```python
from typing import Optional
import json
from soothe.ux.cli.stream_classifier import classify_stream_event, StreamEventClass

class VerbosityDisplayPolicy:
    """Enforce output verbosity at final display layer.

    This is the final gatekeeper before output reaches stdout/stderr.
    Provides defense-in-depth filtering beyond stream-level classification.
    """

    def format_output(
        self,
        namespace: list[str],
        mode: str,
        data: any,
        verbosity: str,
        output_format: str
    ) -> Optional[str]:
        """Format event for output or suppress based on verbosity.

        Args:
            namespace: LangGraph namespace
            mode: Stream mode
            data: Event data
            verbosity: minimal, quiet, normal, detailed, debug
            output_format: text or jsonl

        Returns:
            Formatted string or None (suppress event)
        """
        # Classify event
        event_class = classify_stream_event(namespace, mode, data)

        # JSONL format: Always show structure, but minimal strips content
        if output_format == "jsonl":
            return self._format_jsonl(namespace, mode, data, event_class, verbosity)

        # Text format: Apply strict filtering based on verbosity
        return self._format_text(namespace, mode, data, event_class, verbosity)

    def _format_text(
        self,
        namespace: list[str],
        mode: str,
        data: any,
        event_class: StreamEventClass,
        verbosity: str
    ) -> Optional[str]:
        """Format event as text output or suppress."""

        # Minimal verbosity: ONLY final assistant response
        if verbosity == "minimal":
            if event_class == "assistant_response":
                return self._extract_final_answer(data)
            # Suppress everything else (plan, tools, protocol, lifecycle)
            return None

        # Quiet verbosity: Final answer + brief tool summary
        if verbosity == "quiet":
            if event_class == "assistant_response":
                return self._format_response_normal(data)
            if event_class == "tool_result":
                return self._format_tool_result_brief(data)
            # Suppress plan, protocol, lifecycle
            return None

        # Normal verbosity: Tools + response
        if verbosity == "normal":
            if event_class in ("tool_call", "tool_result", "assistant_response"):
                return self._format_normal(namespace, mode, data, event_class)
            # Suppress plan, protocol, lifecycle
            return None

        # Detailed verbosity: Plan + steps + tools + response
        if verbosity == "detailed":
            if event_class in ("plan", "step", "tool_call", "tool_result", "assistant_response", "error"):
                return self._format_detailed(namespace, mode, data, event_class)
            # Suppress protocol, lifecycle
            return None

        # Debug verbosity: Show everything
        return self._format_debug(namespace, mode, data, event_class)

    def _extract_final_answer(self, data: any) -> str:
        """Extract minimal final answer from assistant response.

        For simple queries (math, facts), return just the answer.
        For complex responses, return full text.
        """
        if isinstance(data, tuple) and len(data) >= 1:
            if isinstance(data[0], AIMessage):
                text = data[0].content

                # Heuristic: If response contains math answer, extract it
                # e.g., "The answer is 4" -> "4"
                # e.g., "15% of 847 is 127.05" -> "127.05"

                # Simple math pattern: "is X" or "answer is X"
                import re
                math_patterns = [
                    r"The answer is (\d+\.?\d*)",
                    r"is (\d+\.?\d*)",
                    r"equals (\d+\.?\d*)",
                    r"result: (\d+\.?\d*)",
                ]

                for pattern in math_patterns:
                    match = re.search(pattern, text, re.IGNORECASE)
                    if match:
                        return match.group(1)

                # Otherwise return full text
                return text.strip()

        return str(data)

    def _format_tool_result_brief(self, data: any) -> str:
        """Format tool result as one-line summary."""
        if isinstance(data, tuple) and len(data) >= 1:
            if isinstance(data[0], ToolMessage):
                tool_name = data[0].name or "tool"
                content = str(data[0].content)

                # Truncate to 80 chars
                if len(content) > 80:
                    content = content[:77] + "..."

                return f"✓ {tool_name}: {content}"

        return None

    def _format_jsonl(
        self,
        namespace: list[str],
        mode: str,
        data: any,
        event_class: StreamEventClass,
        verbosity: str
    ) -> str:
        """Format as JSONL with verbosity-based content filtering."""

        # Minimal: Strip content, keep structure
        if verbosity == "minimal":
            return json.dumps({
                "class": event_class,
                "type": data.get("type") if isinstance(data, dict) else mode,
            })

        # Other verbosity levels: Show full event
        return json.dumps({
            "namespace": namespace,
            "mode": mode,
            "class": event_class,
            "data": data,
        })

    # Additional formatting methods for normal/detailed/debug...
    # (Implementation details omitted for brevity)
```

### Verbosity Hierarchy (Revised)

| Level | Shows | Suppresses | Use Case |
|-------|-------|------------|----------|
| `minimal` | Final answer only | Everything else | Automation, piping, scripts |
| `quiet` | Answer + tool summaries | Plan, protocol, lifecycle | Quick queries, minimal progress |
| `normal` | Tools + answer | Plan, protocol, lifecycle | Default interactive use |
| `detailed` | Plan + steps + tools + answer | Protocol internals | Progress visibility, debugging |
| `debug` | Everything | Nothing | Development, deep debugging |

---

## Implementation Plan

### Week 1: Foundation (Days 1-5)

#### Day 1: Daemon Lifecycle Core (IG-085 Phases 1-2)

**Files**:
- `src/soothe/cli/execution/daemon.py` (Non-TUI headless)
- `src/soothe/daemon/server.py` (Daemon server side)

**Changes**:
1. Remove implicit daemon shutdown logic from headless mode
2. Add graceful shutdown timeout handling (Optimization 2)
3. Implement proper `detach` message handling
4. Add client session tracking verification

**Testing**:
```bash
# Test daemon persistence
$ soothe daemon stop  # Ensure clean start
$ soothe -p "test1" --no-tui
[lifecycle] Daemon started.  # or suppress in minimal
$ soothe daemon status
Daemon running (PID: XXX)  # Should show running

# Test graceful shutdown
$ soothe daemon stop
Daemon stopped gracefully.  # Should NOT require SIGKILL
```

---

#### Day 2: Daemon Lifecycle TUI (IG-085 Phases 3-4)

**Files**:
- `src/soothe/ux/tui/app.py` (TUI client)
- `src/soothe/ux/tui/commands.py` (Slash command handler)

**Changes**:
1. Modify `/exit`/`/quit` to detach client, not stop daemon
2. Implement double Ctrl+C detection (1s window)
3. Add thread running warning modal
4. Show daemon PID in exit messages

**Testing**:
```bash
# TUI exit tests
$ soothe  # Launch TUI
> /exit
TUI exited. Daemon running (PID: XXX).  # Daemon persists

# Double Ctrl+C test
> [Ctrl+C once]
Job cancelled. Press Ctrl+C again within 1s to exit.
> [Ctrl+C again within 1s]
TUI exited. Daemon running (PID: XXX).
```

---

#### Day 3: Daemon Lifecycle Messaging (IG-085 Phases 5-6)

**Files**:
- `src/soothe/utils/lifecycle_messages.py` (new file - Optimization 3)
- `src/soothe/cli/commands/daemon_cmd.py`

**Changes**:
1. Create unified lifecycle message templates
2. Apply templates across TUI/non-TUI modes
3. Add verbosity-based message formatting

**Implementation**:
```python
# src/soothe/utils/lifecycle_messages.py

LIFECYCLE_MESSAGE_TEMPLATES = {
    "minimal": {
        "daemon_start": None,  # Suppress
        "daemon_stop": None,  # Suppress
        "request_complete": None,  # Suppress
        "thread_created": None,  # Suppress
    },
    "quiet": {
        "daemon_start": "✓ Started",
        "daemon_stop": "✓ Stopped",
        "request_complete": "✓ Done",
        "thread_created": None,  # Suppress
    },
    "normal": {
        "daemon_start": "✓ Daemon started",
        "daemon_stop": "✓ Daemon stopped",
        "request_complete": "✓ Request completed",
        "thread_created": None,  # Suppress
    },
    "detailed": {
        "daemon_start": "✓ Daemon started (PID: {pid})",
        "daemon_stop": "✓ Daemon stopped",
        "request_complete": "✓ Done. Daemon running (PID: {pid})",
        "thread_created": "Thread: {thread_id}",
    },
    "debug": {
        "daemon_start": "[lifecycle] Daemon started (PID: {pid}, socket: {socket})",
        "daemon_stop": "[lifecycle] Daemon stopped (duration: {duration_ms}ms)",
        "request_complete": "[lifecycle] Request completed (PID: {pid}, thread: {thread_id})",
        "thread_created": "[lifecycle] Thread created: {thread_id}",
    },
}

def format_lifecycle_message(event_type: str, verbosity: str, **kwargs) -> Optional[str]:
    """Format lifecycle message based on verbosity.

    Returns None if message should be suppressed.
    """
    templates = LIFECYCLE_MESSAGE_TEMPLATES.get(verbosity, {})
    template = templates.get(event_type)

    if template is None:
        return None

    return template.format(**kwargs)
```

---

#### Day 4: Fix Blocking Bugs (IG-084 Phase 1)

**Files**:
- `src/soothe/cli/commands/config_cmd.py` (Config crash fix)
- `src/soothe/cli/commands/health_cmd.py` (Checkhealth exit codes)

**Changes**:
1. Add attribute checking in config show (IG-084 Step 1)
2. Improve checkhealth exit code logic (IG-084 Step 2)
3. Separate critical vs optional checks
4. Mark optional checks clearly with `(optional)` label

**Testing**:
```bash
$ soothe config show
Memory Backend: MemU  # Works without crash

$ soothe checkhealth
✓ System healthy (3 optional checks skipped)  # Exit code 0
```

---

#### Day 5: Event Classification Layer (Optimization 5 Part 1)

**Files**:
- `src/soothe/ux/cli/stream_classifier.py` (new file)

**Changes**:
1. Create event classification function
2. Integrate into daemon runner stream processing
3. Add classification field to thread logs

**Testing**:
```python
# Unit tests in tests/unit/test_stream_classifier.py

def test_classify_assistant_response():
    event = ([], "messages", (AIMessage(content="test"), {}))
    assert classify_stream_event(*event) == "assistant_response"

def test_classify_tool_result():
    event = ([], "messages", (ToolMessage(content="result", name="test"), {}))
    assert classify_stream_event(*event) == "tool_result"

def test_classify_plan():
    event = ([], "custom", {"type": "soothe.plan.created"})
    assert classify_stream_event(*event) == "plan"
```

---

### Week 2: Display Quality (Days 6-10)

#### Day 6: Display Policy Layer (Optimization 1)

**Files**:
- `src/soothe/ux/cli/display_policy.py` (new file)

**Changes**:
1. Create VerbosityDisplayPolicy class
2. Implement text output formatting with filtering
3. Implement JSONL formatting with content stripping
4. Add answer extraction heuristics for minimal mode

**Testing**:
```bash
# Minimal mode tests
$ soothe -p "2+2" --verbosity minimal --no-tui
4  # Only answer

$ soothe -p "Calculate 15% of 847" --verbosity minimal --no-tui
127.05  # Extracted answer

$ soothe -p "search arxiv quantum" --verbosity minimal --no-tui
Found 10 papers: [full response text]  # No extraction possible
```

---

#### Day 7: Integrate Display Policy (Optimization 1 Part 2)

**Files**:
- `src/soothe/cli/execution/daemon_runner.py` (Headless runner)
- `src/soothe/cli/commands/run_cmd.py` (Run command)

**Changes**:
1. Apply display policy in headless runner
2. Pass verbosity level through execution pipeline
3. Suppress Pydantic warnings in non-debug modes

**Implementation**:
```python
# In daemon_runner.py

async def stream_events(client, verbosity, output_format):
    """Stream events with display policy filtering."""
    policy = VerbosityDisplayPolicy()

    import warnings
    if verbosity != "debug":
        # Suppress Pydantic warnings
        warnings.filterwarnings("ignore", category=UserWarning, module="pydantic")

    async for event in client.stream_events():
        # Apply display policy
        output = policy.format_output(
            event.namespace,
            event.mode,
            event.data,
            verbosity,
            output_format
        )

        if output:
            print(output, file=sys.stdout if output_format == "text" else sys.stderr)
```

---

#### Day 8: Headless Stream Cleanup (Optimization 5 Part 2)

**Files**:
- `src/soothe/cli/execution/daemon_runner.py`

**Changes**:
1. Suppress lifecycle messages in minimal/quiet modes
2. Hide protocol events in normal mode
3. Show only essential progress in detailed mode
4. Remove plan reasoning from non-debug output

**Testing**:
```bash
# No internal leakage
$ soothe -p "Calculate 2+2" --verbosity minimal
4  # No plan, no reasoning, no lifecycle

$ soothe -p "Calculate 2+2" --verbosity detailed
[plan] ● Calculate 2+2 (1 step)  # No reasoning text
  ├ S_1: Calculate [completed]
[tool] datetime: ...
The answer is 4
✓ Done. Daemon running.
```

---

#### Day 9: Thread List Improvements (IG-084 Phase 2 Step 4)

**Files**:
- `src/soothe/cli/commands/thread_cmd.py`

**Changes**:
1. Add `--limit` option for pagination
2. Add `--today` filter
3. Hide empty Topic column
4. Suppress tool warnings in normal mode
5. Fill Topic with first user message summary

**Testing**:
```bash
$ soothe thread list --limit 10
[Shows 10 most recent threads, clean output]

$ soothe thread list --today
[Shows today's threads only]

$ soothe thread list
[No "Unknown tool group" warnings]
```

---

#### Day 10: Integration Testing Week 2

**Test all display quality improvements**:

```bash
# Minimal verbosity test suite
./tests/integration/test_verbosity_modes.sh

# Cases:
- Simple math query → extracted answer
- Complex query → full response
- Tool calls → suppressed in minimal
- Plan creation → suppressed in minimal
- Protocol events → suppressed in minimal/quiet/normal
- Lifecycle messages → suppressed in minimal

# Daemon stability test suite
./tests/integration/test_daemon_lifecycle.sh

# Cases:
- Auto-start → persistence
- Graceful shutdown → no SIGKILL
- Multiple requests → same daemon
- Client exit → daemon persists
```

---

### Week 3: Consistency & Polish (Days 11-15)

#### Day 11: Standardize Lifecycle Messages (Optimization 3)

**Files**:
- `src/soothe/utils/lifecycle_messages.py`
- `src/soothe/cli/commands/daemon_cmd.py`
- `src/soothe/cli/execution/daemon.py`
- `src/soothe/ux/tui/app.py`

**Changes**:
1. Apply lifecycle message templates everywhere
2. Ensure consistent format across TUI/non-TUI
3. Add emoji/icons for TUI (optional)

**Testing**:
```bash
# Non-TUI consistency
$ soothe daemon start --verbosity normal
✓ Daemon started

$ soothe -p "test" --verbosity detailed --no-tui
✓ Done. Daemon running (PID: 123).

# TUI consistency (visual check)
$ soothe
TUI shows same emoji/format
```

---

#### Day 12: Quickstart Command (IG-084 Phase 3 Step 5)

**Files**:
- `src/soothe/cli/commands/quickstart_cmd.py` (new file)
- `src/soothe/cli/main.py`

**Implementation**:
```python
@app.command("quickstart")
def quickstart():
    """Interactive first-time setup guide.

    Steps:
    1. Check if config exists → offer to create
    2. Check API keys → guide user to add
    3. Run test query → "Hello! I'm Soothe"
    4. Show next steps
    """
    console = Console()

    # Step 1: Configuration
    if not config_path().exists():
        console.print("[bold]Welcome to Soothe![/bold]")
        console.print("Let's set up your configuration.")

        if Confirm.ask("Create default config at ~/.soothe/config.yml?"):
            run_config_init()
            console.print("✓ Config created")
        else:
            console.print("Skipping config (optional for basic usage)")

    # Step 2: API Keys
    console.print("\n[bold]API Keys[/bold]")
    console.print("Soothe works without API keys (uses datetime, wikipedia, arxiv tools).")
    console.print("For advanced features, add keys to config:")
    console.print("  - openai_api_key: ChatGPT models")
    console.print("  - anthropic_api_key: Claude models")
    console.print("  - tavily_api_key: Web search")

    # Step 3: Test Query
    console.print("\n[bold]Test Run[/bold]")
    if Confirm.ask("Run a test query?"):
        result = run_quick_test("Hello! Who are you?")
        console.print(f"\n✓ Response: {result}")

    # Step 4: Next Steps
    console.print("\n[bold]Next Steps[/bold]")
    console.print("1. Try: soothe 'your question'")
    console.print("2. Interactive TUI: soothe")
    console.print("3. Headless: soothe -p 'your question' --no-tui")
    console.print("4. Check health: soothe checkhealth")
    console.print("5. View config: soothe config show")
    console.print("\n✓ Setup complete! Happy agent building!")
```

---

#### Day 13: Help Text Polish

**Files**:
- `src/soothe/cli/main.py`
- `src/soothe/cli/commands/*.py`

**Changes**:
1. Add examples to all command docstrings
2. Add explanation text for complex commands
3. Improve option descriptions
4. Add cross-references between commands

**Testing**:
```bash
$ soothe --help
[Shows examples in main help]

$ soothe daemon --help
[Shows daemon lifecycle explanation]

$ soothe thread --help
[Shows thread management examples]
```

---

#### Day 14: User Guide Update

**File**: `docs/user_guide.md`

**Add sections**:
1. Daemon Lifecycle Management
   - Auto-start behavior
   - Client exit vs daemon shutdown
   - Persistence semantics
2. Verbosity Modes
   - Minimal/quiet/normal/detailed/debug hierarchy
   - When to use each level
   - Output examples for each
3. Quick Start Guide
   - First-time setup steps
   - Configuration basics
   - Test query examples

---

#### Day 15: Final Verification & Testing

**Run full verification suite**:
```bash
./scripts/verify_finally.sh
```

**Must pass**:
- All unit tests (900+ tests)
- All integration tests
- Linting (zero errors)
- Formatting checks

**Manual testing checklist**:
- [ ] Minimal verbosity works for all query types
- [ ] Daemon lifecycle stable (no SIGKILL)
- [ ] Client exit leaves daemon running
- [ ] Lifecycle messages consistent across modes
- [ ] Config show works without crash
- [ ] Checkhealth has correct exit codes
- [ ] Thread list pagination/filtering works
- [ ] Quickstart guides new users successfully
- [ ] Help text includes examples

---

## Success Metrics

### Before (Current Broken State)

```bash
# Config crash
$ soothe config show
AttributeError: 'MemUConfig' object has no attribute 'database_provider'

# Checkhealth false failures
$ soothe checkhealth
✗ CRITICAL (8 errors, 0 warnings)

# Minimal verbosity too verbose
$ soothe -p "2+2" --verbosity minimal
[plan] ● Calculate... [reasoning...] [lifecycle...]

# Daemon instability
$ soothe daemon restart
Daemon did not stop within 8.0 seconds, sending SIGKILL

# Thread list overload
$ soothe thread list
Unknown tool group 'research', skipping.
[113 threads unpaginated]
```

### After (Fixed Optimized State)

```bash
# Config works
$ soothe config show
✓ Memory Backend: MemU

# Checkhealth accurate
$ soothe checkhealth
✓ System healthy (3 optional checks skipped)

# Minimal verbosity clean
$ soothe -p "2+2" --verbosity minimal
4

$ soothe -p "Calculate 15% of 847" --verbosity minimal
127.05

# Daemon stable
$ soothe daemon restart
Daemon stopped gracefully.
Daemon started (PID: 12345).

# Thread list paginated
$ soothe thread list --limit 10
[10 recent threads, no warnings]

# Quickstart guides users
$ soothe quickstart
Welcome to Soothe!
✓ Setup complete! Happy agent building!
```

---

## Architecture Benefits

### Two-Layer Filtering

1. **Event Classification** (Stream level):
   - Early routing decisions
   - Thread log classification
   - Debugging support

2. **Display Policy** (Output level):
   - Final output gatekeeper
   - Robust filtering guarantee
   - Testable and debuggable

**Defense in Depth**: Even if classification fails, display policy catches leakage.

### Verbosity Hierarchy Clarity

- **minimal**: Scripting/automation (answer only)
- **quiet**: Quick queries (answer + brief tools)
- **normal**: Interactive use (tools + answer)
- **detailed**: Progress visibility (plan + steps + tools)
- **debug**: Deep debugging (everything)

Each level has clear use case, no ambiguity.

### Daemon Lifecycle Stability

- Graceful shutdown with timeout
- Client exit → daemon persists
- Only explicit stop → shutdown
- Unified messaging across modes

---

## Testing Strategy

### Unit Tests

**New test files**:
- `tests/unit/test_stream_classifier.py` (>95% coverage)
- `tests/unit/test_display_policy.py` (>95% coverage)
- `tests/unit/test_lifecycle_messages.py` (>90% coverage)
- `tests/unit/test_daemon_lifecycle.py` (>90% coverage)

### Integration Tests

**New test files**:
- `tests/integration/test_verbosity_modes.py`
- `tests/integration/test_daemon_persistence.py`
- `tests/integration/test_client_detach.py`

### Manual Testing Scripts

Create executable test scripts:
```bash
scripts/test_verbosity_modes.sh  # Test all 5 verbosity levels
scripts/test_daemon_lifecycle.sh  # Test daemon persistence scenarios
scripts/test_cli_commands.sh      # Test all CLI commands
```

---

## Rollback Plan

If critical issues arise:

1. **Daemon instability**: Revert to IG-085 draft state, implement graceful shutdown first
2. **Display policy bugs**: Fallback to IG-084 event filtering only
3. **Verbosity confusion**: Rename hierarchy (minimal→answer, quiet→compact, normal→default)

**Git strategy**: Feature branch `feature/cli-ux-master-optimization`, merge after verification.

---

## Dependencies

**Blocked by**: None (can start immediately)
**Blocks**: Future UX improvements depend on this foundation

**Related RFCs**:
- RFC-0003: CLI TUI Architecture (updated by IG-085)
- RFC-0013: Daemon Communication Protocol (updated by IG-085)
- RFC-0020: Event Display Architecture (alignment needed)

**Related IGs**:
- IG-084: CLI UX Optimization (merged into this)
- IG-085: Daemon Lifecycle Polish (merged into this)

---

## Implementation Timeline

**Total Effort**: 3 weeks (15 days)

**Week 1**: Foundation (daemon lifecycle, bug fixes, event classification)
**Week 2**: Display quality (display policy, stream cleanup, thread list)
**Week 3**: Consistency & polish (lifecycle messages, quickstart, help text, user guide)

**Milestones**:
- Day 5: Daemon stable, blocking bugs fixed
- Day 10: Display quality complete, minimal verbosity working
- Day 15: All polish complete, verification passing

---

## Post-Implementation Tasks

1. Update RFC index with daemon lifecycle semantics
2. Add IG-086 to docs/impl/ index
3. Create verbosity modes reference doc
4. Update CLAUDE.md with daemon lifecycle behavior
5. Consider future enhancements:
   - Configurable daemon idle timeout
   - Client reconnect after crash
   - Web UI daemon dashboard

---

## Key Innovations

### 1. Display Policy Layer
**Novel**: Final gatekeeper approach provides robust filtering guarantee
**Advantage**: Defense in depth, testable, debuggable
**vs IG-084**: IG-084 filters at stream level, display policy enforces at output

### 2. Revised Verbosity Hierarchy
**Novel**: Clear use-case mapping for each level
**Advantage**: Users know exactly what to expect
**vs IG-084**: IG-084's "minimal" still shows tools, new "minimal" shows answer only

### 3. Unified Lifecycle Messages
**Novel**: Template-based formatting with verbosity awareness
**Advantage**: Consistent UX across TUI/non-TUI, testable
**vs Current**: Ad-hoc formatting scattered across codebase

---

## Discussion Items

### Decision 1: Verbosity Level Naming

**Options**:
- A: minimal/quiet/normal/detailed/debug (my proposal)
- B: minimal/normal/detailed/debug (IG-084, minimal shows tools)

**Recommendation**: Option A (5 levels)
**Rationale**: "minimal" should mean minimal (answer only), "quiet" provides middle ground

### Decision 2: Answer Extraction Heuristics

**Options**:
- A: Pattern matching for math/fact queries (my proposal)
- B: Always show full response (simpler)

**Recommendation**: Option A with fallback to B
**Rationale**: Automation users expect clean answers, but fallback ensures reliability

### Decision 3: Implementation Order

**Options**:
- A: IG-085 → IG-084 → New optimizations (my proposal)
- B: IG-084 → IG-085 → New optimizations
- C: Parallel implementation

**Recommendation**: Option A (daemon stability first)
**Rationale**: Daemon instability blocks reliable UX testing

---

## Next Steps

1. **User approval**: Discuss this plan, get sign-off on priorities
2. **Implementation**: Start Week 1 (daemon lifecycle + bug fixes)
3. **Verification**: Run testing after each phase
4. **Documentation**: Update RFCs, user guide, CLAUDE.md

---

**Implementation Status**: Ready to begin upon user approval

**Questions for Discussion**:
1. Verbosity hierarchy: 5 levels vs 4 levels?
2. Answer extraction: Pattern matching vs always full response?
3. Implementation order: Daemon first vs display first?
4. Priority adjustments: Any issues more/less urgent?
5. Scope changes: Add/remove any optimizations?