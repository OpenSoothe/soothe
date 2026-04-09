# Design Draft: Dynamic Tool/System Context Injection

**Date**: 2026-04-09
**Author**: Platonic brainstorming session
**Status**: Draft for review

## Problem Statement

Soothe's current system message construction (RFC-104, RFC-208) injects all context sections statically based on complexity level. This creates inefficiencies:

1. **Token bloat**: Simple queries receive workspace, thread, and protocol context even when irrelevant
2. **No tool-specific guidance**: Tools/subagents cannot inject their own specialized system context
3. **Static architecture**: Context sections are always injected regardless of actual tool usage
4. **Limited extensibility**: Third-party tools cannot contribute system context

**Example inefficiency**:
- User asks "What is 2+2?" (chitchat)
- System injects: `<ENVIRONMENT>`, `<WORKSPACE>`, `<THREAD>`, `<PROTOCOLS>`
- Only `<ENVIRONMENT>` is actually needed
- 300+ tokens wasted

## Proposed Solution

**Dynamic context injection** with two key mechanisms:

1. **Tool-triggered sections**: Tools/subagents declare which system context sections they need via metadata
2. **State-triggered sections**: Context sections injected based on conversation state (multi-turn, active goals)

**Benefits**:
- ✅ 60-70% token reduction for simple queries
- ✅ Tool-specific guidance when relevant
- ✅ Plugin-extensible (follows RFC-600)
- ✅ Clear static/dynamic separation

## Architecture

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

**Dynamic Zone** (injected based on triggers):
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
  <output_interpretation>Browser results include page states...</output_interpretation>
</BROWSER_CONTEXT>
```

### Section Trigger Types

| Section | Trigger Type | Condition | Related Tools |
|---------|--------------|-----------|---------------|
| `<ENVIRONMENT>` | Static | Always | N/A |
| `<WORKSPACE>` | Tool + Condition | File tools used AND workspace set | read_file, write_file, glob, grep, browser |
| `<THREAD>` | State | Multi-turn (messages > 1) OR active goals | Goal management tools |
| `<PROTOCOLS>` | Tool | Protocol tools used | Memory, context, planning tools |
| `<context>` | Tool + Condition | Context tools used AND projection available | research, analysis |
| `<memory>` | Tool + Condition | Memory tools used AND memories recalled | Memory query tools |
| `<BROWSER_CONTEXT>` | Tool | Browser tool invoked | browser subagent |
| `<RESEARCH_RULES>` | Tool | Research tool invoked | research subagent |

### Injection Priority

**For each section**:
1. **Config override** (highest): `subagents.browser.config.system_context`
2. **Plugin metadata**: `@tool(system_context="...")`
3. **None** (no injection)

## Component Design

### 1. Plugin Decorator Extension

**File**: `soothe_sdk/decorators.py`

**Updated `@tool` decorator**:
```python
@tool(
    name="browser",
    description="Browser automation",
    system_context="<BROWSER_CONTEXT>Default browser rules...</BROWSER_CONTEXT>",
    triggers=["WORKSPACE", "BROWSER_CONTEXT"]  # Sections this tool triggers
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
    system_context="<RESEARCH_RULES>Cross-reference sources...</RESEARCH_RULES>",
    triggers=["RESEARCH_RULES", "context"]
)
async def create_researcher(...):
    ...
```

**New decorator parameters**:
- `system_context: str | None` - XML fragment to inject when tool is active
- `triggers: list[str] | None` - List of section names this tool triggers

**Validation**:
- `system_context` validated as well-formed XML at plugin load time
- Malformed XML logs warning but allows plugin to load (graceful degradation)
- `triggers` validated against known section names

### 2. Tool Trigger Registry

**File**: `src/soothe/core/tool_trigger_registry.py`

**Built-in tool triggers** (hardcoded for core tools):
```python
BUILTIN_TOOL_TRIGGERS = {
    # File operation tools
    "read_file": ["WORKSPACE"],
    "write_file": ["WORKSPACE"],
    "glob": ["WORKSPACE"],
    "grep": ["WORKSPACE"],
    "edit_file": ["WORKSPACE"],
    "delete_file": ["WORKSPACE"],

    # Execution tools
    "run_command": ["WORKSPACE"],
    "run_python": ["WORKSPACE"],

    # Web tools
    "search_web": ["WORKSPACE"],  # May need workspace for saving results
    "crawl_web": [],  # No workspace dependency

    # Subagents
    "browser": ["WORKSPACE", "BROWSER_CONTEXT"],
    "research": ["RESEARCH_RULES", "context"],
    "claude": [],  # No special sections

    # Goal management
    "create_goal": ["THREAD", "PROTOCOLS"],
    "list_goals": ["THREAD"],
    "complete_goal": ["THREAD"],
    "fail_goal": ["THREAD"],

    # Data tools
    "inspect_data": ["WORKSPACE"],
    "summarize_data": ["WORKSPACE"],

    # Image/video/audio tools
    "analyze_image": [],
    "transcribe_audio": [],
    "analyze_video": [],
}
```

**Registry class**:
```python
class ToolTriggerRegistry:
    """Registry for tool→section trigger mappings."""

    def __init__(self, plugin_registry: PluginRegistry):
        self._plugin_registry = plugin_registry

    def get_triggered_sections(self, tool_names: list[str]) -> set[str]:
        """Get sections triggered by a set of tool names.

        Args:
            tool_names: List of tool names that were recently invoked.

        Returns:
            Set of section names that should be injected.
        """
        sections = set()

        for tool_name in tool_names:
            # Check built-in triggers first
            if tool_name in BUILTIN_TOOL_TRIGGERS:
                sections.update(BUILTIN_TOOL_TRIGGERS[tool_name])
            else:
                # Check plugin metadata
                metadata = self._plugin_registry.get_tool_metadata(tool_name)
                if metadata and "triggers" in metadata:
                    sections.update(metadata["triggers"])

        return sections
```

### 3. Tool Context Registry

**File**: `src/soothe/core/tool_context_registry.py`

**Purpose**: Map tool names to their system context fragments, with config override support.

```python
class ToolContextRegistry:
    """Registry for tool/subagent system context fragments.

    Merges plugin-defined fragments with config overrides.
    Priority: config override > plugin metadata > None
    """

    def __init__(self, config: SootheConfig, plugin_registry: PluginRegistry):
        self._config = config
        self._plugin_registry = plugin_registry
        self._cache: dict[str, str | None] = {}

    def get_system_context(self, tool_name: str) -> str | None:
        """Get system context fragment for a tool/subagent.

        Args:
            tool_name: Tool or subagent name.

        Returns:
            XML system context string, or None if not defined.
        """
        if tool_name in self._cache:
            return self._cache[tool_name]

        # 1. Check config override (subagents.browser.config.system_context)
        config_fragment = self._get_config_override(tool_name)
        if config_fragment:
            self._cache[tool_name] = config_fragment
            return config_fragment

        # 2. Check plugin metadata
        plugin_fragment = self._get_plugin_metadata(tool_name)
        self._cache[tool_name] = plugin_fragment
        return plugin_fragment

    def _get_config_override(self, tool_name: str) -> str | None:
        """Get config-defined system context for tool."""
        # Check subagents config
        if tool_name in self._config.subagents:
            subagent_config = self._config.subagents[tool_name]
            if subagent_config.config and "system_context" in subagent_config.config:
                return subagent_config.config["system_context"]

        # Check plugins config (for plugin-discovered tools)
        for plugin_cfg in self._config.plugins:
            if plugin_cfg.name == tool_name:
                if plugin_cfg.config and "system_context" in plugin_cfg.config:
                    return plugin_cfg.config["system_context"]

        return None

    def _get_plugin_metadata(self, tool_name: str) -> str | None:
        """Get plugin-defined system context for tool."""
        # Query plugin registry for tool metadata
        tool_metadata = self._plugin_registry.get_tool_metadata(tool_name)
        if tool_metadata and "system_context" in tool_metadata:
            return tool_metadata["system_context"]

        # Check subagent metadata
        subagent_metadata = self._plugin_registry.get_subagent_metadata(tool_name)
        if subagent_metadata and "system_context" in subagent_metadata:
            return subagent_metadata["system_context"]

        return None
```

### 4. Extended SystemPromptOptimizationMiddleware

**File**: `src/soothe/core/middleware/system_prompt_optimization.py`

**New imports**:
```python
from langchain_core.messages import ToolMessage
from soothe.core.tool_trigger_registry import ToolTriggerRegistry
from soothe.core.tool_context_registry import ToolContextRegistry
```

**Extended `__init__`**:
```python
def __init__(
    self,
    config: SootheConfig,
    tool_trigger_registry: ToolTriggerRegistry | None = None,
    tool_context_registry: ToolContextRegistry | None = None,
) -> None:
    self._config = config
    self._tool_trigger_registry = tool_trigger_registry
    self._tool_context_registry = tool_context_registry
```

**New helper methods**:
```python
def _extract_recent_tool_calls(self, messages: list[AnyMessage], window: int = 10) -> list[str]:
    """Extract unique tool names from recent ToolMessages.

    Args:
        messages: Conversation message history.
        window: Number of recent messages to inspect.

    Returns:
        Unique tool names from tool calls, most recent first.
    """
    if not messages:
        return []

    recent_messages = messages[-window:] if len(messages) > window else messages
    tool_names = []

    for msg in reversed(recent_messages):
        if isinstance(msg, ToolMessage):
            # Extract tool name from ToolMessage
            tool_name = msg.name
            if tool_name and tool_name not in tool_names:
                tool_names.append(tool_name)

    # Limit to prevent bloat
    return tool_names[:5]

def _should_inject_workspace(self, state: dict[str, Any]) -> bool:
    """Determine if WORKSPACE section should be injected."""
    # Check if workspace tools were used
    if not self._tool_trigger_registry:
        return False

    messages = state.get("messages", [])
    recent_tools = self._extract_recent_tool_calls(messages)
    triggered = self._tool_trigger_registry.get_triggered_sections(recent_tools)

    if "WORKSPACE" not in triggered:
        return False

    # Check if workspace is actually set
    workspace = state.get("workspace")
    return workspace is not None

def _should_inject_thread(self, state: dict[str, Any]) -> bool:
    """Determine if THREAD section should be injected."""
    # Check conversation turns
    messages = state.get("messages", [])
    if len(messages) > 1:
        return True

    # Check active goals
    active_goals = state.get("active_goals", [])
    if active_goals:
        return True

    return False

def _build_dynamic_sections(self, state: dict[str, Any]) -> str:
    """Build all dynamic context sections based on triggers.

    Args:
        state: Request state with messages and context.

    Returns:
        Dynamic sections string with separator, or empty string.
    """
    if not state or not self._tool_trigger_registry:
        return ""

    messages = state.get("messages", [])
    recent_tools = self._extract_recent_tool_calls(messages)
    triggered_sections = self._tool_trigger_registry.get_triggered_sections(recent_tools)

    # Build sections list
    sections = []

    # WORKSPACE (tool-triggered + condition)
    if "WORKSPACE" in triggered_sections and self._should_inject_workspace(state):
        workspace_section = self._build_workspace_section(
            state.get("workspace"),
            state.get("git_status")
        )
        if workspace_section:
            sections.append(workspace_section)

    # THREAD (state-triggered)
    if self._should_inject_thread(state):
        thread_section = self._build_thread_section(state.get("thread_context", {}))
        if thread_section:
            sections.append(thread_section)

    # PROTOCOLS (tool-triggered)
    if "PROTOCOLS" in triggered_sections:
        protocols_section = self._build_protocols_section(state.get("protocol_summary", {}))
        if protocols_section:
            sections.append(protocols_section)

    # Tool-specific sections (from tool_context_registry)
    if self._tool_context_registry:
        for tool_name in recent_tools:
            tool_section = self._tool_context_registry.get_system_context(tool_name)
            if tool_section:
                sections.append(tool_section.strip())

    if not sections:
        return ""

    # Join with separator
    separator = "\n--- TOOL-SPECIFIC CONTEXT (DYNAMIC) ---\n"
    return separator + "\n\n".join(sections) + "\n"
```

**Modified `_get_prompt_for_complexity`**:
```python
def _get_prompt_for_complexity(self, complexity: str, state: dict[str, Any] | None = None) -> str:
    """Get prompt with separated static and dynamic context sections."""
    base_core = self._get_base_prompt_core(complexity)
    date_line = self._current_date_line()

    # Chitchat: only base + environment + date
    if complexity == "chitchat":
        env_section = self._build_environment_section()
        return f"{base_core}\n\n{env_section}\n\n{date_line}"

    # Build STATIC sections
    static_sections = [base_core]

    # ENVIRONMENT (always static)
    static_sections.append(self._build_environment_section())

    # Context projection and memories (static for CoreAgent, but conditionally included)
    if state:
        projection = state.get("context_projection")
        if projection and projection.entries:
            # Only inject if triggered by tools
            messages = state.get("messages", [])
            recent_tools = self._extract_recent_tool_calls(messages)
            if self._tool_trigger_registry:
                triggered = self._tool_trigger_registry.get_triggered_sections(recent_tools)
                if "context" in triggered:
                    static_sections.append(self._build_context_section(projection))

        memories = state.get("recalled_memories")
        if memories:
            # Only inject if triggered by tools
            messages = state.get("messages", [])
            recent_tools = self._extract_recent_tool_calls(messages)
            if self._tool_trigger_registry:
                triggered = self._tool_trigger_registry.get_triggered_sections(recent_tools)
                if "memory" in triggered:
                    static_sections.append(self._build_memory_section(memories))

    # Build DYNAMIC sections
    dynamic_section = ""
    if state:
        dynamic_section = self._build_dynamic_sections(state)

    # Assemble: static + dynamic (if any) + date
    static_content = "\n\n".join(static_sections)

    if dynamic_section:
        return static_content + "\n" + dynamic_section + "\n\n" + date_line
    else:
        return static_content + "\n\n" + date_line
```

**Key changes**:
- Dynamic sections only built when `state` and registries available
- WORKSPACE conditional on both tool trigger AND workspace existence
- THREAD conditional on multi-turn or active goals
- Tool-specific sections injected from `ToolContextRegistry`
- Clear static/dynamic separation with separator line

### 5. Agent Factory Integration

**File**: `src/soothe/core/agent/_builder.py`

**Create registries**:
```python
def _build_tool_registries(
    config: SootheConfig,
    plugin_registry: PluginRegistry,
) -> tuple[ToolTriggerRegistry, ToolContextRegistry]:
    """Create tool trigger and context registries.

    Args:
        config: Soothe configuration.
        plugin_registry: Plugin registry with tool metadata.

    Returns:
        Tuple of (trigger_registry, context_registry).
    """
    trigger_registry = ToolTriggerRegistry(plugin_registry)
    context_registry = ToolContextRegistry(config, plugin_registry)
    return trigger_registry, context_registry
```

**Wire into middleware**:
```python
def _create_middlewares(config: SootheConfig, plugin_registry: PluginRegistry) -> list[AgentMiddleware]:
    """Create middleware stack with tool context injection."""
    trigger_registry, context_registry = _build_tool_registries(config, plugin_registry)

    middlewares = [
        SystemPromptOptimizationMiddleware(
            config,
            tool_trigger_registry=trigger_registry,
            tool_context_registry=context_registry,
        ),
        # ... other middlewares ...
    ]
    return middlewares
```

## Configuration

### Config Override Example

**File**: `config.yml`

```yaml
subagents:
  browser:
    enabled: true
    config:
      system_context: |
        <BROWSER_CONTEXT>
        <deployment_rules>
        For production deployments, disable social media navigation.
        Always use headless mode in automated workflows.
        Maximum navigation steps: 50.
        </deployment_rules>
        </BROWSER_CONTEXT>
      headless: true
      max_steps: 100

  research:
    enabled: true
    config:
      system_context: |
        <RESEARCH_RULES>
        <citation_policy>
        Always cite sources with URLs and timestamps.
        Cross-reference claims across multiple sources.
        Mark speculation clearly.
        </citation_policy>
        </RESEARCH_RULES>
```

**Priority**: Config override completely replaces plugin-defined `system_context`.

## Plugin Migration

### Example: Browser Plugin

**Before** (current):
```python
@tool(name="browser", description="Browser automation")
def browser_tool(...):
    ...
```

**After** (with system context):
```python
@tool(
    name="browser",
    description="Browser automation",
    system_context="""<BROWSER_CONTEXT>
<navigation_rules>
Always verify HTTPS before navigation.
Handle JavaScript-heavy pages with patience.
Check for CAPTCHAs and interactive elements.
</navigation_rules>
<output_interpretation>
Browser results include: page states, DOM snapshots, screenshots.
URLs show navigation history. Status indicates success/failure.
</output_interpretation>
</BROWSER_CONTEXT>""",
    triggers=["WORKSPACE", "BROWSER_CONTEXT"]
)
def browser_tool(...):
    ...
```

### Example: Research Subagent

**Before**:
```python
@subagent(name="research", description="Research specialist", model="openai:gpt-4o-mini")
async def create_researcher(...):
    ...
```

**After**:
```python
@subagent(
    name="research",
    description="Research specialist",
    model="openai:gpt-4o-mini",
    system_context="""<RESEARCH_RULES>
<source_verification>
Cross-reference claims across multiple sources.
Prefer primary sources over secondary.
Check publication dates for relevance.
</source_verification>
<citation_format>
Use markdown links for sources: [Title](URL)
Include timestamps when available.
</citation_format>
</RESEARCH_RULES>""",
    triggers=["RESEARCH_RULES", "context"]
)
async def create_researcher(...):
    ...
```

## Testing Strategy

### Unit Tests

**Tool Trigger Registry**:
- Test built-in tool trigger mappings
- Test plugin-defined trigger lookup
- Test tool combinations (multiple tools trigger multiple sections)

**Tool Context Registry**:
- Test config override priority
- Test plugin metadata fallback
- Test missing tool handling (returns None)

**SystemPromptOptimizationMiddleware**:
- Test `_extract_recent_tool_calls()` with various message histories
- Test `_should_inject_workspace()` with/without workspace
- Test `_should_inject_thread()` with single-turn vs multi-turn
- Test `_build_dynamic_sections()` with various tool combinations
- Test static/dynamic separator placement
- Test uppercase tags and separator

**Integration Tests**:
- Browser tool invocation → WORKSPACE + BROWSER_CONTEXT injected
- Research tool invocation → RESEARCH_RULES + context injected
- File tools without workspace → no WORKSPACE section
- Single-turn query → no THREAD section
- Multi-turn conversation → THREAD section appears
- Config override replaces plugin metadata

### Verification

```bash
./scripts/verify_finally.sh  # Format, lint, 900+ tests
```

## Token Efficiency Analysis

### Before (Static Injection)

**Complex query**:
- Base prompt: ~200 tokens
- ENVIRONMENT: ~50 tokens
- WORKSPACE: ~150 tokens
- THREAD: ~100 tokens
- PROTOCOLS: ~100 tokens
- **Total**: ~600 tokens (static)

### After (Dynamic Injection)

**Simple query** ("What is 2+2?"):
- Base prompt: ~200 tokens
- ENVIRONMENT: ~50 tokens
- **Total**: ~250 tokens (58% reduction)

**File operation** ("Read README.md"):
- Base prompt: ~200 tokens
- ENVIRONMENT: ~50 tokens
- WORKSPACE: ~150 tokens
- **Total**: ~400 tokens (33% reduction)

**Browser automation** ("Navigate to example.com"):
- Base prompt: ~200 tokens
- ENVIRONMENT: ~50 tokens
- WORKSPACE: ~150 tokens
- BROWSER_CONTEXT: ~100 tokens
- **Total**: ~500 tokens (17% reduction)

**Multi-turn research**:
- Base prompt: ~200 tokens
- ENVIRONMENT: ~50 tokens
- THREAD: ~100 tokens
- RESEARCH_RULES: ~100 tokens
- context: ~150 tokens
- **Total**: ~600 tokens (same as before, but now includes tool-specific guidance)

**Average savings**: 40-60% for typical queries

## Edge Cases

| Case | Handling |
|------|----------|
| Tool with no triggers | Tool executes normally, no sections injected |
| Tool with no system_context | Section triggered but no fragment to inject |
| Malformed system_context XML | Log warning, inject anyway (graceful degradation) |
| Multiple tools trigger same section | Section injected once (deduplication) |
| Config override is empty string | Empty override, no fragment injected |
| Workspace tools but no workspace set | WORKSPACE section not injected (condition check) |
| Single-turn with active goals | THREAD section injected (goal condition) |
| Plugin not found in registry | Return None, no fragment injected |

## Migration Path

1. **Add decorator parameters** (backward compatible):
   - Add `system_context` and `triggers` to `@tool` and `@subagent`
   - Both optional, default to None

2. **Create registries** (no behavior change):
   - `ToolTriggerRegistry` with built-in mappings
   - `ToolContextRegistry` for fragment storage

3. **Extend middleware** (no feature flag needed):
   - Add registry support to `SystemPromptOptimizationMiddleware`
   - Registries are optional parameters (None by default for backward compatibility)
   - When registries are None, middleware behaves exactly as before (static injection)

4. **Migrate built-in tools**:
   - Add `triggers` and `system_context` to browser, research, file tools
   - Test with feature flag enabled

5. **Enable by default**:
   - Set `dynamic_tool_context: true` by default
   - Monitor token usage and LLM response quality

6. **Update documentation**:
   - RFC-104: Note dynamic injection refinement
   - Plugin development guide: Document new decorator parameters

## Success Criteria

- [ ] Tool-specific system context fragments injected when tools are active
- [ ] WORKSPACE only injected when workspace tools used AND workspace set
- [ ] THREAD only injected for multi-turn or active goals
- [ ] Static/dynamic separator clearly marks zones
- [ ] All XML tags and separator use UPPERCASE
- [ ] Config override replaces plugin metadata
- [ ] Token usage reduced 40-60% for typical queries
- [ ] All 900+ tests pass
- [ ] Zero linting errors
- [ ] Backward compatible (tools without triggers work unchanged)

## Open Questions

None. All design decisions finalized through brainstorming.

## References

- RFC-104: Dynamic System Context Injection
- RFC-208: CoreAgent Message Optimization
- RFC-207: SystemMessage/HumanMessage Separation
- RFC-600: Plugin Extension System
- RFC-100: CoreAgent Runtime

---

*This design enables intelligent, tool-driven system context injection while maintaining architectural clarity and token efficiency.*