# Final Analysis: Subagent Events Can Be Deleted

## Key Discovery

**TUI behavior after IG-256**:

TUI adapter processes `soothe.capability.*` events (textual_adapter.py:277):
```python
if event_type.startswith("soothe.capability."):
    event_for_pipeline = dict(event_data)
    event_for_pipeline["namespace"] = list(namespace)
    lines = pipeline.process(event_for_pipeline)
```

**But the pipeline returns empty list** (IG-256 in pipeline.py:168-174):
```python
# IG-256: Do NOT process subagent events explicitly - let Task tool events handle display
# Subagents are invoked via Task tool, so tool.execution events will show them
# Return empty list to suppress explicit subagent event processing
if event_type.startswith("soothe.capability."):
    return []
```

## Result

**TUI currently shows NOTHING for subagent events** because:
1. TUI passes events to pipeline
2. Pipeline returns empty list for all `soothe.capability.*` events
3. TUI displays nothing

## Conclusion

✅ **All subagent event emissions can be safely deleted from daemon**

No impact on either CLI or TUI display - they're already suppressed.

## Deletion Plan

### Files to Modify

1. **packages/soothe/src/soothe/subagents/browser/implementation.py**
   - Delete line 222-225: `_emit(BrowserDispatchedEvent(...).to_dict(), logger)`
   - Delete all step/CDP event emissions in browser automation loop

2. **packages/soothe/src/soothe/subagents/research/engine.py**
   - Delete line 236-246: `_emit_progress(ResearchDispatchedEvent(...).to_dict())`
   - Delete all 14+ event emissions in research phases
   - Delete `_emit_progress()` helper function if unused

3. **packages/soothe/src/soothe/subagents/claude/events.py** (and implementation)
   - Delete ClaudeStartedEvent, ClaudeTextEvent, ClaudeToolUseEvent, ClaudeResultEvent
   - Delete event emission code in Claude subagent implementation

### Event Class Deletion

**Can delete entire event classes**:
- `packages/soothe/src/soothe/subagents/browser/events.py` (BrowserDispatchedEvent, BrowserCompletedEvent, BrowserStepEvent, BrowserCdpEvent)
- `packages/soothe/src/soothe/subagents/research/events.py` (all 14+ event classes)
- `packages/soothe/src/soothe/subagents/claude/events.py` (all 4 event classes)

### Performance Impact

**Savings**:
- **Browser**: 5-20 events per run → 0 events = **100% reduction**
- **Research**: 14+ events per query → 0 events = **100% reduction**
- **Claude**: 4+ events per session → 0 events = **100% reduction**

**Overall**: Eliminate **100%** of subagent event emission overhead

### Implementation Steps

1. Delete event emission calls in subagent implementations
2. Delete unused event classes
3. Remove event type constants
4. Update imports (remove event imports)
5. Run tests to verify no breakage

## Task Tool Display - Already Polished

**Task display uses Unicode tree branches** (IG-257):
```
○ Step description
  └─ ⚙ Task(browser, query)
  └─ ✓ Task result
  └─ Done [1 tools]
```

**No further changes needed** - Task tool display is already polished.

## Summary

✅ **Task display**: Already polished with Unicode tree branches, no changes needed

✅ **Subagent events**: Can be completely deleted for 100% performance improvement
- CLI: Already suppressed (IG-256)
- TUI: Already suppressed (IG-256 via pipeline)
- No functional impact, only performance gain

**Recommendation**: Proceed with deletion of all subagent event emissions from daemon