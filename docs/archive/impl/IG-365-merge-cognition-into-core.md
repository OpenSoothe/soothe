# IG-365: Merge `soothe.cognition` subpackages into `soothe.core`

**Status**: Complete  
**Scope**: Relocate autonomous-goal and AgentLoop code under `soothe.core` for a single framework package boundary.

## Moves

| Former path | New path |
|-------------|----------|
| `soothe.cognition.agent_loop` | `soothe.core.agent_loop` |
| `soothe.cognition.goal_engine` | `soothe.core.goal_engine` |
| `soothe.cognition.channel` | `soothe.core.channel` |
| `soothe.cognition.intention` | `soothe.core.intention` |
| `soothe.cognition.scheduler` | `soothe.core.goal_engine.scheduled_tasks` |

`soothe.core.scheduling` (DAG/concurrency) is unchanged; RFC-204 cron/delay scheduler lives under `goal_engine` as `scheduled_tasks` to keep autonomous goal concerns together.

## Follow-up (no Python package shims)

- **Removed**: `soothe.cognition` Python package, legacy serde module paths for `soothe.cognition.agent_loop.*`, and `from soothe.cognition import …` imports. Use `soothe.core.goal_engine`, `soothe.core.agent_loop`, etc.
- **Wire events**: Event type strings remain under the `soothe.cognition.*` namespace (RFC-403 domain); that is unrelated to the removed import package.

## Tests

Mirror source layout: `tests/unit/core/agent_loop/`, `tests/unit/core/goal_engine/`, etc.

## Verification

Run `./scripts/verify_finally.sh` before merge to main.
