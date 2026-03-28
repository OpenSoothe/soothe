# IG-084: CLI UX Optimization - Real User Experience Analysis

**Status**: In Progress
**Created**: 2026-03-28
**Scope**: Critical UX fixes based on real CLI usage analysis

---

## Overview

This implementation guide documents critical UX improvements identified through real-world CLI testing. Issues were discovered by running actual CLI commands and analyzing output from a product management perspective focused on user experience.

---

## Problems Identified

### Priority 1: Blocking Bugs

#### 1. `config show` Command Crash
**Severity**: BLOCKER
**Impact**: Users cannot view their configuration

**Error**:
```
AttributeError: 'MemUConfig' object has no attribute 'database_provider'
```

**Location**: `src/soothe/ux/cli/commands/config_cmd.py:89`

**Root Cause**: Code assumes config structure that doesn't match actual schema. MemUConfig doesn't have `database_provider` attribute.

**Fix**: Add proper attribute checking before accessing config fields.

---

#### 2. `checkhealth` False Failures
**Severity**: HIGH
**Impact**: Users think system is broken when it's working fine

**Problem**:
- Exit code 2 (critical) for optional component warnings/skips
- External API timeouts count as "errors" (not actionable)
- Skipped checks due to missing config count as "errors"
- 8 "errors" reported when most are skips/timeouts

**Current Output**:
```
✗ CRITICAL (8 errors, 0 warnings)
```

**Reality**:
- Configuration: Skipped (no config loaded) - not an error
- External APIs: Optional, network timeouts - not actionable
- System is actually healthy for basic usage

**Fix**: Improve exit code logic and categorization:
- Exit 0: All critical checks pass (warnings OK)
- Exit 1: Warnings present
- Exit 2: Critical failures only (config missing, daemon unreachable)
- Mark optional checks clearly
- Distinguish "skipped" from "failed"

---

### Priority 2: Major UX Issues

#### 3. `thread list` Information Overload
**Severity**: HIGH
**Impact**: Users can't find relevant threads, feel overwhelmed

**Problems**:
- Shows 113 threads in unpaginated table
- Warning: "Unknown tool group 'research', skipping" at top
- Empty "Topic" column wastes space
- No pagination, filtering, or limit options

**Fix**:
- Add `--limit` option for pagination
- Hide empty columns (Topic)
- Suppress tool warnings in normal mode (move to --debug)
- Add `--today` filter
- Fill Topic with meaningful summary (first user message)

---

#### 4. Headless Mode Shows Internal Events
**Severity**: HIGH
**Impact**: Looks broken/unprofessional, obscures actual results

**Current Output**:
```
[lifecycle] Thread kq4p0o3f8adu created
[protocol] 0 entries, 0 tokens
[plan] ● Calculate 15% of 847 (1 steps)
Pydantic serializer warnings...
```

**User Wants**: Clean answer: "127.05"

**Fix**: Implement verbosity-based filtering:
- `minimal`: Show only final answer
- `normal`: Show tool results + final answer
- `detailed`: Show plan + steps + tool results
- `debug`: Show all internal events + warnings

Suppress Pydantic warnings in non-debug modes.

---

### Priority 3: User Guidance

#### 5. No First-Time User Guidance
**Severity**: MEDIUM
**Impact**: New users don't know where to start

**Problems**:
- `checkhealth` says "Run 'soothe config init'" but no explanation
- No quick start guide
- No progressive disclosure

**Fix**:
- Add `soothe quickstart` command with guided onboarding
- Improve help messages with examples and explanations
- Show next steps after initial setup

---

## Implementation Plan

### Phase 1: Fix Blocking Bugs (Priority 1)

#### Step 1: Fix config show crash
**Files**: `src/soothe/ux/cli/commands/config_cmd.py`

**Changes**:
```python
# Line 89 - BEFORE (crashes):
general_table.add_row("Memory Backend", cfg.protocols.memory.database_provider.title())

# AFTER - Check attribute exists:
memory_backend = (
    cfg.protocols.memory.database_provider.title()
    if hasattr(cfg.protocols.memory, 'database_provider')
    else cfg.protocols.memory.backend.title()
)
general_table.add_row("Memory Backend", memory_backend)
```

**Testing**: Run `soothe config show` successfully without crash.

---

#### Step 2: Improve checkhealth exit codes
**Files**: `src/soothe/ux/cli/commands/health_cmd.py`

**Changes**:
1. Separate critical checks from optional checks
2. Track warnings separately from errors
3. Update exit code logic:
   - Exit 0 if all critical checks pass
   - Exit 1 if warnings present
   - Exit 2 only for critical failures

4. Mark optional checks clearly:
```
○ External APIs (optional)
  ℹ OpenAI API: Not configured (optional for basic usage)
```

5. Distinguish "skipped" from "failed":
   - Use ○ for skipped
   - Use ✗ for failed
   - Use ✓ for passed

**Testing**:
- Run without config: Should exit 1 (warnings), not 2 (critical)
- Run with config but no external APIs: Should exit 0 (healthy)

---

### Phase 2: Clean Output (Priority 2)

#### Step 3: Headless output filtering
**Files**: `src/soothe/ux/cli/commands/run_cmd.py`, `src/soothe/ux/core/event_display.py`

**Changes**:
1. Add verbosity-based event filtering
2. Suppress Pydantic warnings in non-debug modes
3. Hide lifecycle/protocol events in minimal mode

**Implementation**:
```python
# In run_cmd.py
if verbosity == "minimal":
    # Show only final assistant message
    event_filter = lambda e: e.type == "assistant_message"
elif verbosity == "normal":
    # Show tool results + assistant messages
    event_filter = lambda e: e.type in ["tool_result", "assistant_message"]
elif verbosity == "detailed":
    # Show plan, steps, tools, assistant
    event_filter = lambda e: e.type in ["plan", "step", "tool_result", "assistant_message"]
# debug: show all events

# Suppress Pydantic warnings
import warnings
if verbosity != "debug":
    warnings.filterwarnings("ignore", category=UserWarning, module="pydantic")
```

**Testing**:
- `soothe -p "2+2" --no-tui --verbosity minimal`: Shows only "4"
- `soothe -p "2+2" --no-tui --verbosity normal`: Shows tool results + "4"
- `soothe -p "2+2" --no-tui --verbosity detailed`: Shows plan + steps + tools + "4"

---

#### Step 4: Improve thread list
**Files**: `src/soothe/ux/cli/commands/thread_cmd.py`

**Changes**:
1. Add `--limit` option:
```python
limit: Annotated[
    int | None,
    typer.Option("--limit", "-l", help="Limit number of threads shown."),
] = None,
```

2. Add `--today` filter:
```python
today: Annotated[
    bool,
    typer.Option("--today", help="Show only today's threads."),
] = False,
```

3. Hide empty Topic column
4. Suppress tool warnings (move to logger.debug)
5. Fill Topic with first user message summary

**Testing**:
- `soothe thread list --limit 10`: Shows last 10 threads
- `soothe thread list --today`: Shows today's threads
- No "Unknown tool group" warning at top

---

### Phase 3: User Guidance (Priority 3)

#### Step 5: Add quickstart command
**Files**: `src/soothe/ux/cli/main.py`, `src/soothe/ux/cli/commands/quickstart_cmd.py`

**Implementation**: Create guided onboarding:
```python
@app.command("quickstart")
def quickstart() -> None:
    """Interactive first-time setup guide.

    Steps:
    1. Check if config exists → offer to create
    2. Check API keys → guide user to add
    3. Run test query → "Hello! I'm Soothe"
    4. Show next steps
    """
```

**Testing**: Run `soothe quickstart` as new user.

---

## Verification

After all changes, run:
```bash
./scripts/verify_finally.sh
```

Must pass:
- Code formatting check
- Linting (zero errors)
- Unit tests (900+ tests)

---

## Expected Results

### Before (Current Broken State)

```bash
$ soothe config show
AttributeError: 'MemUConfig' object has no attribute 'database_provider'

$ soothe checkhealth
✗ CRITICAL (8 errors, 0 warnings)

$ soothe thread list
Unknown tool group 'research', skipping.
[113 threads in unpaginated table]

$ soothe -p "2+2" --no-tui
[lifecycle] Thread... [protocol]... Pydantic warnings... 4
```

### After (Fixed State)

```bash
$ soothe config show
Memory Backend: MemU
✓ Configuration loaded from ~/.soothe/config.yml

$ soothe checkhealth
✓ System healthy (2 optional checks skipped)

$ soothe thread list --limit 10
[10 most recent threads, clean output]

$ soothe -p "2+2" --no-tui --verbosity minimal
4
```

---

## Success Metrics

- **config show**: Works without crash, shows clear summary
- **checkhealth**: Accurate status, actionable recommendations
- **thread list**: Paginated, clean, no warnings
- **headless**: Clean output matching verbosity level
- **quickstart**: New users can get started in <2 minutes

---

## Related

- RFC-0013: Daemon Communication Protocol
- RFC-0020: Event Display Architecture
- IG-053: CLI Command Nesting
- IG-082: TUI Event Display Polish

---

## Notes

All fixes maintain backward compatibility. No breaking changes to existing behavior, only improvements to output clarity and error handling.