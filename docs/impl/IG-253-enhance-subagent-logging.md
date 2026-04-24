# IG-253: Enhance Subagent Logging

## Status
🟡 In Progress

## Summary
Enhance logging coverage across all subagents (explore, research, browser, claude) to provide comprehensive visibility into LLM decisions, tool executions, and iteration progress. Currently, explore subagent has minimal logging (only 2 warnings), while browser and claude have good coverage.

## Motivation
- **Observability**: Users need visibility into what subagents are doing, especially in TUI and log files
- **Debugging**: Comprehensive logging helps diagnose issues during complex multi-step searches
- **Consistency**: Subagents should have uniform logging patterns for maintainability
- **RFC-613**: Explore agent design requires visibility for iterative LLM-orchestrated search

## Scope
- **Primary**: `packages/soothe/src/soothe/subagents/explore/engine.py`
- **Secondary**: Review logging in:
  - `packages/soothe/src/soothe/subagents/research/engine.py`
  - `packages/soothe/src/soothe/subagents/browser/implementation.py`
  - `packages/soothe/src/soothe/subagents/claude/implementation.py`

## Analysis

### Current State

#### Explore Subagent (`explore/engine.py`)
- ❌ **Minimal logging**: Only 2 `logger.warning` calls
  - Line 107: "LLM did not produce tool calls, using fallback glob"
  - Line 129: "No tool calls to execute"
- ✅ **Progress events**: Uses `emit_progress` for event broadcasting
- ❌ **No info/debug logs** for:
  - Search target initialization
  - LLM planning decisions
  - Tool execution details
  - Assessment decisions
  - Iteration progress
  - Synthesis operations

#### Research Subagent (`research/engine.py`)
- ✅ **Good event coverage**: Uses `_emit_progress` helper throughout
- ✅ **Debug logging**: Line 369 for source failures
- ❌ **Limited info logging**: Could benefit from more structured logging

#### Browser Subagent (`browser/implementation.py`)
- ✅ **Excellent coverage**: 20+ `logger.info` calls
- ✅ **Consistent pattern**: Info-level logging for all major operations
- ✅ **Warning coverage**: LLM intent detection failures
- ✅ **Debug coverage**: Detailed operation info

#### Claude Subagent (`claude/implementation.py`)
- ✅ **Good debug coverage**: Multiple `logger.debug` calls
- ❌ **Limited info logging**: Mostly debug-level, less visible in normal logs

### Logging Patterns to Follow

From browser subagent (best example):
```python
# High-level operation start
logger.info("Browser subagent: task preview: %s", preview_first(str(task), 400))

# Decision points
logger.info("Intent detection for '%s...': %s", preview_first(prompt, 50), result)

# Tool execution
logger.info("Browser subagent: calling browser_session.start()")

# Resource management
logger.info("Cleaned up %d stale Chrome process(es)", killed)
```

## Implementation Plan

### Phase 1: Explore Subagent Enhancement (Primary)

Add structured logging at all key decision points in `explore/engine.py`:

#### 1.1 `plan_search_node` (lines 70-119)
- [ ] Add `logger.info` for search target initialization (first iteration)
- [ ] Add `logger.debug` for LLM planning call details
- [ ] Add `logger.info` for tool calls generated (name + count)
- [ ] Add `logger.debug` for fallback glob pattern

#### 1.2 `execute_action_node` (lines 121-189)
- [ ] Add `logger.info` for tool execution start (tool name)
- [ ] Add `logger.debug` for tool execution details (args preview)
- [ ] Add `logger.info` for findings extraction results (count + paths)
- [ ] Add `logger.debug` for snippet extraction details

#### 1.3 `assess_results_node` (lines 191-236)
- [ ] Add `logger.info` for assessment decision (continue/adjust/finish)
- [ ] Add `logger.debug` for assessment reasoning (iterations used vs max)
- [ ] Add `logger.info` for iteration budget status

#### 1.4 `synthesize_node` (lines 252-292)
- [ ] Add `logger.info` for synthesis start (total findings)
- [ ] Add `logger.debug` for synthesis timing (elapsed_ms)
- [ ] Add `logger.info` for final result summary (matches returned)

#### 1.5 Module-level logging setup
- [ ] Ensure logger is configured with module name (already done at line 37)

### Phase 2: Research Subagent Review

Review `research/engine.py` for logging gaps:

- [ ] Check if `_emit_progress` provides sufficient visibility
- [ ] Consider adding `logger.info` for:
  - Topic analysis completion
  - Query generation count
  - Source selection decisions
  - Reflection decisions
- [ ] Ensure consistency with explore patterns

### Phase 3: Browser & Claude Review

Review existing logging for consistency:

- [ ] Verify browser logging follows established patterns (✅ already good)
- [ ] Consider adding more `logger.info` to claude subagent (currently debug-heavy)
- [ ] Ensure log message formats are consistent across subagents

## Logging Guidelines

### Message Format
- **Info level**: User-visible progress updates
  - Format: `"Explore subagent: <operation> - <summary>"`
  - Example: `"Explore subagent: planning search for 'authentication module'"`
- **Debug level**: Detailed diagnostic information
  - Format: `"Explore: <component> - <details>"`
  - Example: `"Explore: assessment - iterations_used=2, max_iterations=4"`

### What to Log at INFO Level
- Operation starts/completions
- Decision outcomes (continue/adjust/finish)
- Tool execution summaries (name, count)
- Resource allocation/cleanup
- Final results (count, duration)

### What to Log at DEBUG Level
- LLM call details (prompt preview)
- Tool arguments preview
- Internal state transitions
- Performance metrics (timing)
- Iteration budgets

### Preview Helpers
Use existing utilities for truncation:
```python
from soothe.utils.text_preview import preview_first

logger.info("Explore: tool call - %s (args: %s)", tool_name, preview_first(str(args), 100))
```

## Testing Strategy

1. **Manual testing**: Run subagent with verbose logging enabled
   ```bash
   SOOTHE_LOG_LEVEL=DEBUG soothe "find authentication module"
   ```
2. **Log inspection**: Verify all decision points have appropriate logs
3. **TUI verification**: Ensure logs appear in TUI output
4. **Unit tests**: No new tests needed (logging is side effect)

## Verification Checklist

Before committing:
- [ ] Run `./scripts/verify_finally.sh` (format, lint, tests)
- [ ] Manually test explore subagent with DEBUG logging
- [ ] Verify logs appear in both terminal and log files
- [ ] Check log messages follow consistent format
- [ ] Ensure no sensitive data in logs (paths, user queries OK)

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Verbose logging noise | Use INFO for key decisions, DEBUG for details |
| Performance overhead | Logging is minimal overhead compared to LLM calls |
| Log format inconsistency | Follow browser subagent patterns |

## Estimated Impact

- **Explore engine**: ~15-20 new log statements
- **Research engine**: ~5-10 additional log statements
- **Browser/Claude**: Minimal changes (already good)

## Success Criteria

✅ Explore subagent has comprehensive logging at all decision points
✅ All subagents follow consistent logging patterns
✅ Logs provide visibility into LLM decisions and tool execution
✅ Verification script passes (lint + tests)

## References

- **RFC-613**: Explore agent design (`docs/specs/RFC-613-explore-agent-design.md`)
- **Browser logging**: `packages/soothe/src/soothe/subagents/browser/implementation.py`
- **Logging utilities**: `packages/soothe/src/soothe/utils/text_preview.py`

---

## Implementation Notes

(Added during implementation)