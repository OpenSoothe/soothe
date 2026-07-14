# IG-536: Plan Generation Performance Benchmark

## Summary

Benchmark LLMPlanner latency and accuracy using real system prompts and simulated tasks with ground truth plans.

## Scope

| Component | In Scope | Rationale |
|-----------|----------|-----------|
| LLMPlanner | ✅ | Core planner for most tasks (StatusAssessment + PlanGeneration) |
| Plan Subagent Engine | ❌ | Complex tasks with explore subagent — separate IG if needed |
| Accuracy metric | Ground truth comparison | Hand-crafted expected plans per task |
| Model comparison | fast vs think | Evaluate latency/accuracy tradeoff between model roles |

## Architecture Context

**LLMPlanner flow** (`foundation/sloop/cognition/planner.py`):
1. `assess_status()` → `StatusAssessment` (status, goal_progress, assessment_reasoning)
2. If status != "done" → `generate_plan()` → `AgentDecision` (steps, execution_mode, reasoning)

**System prompts**:
- `PLAN_ASSESS_INSTRUCTIONS_FRAGMENT` (`prompts/fragments/instructions/plan_assess_instructions.xml`)
- `PLAN_GENERATE_INSTRUCTIONS_FRAGMENT` (`prompts/fragments/instructions/plan_generate_instructions.xml`)

**Model binding**: Temperature=0 for deterministic structured JSON

**Step schema** (`PlanGenerateStep`):
- `id`, `description`, `full_description`, `expected_output`
- `dependencies` (for DAG steps)
- `kind`: "action" or "ask_user"
- `execution_hint`: "tool", "subagent", "auto"

## Implementation

### 1. Benchmark Script

**Location**: `scripts/benchmark_plan_generation.py`

```python
@dataclass
class PlanBenchmarkResult:
    task_id: str
    task_category: str  # "simple" | "medium"
    model_role: str     # "fast" | "think"

    # Latency (ms)
    assess_latency_ms: float
    generate_latency_ms: float
    total_latency_ms: float

    # Accuracy
    step_count_match: bool
    step_count_diff: int
    dependency_correctness: float  # % of deps correctly identified
    kind_correctness: float        # % of steps with correct kind
    description_similarity: float  # semantic similarity score

    # Generated plan
    generated_steps: list[PlanGenerateStep]
    ground_truth_steps: list[PlanGenerateStep]
```

### 2. Task Fixtures

**Location**: `packages/soothe/tests/fixtures/plan_benchmark_tasks.py`

**Categories**:

| Category | Steps | Dependencies | Examples |
|----------|-------|--------------|----------|
| simple | 1-2 | None | "Read the README.md file", "List files in src/ directory" |
| medium | 2-3 | Yes | "Read config.yml then update the timeout setting", "Find all Python files and count total lines" |

**Fixture structure**:
```python
@dataclass
class BenchmarkTask:
    id: str
    goal: str
    context: PlanContext  # Mocked, no real ledger
    iteration: int  # 0 for first wave
    ground_truth: AgentDecision  # Expected steps, execution_mode
```

### 3. Accuracy Metrics

**Step count accuracy**: `generated_count == ground_truth_count`

**Dependency correctness**:
- For each step with deps, check if generated deps match ground truth
- Score: `correct_deps / total_deps`

**Kind correctness**:
- For each step, check if `kind` matches ground truth
- Score: `correct_kinds / total_steps`

**Description similarity**:
- Use simple token overlap or embedding similarity
- Compare `description` field only (not full_description)

### 4. Model Comparison

**Roles to test**:
- `fast`: `router.fast` model (e.g., gpt-4o-mini)
- `think`: `router.think` model (fallback to default if not set)

**Comparison metrics**:
- Latency delta: `think_latency - fast_latency`
- Accuracy delta: `think_accuracy - fast_accuracy`
- Cost-effectiveness: `accuracy_per_ms`

### 5. Execution Modes

**Offline mode** (default):
- Uses mock LLM responses from fixtures
- Tests prompt construction + parsing logic
- No real API calls → deterministic

**Online mode** (`--online` flag):
- Real LLM API calls
- Measures actual latency
- Requires API keys configured

## Files to Create

| Path | Description |
|------|-------------|
| `scripts/benchmark_plan_generation.py` | Main benchmark script |
| `packages/soothe/tests/fixtures/plan_benchmark_tasks.py` | Task fixtures with ground truth |
| `packages/soothe/tests/unit/sloop/cognition/test_planner_benchmark.py` | Unit tests for benchmark utils |

## CLI Usage

```bash
# Offline mode (mock LLM)
python scripts/benchmark_plan_generation.py

# Online mode (real LLM calls)
python scripts/benchmark_plan_generation.py --online

# Specific model role
python scripts/benchmark_plan_generation.py --online --model-role think

# Output formats
python scripts/benchmark_plan_generation.py --output json
python scripts/benchmark_plan_generation.py --output markdown
```

## Output Report

```markdown
# Plan Generation Benchmark Report

## Summary
- Tasks: 10 (5 simple, 5 medium)
- Model roles: fast, think
- Mode: online

## Latency (ms)

| Role | Assess (avg) | Generate (avg) | Total (avg) | P50 | P95 |
|------|-------------|----------------|-------------|-----|-----|
| fast | 120 | 180 | 300 | 290 | 450 |
| think | 180 | 250 | 430 | 420 | 600 |

## Accuracy

| Role | Step Count % | Dep Correctness % | Kind % | Desc Similarity |
|------|-------------|-------------------|--------|-----------------|
| fast | 85 | 78 | 92 | 0.72 |
| think | 92 | 85 | 95 | 0.78 |

## Cost-Effectiveness

| Role | Accuracy/ms | Notes |
|------|------------|-------|
| fast | 0.28 | Faster but slightly less accurate |
| think | 0.22 | More accurate but slower |
```

## Verification

1. `make lint` passes
2. Unit tests for benchmark utilities pass
3. Online benchmark runs with real API keys
4. Report generation works for both json and markdown formats

## Dependencies

- Existing: `LLMPlanner`, `PlanContext`, `invoke_structured_chat_typed`
- New: Task fixtures, benchmark harness, accuracy scoring

## Risks

| Risk | Mitigation |
|------|------------|
| LLM variability affects accuracy scores | Use temperature=0, run multiple samples, report variance |
| Ground truth plans subjective | Multiple reviewers, clear criteria for each task |
| API rate limits in online mode | Add rate limiting, configurable delay between calls |