# IG-364: Planning and Intent Classification Prompt Layout Optimization

**Status**: ✅ Completed

**Goal**: Optimize planning system prompts and polish intent classification input format with XML structure.

---

## Changes Summary

### 1. Planning System Prompt Optimization

**What changed**: Reordered planning system prompt sections in `PromptBuilder._build_system_message()`:
- Removed `AVAILABLE_CAPABILITIES` section (unused metadata enrichment)
- Placed static sections foremost for cache optimization
- ENVIRONMENT section placed after REASONING_STANDARDS (before WORKSPACE)
- WORKSPACE section placed last (dynamic project-specific content)

**Files modified**:
- `packages/soothe/src/soothe/core/prompts/builder.py`
- `packages/soothe/src/soothe/core/runner/_runner_agentic.py` (removed unused variable)

**New ordering (static-always → conditional static → global → dynamic)**:
```xml
<EXECUTION_POLICIES>        <!-- static-always fragment -->
<PLAN_EXECUTE_LOOP>         <!-- static-always instructions -->
<COMPLETION_SIGNALS>        <!-- static-always instructions -->
<ACTION_PROGRESSION>        <!-- static-always instructions -->
<REASONING_STANDARDS>       <!-- static-always instructions -->
<WORKSPACE_RULES>           <!-- conditional static (when workspace present) -->
<FOLLOW_UP_POLICY>          <!-- conditional static (when prior conversation exists) -->
<ENVIRONMENT>               <!-- global (platform, model) -->
<WORKSPACE>                 <!-- dynamic (project path, git branch) -->
```

**Benefits**:
- Improved prompt cache efficiency (static-always fragments cached longest)
- Clear separation of static-always/conditional-static/global/dynamic content
- Conditional static sections placed after truly static fragments for optimal caching
- Removed unused capability metadata enrichment (46 lines deleted)

### 2. Intent Classification Input Format Polish

**What changed**: Reformatted intent classification prompts to use flat XML structure (removed nested `<runtime_context>` wrapper).

**Files modified**:
- `packages/soothe/src/soothe/cognition/intention/prompts.py` (flat XML structure)
- `packages/soothe/src/soothe/cognition/intention/classifier.py` (no changes needed)

**Before (nested structure from IG-363)**:
```xml
<intent_inputs>
<runtime_context>
  <current_time>2026-05-03 09:21 UTC</current_time>
  <thread_id>g1ru5zrazj98</thread_id>
  <active_goal>None (no active goal in thread)</active_goal>
</runtime_context>
<recent_conversation>
  [Prior conversation excerpts]
</recent_conversation>
<current_query>
  [User's query text]
</current_query>
</intent_inputs>
```

**After (flat structure per IG-364)**:
```xml
<intent_inputs>
<current_time>2026-05-03 09:42 UTC</current_time>
<thread_id>fnw7bdwwwfpe</thread_id>
<active_goal>None (no active goal in thread)</active_goal>
<recent_conversation>

</recent_conversation>
<current_query>
get first 10 lines of project readme
</current_query>
</intent_inputs>
```

**Alignment with planning prompts**:
- ✅ Similar XML envelope structure (`<intent_classification>` wrapper)
- ✅ Clear separation of static instructions (`<intent_instructions>`) and dynamic inputs (`<intent_inputs>`)
- ✅ **Flat XML structure** (runtime context fields as direct children, not nested in `<runtime_context>`)
- ✅ Conversation excerpts use `<user>`/`<assistant>` tags (matching AgentLoop plan style)
- ✅ Consistent with planning system's flat XML approach (WORKSPACE, ENVIRONMENT sections)

**Benefits**:
- Simplified XML structure (no unnecessary nesting)
- Consistent flat XML format across both intent and planning prompts
- Easier to read and maintain

---

## Implementation Details

### Planning Prompt Changes (builder.py)

**Before** (mixed ordering):
```python
# Environment/workspace prefix (RFC-104) - dynamic first
if self.config is not None:
    parts.append(build_shared_environment_workspace_prefix(...))

# Workspace rules - static
if context.workspace:
    parts.append("<WORKSPACE_RULES>...")

# Available capabilities - removed (unused)
if context.available_capabilities:
    parts.append(f"<AVAILABLE_CAPABILITIES>...")

# Static fragments
parts.append(EXECUTION_POLICIES_FRAGMENT)
parts.append(PLAN_EXECUTE_INSTRUCTIONS_FRAGMENT)
```

**After** (optimized ordering):
```python
# Static-always fragments first (best cache efficiency)
parts.append(EXECUTION_POLICIES_FRAGMENT)
parts.append(PLAN_EXECUTE_INSTRUCTIONS_FRAGMENT)  # Contains LOOP/COMPLETION/ACTION/REASONING

# Conditional static sections (present based on context)
if context.workspace:
    parts.append("<WORKSPACE_RULES>...")

if context.recent_messages:
    parts.append("<FOLLOW_UP_POLICY>...")

# Global section (ENVIRONMENT)
if self.config is not None:
    parts.append(build_soothe_environment_section(model=model))

# Dynamic section (WORKSPACE) - last
if context.workspace:
    parts.append(build_soothe_workspace_section(...))
```

**Rationale for ordering**:
- **Static-always fragments** (EXECUTION_POLICIES, PLAN_EXECUTE_INSTRUCTIONS): Always present, placed first for maximum cache efficiency
- **Conditional static sections** (WORKSPACE_RULES, FOLLOW_UP_POLICY): Present based on context, but still static content when included
- **Global section** (ENVIRONMENT): Contains platform/model info, changes rarely
- **Dynamic section** (WORKSPACE): Contains project-specific path/git info, changes frequently, placed last

This ordering ensures prompt cache hits are maximized by grouping content by volatility:
- Cache tier 1: Static-always fragments (never change)
- Cache tier 2: Conditional static sections (change based on context availability)
- Cache tier 3: ENVIRONMENT (changes per platform/model)
- Cache tier 4: WORKSPACE (changes per project)

**Method removed**: `_format_capabilities_with_metadata()` (46 lines, unused since capabilities metadata not needed)

### Linting Fix (_runner_agentic.py)

Removed unused variable `prior_limit` (line 376, flagged by Ruff F841).

---

## Testing

**Verification**:
- `./scripts/verify_finally.sh` runs full suite (format-check, lint, unit tests)
- Linting: Zero errors required ✅
- Tests: Pre-existing failures in `test_agent_loop_adaptive_final.py` (Mock validation errors unrelated to this change)

**Test coverage**:
- `test_plan_phase_prompt_workspace.py`: Checks ENVIRONMENT and WORKSPACE presence
- No ordering-specific tests (order is structural optimization, not functional change)

---

## References

**Related RFCs**:
- RFC-207: System/Human message separation
- RFC-104: Environment/workspace context sections
- RFC-214: AgentLoop ledger history

**Related IGs**:
- IG-183: Prompt caching optimization (prefetched fragments)
- IG-363: Intent classification prompt XML format (prior work)

---

## Completion Checklist

- [x] Planning prompt reordered (static-always → conditional static → ENVIRONMENT → WORKSPACE)
- [x] AVAILABLE_CAPABILITIES section removed
- [x] `_format_capabilities_with_metadata()` method deleted
- [x] Docstring updated in `_build_system_message()` with ordering rationale
- [x] Linting error fixed (`prior_limit` unused variable)
- [x] Intent classification reformatted to flat XML (removed nested `<runtime_context>` wrapper)
- [x] Updated docstring in `prompts.py` to reflect flat XML structure
- [x] Implementation guide created and updated (IG-364)

**Test Results**:
- ✅ Intent classification tests: 21/21 passed
- ✅ Plan phase prompt tests: 6/6 passed
- ✅ Dynamic system context tests: 25/25 passed
- ✅ Linting: Zero errors
- ⚠️ Pre-existing failures in `test_agent_loop_adaptive_final.py` (Mock validation errors unrelated to changes)

---

**Completed**: 2026-05-03