# IG-433: Keyword/Heuristic-Based Logic Optimization

## Status
Complete (Phases 1–5 implemented with feature flags and keyword/regex fallbacks).

## RFC Links
- RFC-204: Goal Criticality Assessment
- RFC-220: Agent Loop Orchestrator
- RFC-616: Synthesis Generation

## Goals
Replace fragile keyword matching, regex patterns, and hardcoded heuristics with semantic alternatives (embeddings, learned classifiers, LLM-based approaches) to improve accuracy, maintainability, and reduce false positives/negatives.

## Background
Audit of the codebase identified 779+ occurrences of regex patterns across ~140 files, with several critical areas relying on keyword matching and hardcoded thresholds that are prone to brittleness.

## Scope

### Priority 1: Critical (Phase 1-2)

#### 1.1 Risk Keyword Detection → Semantic Risk Classifier
**File:** `packages/soothe/src/soothe/core/goal_engine/criticality.py`

**Current Implementation:**
- `HIGH_RISK_KEYWORDS` frozenset with 18 keywords (deploy, delete, destroy, credential, etc.)
- Hardcoded thresholds: `_PRIORITY_MUST_THRESHOLD = 90`, `_MAX_DESCRIPTION_LENGTH = 500`, `_MUST_REASONS_THRESHOLD = 2`
- Simple substring matching: `any(kw in text for kw in keywords)`

**Proposed Replacement:**
```python
# New module: packages/soothe/src/soothe/core/goal_engine/semantic_risk_classifier.py
class RiskAssessment(BaseModel):
    risk_level: Literal["critical", "high", "medium", "low"]
    confidence: float
    reasoning: str
    requires_confirmation: bool

async def semantic_evaluate_risk(
    description: str,
    priority: int,
    model: BaseChatModel,
    *,
    use_semantic_cache: bool = True,
) -> RiskAssessment:
    """LLM-based risk assessment with embedding similarity cache."""
```

**Migration Strategy:**
1. Create new `semantic_risk_classifier.py` module
2. Implement embedding cache for similar descriptions (cosine similarity > 0.9)
3. Add feature flag: `use_semantic_risk = True`
4. A/B test with keyword fallback
5. Deprecate keyword matching after validation

**Benefits:**
- Catches semantically risky operations not in keyword list (e.g., "archive old data")
- Reduces false positives from phrases like "key insights"
- Confidence score enables dynamic threshold adjustment

---

#### 1.2 Goal Relationship Detection → Embedding-Based Semantic Graph
**File:** `packages/soothe/src/soothe/core/goal_engine/relationship_detector.py`

**Current Implementation:**
- `_STOP_WORDS` frozenset with 82 common English words
- Jaccard similarity for text overlap
- Hardcoded thresholds: `_AUTO_APPLY_CONFIDENCE = 0.8`, `_FLAG_FOR_REVIEW_CONFIDENCE = 0.5`
- Regex patterns for artifact extraction

**Proposed Replacement:**
```python
# New module: packages/soothe/src/soothe/core/goal_engine/semantic_relationship_detector.py
@dataclass
class RelationshipConfig:
    embedding_model: str = "text-embedding-3-small"
    auto_apply_threshold: float = 0.85  # Learned from data
    flag_threshold: float = 0.70
    artifact_resolver: Callable | None = None

async def detect_semantic_relationships(
    completed_goal: Goal,
    all_goals: list[Goal],
    config: RelationshipConfig,
) -> list[Relationship]:
    """Embedding-based relationship detection with cosine similarity."""
```

**Key Improvements:**
- Replace stop-word heuristic with proper embeddings
- Configurable thresholds via settings (not hardcoded)
- Pluggable artifact resolver using AST parsing for code

---

### Priority 2: High (Phase 3-4)

#### 2.1 Prerequisite Pattern Detection → Intent Classifier
**File:** `packages/soothe/src/soothe/core/loop/utils/reflection.py`

**Current Implementation:**
- `_PREREQUISITE_PATTERNS` frozenset with 10 keyword patterns
- Simple substring matching in result text

**Proposed Replacement:**
```python
# New module: packages/soothe/src/soothe/core/loop/utils/failure_intent_classifier.py
class FailureIntent(BaseModel):
    category: Literal[
        "missing_prerequisite", "permission_denied", "resource_unavailable",
        "syntax_error", "logic_error", "timeout", "unknown"
    ]
    confidence: float
    suggested_action: Literal["create_prerequisite", "retry", "escalate", "skip"]
    extracted_entities: list[str]
```

**Fallback Strategy:** Keep keyword matching as fast-path; use LLM only when confidence < 0.7

---

#### 2.2 Plan Step Parsing → Structured Output with Validation
**File:** `packages/soothe/src/soothe/core/loop/planning/parser.py`

**Current Implementation:**
- Regex: `r"\*\*Step\s+(\d+)[:\s]*(.+?)\*\*"`
- Manual list marker stripping

**Proposed Replacement:**
```python
# Enhanced: packages/soothe/src/soothe/core/loop/planning/structured_plan_parser.py
class PlanStepExtracted(BaseModel):
    step_number: int
    title: str
    description: str | None = None
    depends_on: list[int] = []
    estimated_complexity: Literal["low", "medium", "high"] | None = None

async def parse_plan_structured(
    goal: str,
    planner_output: str,
    model: BaseChatModel,
) -> Plan:
    """Use LLM with structured output to extract plan."""
```

---

### Priority 3: Medium (Phase 5)

#### 3.1 Scenario Classification → Dynamic Scenario Registry
**File:** `packages/soothe/src/soothe/core/loop/engine/scenario_classifier.py`

**Current Implementation:**
- 10 hardcoded scenario templates in `BUILTIN_SCENARIOS` dict
- Manual scenario description mapping

**Proposed Replacement:**
```yaml
# New: config/scenarios.yml (user-configurable)
scenarios:
  code_architecture_design:
    sections: [Summary, Component Analysis, Key Findings, Recommendations]
    embedding_examples:
      - "Analyze the module structure"
      - "Design system architecture"
```

```python
# New module: packages/soothe/src/soothe/core/loop/engine/scenario_registry.py
class ScenarioRegistry:
    def __init__(self, config_path: str | None = None):
        self.scenarios: dict[str, Scenario] = {}
        self.embedding_cache: dict[str, list[float]] = {}
```

---

#### 3.2 Metadata Extraction → Tool-Specific Parsers
**File:** `packages/soothe/src/soothe/core/loop/engine/metadata_generator.py`

**Current Implementation:**
- Regex patterns for file paths, exit codes, domains
- Keyword-based success detection

**Proposed Replacement:**
```python
# New module: packages/soothe/src/soothe/core/loop/engine/tool_result_registry.py
class ToolResultParser(Protocol):
    def parse(self, result: Any) -> dict[str, Any]: ...
    def get_schema(self) -> dict[str, Any]: ...

@dataclass
class FileReadParser(ToolResultParser):
    """Parse file read results using actual file metadata."""
```

---

#### 3.3 Completion Detection (removed)

**Status:** Heuristic `completion_classifier` (IG-433) was implemented then **removed**. Plan completion follows RFC-604 `StatusAssessment` only; evidence-volume force-done caused premature completion on read-heavy goals (e.g. multi-RFC refine).

---

## Implementation Roadmap

| Phase | Duration | Tasks |
|-------|----------|-------|
| Phase 1 | Week 1-2 | Implement semantic risk classifier, A/B test with keyword fallback |
| Phase 2 | Week 3-4 | Deploy embedding-based relationship detection, tune thresholds |
| Phase 3 | Week 5-6 | Replace prerequisite pattern detection with intent classifier |
| Phase 4 | Week 7-8 | Implement structured plan parser, scenario registry |
| Phase 5 | Week 9-10 | Tool-specific result parsers |
| Phase 6 | Ongoing | Fine-tuned models, threshold optimization |

---

## Files to Modify

### New Files
- `packages/soothe/src/soothe/core/goal_engine/semantic_risk_classifier.py`
- `packages/soothe/src/soothe/core/goal_engine/semantic_relationship_detector.py`
- `packages/soothe/src/soothe/core/loop/utils/failure_intent_classifier.py`
- `packages/soothe/src/soothe/core/loop/planning/structured_plan_parser.py`
- `packages/soothe/src/soothe/core/loop/engine/scenario_registry.py`
- `packages/soothe/src/soothe/core/loop/engine/tool_result_registry.py`
- `config/scenarios.yml`

### Modified Files
- `packages/soothe/src/soothe/core/goal_engine/criticality.py` (add semantic path)
- `packages/soothe/src/soothe/core/goal_engine/relationship_detector.py` (add semantic path)
- `packages/soothe/src/soothe/core/loop/utils/reflection.py` (add failure intent path)
- `packages/soothe/src/soothe/core/loop/planning/parser.py` (add structured path)
- `packages/soothe/src/soothe/core/loop/engine/scenario_classifier.py` (use registry)
- `packages/soothe/src/soothe/core/loop/engine/metadata_generator.py` (use registry)
- `packages/soothe/src/soothe/config/settings.py` (add new config options)

### Tests
- `packages/soothe/tests/unit/core/goal_engine/test_semantic_risk_classifier.py`
- `packages/soothe/tests/unit/core/goal_engine/test_semantic_relationship_detector.py`
- `packages/soothe/tests/unit/core/loop/utils/test_failure_intent_classifier.py`
- `packages/soothe/tests/unit/core/loop/planning/test_structured_plan_parser.py`
- `packages/soothe/tests/unit/core/loop/engine/test_scenario_registry.py`
- `packages/soothe/tests/unit/core/loop/engine/test_tool_result_registry.py`

---

## Configuration Additions

```yaml
# config/config.template.yml additions
optimization:
  semantic_risk:
    enabled: true
    cache_enabled: true
    cache_similarity_threshold: 0.9
    fallback_to_keywords: true
  
  semantic_relationships:
    enabled: true
    embedding_model: "text-embedding-3-small"
    auto_apply_threshold: 0.85
    flag_threshold: 0.70
  
  failure_intent:
    enabled: true
    llm_confidence_threshold: 0.7
```

---

## Migration Strategy

### Pattern: Gradual Rollout with Fallback

```python
# Example: criticality.py migration
async def evaluate_criticality_v2(
    description: str,
    priority: int,
    *,
    use_semantic: bool = True,  # Feature flag
) -> CriticalityResult:
    if use_semantic:
        try:
            return await semantic_evaluate_risk(description, priority, model)
        except Exception:
            logger.warning("Semantic risk eval failed, falling back to keywords")
    
    # Legacy path
    return evaluate_criticality_legacy(description, priority)
```

---

## Monitoring Metrics

1. **False Negative Rate:** Risky operations that bypassed confirmation
2. **False Positive Rate:** Safe operations that triggered unnecessary confirmation
3. **Latency:** p95 response time for each classifier
4. **Cache Hit Rate:** Semantic cache effectiveness
5. **Accuracy:** Compared to manual labeling on sample set

---

## Success Criteria

- [ ] Semantic risk classifier achieves <5% false negative rate (production validation pending)
- [ ] Relationship detection maintains >90% precision at 0.85 threshold (production validation pending)
- [ ] Prerequisite detection reduces false positives by 50% (production validation pending)
- [x] All phases have unit tests
- [x] `./scripts/verify_finally.sh` passes
- [x] No regression in existing test suite

---

## Dependencies

- `sentence-transformers` (already optional dependency)
- `scikit-learn` (for completion classifier)
- `numpy` (already available)

---

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| LLM latency for risk classification | Implement embedding cache for common patterns |
| Embedding model not available | Fallback to keyword matching always enabled |
| Training data for completion classifier | Start with heuristic labels, refine with user feedback |
| Breaking changes to existing behavior | Feature flags for gradual rollout |

---

## References

- Prior audit: `docs/impl/IG-XXX-keyword-heuristic-audit.md` (if created)
- Related IGs: IG-394 (AgentLoop), IG-396 (Loop Graph)
- RFCs: RFC-204, RFC-220, RFC-616
