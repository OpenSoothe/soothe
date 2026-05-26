# IG-432: Tacitus Latency Control Mechanisms

**Status**: In Progress (Phase 1 Complete)  
**RFC**: RFC-619 (Tacitus Subagent)  
**Created**: 2026-05-25  
**Depends on**: IG-425, IG-431  

---

## 1. Goal

Implement comprehensive latency control mechanisms for the Tacitus deep research subagent to reduce end-to-end research time while maintaining answer quality.

**Target**: Reduce p99 research latency by 40-60% through parallelization, timeouts, and adaptive depth control.

---

## 2. Problem Statement

Current Tacitus implementation has several latency bottlenecks:

| Bottleneck | Location | Impact | Current Behavior |
|------------|----------|--------|------------------|
| Sequential source queries | `engine.py:411-433` | 15-40s per gather | Sources queried in loop |
| Thread pool blocking | `engine.py:425-426` | 2-5s overhead | `submit().result()` pattern |
| Synchronous LLM calls | Multiple nodes | 10-25s per loop | `model.invoke()` blocking |
| Fixed loop depth | `effort.py` | Unbounded iterations | 2-5 loops regardless of results |
| No source timeouts | `sources/*.py` | Hung queries block forever | No timeout enforcement |
| Slow synthesis model | `protocol.py:68` | 5-10s final step | Defaults to "think" role |

**Example Timeline (xhigh effort)**:
```
analyze (2s) → generate (2s) → gather (20s) → summarize (4s) → reflect (2s)
     ↓
gather (15s) → summarize (3s) → reflect (2s)
     ↓
gather (15s) → summarize (3s) → reflect (2s)
     ↓
synthesize (8s)
Total: ~78 seconds
```

---

## 3. Design Principles

1. **Parallelize where possible** - Independent operations should run concurrently
2. **Fail fast** - Timeouts prevent hung operations from blocking progress
3. **Adaptive depth** - Dynamic loop termination based on result quality
4. **Quality-preserving** - Latency reduction should not significantly impact answer quality
5. **Observable** - All latency controls emit events for monitoring

---

## 4. Proposed Mechanisms

### 4.1 Parallel Source Gathering (P0)

**Current**:
```python
for src in selected:
    results = await src.query(...)  # Sequential
```

**Proposed**:
```python
import asyncio
from asyncio import TimeoutError

async def gather_with_timeout(
    sources: list[PublicInformationSource],
    query: str,
    context: GatherContext,
    timeout_sec: float = 10.0,
) -> list[SourceResult]:
    """Query all sources in parallel with individual timeouts."""
    async def query_one(src: PublicInformationSource) -> list[SourceResult]:
        try:
            return await asyncio.wait_for(
                src.query(query, context),
                timeout=timeout_sec
            )
        except TimeoutError:
            logger.warning("Source %s timed out for query: %s", src.name, query[:60])
            return []
        except Exception as exc:
            logger.debug("Source %s failed: %s", src.name, exc)
            return []

    # Run all queries concurrently
    results = await asyncio.gather(*[query_one(src) for src in sources])
    return [r for sublist in results for r in sublist]
```

**Benefits**:
- Reduces gather time from sum to max(source_latency)
- With 4 sources at 3s each: 12s → 3s
- Individual timeouts prevent slow sources from blocking

**Files to modify**:
- `packages/soothe/src/soothe/subagents/tacitus/engine.py`

---

### 4.2 Async LLM with Streaming (P1)

**Current**:
```python
resp = loop_model.invoke([{"role": "user", "content": prompt}])
parsed = parse_json_object(llm_response_text(resp))
```

**Proposed**:
```python
async def invoke_llm_with_timeout(
    model: BaseChatModel,
    prompt: str,
    timeout_sec: float = 15.0,
    max_tokens: int | None = None,
) -> BaseMessage:
    """Async LLM invocation with timeout and token limit."""
    from langchain_core.messages import HumanMessage
    
    # Use ainvoke for async operation
    coro = model.ainvoke([HumanMessage(content=prompt)])
    
    try:
        return await asyncio.wait_for(coro, timeout=timeout_sec)
    except TimeoutError:
        logger.warning("LLM invocation timed out after %ss", timeout_sec)
        raise ResearchTimeoutError(f"LLM timeout after {timeout_sec}s")
```

**Benefits**:
- Prevents hung LLM calls from blocking indefinitely
- Enables cancellation during shutdown
- Consistent with async architecture

---

### 4.3 Adaptive Loop Termination (P1)

**Current**: Fixed `max_loops` based on effort level

**Proposed**: Add early termination conditions

```python
class LoopTerminationChecker:
    """Determine if research should terminate early based on result quality."""
    
    def __init__(self, config: TacitusConfig):
        self.min_results_threshold = 3  # Need at least N results
        self.confidence_threshold = 0.7  # Average confidence
        self.coverage_threshold = 0.8  # Topic coverage estimate
        
    def should_terminate_early(
        self,
        state: dict[str, Any],
        iteration: int,
        results: list[SourceResult],
    ) -> tuple[bool, str]:
        """Check if we have sufficient results to terminate early.
        
        Returns:
            (should_terminate, reason)
        """
        # Check minimum results
        total_results = len(state.get("references_gathered", []))
        if total_results >= self.min_results_threshold and iteration >= 2:
            # Check if last iteration added new information
            prev_count = state.get("_prev_result_count", 0)
            if total_results == prev_count:
                return True, "no_new_results"
                
        # Check result diversity
        sources = set(r.source_name for r in results)
        if len(sources) >= 3 and iteration >= 2:
            return True, "diverse_sources"
            
        return False, ""
```

**Integration in reflect_node**:
```python
def reflect_node(state: dict[str, Any]) -> dict[str, Any]:
    # ... existing reflection logic ...
    
    # Check early termination
    checker = LoopTerminationChecker(_default_config)
    should_exit, reason = checker.should_terminate_early(
        state, loop_count, all_results
    )
    
    if should_exit:
        logger.info("[Tacitus] Early termination: %s", reason)
        return {
            "loop_count": loop_count + 1,
            "_is_sufficient": True,
            "_follow_up_queries": [],
            "_early_termination_reason": reason,
        }
    
    # ... continue with normal reflection ...
```

**Benefits**:
- Reduces unnecessary iterations
- Typical savings: 1-2 loops (15-30s)

---

### 4.4 Source Timeout Configuration (P1)

**Add to TacitusConfig**:
```python
class TacitusConfig(BaseModel):
    # ... existing fields ...
    
    source_timeout_sec: float = Field(
        default=10.0,
        ge=1.0,
        le=60.0,
        description="Per-source query timeout in seconds.",
    )
    
    llm_timeout_sec: float = Field(
        default=15.0,
        ge=5.0,
        le=60.0,
        description="LLM invocation timeout in seconds.",
    )
    
    enable_parallel_sources: bool = Field(
        default=True,
        description="Query sources in parallel (vs sequential).",
    )
    
    enable_early_termination: bool = Field(
        default=True,
        description="Enable adaptive loop termination.",
    )
```

---

### 4.5 Fast Synthesis by Default (P2)

**Current**:
```python
synthesis_role: str = Field(default="think", ...)
```

**Proposed**:
```python
synthesis_role: str = Field(
    default="fast",
    description="Router role for final synthesis (fast=lower latency, think=higher quality).",
)
```

**Rationale**: Synthesis is mostly about organizing existing information, not deep reasoning. Fast model is sufficient.

---

### 4.6 Result Streaming (P2)

**New Event**: `TacitusProgressEvent`

```python
class TacitusProgressEvent(SootheEvent):
    """Incremental progress during Tacitus execution."""
    
    type: Literal["soothe.subagent.tacitus.progress"] = "soothe.subagent.tacitus.progress"
    phase: str  # "analyze", "gather", "summarize", "reflect", "synthesize"
    iteration: int
    sources_completed: int
    sources_total: int
    elapsed_ms: int
    estimated_remaining_ms: int | None = None
```

**Benefits**:
- TUI can show progress during long operations
- Users see activity instead of waiting blindly
- Enables cancellation mid-operation

---

## 5. Implementation Plan

### Phase 1: Parallel Sources (Week 1)

1. **Modify `engine.py`**:
   - Add `gather_with_timeout()` helper
   - Replace sequential source loop with `asyncio.gather()`
   - Add per-source timeout handling

2. **Add config options**:
   - `source_timeout_sec` (default 10s)
   - `enable_parallel_sources` (default True)

3. **Tests**:
   - Test parallel gathering with mock sources
   - Test timeout behavior
   - Test fallback when sources fail

### Phase 2: Adaptive Termination (Week 2)

1. **Create `termination.py`**:
   - `LoopTerminationChecker` class
   - Configurable thresholds

2. **Modify `engine.py`**:
   - Integrate early termination check in reflect_node
   - Add `_early_termination_reason` to state

3. **Add config options**:
   - `enable_early_termination` (default True)
   - `min_results_for_termination` (default 3)

4. **Tests**:
   - Test early termination triggers
   - Test continuation when results insufficient

### Phase 3: LLM Timeouts (Week 2-3)

1. **Modify `engine.py`**:
   - Add `invoke_llm_with_timeout()` helper
   - Wrap all `model.invoke()` calls
   - Add `llm_timeout_sec` config

2. **Error handling**:
   - Define `ResearchTimeoutError`
   - Graceful degradation on timeout

3. **Tests**:
   - Test timeout behavior
   - Test error propagation

### Phase 4: Streaming & Observability (Week 3-4)

1. **Add progress events**:
   - `TacitusProgressEvent` in `events.py`
   - Emit during each phase

2. **Update TUI**:
   - Display progress in step cards
   - Show estimated time remaining

3. **Metrics**:
   - Track latency per phase
   - Track early termination rate

---

## 6. Configuration

**New config section in `config.template.yml`**:

```yaml
subagents:
  tacitus:
    # Model roles
    llm_role: "fast"
    synthesis_role: "fast"  # Changed from "think"
    
    # Effort levels (unchanged)
    effort: "normal"
    max_loops: 3
    
    # Latency control (NEW)
    source_timeout_sec: 10.0
    llm_timeout_sec: 15.0
    enable_parallel_sources: true
    enable_early_termination: true
    min_results_for_termination: 3
    
    # Capabilities (unchanged)
    enabled_capabilities:
      - "web_search"
      - "academic_search"
      - "url_crawl"
```

---

## 7. Expected Impact

### Latency Reduction by Effort Level

| Effort | Current p99 | Target p99 | Reduction |
|--------|-------------|------------|-----------|
| normal | 25s | 12s | 52% |
| high | 50s | 25s | 50% |
| xhigh | 80s | 40s | 50% |

### Breakdown by Mechanism

| Mechanism | Expected Savings | Implementation |
|-----------|------------------|----------------|
| Parallel sources | 10-25s | Phase 1 |
| Early termination | 15-30s | Phase 2 |
| Fast synthesis | 3-5s | Phase 3 |
| LLM timeouts | 5-10s (prevents outliers) | Phase 3 |
| **Total** | **33-70s** | All phases |

---

## 8. Risk Mitigation

| Risk | Mitigation |
|------|------------|
| Quality degradation from fast synthesis | A/B test with quality metrics; keep "think" as option |
| Early termination misses important info | Conservative thresholds; require diverse sources |
| Timeout too aggressive | Configurable; default 10s is generous |
| Parallel sources overwhelm APIs | Respect rate limits; max 4 concurrent |
| Async complexity bugs | Comprehensive tests; gradual rollout |

---

## 9. Testing Strategy

### Unit Tests
- `test_parallel_gather.py` - Mock sources with varying latencies
- `test_early_termination.py` - Trigger conditions
- `test_timeouts.py` - Timeout behavior and cleanup

### Integration Tests
- End-to-end latency benchmarks
- Quality comparison (parallel vs sequential)
- Error recovery scenarios

### Benchmarks
```python
# Example benchmark
async def benchmark_research_latency():
    queries = [
        "What is agentic memory?",
        "Latest developments in LLM agents 2025",
        "Compare LangGraph vs AutoGen frameworks",
    ]
    for query in queries:
        for effort in ["normal", "high", "xhigh"]:
            # Run 10 times, measure p50/p99
            # Compare before/after optimization
```

---

## 10. Migration Path

1. **Phase 1**: Deploy parallel sources (opt-in via config)
2. **Phase 2**: Enable by default after 1 week
3. **Phase 3**: Deploy early termination (opt-in)
4. **Phase 4**: Enable by default, change synthesis_role default

---

## 11. Done When

### Phase 1 (Complete)
- [x] Parallel source gathering implemented and tested
- [x] Source timeout configuration added to TacitusConfig
- [x] `_gather_from_sources_parallel()` helper function implemented
- [x] `./scripts/verify_finally.sh` passes

### Phase 2 (Complete)
- [x] Early termination logic implemented and tested
- [x] `LoopTerminationChecker` class with diversity/quality heuristics
- [x] `should_terminate_early()` convenience function
- [x] Config options added to TacitusConfig
- [x] Integration with reflect_node
- [x] 16 unit tests for termination logic

### Phase 3 (Complete)
- [x] LLM timeouts implemented and tested
- [x] `_invoke_llm_with_timeout()` async helper
- [x] `_invoke_llm_sync_with_timeout()` sync wrapper
- [x] All 5 engine nodes use timeout-protected LLM calls
- [x] Config option `llm_timeout_sec` added to TacitusConfig
- [x] Fallback behavior on timeout for each node

### Phase 4 (Complete)
- [x] Progress events implemented
- [x] `TacitusProgressEvent` with phase, loop_count, sources info
- [x] Real-time progress emitted from all nodes
- [x] Verbosity tier: DETAILED

### Phase 5 (Complete)
- [x] Unit tests for all new features
- [x] Config option tests (8 test cases)
- [x] Progress event tests (3 test cases)
- [x] LLM timeout helper tests (2 test cases)
- [x] Integration tests (1 test case)
- [x] Total: 72 Tacitus unit tests passing

### Phase 6 (Pending)
- [ ] Config options added to template and dev configs
- [ ] Benchmarks show 40%+ latency reduction
- [ ] Quality metrics show <5% degradation

---

## Appendix: Code Sketch

### Full gather_node with parallel sources

```python
async def gather_node(state: dict[str, Any]) -> dict[str, Any]:
    query = state.get("_gather_query", "")
    domain_hint = state.get("_gather_domain", "public")
    profile = _effort_profile_for_state(state, _default_config)

    selected = router.select(
        query,
        domain=domain_hint,
        max_sources=profile.max_sources_per_query,
    )
    
    if not selected:
        emit_subagent_wire_event(
            TacitusGatherSummaryEvent(
                query_preview=str(query)[:120],
                result_count=0,
                sources_touched=0,
            ).to_dict(),
            logger,
        )
        return {
            "search_summaries": [f"No sources available for: {query}"],
            "sources_gathered": [f"none:{query}"],
        }

    from .protocol import GatherContext
    context = GatherContext(
        topic=_extract_topic(state),
        existing_summaries=state.get("search_summaries", []),
        iteration=state.get("loop_count", 0),
    )

    # PARALLEL: Query all sources concurrently with timeout
    timeout_sec = _default_config.source_timeout_sec
    all_results = await _gather_from_sources_parallel(
        selected, query, context, timeout_sec
    )

    if not all_results:
        emit_subagent_wire_event(...)
        return {...}

    # Process results...
```

---

**Related**: RFC-619, IG-425, IG-431
