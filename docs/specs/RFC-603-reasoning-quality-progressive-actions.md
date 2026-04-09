# RFC-603: Reasoning Quality & Progressive Actions

**Status**: Draft
**Type**: Feature Enhancement
**Authors**: Claude Code
**Created**: 2026-04-09
**Related**: IG-143, RFC-0008 (Agentic Loop)

---

## Abstract

Refactor the reasoning layer to ensure progressive action descriptions and comprehensive final reports. This RFC addresses IG-143 Issues #2 and #3 by implementing prompt engineering, post-processing, and an optional synthesis phase. Additionally improves confidence estimation and progress tracking with evidence-based calculations.

---

## Motivation

### Problem 1: Non-Progressive Actions

Current behavior shows action descriptions regressing from specific back to generic:

```
Iteration 1: "Use file and shell tools..." (generic)
Iteration 2: "Use file and shell tools..." (repeated - NO PROGRESS)
Iteration 3: "List the root directory structure..." (specific - GOOD!)
Iteration 4: "Use file and shell tools..." (REGRESSED - BAD!)
```

**Impact**: Users cannot track reasoning progress, actions feel repetitive, degrades UX quality.

**Root Cause**: `soothe_next_action` field is LLM-generated without post-processing or progression tracking.

### Problem 2: Insufficient Final Reports

Current final reports:
```
✓ The Soothe project architecture has already been fully analyzed.
It's a Python-based system with ~18K lines across 338 files...
```

**Issues**:
- Says "already analyzed" instead of synthesizing findings
- Minimal detail (just line count and file count)
- No architecture breakdown
- No key components identified
- No design patterns explained

**Impact**: Users don't receive comprehensive, actionable summaries for complex goals.

**Root Cause**: `full_output` concatenates raw step results without synthesis.

### Problem 3: Unreliable Quality Metrics

Current confidence and progress metrics rely solely on LLM self-assessment without evidence validation.

**Impact**: Confidence/progress often inaccurate, misleading users about actual completion.

---

## Specification

### 1. Progressive Actions

#### 1.1 Enhanced Prompts

**Location**: `src/soothe/core/prompts/fragments/instructions/output_format.xml`

Add new `<PROGRESSIVE_ACTIONS>` section requiring:
- Reference learnings from previous iterations
- Never repeat identical action text
- Progress from exploration → investigation → synthesis
- Explicit strategy pivots when stuck

**Action Evolution Pattern**:
- Iteration 1: Broad exploration
- Iteration 2: Targeted investigation
- Iteration 3: Deep analysis
- Iteration 4+: Synthesis and validation

#### 1.2 Action Post-Processing

**Location**: `src/soothe/cognition/loop_agent/action_quality.py` (NEW)

**Functions**:

```python
def enhance_action_specificity(
    action: str,
    goal: str,
    iteration: int,
    previous_actions: list[str],
    step_results: list[StepResult],
) -> str
```

**Logic**:
1. Check if action is already specific (paths, counts, references to prior work)
2. Check for repetition against last 3 actions (normalized comparison)
3. If repeated, derive new action from recent evidence
4. If generic, add context from step results

**Specificity Detection Patterns**:
- Numbers: `\d+ (files|components|modules|layers)`
- Paths: `(examine|analyze|investigate) \S+/`
- References: `based on (findings|results|analysis)`
- Discoveries: `(identified|found|discovered) \d+`

**Integration**: Called in `reason.py` after LLM generates `ReasonResult`, before emitting event.

#### 1.3 Action History Tracking

**Schema Change**: Add to `LoopState`:
```python
action_history: list[str] = Field(default_factory=list)

def add_action_to_history(self, action: str) -> None
def get_recent_actions(self, n: int = 3) -> list[str]
```

**Usage**: Record each iteration's `soothe_next_action` for deduplication.

---

### 2. Synthesis Phase

#### 2.1 Synthesis Trigger Logic

**Location**: `src/soothe/cognition/loop_agent/synthesis.py` (NEW)

**Class**: `SynthesisPhase`

**Trigger Criteria** (all must be met):

| Criterion | Threshold | Rationale |
|-----------|-----------|-----------|
| Step count | ≥ 2 | Enough evidence to synthesize |
| Success rate | ≥ 60% | Quality evidence |
| Evidence volume | ≥ 500 chars | Sufficient content |
| Unique steps | ≥ 2 | Multiple perspectives |

**Decision Logic**:
```python
def should_synthesize(self, goal: str, state: LoopState, reason_result: ReasonResult) -> bool
```

Evidence-based heuristics only (no keyword matching).

#### 2.2 Synthesis Generation

**Process**:
1. Classify goal type from evidence patterns (not keywords)
2. Build synthesis prompt with goal, evidence, type
3. Call LLM for synthesis
4. Return structured summary

**Goal Classification** (evidence-based):
- Architecture analysis: Multiple directories + layer mentions
- Research synthesis: Multiple findings counts
- Implementation summary: Code patterns
- General synthesis: Default

#### 2.3 Synthesis Prompt Template

**Location**: `src/soothe/core/prompts/fragments/instructions/synthesis_format.xml` (NEW)

**Requirements**:
- Do NOT say "already analyzed"
- Be specific with numbers, names, concrete findings
- Structure appropriately for goal type
- 300-600 words for complex goals

**Architecture Analysis Structure**:
- System Overview
- Architecture Layers
- Key Components
- Design Patterns
- Dependencies
- Notable Features

**Research Structure**:
- Key Findings
- Methodology
- Conclusions

**Implementation Structure**:
- What Was Built
- Implementation Details
- Usage

#### 2.4 Integration

**Location**: `src/soothe/cognition/loop_agent/loop_agent.py`

**Trigger Point**: After `reason_result.is_done()` returns True

**Process**:
1. Initialize `SynthesisPhase` with synthesis LLM client
2. Check `should_synthesize()`
3. If True, call `synthesize()` and update `full_output`
4. If False, use raw evidence concatenation
5. Emit completed event

**Error Handling**: If synthesis fails, fall back to raw `full_output`.

---

### 3. Quality Improvements

#### 3.1 Evidence-Based Confidence

**Location**: `src/soothe/backends/planning/simple.py`

**Function**:
```python
def _calculate_evidence_based_confidence(
    state: LoopState,
    reason_result: ReasonResult,
) -> float
```

**Formula**:
```
confidence = (
    llm_confidence * 0.5 +
    success_rate * 0.3 +
    evidence_volume_score * 0.3 +
    iteration_efficiency * 0.4
) / 1.5
```

**Factors**:
- Success rate (30%): Percentage of successful steps
- Evidence volume (30%): 0 chars = 0.0, 2000+ chars = 1.0
- Iteration efficiency (40%): Progress per iteration

**Integration**: Apply after parsing LLM response in `parse_reason_response_text()`.

#### 3.2 Evidence-Based Progress

**Location**: `src/soothe/backends/planning/simple.py`

**Function**:
```python
def _calculate_evidence_based_progress(
    state: LoopState,
    reason_result: ReasonResult,
) -> float
```

**Formula**:
```
progress = (
    llm_progress * 0.6 +
    step_completion_ratio * 0.2 +
    evidence_growth_rate * 0.2
)
```

**Factors**:
- Step completion (20%): Completed steps / total steps
- Evidence growth (20%): Recent vs earlier evidence ratio

**Special Case**: If `status="done"`, return 1.0.

**Integration**: Apply after parsing LLM response in `parse_reason_response_text()`.

#### 3.3 Better Reasoning Guidance

**Location**: `src/soothe/core/prompts/fragments/instructions/output_format.xml`

Add `<REASONING_QUALITY>` section requiring:
- Cite specific evidence
- Quantify findings
- Justify status with evidence
- 2-4 concise sentences

**Example**:
```
"Analysis of src/ revealed 8 protocol files and 12 backend implementations.
Evidence shows a layered architecture with clear separation.
Progress: examined 60% of key directories.
Status=continue to examine remaining backends."
```

---

### 4. Schema Changes

#### 4.1 ReasonResult Updates

**Location**: `src/soothe/cognition/loop_agent/schemas.py`

**New Fields**:

```python
synthesis_performed: bool = Field(
    default=False,
    description="Whether synthesis phase was run"
)

action_specificity_score: float | None = Field(
    default=None,
    ge=0.0,
    le=1.0,
    description="Post-processed specificity score"
)

evidence_quality_score: float = Field(
    default=0.0,
    ge=0.0,
    le=1.0,
    description="Calculated quality of evidence"
)
```

#### 4.2 LoopState Updates

**Location**: `src/soothe/cognition/loop_agent/schemas.py`

**New Fields**:

```python
action_history: list[str] = Field(
    default_factory=list,
    description="Chronological action history"
)
```

**New Methods**:

```python
def add_action_to_history(self, action: str) -> None
def get_recent_actions(self, n: int = 3) -> list[str]
```

---

## Implementation Plan

### Phase 1: Progressive Actions (1 day)

**Files**:
- `schemas.py`: Add action history
- `output_format.xml`: Add progressive action guidance
- `action_quality.py`: NEW, implement post-processing
- `reason.py`: Integrate enhancement

**Tests**:
- Unit: Specificity detection, repetition checking, enhancement
- Integration: Multi-step actions become progressive

### Phase 2: Quality Improvements (0.5 days)

**Files**:
- `simple.py`: Add evidence-based confidence/progress
- `output_format.xml`: Add reasoning quality guidance

**Tests**:
- Unit: Confidence and progress calculations

### Phase 3: Synthesis Phase (1.5 days)

**Files**:
- `schemas.py`: Add synthesis fields
- `synthesis_format.xml`: NEW, synthesis template
- `synthesis.py`: NEW, implement SynthesisPhase
- `loop_agent.py`: Integrate synthesis trigger

**Tests**:
- Unit: Trigger logic, output structure
- Integration: Architecture analysis produces comprehensive report

### Phase 4: Benchmarks (1 day)

**Files**:
- `benchmarks/reasoning-quality/`: 10 benchmark files
- `run-benchmarks.py`: Benchmark runner

**Test Cases**:
1. Architecture analysis (synthesis expected)
2. Code investigation (synthesis expected)
3. Simple lookup (synthesis NOT expected)
4. Research task (synthesis expected)
5. Structure analysis (synthesis expected)
6. Error investigation (synthesis expected)
7. Comparison task (synthesis expected)
8. Documentation generation (synthesis expected)
9. Performance analysis (synthesis expected)
10. Quick summary (synthesis NOT expected)

### Phase 5: Testing & Documentation (1 day)

**Activities**:
- Run real-world test: `soothe --no-tui -p "analyze this project arch"`
- Verify progressive actions improve
- Verify comprehensive reports
- Update documentation

**Total Time**: 5 days

---

## Breaking Changes

No backward compatibility maintained.

**Changes**:
- Remove `full_output` fallback (always synthesize or fail)
- Replace confidence/progress calculations entirely
- Require specific actions (enhance if needed)

**Rationale**: Cleaner code, consistent quality, easier testing.

---

## Success Criteria

### Primary Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| Benchmark pass rate | ≥ 80% | 8/10 cases pass validation |
| Progressive actions | ≥ 85% | Actions improve in 6/7 multi-step cases |
| Synthesis quality | ≥ 90% | Comprehensive reports when synthesis triggered |
| Iteration efficiency | Within expected ranges | No runaway loops |

### Quality Metrics

**Before**:
- Actions: Generic and repeated
- Final report: ~100 words, minimal detail
- Confidence: LLM self-assessment only
- Progress: LLM estimate only

**After**:
- Actions: Progressive specificity (0% → 80%+ specific)
- Final report: 300-600 words, structured
- Confidence: Evidence-based (success + volume + efficiency)
- Progress: Step completion + evidence growth

---

## Risk Mitigation

| Risk | Mitigation | Fallback |
|------|------------|----------|
| Synthesis adds latency | Skip for simple goals (evidence heuristics) | Use raw evidence |
| Post-processing over-corrects | Only enhance repeated/generic actions | Keep original if uncertain |
| LLM ignores progressive prompts | Post-processing safety net | Accept some imperfection |
| Quality heuristics inaccurate | Conservative thresholds, log for tuning | Adjust thresholds |
| Synthesis quality poor | Strong prompt template | Fall back to raw evidence |

---

## Future Enhancements

**Potential Follow-ups**:
1. Template library for goal-type-specific synthesis
2. Action memory across sessions
3. ML models for synthesis benefit prediction
4. Streaming synthesis progress
5. Multi-model synthesis for different types

---

## References

- IG-143: CLI Display Architecture Refactoring
- RFC-0008: Layer 2 Agentic Loop
- RFC-000: System Conceptual Design
- `src/soothe/cognition/loop_agent/` - Agentic loop implementation
- `src/soothe/backends/planning/` - Reasoning backend

---

## Appendix A: Benchmark Specifications

### Benchmark Format

Each benchmark includes:
- **Metadata**: ID, type, expected iterations, synthesis expected
- **Task**: User query to execute
- **Success Criteria**: Checkboxes for validation
- **Execution Instructions**: How to run and verify
- **Expected Output**: Description of quality output

### Benchmark Locations

```
benchmarks/reasoning-quality/
├── 01-architecture-analysis.md
├── 02-code-investigation.md
├── 03-simple-lookup.md
├── 04-research-task.md
├── 05-structure-analysis.md
├── 06-error-investigation.md
├── 07-comparison-task.md
├── 08-documentation-generation.md
├── 09-performance-analysis.md
└── 10-quick-summary.md
```

### Validation Criteria Examples

**Architecture Analysis**:
- [ ] Final report includes "overview" section
- [ ] Final report includes "architecture" section
- [ ] Final report includes "components" section
- [ ] Identifies at least 5 key components by name
- [ ] Reports concrete numbers (file count, line count)
- [ ] Actions become more specific across iterations
- [ ] No duplicate action text

**Simple Lookup**:
- [ ] Direct answer provided
- [ ] Report length ≤ 100 words
- [ ] Completed in 1-2 iterations
- [ ] No synthesis performed

---

## Appendix B: File Change Summary

| File | Change Type | Lines Changed |
|------|-------------|----------------|
| `action_quality.py` | NEW | ~150 |
| `synthesis.py` | NEW | ~200 |
| `reason.py` | MODIFY | ~20 |
| `loop_agent.py` | MODIFY | ~30 |
| `schemas.py` | MODIFY | ~40 |
| `simple.py` | MODIFY | ~80 |
| `output_format.xml` | MODIFY | ~50 |
| `synthesis_format.xml` | NEW | ~100 |
| **Total** | | **~670 lines** |

---

**RFC Status**: Draft - Ready for Implementation Guide