# IG-509: Loop 7cba Hang Analysis

**RFC**: N/A (Incident analysis from log forensics)
**Created**: 2026-06-26
**Status**: Analysis complete — fixes pending
**Logs**: `~/.soothe/logs/soothe.log`, `~/.soothe/logs/daemon.log`, `~/.soothe/data/loops/019f01c8-56e9-73d1-9271-0ca7ba307cba/runner.log`

## Executive Summary

Loop `[7cba]` (`019f01c8-56e9-73d1-9271-0ca7ba307cba`) **did not crash**. It **hung** inside step `UZH-02` when the `explore` subagent triggered workspace-root grep operations that fell back to an unbounded Python `os.walk()` over `/Users/chenxm/Workspace/soothe`. The daemon remained healthy; `thread-worker-0` never completed its request. The TUI stopped receiving events because the worker thread blocked with no request-level timeout.

| Question | Answer |
|----------|--------|
| Did the runner crash? | **No** |
| Which worker? | `thread-worker-0`, request `49d8bc28a17c4b44` |
| Where did it hang? | Explore subagent → grep → Python walk fallback |
| Last activity | 2026-06-26 10:47:25 CST |
| Daemon state | Alive (PID 45119), ~100% CPU on blocked grep |

## Goal and Context

**User input** (2026-06-26 10:35:58):

> anlyze ~/.soothe/logs/soothe.log of loop 3328, classify the errors, analyze why step "Write unit tests for identify service components" failed with "Stream ended unexpectedly" and how to optimize it. analyze why we have only four steps displayed on TUI but the logs recorded more steps

This is a meta-analysis task: loop `[7cba]` was created to investigate failures observed in loop `[3328]`.

**Daemon context**: The daemon had restarted cleanly at 10:34:49 (PID 45119, Soothe v0.6.12) in **thread pool mode** (`min=2`, `max=8`, `idle_timeout=300s`, `max_requests=100`, `request_timeout=0`).

## Timeline

| Time (CST) | Source | Event |
|------------|--------|-------|
| 10:34:40 | daemon.log | Previous daemon stopped |
| 10:34:49 | daemon.log | New daemon starts; thread pool pre-warmed (`thread-worker-0`, `thread-worker-1`) |
| 10:35:34 | daemon.log | `loop_new` → loop `019f01c8-...` created (workspace: `/Users/chenxm/Workspace/soothe`) |
| 10:35:58 | daemon.log | `loop_input` queued; `thread-worker-0 starting request` |
| 10:35:58 | soothe.log | Loop worker logging enabled; StrangeLoop iteration 0 starts |
| 10:36:23 | soothe.log | Plan generated: 2 steps (`UZH-01`, `UZH-02`) |
| 10:36:23 | soothe.log | Execute `UZH-01`: extract/classify loop 3328 log entries |
| 10:41:06 | soothe.log | `UZH-01` completed (~283s, 53 tool calls) |
| 10:41:07 | soothe.log | Execute `UZH-02`: root-cause analysis (stream failure + TUI step count) |
| 10:46:37 | soothe.log | `explore` subagent launched (TUI adapter, plan_decision, executor code search) |
| **10:47:25** | soothe.log | **Last `[7cba]` log**: grep on repo root; `ag` skipped (>200 files); Python walk fallback |
| 10:47:50 | daemon.log | Last `event_size_stats` batch to TUI client (512 events) |
| 10:49:52+ | both logs | Periodic `thread-worker-1` idle timeout / respawn (unrelated spare worker) |

After 10:47:25, **`soothe.log` shows zero `[7cba]` entries**. Loop metadata remained `"status": "running"` with a stale `updated_at`.

## Evidence: Not a Crash

### soothe.log

- No `worker exit`, `orphan`, `Stream ended unexpectedly`, or step-failure log for `[7cba]`
- No `Step UZH-02 completed` or `Step UZH-02 failed`
- Daemon process alive; no separate loop worker child process (thread pool runs inside daemon)

### daemon.log

- `thread-worker-0 starting request loop=019f01c8-...` at 10:35:58
- **Never** logs `thread-worker-0 completed request` for this loop
- **Never** logs `thread-worker-0 thread ended (busy=True, ...)`
- **Never** logs `Worker thread exited unexpectedly during query execution`
- WebSocket session for loop owner remained connected

### Misleading log lines (not crash recovery)

Every ~5 minutes, `daemon.log` shows:

```
Thread worker thread-worker-1 idle timeout (300s), exiting
Thread worker thread-worker-1 exiting after 0 requests
ThreadPool: respawning dead worker thread-worker-1
[WorkerRunner] Warmed SootheRunner for worker reuse
```

These refer to the **idle spare worker** (`thread-worker-1`), which never received work. The matching `[main] SootheRunner initialized` lines in `soothe.log` are warmup on respawn, **not** recovery from loop `[7cba]` crashing.

## Root Cause

### Primary: Unbounded Python grep fallback

At 10:47:25, the explore subagent inside step `UZH-02` issued grep operations on the workspace root. Two parallel greps logged:

```
Directory /Users/chenxm/Workspace/soothe has >200 files, skipping ag to avoid FD exhaustion
```

When `ag` is skipped proactively, `grep_with_ag()` returns `None` and `LocalFilesystem.grep()` falls through to `_grep_python_walk()`:

```python
# packages/soothe/src/soothe/foundation/core/filesystem/local.py
if is_ag_available():
    ag_result = grep_with_ag(...)
    if ag_result is not None:
        return ag_result
return self._grep_python_walk(...)  # unbounded os.walk, no timeout, no ignore dirs
```

`_grep_python_walk()`:

- Walks the **entire** directory tree with `os.walk()`
- Does **not** skip `.venv`, `node_modules`, `.git`, etc.
- Reads every file with `f.read()` (no size cap)
- Has **no timeout**

On a repo containing `.venv` and other large trees, this can run indefinitely and peg CPU — consistent with daemon at ~100% CPU and complete log silence.

**Irony**: IG-503 added the FD pre-flight check to *prevent* `ag` from exhausting file descriptors, but the fallback path is worse for large workspaces because it performs a synchronous full-tree scan in the worker thread.

### Secondary: No request-level timeout in thread pool

From `thread_runner.py`:

- `idle_timeout_seconds=300` applies only while **waiting** on `request_queue.get()` — not during active execution
- `request_timeout_seconds` defaults to **0** (disabled)

A hung tool call can hold `thread-worker-0` forever with no pool-level recovery.

### Contributing factors (non-fatal)

During `UZH-02` before the hang:

| Issue | Log evidence |
|-------|--------------|
| `UnicodeDecodeError` in `run_command` | Reading `large_tool_results/` blobs |
| `ValueError: No checkpointer set` | Step completion interrupt detection (also seen on loop 3328) |
| Large step output | `UZH-01` ledger output ~142KB slowed iteration |
| Explore read_file path errors | Subagent used `/packages/soothe/...` instead of workspace-relative paths (recovered via `glob`) |

## Architecture Diagram

```
TUI client
    │ loop_input (10:35:58)
    ▼
daemon main thread
    │ dispatch to thread-worker-0
    ▼
thread-worker-0  ──►  StrangeLoop iter 0
                           ├── UZH-01 ✓ (10:41:06)
                           └── UZH-02 (in progress)
                                 └── explore subagent
                                       └── grep(workspace root)
                                             ├── ag skipped (>200 files)
                                             └── _grep_python_walk()  ← HUNG

thread-worker-1  ──►  idle → 300s timeout → respawn (normal, unrelated)
```

## Plan Progress at Hang

| Step | Status | Duration | Notes |
|------|--------|----------|-------|
| `UZH-01` | Completed | ~283s | 53 tool calls; extracted loop 3328 log data |
| `UZH-02` | **Stuck** | >6 min at hang | Root-cause analysis; explore subagent grep blocked |

Iteration 0 never completed → TUI showed no further progress.

## Recommended Fixes

### P0 — Grep fallback safety

1. When `_should_skip_ag_due_to_fd_limit()` returns true, **do not** fall back to unbounded Python walk on large directories. Options:
   - Return an explicit error telling the agent to narrow scope
   - Run bounded subprocess grep with ignore patterns (`.venv`, `.git`, `node_modules`)
   - Cap walk depth / file count / total bytes read
2. Add timeout to `_grep_python_walk()` (mirror `_AG_GREP_TIMEOUT_S = 120`)
3. Apply standard ignore directories in Python walk (same as FD pre-flight check)

### P1 — Thread pool request timeout

- Enable non-zero `request_timeout_seconds` in daemon config, or
- Add watchdog that marks stuck requests failed and frees the worker slot

### P2 — Operational

- Document that broad repo-root greps from explore subagent are high-risk on large workspaces
- Consider scoping explore default search paths to `packages/` rather than workspace root

## Immediate Recovery

1. **Cancel the loop** from TUI, or
2. **Restart the daemon** (`soothe daemon restart` or kill PID 45119)

Either action frees `thread-worker-0`. The loop checkpoint may remain `running` until explicitly cleared.

## Related Work

- [IG-503](IG-503-file-descriptor-leak-and-network-resilience-fixes.md) — FD pre-flight for `ag` (introduced the skip that triggers this fallback)
- [IG-507](IG-507-loop-3328-log-analysis-fixes.md) — Original loop 3328 issues this meta-loop was investigating
- [IG-508](IG-508-step-full-description.md) — Step description context loss (relevant to why agent re-grepped instead of using step-01 output)

## Verification (when fixes land)

1. Unit test: grep on workspace with >200 top-level files returns error or bounded result, not infinite walk
2. Integration: explore subagent grep on soothe repo completes within timeout
3. Thread pool: hung request triggers timeout and worker recovery within configured deadline
4. `./scripts/verify_finally.sh` passes
