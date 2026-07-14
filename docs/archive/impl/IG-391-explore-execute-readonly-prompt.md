# IG-391: Explore — add `execute`, mandatory read-only tool rules

**Status**: Completed  
**Scope**: Expose deepagents `execute` on the explore subagent; strengthen `EXPLORE_AGENT_SYSTEM` with non-negotiable read-only constraints for **all** tools including shell. No `run_readonly_command` wrapper.

## Files

| Path |
|------|
| `packages/soothe/src/soothe/subagents/explore/tools.py` |
| `packages/soothe/src/soothe/subagents/explore/prompts.py` |
| `packages/soothe/src/soothe/subagents/explore/middleware.py` |
| `packages/soothe/src/soothe/subagents/explore/engine.py` |
| `packages/soothe/tests/unit/subagents/explore/test_explore_tools.py` |

## Verification

```bash
./scripts/verify_finally.sh
```
