# IG-323: Fix Explore Subagent Routing - LLM Directive Enforcement

**Status**: In Progress  
**Date**: 2026-04-30  
**Scope**: Fix `/explore` routing bug where Claude subagent was invoked instead of Explore

---

## Problem Statement

**Bug**: `/explore` queries routed to Claude subagent instead of Explore subagent

**Evidence** (soothed.log analysis - Thread `n5xdyprutlfm`, 14:32:04):
```
preferred_subagent='explore'  ← ✅ Routing classification correct
<SUBAGENT_ROUTING_DIRECTIVE>  ← ✅ Directive injected
tools narrowed to 'task' only  ← ✅ Enforcement correct
Claude subagent starting  ← ❌ Wrong subagent!
tool=Bash (shell execution)  ← ❌ Wrong toolset
```

**Root Cause**: LLM ignored routing directive and chose Claude instead of honoring `subagent_type='explore'`

---

## Solution

**Strategy**: Strengthen directive enforcement + add debug logging

### 1. Enhanced Directive Text

**File**: `packages/soothe/src/soothe/middleware/system_prompt_optimization.py:354-365`

**Change**: Added explicit warnings to prevent LLM substitution:

```python
f"CRITICAL INSTRUCTION:\n"
f"- The subagent_type argument MUST be exactly '{subagent_directive}' (not 'claude', 'browser', etc.)\n"
f"- Do NOT substitute or override this choice with a different subagent\n"
f"- The user selected {subagent_directive} for a specific reason and will be confused if you use a different one\n"
```

**Rationale**: Make it impossible for LLM to misunderstand the directive

---

### 2. Debug Logging

**File**: `packages/soothe/src/soothe/core/agent/_patch.py:120-126`

**Change**: Added logging to track actual `subagent_type` argument:

```python
logger.debug(
    "[Task Tool] subagent_type='%s' description='%s' directive='%s'",
    subagent_type,
    description[:100],
    runtime.state.get("_subagent_routing_directive", "none"),
)
```

**Rationale**: Confirm hypothesis and detect future routing issues

---

## Files Modified

| File | Lines | Changes |
|------|-------|---------|
| `packages/soothe/src/soothe/core/agent/_patch.py` | 9-11, 120-126 | Added logger + debug logging |
| `packages/soothe/src/soothe/middleware/system_prompt_optimization.py` | 351-365 | Enhanced directive enforcement |

---

## Expected Behavior After Fix

**Before Fix**:
```
Query: "/explore count all files types"
→ preferred_subagent='explore' (correct)
→ Claude subagent invoked (wrong)
→ Bash/shell tools used (wrong)
```

**After Fix**:
```
Query: "/explore count all files types"
→ preferred_subagent='explore' (correct)
→ Directive: "subagent_type MUST be 'explore'"
→ LLM passes subagent_type='explore' (forced)
→ Explore subagent invoked (correct)
→ Readonly tools: glob/grep/ls/read_file (correct)
→ Debug log: "[Task Tool] subagent_type='explore' directive='explore'"
```

---

## Verification

**Command**: `./scripts/verify_finally.sh`

**Expected Results**:
- ✅ All tests pass (1363+ tests)
- ✅ No lint/format errors
- ✅ Code changes validated

**Post-Verification Testing**:
1. Run `/explore` query via CLI
2. Check soothed.log for `[Task Tool]` debug messages
3. Verify explore subagent invoked (not Claude)
4. Confirm readonly tools used

---

## Related Work

- **IG-322**: Explore prompt routing and parallel checkpoint isolation
- **RFC-613**: Explore subagent design
- **RFC-605**: Parallel subagent spawning

---

## Success Criteria

✅ `/explore` queries route to explore subagent  
✅ Explore uses readonly tools (no shell execution)  
✅ Debug logs confirm correct routing  
✅ All tests pass  
✅ No regression in other subagent routing (`/browser`, `/claude`, `/research`)

---

## Implementation Notes

**Design Decision**: Enhanced prompt enforcement instead of code-level routing

**Reasoning**:
- LLM behavior issue (not code bug)
- Task tool routing logic is correct
- Explore IS registered in `subagent_graphs`
- Problem is LLM choosing wrong `subagent_type` value

**Alternative Considered**: Remove other subagents from task tool description when directive present

**Rejected**: Would require modifying deepagents upstream code (invasive)

**Chosen Approach**: Prompt engineering (minimal, safe, immediate fix)

---

## Testing Plan

### Test Case 1: Basic `/explore` Routing

**Query**: `/explore find Python files in cognition/`

**Expected Log**:
```
[Task Tool] subagent_type='explore' directive='explore'
Explore subagent starting
tool=glob, tool=grep, tool=read_file
```

**Should NOT See**: `Claude subagent starting`, `tool=Bash`

---

### Test Case 2: All Subagent Routing

**Test each directive**:
- `/browser open x.com` → browser
- `/claude reason` → claude  
- `/research AI papers` → research
- `/explore search config` → explore

**Verify**: Each routes to correct subagent

---

## Risk Assessment

**Risk Level**: LOW

**Justification**:
- Changes are minimal and well-contained
- Logging is debug-level (non-invasive)
- Directive text is prompt-only (no code logic)
- No test modifications required
- No upstream dependencies affected

**Potential Issues**:
- LLM might still ignore directive (unlikely with explicit warnings)
- Logging reveals unexpected patterns (good for debugging)

---

## Next Steps

1. ✅ Code changes implemented
2. ⏳ Verification running (`./scripts/verify_finally.sh`)
3. ⏳ Test `/explore` query via CLI
4. ⏳ Verify explore subagent invoked
5. ⏳ Update IG-323 status to completed
6. ⏳ Commit changes with IG-323 reference

---

## References

- soothed.log analysis: `/tmp/why_claude_subagent_analysis.md`
- Routing flow diagram: `/tmp/soothed_log_routing_analysis.md`
- Implementation details: `/tmp/explore_routing_fix_IG-323.md`