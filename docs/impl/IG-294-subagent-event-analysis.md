# Subagent Events Analysis - Performance Optimization Recommendations

## Current Status (IG-256 + IG-257)

### CLI (Headless Mode)
- **IG-256**: Suppressed all `soothe.capability.*` and `.subagent.*` events
- Pipeline returns empty list for these events (line 168-174)
- **Impact**: Task tool events flow through naturally as regular tools
- **Result**: No subagent-specific event processing in CLI

### TUI (Textual Mode)
- **Still processes** `soothe.capability.*` events
- textual_adapter.py line 277: `if event_type.startswith("soothe.capability.")`
- Passes events through `progress_pipeline.process()`
- But: IG-256 suppressed subagent handlers in StreamDisplayPipeline

**Question**: Does TUI actually need subagent events?

## Subagent Event Emission Points

### Browser Subagent
**File**: `packages/soothe/src/soothe/subagents/browser/implementation.py:219-225`
- Emits: `BrowserDispatchedEvent` (soothe.capability.browser.started)
- Usage: Display task preview in progress

**Also emits** step events during browser automation:
- Browser step events (step.running, etc.)
- Browser CDP events

### Research Subagent
**File**: `packages/soothe/src/soothe/subagents/research/engine.py:236-246`
- Emits: `ResearchDispatchedEvent`, `ResearchAnalyzeEvent`, etc.
- 14+ different event types defined
- Usage: Show research progress phases (analyzing, gathering, synthesizing)

### Claude Subagent
**File**: `packages/soothe/src/soothe/subagents/claude/events.py`
- Emits: `ClaudeStartedEvent`, `ClaudeTextEvent`, `ClaudeToolUseEvent`, `ClaudeResultEvent`
- Usage: Show Claude's internal text and tool usage

## Recommendations

### Option 1: Delete All Subagent Events (Maximum Performance)

**Daemon side deletions**:
- Remove event emission in browser/implementation.py (line 222-225)
- Remove event emission in research/engine.py (line 236-246, etc.)
- Remove event emission in claude subagent

**Impact**:
- ✅ Reduced event emission overhead (significant for research with 14+ events)
- ✅ Smaller event queues
- ❌ TUI loses subagent progress display
- ❌ Need to verify TUI actually uses these meaningfully

### Option 2: Keep Minimal Events (Balanced)

**Keep only**:
- `*.started` events (dispatch/dispatched)
- `*.completed` events

**Delete internal progress events**:
- Browser step events
- Research analyze/gather/synthesize events
- Claude text/tool events

**Impact**:
- ✅ TUI shows dispatch + completion only
- ✅ Reduced overhead by ~60-80%
- ❌ Less detailed progress info

### Option 3: Conditional Emission (Smart)

**Emit only when needed**:
- Check if TUI is active before emitting detailed events
- Add verbosity flag to daemon

**Impact**:
- ✅ CLI mode: no emission overhead
- ✅ TUI mode: full progress display
- ❌ Requires daemon-to-client communication

## Task Tool Display (Polish Recommendations)

### Current Task Display

Task tool is from deepagents, not Soothe-defined.

**Current CLI output** (IG-257 tree structure):
```
○ Step
  └─ ⚙ Task(browser, query)
  └─ ✓ Task result
```

**Polish opportunities**:
1. ✅ Already uses Unicode tree branch "└─" (IG-257)
2. ✅ Already indented under step (IG-257)
3. Could add subagent icon differentiation (but IG-256 restored uniform wrench)

### Recommendation: Keep Current Task Display

Task display is already polished with:
- Unicode tree branches
- Step context indentation
- Uniform wrench emoji (per IG-256)

No further changes needed for Task tool display.

## Performance Impact Estimate

### Current Emission Cost

**Browser subagent**:
- 1 dispatch event + multiple step events per automation
- ~5-20 events per browser run

**Research subagent**:
- 14+ events per research query
- High overhead for complex queries

**Claude subagent**:
- 4+ events per Claude session

### If Deleted (Option 1)

**Savings**:
- Browser: 5-20 events → 0 events = 100% reduction
- Research: 14+ events → 0 events = 100% reduction
- Claude: 4+ events → 0 events = 100% reduction

**Overall**: 100% subagent event overhead eliminated

### If Minimal (Option 2)

**Savings**:
- Browser: 5-20 events → 2 events = 60-90% reduction
- Research: 14+ events → 2 events = ~85% reduction
- Claude: 4+ events → 2 events = 50% reduction

**Overall**: ~70-85% overhead reduction

## Verification Steps

Before deleting events:

1. **Check TUI actual usage**:
   ```bash
   # Run TUI and verify if subagent events show meaningful progress
   soothe "search for current time"  # Uses browser
   soothe "research AI trends"  # Uses research
   ```

2. **Check if TUI handles suppressed events gracefully**:
   - TUI adapter calls pipeline.process()
   - Pipeline returns [] for subagent events (IG-256)
   - TUI should already show nothing for subagent events

3. **If TUI shows nothing currently**: DELETE all subagent events

4. **If TUI shows meaningful progress**: Use Option 2 (minimal events)

## Implementation Path

### Phase 1: Verify Current TUI Behavior

Run test to see if TUI actually displays subagent events after IG-256:

```bash
# Check TUI display
soothe "research AI trends"
# Observe if research phases show in TUI
```

### Phase 2: Delete Based on Verification

**If TUI shows nothing**:
- Delete all event emission code in subagent implementations
- Remove unused event classes

**If TUI shows progress**:
- Keep minimal events (started, completed)
- Delete internal progress events

## Conclusion

**Task tool display**: Already polished, no changes needed

**Subagent events**: Need verification before deletion
- CLI: Already suppressed (no emission needed)
- TUI: Need to verify actual usage
- Recommendation: Delete after verification

**Next step**: Run TUI test to verify subagent event display behavior