# IG-146: Dynamic Tool/System Context Injection Implementation

**Implementation Guide**: 0146
**RFC**: RFC-210
**Status**: Ready for Implementation
**Created**: 2026-04-09
**Dependencies**: RFC-104, RFC-208, RFC-600

## Overview

This guide implements RFC-210: Dynamic Tool/System Context Injection, enabling tools and subagents to declare and inject tool-specific system message fragments based on actual usage.

**Key Changes**:
1. Extend `@tool`/`@subagent` decorators with `system_context` and `triggers` parameters
2. Create `ToolTriggerRegistry` and `ToolContextRegistry` for managing tool→section mappings
3. Extend `SystemPromptOptimizationMiddleware` to build dynamic sections based on tool usage
4. Migrate built-in tools/subagents to use new system

**Estimated Scope**: ~480 lines across 6 files + test updates

---

## Implementation Steps

### Step 1: Extend Plugin Decorators (soothe_sdk)

**File**: `soothe_sdk/decorators.py`

**Changes**:
```python
def tool(
    name: str,
    description: str,
    system_context: str | None = None,  # NEW
    triggers: list[str] | None = None,   # NEW
    **kwargs
):
    """Tool decorator with optional system context injection.

    Args:
        name: Tool name.
        description: Tool description.
        system_context: Optional XML fragment for system message when tool is active.
        triggers: Optional list of section names this tool triggers.
        **kwargs: Additional tool configuration.
    """
    def decorator(func):
        # Store in function metadata
        func._tool_metadata = {
            "name": name,
            "description": description,
            "system_context": system_context,
            "triggers": triggers or [],
            **kwargs
        }
        return func
    return decorator

def subagent(
    name: str,
    description: str,
    model: str | None = None,
    system_context: str | None = None,  # NEW
    triggers: list[str] | None = None,   # NEW
    **kwargs
):
    """Subagent decorator with optional system context injection."""
    def decorator(func):
        func._subagent_metadata = {
            "name": name,
            "description": description,
            "model": model,
            "system_context": system_context,
            "triggers": triggers or [],
            **kwargs
        }
        return func
    return decorator
```

**Testing**:
```python
def test_tool_decorator_with_system_context():
    @tool(name="test", description="Test", system_context="<TEST>content</TEST>", triggers=["TEST"])
    def test_tool():
        pass

    assert test_tool._tool_metadata["system_context"] == "<TEST>content</TEST>"
    assert test_tool._tool_metadata["triggers"] == ["TEST"]
```

---

### Step 2: Create ToolTriggerRegistry

**File**: `src/soothe/core/tool_trigger_registry.py` (new file)

**Implementation**:
```python
"""Registry for tool→section trigger mappings."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from soothe.plugin.registry import PluginRegistry


# Built-in tool triggers (hardcoded for core tools)
BUILTIN_TOOL_TRIGGERS: dict[str, list[str]] = {
    # File operation tools
    "read_file": ["WORKSPACE"],
    "write_file": ["WORKSPACE"],
    "glob": ["WORKSPACE"],
    "grep": ["WORKSPACE"],
    "edit_file": ["WORKSPACE"],
    "delete_file": ["WORKSPACE"],
    "insert_lines": ["WORKSPACE"],
    "apply_diff": ["WORKSPACE"],

    # Execution tools
    "run_command": ["WORKSPACE"],
    "run_python": ["WORKSPACE"],
    "run_background": ["WORKSPACE"],
    "kill_process": [],

    # Web tools
    "search_web": [],  # No workspace dependency
    "crawl_web": [],

    # Data tools
    "inspect_data": ["WORKSPACE"],
    "summarize_data": ["WORKSPACE"],
    "check_data_quality": ["WORKSPACE"],
    "extract_text": ["WORKSPACE"],
    "get_data_info": ["WORKSPACE"],
    "ask_about_file": ["WORKSPACE"],

    # Image/audio/video tools
    "analyze_image": [],
    "transcribe_audio": [],
    "analyze_video": [],

    # Subagents
    "browser": ["WORKSPACE", "BROWSER_CONTEXT"],
    "research": ["RESEARCH_RULES", "context"],
    "claude": [],

    # Goal management tools
    "create_goal": ["THREAD", "PROTOCOLS"],
    "list_goals": ["THREAD"],
    "complete_goal": ["THREAD"],
    "fail_goal": ["THREAD"],

    # Datetime
    "datetime": [],
}


class ToolTriggerRegistry:
    """Registry for tool→section trigger mappings.

    Tools declare which system message sections they require.
    Built-in tools have hardcoded triggers, plugins define their own.
    """

    def __init__(self, plugin_registry: PluginRegistry | None = None) -> None:
        """Initialize trigger registry.

        Args:
            plugin_registry: Optional plugin registry for plugin tool metadata.
        """
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
            elif self._plugin_registry:
                # Check plugin metadata for custom tools
                tool_metadata = self._plugin_registry.get_tool_metadata(tool_name)
                if tool_metadata and "triggers" in tool_metadata:
                    sections.update(tool_metadata["triggers"])

        return sections
```

**Unit tests**:
```python
def test_builtin_tool_triggers():
    registry = ToolTriggerRegistry()

    # Single tool
    assert registry.get_triggered_sections(["read_file"]) == {"WORKSPACE"}

    # Multiple tools
    assert registry.get_triggered_sections(["read_file", "write_file"]) == {"WORKSPACE"}

    # Different tools, different sections
    assert registry.get_triggered_sections(["read_file", "browser"]) == {"WORKSPACE", "BROWSER_CONTEXT"}

def test_unknown_tool_no_triggers():
    registry = ToolTriggerRegistry()
    assert registry.get_triggered_sections(["unknown_tool"]) == set()

def test_plugin_tool_triggers():
    # Mock plugin registry with custom tool
    mock_registry = Mock()
    mock_registry.get_tool_metadata.return_value = {"triggers": ["CUSTOM_SECTION"]}

    registry = ToolTriggerRegistry(plugin_registry=mock_registry)
    assert registry.get_triggered_sections(["custom_tool"]) == {"CUSTOM_SECTION"}
```

---

### Step 3: Create ToolContextRegistry

**File**: `src/soothe/core/tool_context_registry.py` (new file)

**Implementation**:
```python
"""Registry for tool/subagent system context fragments."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from soothe.config import SootheConfig
    from soothe.plugin.registry import PluginRegistry

logger = logging.getLogger(__name__)


class ToolContextRegistry:
    """Registry for tool/subagent system context fragments.

    Merges plugin-defined fragments with config overrides.
    Priority: config override > plugin metadata > None
    """

    def __init__(self, config: SootheConfig, plugin_registry: PluginRegistry | None = None) -> None:
        """Initialize context registry.

        Args:
            config: Soothe configuration for override lookup.
            plugin_registry: Optional plugin registry for metadata lookup.
        """
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

        # 1. Check config override (highest priority)
        config_fragment = self._get_config_override(tool_name)
        if config_fragment:
            logger.debug("Using config override for tool '%s' system_context", tool_name)
            self._cache[tool_name] = config_fragment
            return config_fragment

        # 2. Check plugin metadata
        plugin_fragment = self._get_plugin_metadata(tool_name)
        if plugin_fragment:
            logger.debug("Using plugin metadata for tool '%s' system_context", tool_name)

        self._cache[tool_name] = plugin_fragment
        return plugin_fragment

    def _get_config_override(self, tool_name: str) -> str | None:
        """Get config-defined system context for tool.

        Checks:
        - subagents[name].config.system_context
        - plugins config (if tool discovered via plugin)

        Args:
            tool_name: Tool or subagent name.

        Returns:
            System context string from config, or None.
        """
        # Check subagents config
        if tool_name in self._config.subagents:
            subagent_config = self._config.subagents[tool_name]
            if subagent_config.config and "system_context" in subagent_config.config:
                return subagent_config.config["system_context"]

        # Check plugins config
        for plugin_cfg in self._config.plugins:
            if plugin_cfg.name == tool_name:
                if plugin_cfg.config and "system_context" in plugin_cfg.config:
                    return plugin_cfg.config["system_context"]

        return None

    def _get_plugin_metadata(self, tool_name: str) -> str | None:
        """Get plugin-defined system context for tool.

        Args:
            tool_name: Tool or subagent name.

        Returns:
            System context string from plugin metadata, or None.
        """
        if not self._plugin_registry:
            return None

        # Check tool metadata
        tool_metadata = self._plugin_registry.get_tool_metadata(tool_name)
        if tool_metadata and "system_context" in tool_metadata:
            return tool_metadata["system_context"]

        # Check subagent metadata
        subagent_metadata = self._plugin_registry.get_subagent_metadata(tool_name)
        if subagent_metadata and "system_context" in subagent_metadata:
            return subagent_metadata["system_context"]

        return None
```

**Unit tests**:
```python
def test_config_override_priority():
    config = SootheConfig(
        subagents={
            "browser": SubagentConfig(
                config={"system_context": "<CONFIG>override</CONFIG>"}
            )
        }
    )
    mock_plugin_registry = Mock()
    mock_plugin_registry.get_tool_metadata.return_value = {
        "system_context": "<PLUGIN>default</PLUGIN>"
    }

    registry = ToolContextRegistry(config, mock_plugin_registry)
    result = registry.get_system_context("browser")

    assert result == "<CONFIG>override</CONFIG>"

def test_plugin_metadata_fallback():
    config = SootheConfig()
    mock_plugin_registry = Mock()
    mock_plugin_registry.get_tool_metadata.return_value = {
        "system_context": "<PLUGIN>default</PLUGIN>"
    }

    registry = ToolContextRegistry(config, mock_plugin_registry)
    result = registry.get_system_context("custom_tool")

    assert result == "<PLUGIN>default</PLUGIN>"

def test_missing_tool_returns_none():
    config = SootheConfig()
    registry = ToolContextRegistry(config, None)

    result = registry.get_system_context("nonexistent")
    assert result is None
```

---

### Step 4: Extend SystemPromptOptimizationMiddleware

**File**: `src/soothe/core/middleware/system_prompt_optimization.py`

**Changes**:

1. **New imports**:
```python
from langchain_core.messages import ToolMessage
from soothe.core.tool_trigger_registry import ToolTriggerRegistry
from soothe.core.tool_context_registry import ToolContextRegistry
```

2. **Extended `__init__`**:
```python
def __init__(
    self,
    config: SootheConfig,
    tool_trigger_registry: ToolTriggerRegistry | None = None,
    tool_context_registry: ToolContextRegistry | None = None,
) -> None:
    """Initialize the system prompt optimization middleware.

    Args:
        config: Soothe configuration instance.
        tool_trigger_registry: Optional registry for tool→section triggers.
        tool_context_registry: Optional registry for tool→context fragments.
    """
    self._config = config
    self._tool_trigger_registry = tool_trigger_registry
    self._tool_context_registry = tool_context_registry
```

3. **New helper methods** (add after `__init__`):
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
    """Determine if WORKSPACE section should be injected.

    Conditions:
    1. Workspace tools were recently used
    2. Workspace is actually set

    Args:
        state: Request state.

    Returns:
        True if WORKSPACE should be injected.
    """
    if not self._tool_trigger_registry:
        return False

    messages = state.get("messages", [])
    recent_tools = self._extract_recent_tool_calls(messages)
    triggered = self._tool_trigger_registry.get_triggered_sections(recent_tools)

    if "WORKSPACE" not in triggered:
        return False

    # Check if workspace is set
    workspace = state.get("workspace")
    return workspace is not None

def _should_inject_thread(self, state: dict[str, Any]) -> bool:
    """Determine if THREAD section should be injected.

    Conditions:
    1. Multi-turn conversation (messages > 1)
    2. OR active goals exist

    Args:
        state: Request state.

    Returns:
        True if THREAD should be injected.
    """
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

    # Join with separator (UPPERCASE)
    separator = "\n--- TOOL-SPECIFIC CONTEXT (DYNAMIC) ---\n"
    return separator + "\n\n".join(sections) + "\n"
```

4. **Update `_build_workspace_section`** to use UPPERCASE tag:
```python
def _build_workspace_section(self, workspace: Path | None, git_status: dict | None) -> str:
    """Build <WORKSPACE> section."""
    # ... existing implementation ...
    return "<WORKSPACE>\n" + "\n".join(content) + "\n</WORKSPACE>"
```

5. **Update `_build_thread_section`** to use UPPERCASE tag:
```python
def _build_thread_section(self, thread_context: dict) -> str:
    """Build <THREAD> section."""
    # ... existing implementation ...
    return "<THREAD>\n" + "\n".join(content) + "\n</THREAD>"
```

6. **Update `_build_protocols_section`** to use UPPERCASE tag:
```python
def _build_protocols_section(self, protocol_summary: dict) -> str:
    """Build <PROTOCOLS> section."""
    # ... existing implementation ...
    return "<PROTOCOLS>\n" + "\n".join(content) + "\n</PROTOCOLS>"
```

7. **Modify `_get_prompt_for_complexity`**:
```python
def _get_prompt_for_complexity(self, complexity: str, state: dict[str, Any] | None = None) -> str:
    """Get prompt with separated static and dynamic context sections."""
    base_core = self._get_base_prompt_core(complexity)
    date_line = self._current_date_line()

    # Chitchat: only base + ENVIRONMENT + date
    if complexity == "chitchat":
        env_section = self._build_environment_section()
        return f"{base_core}\n\n{env_section}\n\n{date_line}"

    # Build STATIC sections
    static_sections = [base_core]

    # ENVIRONMENT (always static)
    static_sections.append(self._build_environment_section())

    # Context projection and memories (conditional on tool triggers)
    if state and self._tool_trigger_registry:
        messages = state.get("messages", [])
        recent_tools = self._extract_recent_tool_calls(messages)
        triggered = self._tool_trigger_registry.get_triggered_sections(recent_tools)

        projection = state.get("context_projection")
        if projection and projection.entries and "context" in triggered:
            static_sections.append(self._build_context_section(projection))

        memories = state.get("recalled_memories")
        if memories and "memory" in triggered:
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

**Unit tests**:
```python
def test_extract_recent_tool_calls():
    messages = [
        HumanMessage(content="test"),
        AIMessage(content="", tool_calls=[{"name": "read_file", "args": {}}]),
        ToolMessage(content="file content", name="read_file"),
        AIMessage(content="done"),
    ]

    middleware = SystemPromptOptimizationMiddleware(SootheConfig())
    tools = middleware._extract_recent_tool_calls(messages)

    assert tools == ["read_file"]

def test_should_inject_workspace_with_tools():
    config = SootheConfig()
    trigger_registry = ToolTriggerRegistry()
    middleware = SystemPromptOptimizationMiddleware(
        config,
        tool_trigger_registry=trigger_registry
    )

    messages = [ToolMessage(content="", name="read_file")]
    state = {"messages": messages, "workspace": "/tmp"}

    assert middleware._should_inject_workspace(state) is True

def test_should_inject_workspace_without_workspace():
    config = SootheConfig()
    trigger_registry = ToolTriggerRegistry()
    middleware = SystemPromptOptimizationMiddleware(
        config,
        tool_trigger_registry=trigger_registry
    )

    messages = [ToolMessage(content="", name="read_file")]
    state = {"messages": messages, "workspace": None}

    assert middleware._should_inject_workspace(state) is False

def test_should_inject_thread_multi_turn():
    middleware = SystemPromptOptimizationMiddleware(SootheConfig())

    state = {"messages": [HumanMessage("a"), AIMessage("b")]}

    assert middleware._should_inject_thread(state) is True

def test_should_inject_thread_active_goals():
    middleware = SystemPromptOptimizationMiddleware(SootheConfig())

    state = {"messages": [], "active_goals": ["goal1"]}

    assert middleware._should_inject_thread(state) is True

def test_build_dynamic_sections():
    config = SootheConfig()
    trigger_registry = ToolTriggerRegistry()
    context_registry = Mock()
    context_registry.get_system_context.return_value = "<BROWSER_CONTEXT>test</BROWSER_CONTEXT>"

    middleware = SystemPromptOptimizationMiddleware(
        config,
        tool_trigger_registry=trigger_registry,
        tool_context_registry=context_registry
    )

    messages = [ToolMessage(content="", name="browser")]
    state = {
        "messages": messages,
        "workspace": "/tmp",
        "git_status": {"branch": "main"}
    }

    result = middleware._build_dynamic_sections(state)

    assert "--- TOOL-SPECIFIC CONTEXT (DYNAMIC) ---" in result
    assert "<WORKSPACE>" in result
    assert "<BROWSER_CONTEXT>" in result
```

---

### Step 5: Wire Registries in Agent Factory

**File**: `src/soothe/core/agent/_builder.py`

**New import**:
```python
from soothe.core.tool_trigger_registry import ToolTriggerRegistry
from soothe.core.tool_context_registry import ToolContextRegistry
```

**New helper function**:
```python
def _build_tool_registries(
    config: SootheConfig,
    plugin_registry: PluginRegistry | None = None,
) -> tuple[ToolTriggerRegistry | None, ToolContextRegistry | None]:
    """Create tool trigger and context registries.

    Args:
        config: Soothe configuration.
        plugin_registry: Optional plugin registry.

    Returns:
        Tuple of (trigger_registry, context_registry), or (None, None) if not configured.
    """
    if not config.performance.enabled or not config.performance.optimize_system_prompts:
        return None, None

    trigger_registry = ToolTriggerRegistry(plugin_registry)
    context_registry = ToolContextRegistry(config, plugin_registry)

    return trigger_registry, context_registry
```

**Modify `_create_middlewares`**:
```python
def _create_middlewares(
    config: SootheConfig,
    plugin_registry: PluginRegistry | None = None,
    # ... other parameters ...
) -> list[AgentMiddleware]:
    """Create middleware stack."""
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

---

### Step 6: Migrate Built-in Tools/Subagents

#### Browser Subagent

**File**: `src/soothe/subagents/browser/__init__.py`

**Changes**:
```python
@subagent(
    name="browser",
    description=(
        "Browser automation specialist for web tasks. Can navigate pages, click "
        "elements, fill forms, extract content, and take screenshots. Use for "
        "web scraping, form automation, and browser-based testing."
    ),
    model="openai:gpt-4o-mini",
    system_context="""<BROWSER_CONTEXT>
<navigation_rules>
Always verify URLs before navigation to prevent security issues.
Check for HTTPS when handling sensitive data (logins, payments).
Handle JavaScript-heavy pages with patience - wait for dynamic content.
Detect and handle CAPTCHAs, authentication prompts, and interactive elements.
</navigation_rules>
<output_interpretation>
Browser results include page states, DOM snapshots, and screenshots.
URLs in results show navigation history and current page location.
Status indicators show success/failure of navigation actions.
Screenshots capture visual state for verification.
</output_interpretation>
<best_practices>
Use specific selectors (CSS, XPath) for reliable element interaction.
Implement retry logic for transient failures.
Capture screenshots at key navigation points for debugging.
</best_practices>
</BROWSER_CONTEXT>""",
    triggers=["WORKSPACE", "BROWSER_CONTEXT"]
)
async def create_browser(...):
    ...
```

#### Research Subagent

**File**: `src/soothe/subagents/research/__init__.py`

**Changes**:
```python
@subagent(
    name="research",
    description="Deep research and investigation agent",
    model="openai:gpt-4o-mini",
    system_context="""<RESEARCH_RULES>
<source_verification>
Cross-reference claims across multiple independent sources.
Prefer primary sources (original papers, official docs) over secondary.
Check publication dates and relevance to current context.
Identify and note potential conflicts of interest or bias.
</source_verification>
<citation_format>
Use markdown links for sources: [Title](URL)
Include timestamps when available: [Title](URL) (accessed YYYY-MM-DD)
Format quotes clearly with attribution.
</citation_format>
<depth_guidelines>
Start broad to understand context, then narrow to specifics.
Investigate contradictory information thoroughly.
Document search strategy and sources consulted.
Provide confidence levels for claims based on evidence strength.
</depth_guidelines>
</RESEARCH_RULES>""",
    triggers=["RESEARCH_RULES", "context"]
)
async def create_research(...):
    ...
```

#### File Tools

**File**: `src/soothe/tools/file_ops/__init__.py` (or wherever file tools are registered)

**Changes** (example for read_file):
```python
@tool(
    name="read_file",
    description="Read file contents",
    triggers=["WORKSPACE"]
)
def read_file(...):
    ...
```

Apply same pattern to all file operation tools.

---

## Testing Plan

### Unit Tests (new file)

**File**: `tests/unit/core/test_tool_trigger_registry.py`

Test cases:
- Built-in tool trigger lookup
- Plugin tool trigger lookup
- Multiple tools trigger union
- Unknown tool returns empty set

**File**: `tests/unit/core/test_tool_context_registry.py`

Test cases:
- Config override replaces plugin metadata
- Plugin metadata fallback
- Missing tool returns None
- Caching works correctly

**File**: `tests/unit/middleware/test_system_prompt_optimization_dynamic.py`

Test cases:
- `_extract_recent_tool_calls()` extracts from ToolMessages
- `_should_inject_workspace()` respects workspace condition
- `_should_inject_thread()` respects multi-turn/goal condition
- `_build_dynamic_sections()` builds correct sections
- Separator placement and UPPERCASE formatting
- Integration with registries

### Integration Tests

**File**: `tests/integration/test_dynamic_tool_context.py`

Test cases:
- Browser tool invocation injects WORKSPACE + BROWSER_CONTEXT
- Research tool invocation injects RESEARCH_RULES
- File tools without workspace don't inject WORKSPACE
- Multi-turn conversation injects THREAD
- Config override replaces plugin system_context
- Token efficiency verification

### Verification

```bash
# Run all tests
./scripts/verify_finally.sh

# Expected results:
# - All formatting checks pass
# - Zero linting errors
# - All 900+ unit tests pass
# - Integration tests pass
```

---

## Rollback Plan

If issues arise:

1. **Disable dynamic injection**:
   - Pass `None` for registries in `_create_middlewares()`
   - System reverts to static injection (RFC-104/208 behavior)

2. **Disable specific tool**:
   - Remove `triggers` and `system_context` from tool decorator
   - Tool works normally, just no context injection

3. **Override config**:
   - Set `system_context: ""` in config.yml to disable specific tool's context

---

## Success Criteria

- [ ] All decorator parameters implemented and tested
- [ ] ToolTriggerRegistry and ToolContextRegistry created
- [ ] SystemPromptOptimizationMiddleware extended with dynamic injection
- [ ] Built-in tools migrated (browser, research, file ops)
- [ ] All unit tests pass
- [ ] Integration tests verify injection behavior
- [ ] Token usage reduced 40-60% for typical queries
- [ ] Zero linting errors
- [ ] UPPERCASE formatting for all tags and separator

---

## Timeline

**Estimated effort**: 2-3 days

- Day 1: Implement registries + middleware changes (Steps 1-4)
- Day 2: Wire factory + migrate tools (Steps 5-6)
- Day 3: Write tests, verify, polish

---

## Post-Implementation

1. **Monitor token usage**: Compare before/after token counts for typical queries
2. **Gather feedback**: Check if tool-specific guidance improves LLM responses
3. **Document**: Update RFC-104/208 to reference RFC-210 as refinement
4. **Extend**: Encourage plugin authors to add `system_context` to their tools

---

*This implementation guide provides step-by-step instructions for RFC-210 dynamic tool context injection.*