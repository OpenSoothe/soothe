# IG-181: Optimize Headless Error Handling Performance

**Status**: In Progress
**Created**: 2026-04-16
**RFCs**: RFC-0019 (EventProcessor), RFC-401 (Event Processing)

---

## Problem

The test `test_run_headless_via_daemon_returns_direct_error_before_query_start` has performance issues because the current implementation in `daemon.py:run_headless_via_daemon()` doesn't exit immediately when receiving an error before query starts.

**Current behavior**:
- Receives error event with type `"error"` or `soothe.error.*` before `query_started=True`
- Still waits for 20-second `_QUERY_START_TIMEOUT_S` before returning
- Unnecessary heartbeat timeout tracking complexity
- Error checking happens deep inside the loop instead of early exit

**Test scenario**:
- Mock client returns: status → daemon_ready → status with thread → subscription_confirmed → **error (DAEMON_BUSY)**
- Error arrives *before* sending input, but code still waits for timeout
- Expected: immediate return with exit code 1
- Actual: waits up to 20 seconds before returning

---

## Root Cause Analysis

### Issue 1: Late Error Detection (Lines 165-177)

```python
# Detect errors before query started as a hard failure
ev_data = event.get("data")
if event_type == "error":
    typer.echo(f"Daemon error: {event.get('message', 'unknown')}", err=True)
    return 1

if (
    not query_started
    and isinstance(ev_data, dict)
    and str(ev_data.get("type", "")).startswith("soothe.error")
):
    typer.echo(f"Daemon error: {ev_data.get('error', 'unknown')}", err=True)
    return 1
```

**Problem**: This check happens AFTER the timeout logic on line 96-103, so we've already waited.

### Issue 2: Timeout Applied Even When Error Received (Lines 96-103)

```python
if query_started:
    event = await client.read_event()
else:
    # Extend timeout if heartbeat received recently
    time_since_heartbeat = asyncio.get_event_loop().time() - last_heartbeat
    effective_timeout = max(1.0, _QUERY_START_TIMEOUT_S - time_since_heartbeat)
    event = await asyncio.wait_for(client.read_event(), timeout=effective_timeout)
```

**Problem**: Timeout is applied BEFORE checking if the received event is an error. Should exit immediately on error.

### Issue 3: Heartbeat Complexity

Heartbeat tracking (lines 111-119, 141-145) adds overhead and complexity for timeout extension, but errors should just exit immediately regardless of heartbeat state.

---

## Solution

### Optimization Strategy

**Early exit pattern**: Check for errors immediately after reading event, BEFORE any timeout logic.

```python
# Read event (with timeout only if query not started)
try:
    if query_started:
        event = await client.read_event()
    else:
        event = await asyncio.wait_for(client.read_event(), timeout=_QUERY_START_TIMEOUT_S)
except TimeoutError:
    return _DAEMON_FALLBACK_EXIT_CODE

if not event:
    break

# IMMEDIATE error check - exit before any other processing
event_type = event.get("type", "")
if event_type == "error":
    typer.echo(f"Daemon error: {event.get('message', 'unknown')}", err=True)
    return 1

# Check soothe.error.* events before query starts
ev_data = event.get("data")
if (
    not query_started
    and isinstance(ev_data, dict)
    and str(ev_data.get("type", "")).startswith("soothe.error")
):
    typer.echo(f"Daemon error: {ev_data.get('error', 'unknown')}", err=True)
    return 1
```

### Changes

1. **Move error checks to top of loop** - before timeout/heartbeat logic
2. **Remove heartbeat timeout extension** - simpler logic, immediate exit on error
3. **Keep timeout for query start only** - but don't apply if error already received

---

## Implementation Plan

### Step 1: Refactor Main Loop

File: `packages/soothe-cli/src/soothe_cli/cli/execution/daemon.py`

- Remove heartbeat timeout tracking (lines 91-93, 111-119)
- Move error checks to line 108 (immediately after `if not event: break`)
- Simplify timeout logic to only apply when `not query_started`

### Step 2: Update Test Expectations

File: `packages/soothe/tests/unit/cli/test_cli_daemon.py`

- Test should verify immediate return (no 20-second delay)
- Mock client returns error immediately after subscription_confirmed
- Existing assertions should pass without changes

### Step 3: Verify

```bash
./scripts/verify_finally.sh
```

---

## Expected Performance Impact

- **Before**: Error at t=0 → waits up to 20 seconds → returns at t=20
- **After**: Error at t=0 → checks immediately → returns at t=0
- **Performance gain**: ~20 seconds faster for pre-query errors

---

## Risks

1. **Heartbeat handling removal**: Need to verify if heartbeat is actually used elsewhere
   - RFC-401 and RFC-0019 don't mention heartbeat for timeout extension
   - Heartbeat likely for daemon health monitoring, not query timeout

2. **Timeout semantics**: Ensure timeout still applies for legitimate "waiting for query start" cases
   - Timeout should only fire if daemon is unresponsive
   - Error events should exit immediately regardless

---

## Verification Checklist

- [ ] Error events exit immediately before query starts
- [ ] Timeout still applies for legitimate delays
- [ ] Test `test_run_headless_via_daemon_returns_direct_error_before_query_start` passes
- [ ] All other headless tests pass
- [ ] Lint check passes (zero errors)
- [ ] Full test suite passes (900+ tests)

---

## References

- Test file: `packages/soothe/tests/unit/cli/test_cli_daemon.py:487`
- Implementation: `packages/soothe-cli/src/soothe_cli/cli/execution/daemon.py:32`
- RFC-0019: `docs/specs/RFC-0019-event-processor.md`
- RFC-401: `docs/specs/RFC-401-event-processing.md`