# Daemon Lifecycle Polish - Design Draft

**Created**: 2026-03-28
**Status**: Draft
**Category**: Architecture Refinement

## Problem Statement

Current daemon behavior creates confusion around daemon lifecycle, thread attachment, and client exit semantics:

1. **Non-TUI Mode**: When running with `-p "prompt"`, the daemon behavior is unclear - does it start/stop with the request?
2. **TUI Mode**: `/exit` and `/quit` commands shutdown the daemon entirely, not just the client connection
3. **Double Ctrl+C**: Inconsistent behavior across modes for interrupt handling
4. **Daemon Persistence**: No clear separation between "exit thread" vs "exit daemon"

## Desired Behavior

### Non-TUI Mode (Headless Single-Prompt)

**Current Flow**:
```
soothe -p "query" → Check daemon → If not running, start daemon → Connect → Execute → Daemon stops?
```

**Polished Flow**:
```
soothe -p "query" → Check daemon
  → If running: Connect, create thread, execute, thread finishes, client disconnects, daemon keeps running
  → If not running: Start daemon, connect, create thread, execute, thread finishes, client disconnects, daemon keeps running in background
```

**Key Changes**:
- Daemon auto-starts if not running (already implemented)
- Creates a thread for the request
- Thread executes and completes
- **Client disconnects**, but daemon remains running
- No implicit daemon shutdown

### TUI Mode

**Current Flow**:
```
soothe → Start daemon → Connect → Interactive session
  → /exit or /quit → Daemon shutdown
  → Ctrl+C once → Cancel current job
  → Ctrl+C twice → Exit TUI (daemon behavior unclear)
```

**Polished Flow**:
```
soothe → Check daemon
  → If running: Attach to existing daemon, create/resume thread
  → If not running: Start daemon, connect, create thread
Interactive session:
  → /exit or /quit → Exit TUI client, daemon keeps running
  → /detach → Explicit detach (daemon keeps running)
  → Ctrl+C once → Cancel current job
  → Ctrl+C twice (within 1s) → Exit TUI client, daemon keeps running
```

**Key Changes**:
- `/exit` and `/quit` become synonyms for `/detach` - they exit the TUI client, not the daemon
- Double Ctrl+C (within 1 second) exits the TUI client cleanly
- Daemon persists after TUI exits
- Clear messaging: "TUI exited, daemon still running (PID: XXX)"

### Daemon Lifecycle Management

**Explicit Daemon Control**:
- `soothed start` - Start daemon in background (foreground mode with `--foreground`)
- `soothed stop` - Stop running daemon (SIGTERM, then SIGKILL if timeout)
- `soothed restart` - Restart daemon
- `soothed status` - Show daemon status (PID, state)

**Daemon Auto-Start Behavior**:
- Non-TUI mode: Auto-start if not running, keep running after request
- TUI mode: Auto-start if not running, keep running after TUI exit
- Daemon remains running across multiple client sessions

**Daemon Shutdown Triggers**:
- Only explicit `soothed stop` command
- System shutdown/SIGTERM to daemon process
- Manual foreground daemon Ctrl+C (when running with `--foreground`)

## Design Questions

### Q1: Should daemon auto-start in TUI mode?

**Option A**: Always auto-start if not running
- Pros: Seamless user experience, no manual daemon management needed
- Cons: User may not realize daemon is running, resource consumption

**Option B**: Prompt user to start daemon if not running
- Pros: User awareness, explicit consent
- Cons: Extra step, breaks flow for new users

**Recommendation**: **Option A** - Auto-start daemon in TUI mode for seamless experience. Show clear message: "Daemon started (PID: XXX). Use 'soothed stop' to shutdown."

### Q2: What happens when daemon crashes during client session?

**Option A**: Client detects daemon disconnect, prompts to restart
- Pros: Graceful recovery, user can continue
- Cons: Complex reconnect logic, state loss

**Option B**: Client exits with error message
- Pros: Simple, clear failure mode
- Cons: Lost session, user must restart manually

**Recommendation**: **Option B** - Client exits with clear error: "Daemon connection lost. Restart with 'soothed start'." Keep simple for initial implementation. Future RFC can add reconnect logic.

### Q3: Should TUI warn before exiting with active thread?

**Option A**: No warning, exit immediately
- Pros: Fast exit, respects user intent
- Cons: Thread state may be incomplete

**Option B**: Warning if thread is in "running" state
- Pros: Prevents accidental exit during execution
- Cons: Extra step, may annoy user

**Recommendation**: **Option B** - Warn if thread is running: "Thread {id} is still running. Exit anyway? (y/n)". If thread is idle, exit immediately without warning.

### Q4: How to handle double Ctrl+C timing?

**Option A**: Any Ctrl+C twice exits
- Pros: Simple, no timing constraint
- Cons: Accidental double-press may exit unintentionally

**Option B**: Ctrl+C twice within 1 second exits
- Pros: Intentional exit, clear signal
- Cons: Timing constraint may be missed

**Recommendation**: **Option B** - Double Ctrl+C within 1 second triggers exit. Show message after first Ctrl+C: "Press Ctrl+C again within 1s to exit TUI."

## Implementation Approach

### Phase 1: Update RFCs

1. **RFC-400**: Add daemon lifecycle semantics section
   - Define daemon persistence behavior
   - Clarify client vs daemon shutdown
   - Update protocol messages if needed

2. **RFC-500**: Update CLI/TUI architecture
   - Clarify `/exit`/`/quit` semantics
   - Define double Ctrl+C behavior
   - Update slash command documentation

### Phase 2: Implementation Guide

1. **Modify daemon client behavior**:
   - Non-TUI: Keep daemon running after request
   - Remove implicit daemon shutdown

2. **Modify TUI exit handlers**:
   - `/exit` and `/quit` → detach and exit TUI
   - Double Ctrl+C detection (1s window)
   - Warning if thread running

3. **Add clear messaging**:
   - "TUI exited, daemon still running (PID: XXX)"
   - "Thread finished, daemon keeps running"

4. **Update CLI documentation**:
   - Help text, examples
   - User guide updates

### Phase 3: Testing

1. **Non-TUI mode tests**:
   - Daemon not running → auto-start → request → daemon keeps running
   - Daemon running → attach → request → daemon keeps running

2. **TUI mode tests**:
   - `/exit` → TUI exits, daemon running
   - `/quit` → TUI exits, daemon running
   - Double Ctrl+C → TUI exits, daemon running
   - Single Ctrl+C → cancel job, stay in TUI

3. **Daemon lifecycle tests**:
   - `soothed start` → daemon running
   - `soothed stop` → daemon stopped
   - Multiple client sessions → daemon persists

## Trade-offs

### Simplicity vs Flexibility

**Simple approach**: Daemon always persists, explicit stop required
- Easy to understand, predictable behavior
- May have resource consumption concerns

**Flexible approach**: Configurable daemon timeout (e.g., stop after 1 hour idle)
- More sophisticated, auto-cleanup
- Adds complexity, user confusion about timeout behavior

**Decision**: **Simple approach** for now. Future RFC can add configurable timeout if needed.

### User Experience vs Resource Efficiency

**UX-focused**: Always auto-start, always persist
- Seamless experience, no friction
- Background daemon resource consumption

**Resource-focused**: Prompt before start, auto-stop on idle
- Efficient resource usage
- Extra steps, breaks flow

**Decision**: **UX-focused** - Prioritize seamless experience. Users can explicitly stop daemon when desired.

## Success Criteria

1. **Non-TUI mode**: Daemon persists after request completion ✓
2. **TUI mode**: `/exit`/`/quit` exit client, daemon keeps running ✓
3. **Double Ctrl+C**: Clean TUI exit within 1s window ✓
4. **Clear messaging**: User understands daemon state at all times ✓
5. **No implicit shutdown**: Only explicit `soothed stop` kills daemon ✓
6. **Backward compatible**: Existing workflows continue working ✓

## Next Steps

1. Proceed to Phase 1: Update RFC-400 and RFC-500
2. Create implementation guide IG-XXX
3. Implement changes following guide
4. Test all scenarios
5. Update user documentation

---

**Status**: Ready for Phase 1 (RFC Updates)