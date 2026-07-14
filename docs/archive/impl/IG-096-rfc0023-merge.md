# IG-096: RFC-100 Merge into RFC-400 and RFC-201

**Status**: Completed
**Created**: 2026-03-29
**Related**: RFC-400, RFC-201

## Summary

RFC-100 (Daemon Query Performance and Readiness Architecture) was a standalone spec covering daemon readiness reliability and agentic loop performance optimizations. Its content has been merged into the appropriate owning RFCs and the standalone spec deleted.

## Merge Distribution

| Content | Destination RFC | Reason |
|---------|-----------------|--------|
| Daemon lifecycle phases (starting → warming → ready → degraded → error) | RFC-400 | Daemon protocol ownership |
| Staged startup architecture | RFC-400 | Daemon startup ownership |
| Readiness handshake protocol | RFC-400 | Client-server protocol ownership |
| Stale daemon cleanup | RFC-400 | Daemon lifecycle ownership |
| DAEMON_BUSY rejection | RFC-400 | Error code ownership |
| Query execution tiers (fast, light-agentic, full-agentic) | RFC-201 | Agentic loop execution ownership |
| Query-scoped observation reuse | RFC-201 | Observation phase ownership |
| Token-count planning strategy | RFC-201 | Planning strategy ownership |
| Early termination optimization | RFC-201 | Verification phase ownership |
| Query timing instrumentation | RFC-201 (partial) and RFC-400 (startup) | Distributed by phase |

## Implementation Work Completed

### Phase 1: Daemon Readiness (RFC-400 domain)

Files modified:
- `src/soothe/daemon/server.py` — Added daemon-level readiness state/event
- `src/soothe/daemon/_handlers.py` — Added readiness handshake message
- `src/soothe/daemon/client.py` — Added `wait_for_daemon_ready()` helper
- `src/soothe/ux/cli/execution/headless.py` — Removed socket-only readiness check
- `src/soothe/ux/cli/execution/daemon.py` — Restructured bootstrap order
- `src/soothe/ux/cli/commands/daemon_cmd.py` — Detached start reports success only after readiness

Key behaviors:
- Headless startup waits for protocol-level daemon readiness
- Clients retry boundedly while daemon reports `starting` or `warming`
- Startup failure surfaces explicit lifecycle error instead of generic timeout
- DAEMON_BUSY rejection for overlapping requests on same thread
- Stale daemon cleanup before restart

### Phase 2: Observation Reuse (RFC-201 domain)

Files modified:
- `src/soothe/core/runner/_types.py` — Extended `RunnerState` with query-scoped observation metadata
- `src/soothe/core/runner/_runner_agentic.py` — Changed `_agentic_observe()` to reuse query-scoped observation
- `src/soothe/core/runner/_runner_steps.py` — Stopped unconditional per-step recall/projection
- `src/soothe/core/runner/_runner_phases.py` — Conservative memory-to-context reinjection

Key behaviors:
- Observation snapshot reused across iterations after iteration 0
- Refresh only on replan, materially changed scope, or explicit escalation
- Step execution inherits parent observation by default

### Phase 3: Planning Strategy Optimization (RFC-201 domain)

Files modified:
- `src/soothe/core/runner/_runner_agentic.py` — Reuse `state.plan` across iterations
- `src/soothe/cognition/planning/simple.py` — Updated `_build_plan_prompt()` for smaller fast-verifiable steps

Key behaviors:
- Token-count threshold determines no-plan path (≤ threshold → direct stream)
- Plans favor fewest useful steps, independently checkable, short evidence-gathering
- Existing plan reused unless revision explicitly required

## Tests

Tests extended:
- `tests/unit/test_cli_daemon.py` — Daemon readiness behavior
- `tests/unit/test_daemon_lifecycle.py` — Lifecycle state transitions
- `tests/unit/test_planning.py` — Planning strategy heuristics
- `tests/unit/test_runner_checkpoint.py` — Observation reuse

Test behaviors verified:
- Headless startup succeeds when socket connectable before daemon ready
- Startup failure surfaces explicit error, not generic timeout
- Repeated iterations reuse query-scoped observation
- Replan invalidates and refreshes observation
- Token-count threshold routes to no-plan path correctly

## Verification

- `./scripts/verify_finally.sh` — All tests pass

## Post-Merge Actions

1. Deleted RFC-100 standalone file
2. Updated RFC-400 with daemon readiness sections
3. Updated RFC-201 with observation reuse and planning optimization sections
4. Updated RFC index to remove RFC-100 entry
5. Updated RFC history to document merger

## Files Changed

```
docs/specs/RFC-400-daemon-communication-protocol.md  # Merged daemon readiness
docs/specs/RFC-201-agentic-loop-execution.md          # Merged observation reuse, planning
docs/specs/rfc-index.md                                # Removed RFC-100 entry
docs/specs/rfc-history.md                              # Documented merger
docs/specs/RFC-100-daemon-query-performance-and-readiness.md  # DELETED
```

## Conclusion

RFC-100 content now lives in its proper owning specs. The daemon reliability fixes and agentic loop optimizations are documented where they belong architecturally.