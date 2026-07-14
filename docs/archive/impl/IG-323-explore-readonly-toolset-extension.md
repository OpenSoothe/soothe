# IG-323: Explore subagent — extend read-only toolset

**Status**: Completed  
**Scope**: Add Soothe built-in readonly filesystem tools to the explore subagent alongside deepagents glob/grep/ls/read_file.

## Change

- `get_explore_tools` uses `SootheFilesystemMiddleware` (same backend boundary as before) and whitelists: `glob`, `grep`, `ls`, `read_file`, **`file_info`**.
- Mutating tools (`write_file`, `edit_file`, `execute`, `delete_*`, surgical writes) remain excluded.
- `execute_action_node` records `file_info` results into findings using `tool_call_id` → args path.

## Files

- `packages/soothe/src/soothe/subagents/explore/tools.py`
- `packages/soothe/src/soothe/subagents/explore/engine.py`
- `packages/soothe/src/soothe/subagents/explore/prompts.py`
- `packages/soothe/tests/unit/subagents/explore/test_explore_tools.py`

## Verification

```bash
./scripts/verify_finally.sh
```
