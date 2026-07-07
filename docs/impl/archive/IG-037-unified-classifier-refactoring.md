# Template Intent Optimization - Implementation Complete

## Summary

Successfully optimized planning intent classification by consolidating two separate LLM calls into a single unified classification call. This reduces latency for non-chitchat queries while maintaining all safety guarantees.

## Changes Made

### 1. Extended UnifiedClassification Model
- **File**: `src/soothe/core/unified_classifier.py`
- Added `template_intent` field with type `Literal["question", "search", "analysis", "implementation"] | None`
- Default value is `None` (for chitchat queries or queries that don't fit categories)

### 2. Updated Classification Prompt
- **File**: `src/soothe/core/unified_classifier.py`
- Extended `_UNIFIED_CLASSIFICATION_PROMPT` to include template intent classification
- Added comprehensive guide for classifying intent:
  - question: who/what/where/when/why/how queries
  - search: search/find/look up queries
  - analysis: analyze/review/examine/investigate queries
  - implementation: implement/create/build/write queries
  - null: chitchat or queries that don't fit other categories

### 3. Updated SimplePlanner
- **File**: `src/soothe/cognition/planning/simple.py`
- Modified `create_plan()` to check for pre-computed `template_intent` from `context.unified_classification`
- Removed `classify_intent()` call (previously made a second LLM call)
- Removed `fast_model` parameter from constructor (no longer needed)
- Updated docstrings to reflect new optimization

### 4. Removed classify_intent Function
- **File**: `src/soothe/cognition/planning/_templates.py`
- Deleted `_INTENT_CLASSIFY_PROMPT` constant
- Deleted `classify_intent()` async function
- Removed import from `simple.py`

### 5. Updated Resolver
- **File**: `src/soothe/core/resolver.py`
- Removed `fast_model` parameter from `SimplePlanner` instantiation
- Simplified planner initialization

### 6. Comprehensive Test Coverage
- **File**: `tests/unit_tests/test_unified_classifier.py`
- Added `TestTemplateIntent` class with 5 new tests
- Updated all existing tests to include `template_intent` field where appropriate

## Verification Results

### Unit Tests
- `test_unified_classifier.py`: 21 passed ✓
- `test_planning.py`: 17 passed ✓

### Integration Test
Verified that:
1. UnifiedClassification correctly includes `template_intent`
2. Classifier returns the intent in a single LLM call
3. SimplePlanner can access and use pre-computed intent
4. Template matching works with pre-computed intent
5. All imports and dependencies work correctly

## Benefits Achieved

1. **Reduced Latency**: Eliminated one fast-model LLM call for non-chitchat queries
   - Before: 2 calls (UnifiedClassifier + classify_intent)
   - After: 1 call (UnifiedClassifier with template_intent)

2. **Consistent Classification**: Single classification point ensures routing and planning decisions are coherent

3. **Maintained Safety**: Chitchat queries still skip planning (template_intent is null and unused)

4. **Better UX**: Faster response times for common query types

## Architecture Flow

### Before Optimization
```
SootheRunner._run_single_pass()
  → UnifiedClassifier.classify() → FAST MODEL CALL #1
  → if chitchat: exit early
  → else: SimplePlanner.create_plan()
    → classify_intent() → FAST MODEL CALL #2 (if template regex fails)
```

### After Optimization
```
SootheRunner._run_single_pass()
  → UnifiedClassifier.classify() → SINGLE FAST MODEL CALL
    → Returns: task_complexity + is_plan_only + template_intent
  → if chitchat: exit early (no planning, no intent used)
  → else: SimplePlanner.create_plan()
    → Use pre-computed template_intent from context
```
