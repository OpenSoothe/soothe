# IG-244: Remove Thread Writable Commands (Loop-First UX)

> **Implementation Guide**: IG-244 - Remove User-Side Thread Writable Commands
> **RFC**: RFC-503 (Loop-First User Experience)
> **Status**: In Progress
> **Created**: 2026-04-22
> **Dependencies**: IG-238 (Completion Status)

---

## Executive Summary

Remove user-side writable thread subcommands from CLI as part of loop-first UX transformation. Users interact with loops, not threads. Threads are internal implementation details managed by AgentLoop.

**Writable commands to REMOVE**:
- `soothe thread continue` - writable (creates/activates thread)
- `soothe thread archive` - writable (modifies thread status)
- `soothe thread delete` - writable (destroys thread)
- `soothe thread tag` - writable (modifies metadata)
- `soothe thread create` - writable (creates new thread)

**Read-only commands to KEEP**:
- `soothe thread list` - read-only (view threads)
- `soothe thread show` - read-only (view thread details)
- `soothe thread stats` - read-only (view statistics)
- `soothe thread export` - read-only (export data)
- `soothe thread artifacts` - read-only (view artifacts)

---

## Motivation

Per RFC-503 and IG-238, the new user model is **loop-first**:
- Users manage loops (primary entity)
- Threads are internal execution contexts
- Thread lifecycle is managed internally by AgentLoop
- Users should not create, archive, delete, or modify threads directly

**Thread commands purpose after removal**:
- Debugging/diagnostics only (read-only inspection)
- Internal state visibility for advanced users
- No user-facing thread lifecycle management

---

## Implementation Tasks

### Phase 1: Remove Writable Commands from CLI Main

**File**: `packages/soothe-cli/src/soothe_cli/cli/main.py`

Remove command registrations:
```python
# REMOVE these commands:
@thread_app.command("continue")  # ❌ Remove
@thread_app.command("archive")   # ❌ Remove
@thread_app.command("delete")    # ❌ Remove
@thread_app.command("tag")       # ❌ Remove
@thread_app.command("create")    # ❌ Remove
```

**Keep these commands**:
```python
# KEEP these commands:
@thread_app.command("list")      # ✅ Read-only
@thread_app.command("show")      # ✅ Read-only
@thread_app.command("stats")     # ✅ Read-only
@thread_app.command("export")    # ✅ Read-only
@thread_app.command("artifacts") # ✅ Read-only
```

---

### Phase 2: Remove Writable Functions from thread_cmd.py

**File**: `packages/soothe-cli/src/soothe_cli/cli/commands/thread_cmd.py`

Remove implementation functions:
```python
# REMOVE these functions:
def thread_continue()  # ❌ Remove (lines 184-252)
def thread_archive()   # ❌ Remove (lines 255-280)
def thread_delete()    # ❌ Remove (lines 334-370)
def thread_tag()       # ❌ Remove (lines 501-582)
def thread_create()    # ❌ Remove (lines 585-629)
```

**Keep these functions**:
```python
# KEEP these functions:
def thread_list()      # ✅ Read-only
def thread_show()      # ✅ Read-only
def thread_stats()     # ✅ Read-only
def thread_export()    # ✅ Read-only
def thread_artifacts() # ✅ Read-only
```

---

### Phase 3: Update Help Text

**File**: `packages/soothe-cli/src/soothe_cli/cli/main.py`

Update thread command group description:
```python
# OLD:
thread_app = typer.Typer(name="thread", help="Manage conversation threads")

# NEW:
thread_app = typer.Typer(
    name="thread",
    help="Inspect conversation threads (read-only diagnostics)"
)
```

Update individual command descriptions:
```python
@thread_app.command("list")
def _thread_list():
    """List all agent threads (read-only diagnostics).

    Examples:
        soothe thread list
        soothe thread list --status active
    """
```

---

### Phase 4: Update Documentation

**Update examples in CLI main.py**:
- Remove writable command examples from docstrings
- Add note about loop-first UX
- Reference loop commands for thread lifecycle management

**Example note**:
```
Note: Thread commands are read-only diagnostics.
For thread lifecycle management, use loop commands:
- soothe loop list (list loops)
- soothe loop describe (show loop with threads)
- soothe loop delete (delete loop and threads)
```

---

### Phase 5: Update CLAUDE.md

**Add guidance for thread commands**:
```markdown
### Thread Commands (Read-Only)
Thread commands are for diagnostics only (loop-first UX):
- `soothe thread list` - List threads (read-only)
- `soothe thread show` - Show thread details (read-only)
- `soothe thread stats` - Show statistics (read-only)
- `soothe thread export` - Export conversation (read-only)
- `soothe thread artifacts` - List artifacts (read-only)

**For thread lifecycle management, use loop commands**:
- Users manage loops (primary entity)
- Threads are internal execution contexts
- Use `soothe loop` commands to manage loops and threads
```

---

## Verification Checklist

1. ✅ Removed writable thread commands from `cli/main.py`
2. ✅ Removed writable functions from `thread_cmd.py`
3. ✅ Updated help text (thread group description)
4. ✅ Updated command descriptions (read-only note)
5. ✅ Updated documentation examples
6. ✅ Loop commands remain unchanged
7. ✅ Read-only thread commands functional
8. ✅ Tests passing

---

## Testing

**Test removed commands**:
```bash
soothe thread continue  # Should fail with "unknown command"
soothe thread archive   # Should fail with "unknown command"
soothe thread delete    # Should fail with "unknown command"
soothe thread tag       # Should fail with "unknown command"
soothe thread create    # Should fail with "unknown command"
```

**Test remaining commands**:
```bash
soothe thread list      # Should work (read-only)
soothe thread show      # Should work (read-only)
soothe thread stats     # Should work (read-only)
soothe thread export    # Should work (read-only)
soothe thread artifacts # Should work (read-only)
```

---

## Related Specifications

- RFC-503: Loop-First User Experience
- RFC-504: Loop Management CLI Commands
- IG-238: AgentLoop Checkpoint Unified Integration (Completion Status)

---

## Success Criteria

1. Writable thread commands removed from CLI ✅
2. Read-only thread commands remain functional ✅
3. Help text updated with read-only note ✅
4. Documentation updated with loop-first UX guidance ✅
5. All tests passing ✅
6. Loop commands unchanged ✅

---

**Implementation Status**: In Progress

**End of IG-244 Implementation Guide**