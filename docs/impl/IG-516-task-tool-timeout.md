# IG-516: Fix Task Tool Timeout for Subagent Invocation

## Problem

When invoking subagents (explore, browser_use, etc.) via the `task` tool, the timeout middleware applied the default 60s timeout instead of the intended timeout for subagent operations. This caused:

1. **Premature timeout**: The `task` tool timed out after 60s
2. **Race condition**: The subagent continued running in background after timeout
3. **UI inconsistency**: Step card showed failure while subagent card showed "running"

### Evidence from Loop b3d7

```
20260627T221030.576 - Task tool invoked with subagent_type='explore'
20260627T221110.064 - Explore budget exhausted, synthesis started
20260627T221130.638 - Tool timeout middleware fired at 60s (WRONG!)
20260627T221130.651 - Error returned, step marked failed
```

The explore subagent was synthesizing results (takes ~20s for LLM call) when the timeout hit.

## Root Cause

The timeout middleware's `SUBAGENT_TOOL_NAMES` included:
- `browser_use`, `explore`, `plan`, `tacitus`, `delegate`

But when the agent invokes subagents, it uses the **`task` tool** from deepagents, which wraps the actual subagent invocation. The `task` tool name was missing from the list, so it fell through to the default 60s timeout.

## Solution

### Timeout Values

| Tool | Timeout | Reason |
|------|---------|--------|
| `task` | 86400s (24h) | Autonomous subagent work can run for extended periods |
| `explore` | 1800s (30min) | Exploration searches, reads files, synthesizes |
| `browser_use` | 1800s (30min) | Browser automation can take time for complex tasks |
| Default | 60s | Standard tools |

### Implementation

1. **Add `DEFAULT_TASK_TIMEOUT_SECONDS` constant** (24 hours)

```python
DEFAULT_TASK_TIMEOUT_SECONDS: float = 86400.0  # 24 hours
DEFAULT_SUBAGENT_TIMEOUT_SECONDS: float = 1800.0  # 30 minutes
```

2. **Special handling for `task` tool** in `_get_timeout_for_tool`

```python
if tool_name == "task":
    return DEFAULT_TASK_TIMEOUT_SECONDS
```

3. **Update Pydantic defaults and config template**

```yaml
tool_timeout:
  per_tool:
    explore: 1800.0  # 30 minutes
    browser_use: 1800.0  # 30 minutes
    task: 86400.0  # 24 hours
```

## Verification

- All unit tests pass
- Config template matches Pydantic defaults
- `./scripts/verify_finally.sh` passes

## Impact

- Subagent invocations via `task` tool now have proper 24h timeout
- Explore/browser_use have 30min timeout (sufficient for most operations)
- No more premature timeouts during synthesis phase
- Step and subagent cards stay consistent

## Related

- IG-511: Original tool timeout middleware implementation