# RFC-207: Dynamic Tool/System Context Injection

**RFC**: 0210
**Title**: Dynamic Tool/System Context Injection
**Status**: Draft
**Kind**: Architecture Refinement
**Created**: 2026-04-09
**Dependencies**: RFC-104, RFC-207, RFC-207, RFC-600, RFC-100
**Replaces**: None (refines RFC-104/208 context injection)

## Abstract

This RFC introduces dynamic, tool-driven system context injection where tools and subagents declare which system message sections they require. This replaces static complexity-based injection with intelligent trigger-based injection, reducing token usage by 40-60% for typical queries while enabling tool-specific guidance.

## Motivation

### Current Limitations

Soothe's system message construction (RFC-104, RFC-207) injects context sections statically based on complexity:

**Problems**:

1. **Token inefficiency**: Simple queries receive workspace, thread, protocol context even when irrelevant
   - Example: "What is 2+2?" receives 300+ tokens of irrelevant workspace/git/thread info

2. **No tool-specific guidance**: Tools cannot inject specialized system context
   - Browser tool cannot add navigation rules to system message
   - Research tool cannot add citation policies

3. **Static architecture**: Context injection is complexity-driven, not usage-driven
   - WORKSPACE injected for all medium/complex queries regardless of actual file operations

4. **Limited extensibility**: Third-party tools cannot contribute system context

### Proposed Solution

**Tool-triggered dynamic injection**:

1. Tools/subagents declare which sections they trigger via metadata
2. Middleware inspects recent tool calls to determine active sections
3. Only relevant sections are injected into system message
4. Clear static/dynamic separation with symbolic marker

**Benefits**:

- ✅ 40-60% token reduction for typical queries
- ✅ Tool-specific guidance when relevant
- ✅ Plugin-extensible (follows RFC-600)
- ✅ Backward compatible

---

## Specification

### Static vs Dynamic Zones

**Static Zone** (always injected):
```
[base prompt]
<ENVIRONMENT>
  <platform>darwin</platform>
  <shell>/bin/zsh</shell>
  <os_version>Darwin 25.2.0</os_version>
  <model>claude-sonnet-4-6</model>
  <knowledge_cutoff>2025-05</knowledge_cutoff>
</ENVIRONMENT>

Today's date is 2026-04-09.
```

**Dynamic Zone** (tool/condition-triggered):
```
--- TOOL-SPECIFIC CONTEXT (DYNAMIC) ---

<WORKSPACE>
  <root>/Users/chenxm/Workspace/Soothe</root>
  <vcs present="true">
    <branch>develop</branch>
    <main_branch>main</main_branch>
  </vcs>
</WORKSPACE>

<BROWSER_CONTEXT>
  <navigation_rules>Always verify HTTPS before navigation...</navigation_rules>
</BROWSER_CONTEXT>
```

**Separator**: Text separator `--- TOOL-SPECIFIC CONTEXT (DYNAMIC) ---` marks boundary.

**Style**: All XML tags and separator text use UPPERCASE for consistency.

### Section Trigger Types

| Section | Trigger Type | Condition | Related Tools |
|---------|--------------|-----------|---------------|
| `<ENVIRONMENT>` | Static | Always | N/A |
| `<WORKSPACE>` | Tool + Condition | File tools used AND workspace set | read_file, write_file, glob, grep, browser |
| `<THREAD>` | State | Multi-turn (messages > 1) OR active goals | Goal management |
| `<PROTOCOLS>` | Tool | Protocol tools used | Memory, context, planning |
| `<context>` | Tool + Condition | Context tools used AND projection available | research |
| `<memory>` | Tool + Condition | Memory tools used AND memories recalled | Memory queries |
| Tool-specific | Tool | Specific tool invoked | browser, research, etc. |

### Component Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Tool Execution (LangGraph loop)                            │
│  - Tool invoked → ToolMessage added to messages[]           │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│  SystemPromptOptimizationMiddleware                          │
│  1. Extract recent tool names from ToolMessages             │
│  2. Query ToolTriggerRegistry for triggered sections        │
│  3. Query ToolContextRegistry for tool-specific fragments   │
│  4. Build dynamic sections with separator                   │
│  5. Inject into SystemMessage                               │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│  Model receives enriched SystemMessage                       │
│  - Static context (ENVIRONMENT)                             │
│  - Dynamic context (WORKSPACE, BROWSER_CONTEXT, etc.)       │
└─────────────────────────────────────────────────────────────┘
```

### Plugin Decorator Extension

**Updated `@tool` decorator** (soothe_sdk):
```python
@tool(
    name="browser",
    description="Browser automation",
    system_context="<BROWSER_CONTEXT>Navigation rules...</BROWSER_CONTEXT>",
    triggers=["WORKSPACE", "BROWSER_CONTEXT"]
)
def browser_tool(...):
    ...
```

**Updated `@subagent` decorator**:
```python
@subagent(
    name="research",
    description="Research specialist",
    model="openai:gpt-4o-mini",
    system_context="<RESEARCH_RULES>Citation policies...</RESEARCH_RULES>",
    triggers=["RESEARCH_RULES", "context"]
)
async def create_researcher(...):
    ...
```

**New parameters**:
- `system_context: str | None` - XML fragment to inject when tool is active
- `triggers: list[str] | None` - Section names this tool triggers

### Tool Trigger Registry

**File**: `src/soothe/core/tool_trigger_registry.py`

**Built-in triggers** (hardcoded for core tools):
```python
BUILTIN_TOOL_TRIGGERS = {
    # File tools
    "read_file": ["WORKSPACE"],
    "write_file": ["WORKSPACE"],
    "glob": ["WORKSPACE"],
    "grep": ["WORKSPACE"],
    "edit_file": ["WORKSPACE"],

    # Execution tools
    "run_command": ["WORKSPACE"],
    "run_python": ["WORKSPACE"],

    # Subagents
    "browser": ["WORKSPACE", "BROWSER_CONTEXT"],
    "research": ["RESEARCH_RULES", "context"],

    # Goal management
    "create_goal": ["THREAD", "PROTOCOLS"],
    "list_goals": ["THREAD"],
}
```

**Registry class**:
```python
class ToolTriggerRegistry:
    """Registry for tool→section trigger mappings."""

    def get_triggered_sections(self, tool_names: list[str]) -> set[str]:
        """Get sections triggered by tool names.

        Checks built-in triggers first, then plugin metadata.
        """
        ...
```

### Tool Context Registry

**File**: `src/soothe/core/tool_context_registry.py`

**Priority**: Config override > Plugin metadata > None

```python
class ToolContextRegistry:
    """Registry for tool system context fragments."""

    def get_system_context(self, tool_name: str) -> str | None:
        """Get system context for tool.

        Checks:
        1. subagents[name].config.system_context (override)
        2. plugins[name].config.system_context (override)
        3. Plugin metadata (tool/subagent decorator)
        """
        ...
```

### Middleware Implementation

**File**: `src/soothe/core/middleware/system_prompt_optimization.py`

**New methods**:
```python
def _extract_recent_tool_calls(messages: list[AnyMessage], window: int = 10) -> list[str]:
    """Extract tool names from recent ToolMessages."""
    ...

def _should_inject_workspace(state: dict) -> bool:
    """Check if WORKSPACE section should be injected."""
    # Condition: workspace tools used AND workspace is set
    ...

def _should_inject_thread(state: dict) -> bool:
    """Check if THREAD section should be injected."""
    # Condition: multi-turn OR active goals
    ...

def _build_dynamic_sections(state: dict) -> str:
    """Build all dynamic sections with separator."""
    ...
```

**Modified `_get_prompt_for_complexity`**:
```python
def _get_prompt_for_complexity(complexity: str, state: dict) -> str:
    """Build system message with static and dynamic zones."""
    # Static: base + ENVIRONMENT
    static = [base_core, self._build_environment_section()]

    # Dynamic: triggered sections + tool-specific fragments
    dynamic = self._build_dynamic_sections(state)

    # Assemble with separator
    if dynamic:
        return "\n\n".join(static) + "\n" + dynamic + "\n\n" + date_line
    else:
        return "\n\n".join(static) + "\n\n" + date_line
```

### Configuration Override

**File**: `config.yml`

```yaml
subagents:
  browser:
    enabled: true
    config:
      system_context: |
        <BROWSER_CONTEXT>
        <deployment_rules>Production-specific browser policies...</deployment_rules>
        </BROWSER_CONTEXT>
      headless: true
```

**Behavior**: Config `system_context` completely replaces plugin-defined fragment.

---

## Implementation

### Files Modified

1. **`soothe_sdk/decorators.py`** (~20 lines):
   - Add `system_context` and `triggers` parameters to decorators
   - Include in metadata dict

2. **`src/soothe/core/tool_trigger_registry.py`** (new file, ~80 lines):
   - Define `BUILTIN_TOOL_TRIGGERS` dict
   - Implement `ToolTriggerRegistry` class

3. **`src/soothe/core/tool_context_registry.py`** (new file, ~100 lines):
   - Implement `ToolContextRegistry` class
   - Config override logic
   - Plugin metadata lookup

4. **`src/soothe/core/middleware/system_prompt_optimization.py`** (~150 lines modified):
   - Add registry parameters to `__init__`
   - Add `_extract_recent_tool_calls()` method
   - Add `_should_inject_workspace()` method
   - Add `_should_inject_thread()` method
   - Add `_build_dynamic_sections()` method
   - Modify `_get_prompt_for_complexity()` to use dynamic injection

5. **`src/soothe/core/agent/_builder.py`** (~30 lines):
   - Create registry instances
   - Pass to middleware constructor

6. **Built-in tools/subagents** (~100 lines total):
   - Add `triggers` and `system_context` to file tools
   - Add to browser subagent
   - Add to research subagent

**Total**: ~480 new/modified lines across 6 files

### Migration Strategy

1. **Add decorator parameters** (backward compatible):
   - Optional parameters, default None
   - Existing tools work unchanged

2. **Create registries** (no behavior change):
   - Standalone components
   - Not wired into middleware yet

3. **Extend middleware** (backward compatible):
   - Registry parameters are optional
   - When None, behaves exactly as before

4. **Wire registries** (feature activation):
   - Agent factory creates and passes registries
   - Dynamic injection activates

5. **Migrate built-in tools**:
   - Add triggers and system_context to core tools
   - Test token efficiency and LLM quality

**Rollback**: Pass None for registries → reverts to static injection

---

## Testing

### Unit Tests

**ToolTriggerRegistry**:
- Built-in tool trigger lookup
- Plugin metadata trigger lookup
- Multiple tools trigger union of sections

**ToolContextRegistry**:
- Config override replaces plugin metadata
- Plugin metadata fallback when no config
- Missing tool returns None

**SystemPromptOptimizationMiddleware**:
- `_extract_recent_tool_calls()` extracts from ToolMessages
- `_should_inject_workspace()` respects workspace condition
- `_should_inject_thread()` respects multi-turn/goal condition
- `_build_dynamic_sections()` builds correct sections
- Separator placement correct
- UPPERCASE tags and separator

### Integration Tests

- Browser tool → WORKSPACE + BROWSER_CONTEXT injected
- File tools without workspace → no WORKSPACE section
- Single-turn query → no THREAD section
- Multi-turn conversation → THREAD section appears
- Config override replaces plugin system_context
- Token usage reduced for simple queries

### Verification

```bash
./scripts/verify_finally.sh  # Format, lint, 900+ tests
```

---

## Token Efficiency

### Before (Static)

**Complex query**: ~600 tokens (base + ENV + WORKSPACE + THREAD + PROTOCOLS)

### After (Dynamic)

**Simple query** ("What is 2+2?"):
- ~250 tokens (base + ENVIRONMENT only)
- **58% reduction**

**File operation** ("Read README.md"):
- ~400 tokens (base + ENV + WORKSPACE)
- **33% reduction**

**Browser automation**:
- ~500 tokens (base + ENV + WORKSPACE + BROWSER_CONTEXT)
- **17% reduction**

**Average savings**: 40-60% for typical queries

---

## Edge Cases

| Case | Handling |
|------|----------|
| Tool with no triggers | No sections triggered, tool executes normally |
| Tool with no system_context | Section triggered but no fragment injected |
| Malformed system_context XML | Log warning, inject anyway |
| Multiple tools trigger same section | Section injected once (deduplication) |
| Config override empty string | No fragment injected (empty override) |
| Workspace tools but no workspace | WORKSPACE not injected (condition check) |
| Single-turn with active goals | THREAD injected (goal condition met) |

---

## Benefits

### Token Efficiency
✅ 40-60% reduction for typical queries
✅ Only inject relevant context
✅ Prevents token bloat on simple tasks

### Tool-Specific Guidance
✅ Browser navigation rules when browser active
✅ Research citation policies when research active
✅ Deployment-specific overrides via config

### Architectural Clarity
✅ Clear static/dynamic separation
✅ Tool ownership of context (follows RFC-600)
✅ Plugin-extensible mechanism

### Backward Compatibility
✅ Existing tools work unchanged
✅ Optional decorator parameters
✅ Registry parameters optional in middleware

---

## Success Criteria

- [ ] Tool-specific fragments injected when tools active
- [ ] WORKSPACE only when workspace tools used AND workspace set
- [ ] THREAD only for multi-turn or active goals
- [ ] Static/dynamic separator marks zones
- [ ] All tags and separator use UPPERCASE
- [ ] Config override replaces plugin metadata
- [ ] Token usage reduced 40-60%
- [ ] All 900+ tests pass
- [ ] Zero linting errors

---

## Related Specifications

- RFC-104: Dynamic System Context Injection
- RFC-207: CoreAgent Message Optimization
- RFC-207: SystemMessage/HumanMessage Separation
- RFC-600: Plugin Extension System
- RFC-100: CoreAgent Runtime

---

## Changelog

**2026-04-09 (created)**:
- Initial RFC for dynamic tool-triggered context injection
- Replaces static complexity-based injection
- Introduces tool trigger and context registries
- Defines static/dynamic zone separation

---

*This RFC enables intelligent, usage-driven system context injection while maintaining token efficiency and architectural clarity.*