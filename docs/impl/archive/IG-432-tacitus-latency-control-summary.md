# Tacitus Latency Control: Quick Reference

## Overview

This document summarizes the latency optimization mechanisms for the Tacitus deep research subagent.

## Current Bottlenecks

```
Sequential Sources:  15-40s  ████████████████████
LLM Invocations:     10-25s  ████████████
Thread Pool Block:    2-5s   ██
Fixed Loop Depth:    Variable (2-5 loops)
Slow Synthesis:       5-10s   ██████
```

## Proposed Optimizations

### 1. Parallel Source Gathering ⭐ (P0)

**Before**: Query sources one by one
```python
for src in selected:
    results = await src.query(...)  # 4 sources × 5s = 20s
```

**After**: Query all sources concurrently
```python
results = await asyncio.gather(*[
    query_with_timeout(src) for src in selected
])  # max(5s) = 5s
```

**Config**:
```yaml
subagents:
  tacitus:
    enable_parallel_sources: true
    source_timeout_sec: 10.0
```

**Expected Savings**: 10-25s per gather node

---

### 2. Early Loop Termination (P1)

**Trigger Conditions**:
- Sufficient diverse sources (≥3 source types)
- No new information in last iteration
- High confidence in collected results

**Config**:
```yaml
subagents:
  tacitus:
    enable_early_termination: true
    min_results_for_termination: 3
```

**Expected Savings**: 15-30s (1-2 fewer loops)

---

### 3. LLM Invocation Timeouts (P1)

**Prevents**: Hung LLM calls from blocking indefinitely

**Config**:
```yaml
subagents:
  tacitus:
    llm_timeout_sec: 15.0
```

**Expected Savings**: Prevents 30s+ outliers

---

### 4. Fast Synthesis Model (P2)

**Before**: Uses "think" role (slow, high quality)
**After**: Uses "fast" role (fast, sufficient for synthesis)

**Config**:
```yaml
subagents:
  tacitus:
    synthesis_role: "fast"  # Changed from "think"
```

**Expected Savings**: 3-5s on final step

---

## Target Latencies

| Effort | Current | Target | Reduction |
|--------|---------|--------|-----------|
| normal | 25s | 12s | 52% |
| high | 50s | 25s | 50% |
| xhigh | 80s | 40s | 50% |

## Implementation Phases

```
Week 1: Parallel Sources
  └── engine.py: asyncio.gather() for source queries
  └── Add source_timeout_sec config

Week 2: Early Termination + LLM Timeouts
  └── termination.py: LoopTerminationChecker
  └── engine.py: Integrate early exit
  └── Add llm_timeout_sec config

Week 3-4: Streaming & Observability
  └── TacitusProgressEvent for real-time updates
  └── TUI progress display
```

## Key Code Changes

### engine.py - gather_node
```python
# OLD: Sequential
for src in selected:
    results = await src.query(query, context)

# NEW: Parallel with timeout
async def query_one(src):
    try:
        return await asyncio.wait_for(
            src.query(query, context),
            timeout=timeout_sec
        )
    except TimeoutError:
        return []

results = await asyncio.gather(*[query_one(s) for s in selected])
```

### effort.py - Early Termination
```python
class LoopTerminationChecker:
    def should_terminate_early(self, state, iteration, results):
        # Check diversity
        sources = set(r.source_name for r in results)
        if len(sources) >= 3 and iteration >= 2:
            return True, "diverse_sources"
        
        # Check for new information
        if no_new_results_since_last_iteration(state):
            return True, "no_new_results"
        
        return False, ""
```

## Risk Controls

| Risk | Control |
|------|---------|
| Quality loss | Keep "think" as option; A/B test |
| Missed info | Conservative thresholds; require diversity |
| API overload | Max 4 concurrent; respect rate limits |
| Timeout too fast | Configurable; 10s default is generous |

## Testing Checklist

- [ ] Parallel gather with 4 mock sources (varying latency)
- [ ] Early termination triggers correctly
- [ ] Timeout handling and cleanup
- [ ] Quality comparison: parallel vs sequential
- [ ] Latency benchmarks: p50, p95, p99
- [ ] Error recovery when sources fail

## Events

| Event | When | Payload |
|-------|------|---------|
| `tacitus.started` | Research begins | topic_preview, effort |
| `tacitus.progress` | Phase complete | phase, iteration, elapsed_ms |
| `tacitus.gather.summary` | Gather done | result_count, sources_touched |
| `tacitus.completed` | Research done | duration_ms, answer_length |

## Related

- RFC-619: Tacitus Subagent
- IG-425: Tacitus Implementation
- IG-431: Tacitus Effort & References
