# IG-485: Fix Proposal Tools Not Loaded + Add Resume Command

## Goal
1. Fix the root cause where `suggest_goal` and `add_finding` proposal tools were never loaded into the agent's available tools
2. Add CLI/HTTP resume command to reactivate suspended goals

## Problem
Goals were being suspended with reasoning like:
- "the goal explicitly requires using the suggest_goal tool... there's no evidence that suggest_goal was invoked"
- "agent merely echoed the goal description rather than invoking suggest_goal"

Investigation revealed that the agent **never had access to the `suggest_goal` tool** because the `"proposal"` tool group was missing from the hardcoded list in `resolve_tools()`.

## Root Cause
In `_resolver_tools.py:157-172`, the enabled tool groups list hardcoded:
```python
enabled_tools = [
    name
    for name in [
        "execution", "file_ops", "datetime", "data", "wizsearch",
        "http_requests", "image", "audio", "video", "deepxiv",
    ]  # <-- "proposal" was NOT in this list!
    ...
]
```

Even though:
1. `ToolsConfig` has `proposal: ToolConfig` field (enabled by default)
2. `_resolve_single_tool_group()` has handling for `"proposal"` (line 534)

The agent never received `suggest_goal` and `add_finding` tools, so goals requiring them failed consensus validation.

## Fix 1: Add proposal to tool groups list
Added `"proposal"` to the tool groups list in `resolve_tools()`:

```python
enabled_tools = [
    name
    for name in [
        "execution",
        "file_ops",
        "datetime",
        "data",
        "wizsearch",
        "http_requests",
        "image",
        "audio",
        "video",
        "deepxiv",
        "proposal",  # RFC-204 Group C: suggest_goal, add_finding tools
    ]
    ...
]
```

**Result**: Agent now has 39 tools (was 37) including `suggest_goal` and `add_finding`.

## Fix 2: Add resume command for suspended goals
Added HTTP REST endpoint, SDK client method, and CLI command to reactivate suspended goals:

- **HTTP**: `POST /api/v1/autopilot/goals/{goal_id}/resume`
- **SDK**: `AutopilotHttpClient.resume(goal_id)`
- **CLI**: `soothe autopilot resume <goal_id>`

## Files Modified
1. `packages/soothe/src/soothe/core/resolver/_resolver_tools.py` - Add "proposal" to tool groups
2. `packages/soothe-daemon/src/soothe_daemon/channels/http_rest.py` - Add resume endpoint
3. `packages/soothe-sdk/src/soothe_sdk/client/autopilot_http.py` - Add resume method
4. `packages/soothe-cli/src/soothe_cli/cli/commands/autopilot_cmd.py` - Add resume command

## Verification
- Ran `./scripts/verify_finally.sh` - all 537 tests passed

## Usage
To resume a suspended goal:
```bash
# List goals to see suspended ones
soothe autopilot jobs

# Resume a specific goal
soothe autopilot resume 8b59e5f4
```

## Status
✅ Completed

> **Note (IG-504)**: The HTTP REST endpoint, `channels/http_rest.py`, and
> `autopilot_http.py` references below are superseded by IG-504 (Remove HTTP REST
> Channel). The resume command now uses WebSocket via `WsCommandClient`. These
> HTTP REST references are retained for historical context only.