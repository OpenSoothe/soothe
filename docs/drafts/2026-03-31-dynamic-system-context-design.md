# Dynamic System Context Injection Design

**Date:** 2026-03-31
**Status:** Draft
**Author:** Platonic brainstorming session

## Problem Statement

Soothe agents receive static system prompts set at agent creation time. The LLM lacks awareness of:
- Current working directory and git repository state
- Platform, shell, and environment context
- Thread-specific state (goals, conversation history)
- Protocol availability and state (memory, context, planner)

This limits the agent's ability to make context-aware decisions, especially for file operations and workspace-relative tasks.

**Reference:** Claude Code's approach (see `workspace-context-analysis.md`) injects environment context directly into system prompts, enabling correct tool argument generation.

## Design Overview

Extend `SystemPromptOptimizationMiddleware` to dynamically inject structured XML context sections into system prompts. Each section uses `<SOOTHE_*>` tags for clear LLM comprehension.

### Key Decisions

| Decision | Choice | Reason |
|----------|--------|--------|
| Injection point | Extend existing middleware | Reuses classification access, unified prompt handling |
| XML tag purpose | LLM comprehension | Structured sections help LLM distinguish context sources |
| Trigger mechanism | Classification-driven adaptive | Aligns with existing complexity-based optimization |
| Section visibility | Complexity-dependent | Minimal for chitchat, full for complex tasks |

## Architecture

### XML Tag Structure

Each context section uses a dedicated `<SOOTHE_*>` tag:

```xml
<SOOTHE_ENVIRONMENT>
  Platform: darwin
  Shell: zsh
  OS Version: Darwin 25.2.0
  Model: claude-opus-4-6
  Knowledge cutoff: 2025-05
</SOOTHE_ENVIRONMENT>

<SOOTHE_WORKSPACE>
  Primary working directory: /Users/chenxm/Workspace/Soothe
  Is a git repository: true
  Current branch: develop
  Main branch: main
  Status: M src/soothe/core/agent.py
  Recent commits:
    7f7d076 fix: replace os.getcwd() with Path.cwd()
    878c1ad fix: convert logging f-strings to lazy formatting
</SOOTHE_WORKSPACE>

<SOOTHE_THREAD>
  Thread ID: thread-abc123
  Active goals: ["Implement RFC-103", "Write tests"]
  Conversation turns: 5
</SOOTHE_THREAD>

<SOOTHE_PROTOCOLS>
  Context: VectorContext (8 entries, 1200 tokens)
  Memory: KeywordMemory (3 items recalled)
  Planner: ClaudePlanner (active)
  Policy: ConfigDrivenPolicy (profile: default)
</SOOTHE_PROTOCOLS>
```

### Section Content Details

#### SOOTHE_ENVIRONMENT

Static environment information available at startup:

| Field | Source |
|-------|--------|
| Platform | `platform.system()` (darwin, linux, windows) |
| Shell | `os.environ.get("SHELL")` or derived from `$0` |
| OS Version | `platform.platform()` or `uname -sr` |
| Model | `config.resolve_model("default")` |
| Knowledge cutoff | Model-specific constant (hardcoded per model family) |

#### SOOTHE_WORKSPACE

Dynamic workspace information collected per-request:

| Field | Source |
|-------|--------|
| Primary working directory | `FrameworkFilesystem.get_current_workspace()` or `Path.cwd()` |
| Is a git repository | Check `.git` existence |
| Current branch | `git branch --show-current` |
| Main branch | `git symbolic-ref refs/remotes/origin/HEAD` or fallback |
| Status | `git status --short` (truncated to 20 lines) |
| Recent commits | `git log --oneline -n 5` |

#### SOOTHE_THREAD

Thread-specific state from runner state:

| Field | Source |
|-------|--------|
| Thread ID | `state.thread_id` |
| Active goals | `state.active_goals` or goal engine state |
| Conversation turns | Message count from state or checkpoint |
| Current plan | `state.plan` summary if exists |

#### SOOTHE_PROTOCOLS

Protocol availability and current state:

| Field | Source |
|-------|--------|
| Context | `agent.context` type name + entry count/tokens |
| Memory | `agent.memory` type name + items recalled |
| Planner | `agent.planner` type name + status |
| Policy | `agent.policy` type name + profile |

### Classification-Driven Injection Rules

| Complexity | Sections Injected | Token Budget |
|------------|-------------------|--------------|
| `chitchat` | None | ~50 tokens (base prompt only) |
| `medium` | `<SOOTHE_ENVIRONMENT>`, `<SOOTHE_WORKSPACE>` | ~300 tokens |
| `complex` | All four sections | ~600 tokens |

**Why:** Chitchat queries (greetings, quick questions) don't need workspace context. Medium tasks (file operations, simple commands) need workspace awareness. Complex tasks (multi-step projects, research) benefit from full context.

## Component Changes

### 1. SystemPromptOptimizationMiddleware

**File:** `src/soothe/middleware/system_prompt_optimization.py`

Add new private methods for section building:

```python
def _build_environment_section(self) -> str:
    """Build <SOOTHE_ENVIRONMENT> section with platform/shell/model info."""

def _build_workspace_section(self, workspace: Path | None) -> str:
    """Build <SOOTHE_WORKSPACE> section with cwd/git status."""

def _build_thread_section(self, state: dict) -> str:
    """Build <SOOTHE_THREAD> section with thread/goal info."""

def _build_protocols_section(self, agent: CoreAgent) -> str:
    """Build <SOOTHE_PROTOCOLS> section with protocol state."""
```

Modify `_get_prompt_for_complexity()`:

```python
def _get_prompt_for_complexity(self, complexity: str, state: dict) -> str:
    base_prompt = ... # existing logic

    sections = []
    if complexity in ("medium", "complex"):
        sections.append(self._build_environment_section())
        sections.append(self._build_workspace_section(state.get("workspace")))

    if complexity == "complex":
        sections.append(self._build_thread_section(state))
        sections.append(self._build_protocols_section(state))

    if sections:
        return base_prompt + "\n\n" + "\n\n".join(sections)

    return base_prompt
```

Update `modify_request()` to pass state to prompt builder:

```python
def modify_request(self, request: ModelRequest) -> ModelRequest:
    classification = request.state.get("unified_classification")
    complexity = classification.task_complexity if classification else "medium"

    optimized_prompt = self._get_prompt_for_complexity(complexity, request.state)
    return request.override(system_message=SystemMessage(content=optimized_prompt))
```

### 2. Git Status Collection

**File:** `src/soothe/safety/workspace.py`

Add async git status helper:

```python
async def get_git_status(workspace: Path) -> dict | None:
    """Collect git repository status for workspace.

    Returns None if not a git repository or git unavailable.

    Returns:
        dict with keys: branch, main_branch, status, recent_commits
    """
    if not (workspace / ".git").exists():
        return None

    # Use asyncio.to_thread for subprocess calls
    branch = await asyncio.to_thread(_run_git, ["branch", "--show-current"])
    main_branch = await asyncio.to_thread(_run_git, ["symbolic-ref", "refs/remotes/origin/HEAD"])
    status = await asyncio.to_thread(_run_git, ["status", "--short"])
    commits = await asyncio.to_thread(_run_git, ["log", "--oneline", "-n", "5"])

    return {
        "branch": branch,
        "main_branch": _parse_main_branch(main_branch),
        "status": status[:20],  # Truncate
        "recent_commits": commits,
    }
```

### 3. Knowledge Cutoff Constants

**File:** `src/soothe/config/models.py`

Add knowledge cutoff mapping:

```python
MODEL_KNOWLEDGE_CUTOFFS = {
    "claude-opus-4-6": "2025-05",
    "claude-sonnet-4-6": "2025-05",
    "claude-haiku-4-5": "2025-10",
    "claude-3-5-sonnet": "2025-04",
    # ... other models
}
```

### 4. Protocol State Access

The middleware needs access to protocol instances. Two options:

**Option A:** Pass agent reference to middleware constructor (simple)

```python
class SystemPromptOptimizationMiddleware(AgentMiddleware):
    def __init__(self, config: SootheConfig, agent: CoreAgent) -> None:
        self._config = config
        self._agent = agent  # For protocol state access
```

**Option B:** Inject protocol state into request.state by runner (cleaner separation)

Runner adds protocol summary to state during pre-stream:
```python
state["protocol_summary"] = {
    "context": {"type": "VectorContext", "entries": 8, "tokens": 1200},
    "memory": {"type": "KeywordMemory", "recalled": 3},
    ...
}
```

**Recommendation:** Option B - maintains middleware as pure request modifier, runner owns state assembly.

## Data Flow

```
┌─────────────────────────────────────────────────────────────────┐
│  SootheRunner.astream()                                          │
│  - tier-1: UnifiedClassification (complexity determination)     │
│  - tier-2: Protocol pre-stream (memory recall, context project) │
│  - Collect: workspace, git status, thread state, protocol state │
│  - Inject: all into request.state                               │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  SystemPromptOptimizationMiddleware.modify_request()             │
│  - Read: classification from request.state                      │
│  - Determine: complexity level (chitchat/medium/complex)        │
│  - Select: base prompt template (existing logic)                │
│  - Build: XML sections based on complexity:                     │
│    • chitchat: none                                             │
│    • medium: environment + workspace                            │
│    • complex: all four sections                                 │
│  - Append: sections to base prompt                              │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  Model receives enriched system prompt                           │
│  - Base behavioral instructions                                 │
│  - Structured context in <SOOTHE_*> XML tags                   │
│  - LLM can parse and reference context explicitly               │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  LLM generates tool arguments                                    │
│  - Aware of workspace: resolves paths correctly                 │
│  - Aware of git state: uses correct branch/main                 │
│  - Aware of protocols: can reference memory/context             │
└─────────────────────────────────────────────────────────────────┘
```

## Error Handling

| Failure Scenario | Behavior | Logging |
|------------------|----------|---------|
| Git status unavailable | Skip `<SOOTHE_WORKSPACE>` section | Debug: "Git status collection failed: {reason}" |
| Workspace ContextVar empty | Use `Path.cwd()` as fallback | Debug: "No workspace in context, using cwd" |
| Thread state empty | Skip `<SOOTHE_THREAD>` section | Debug: "No thread state available" |
| Protocol instances None | Skip `<SOOTHE_PROTOCOLS>` section | Debug: "Protocols not initialized" |
| Classification missing | Default to "medium" complexity | Debug: "No classification, defaulting to medium" |
| Section exceeds token budget | Truncate content (git status, commits) | Debug: "Truncated {section} to budget" |

**Principle:** Never block agent execution due to context collection failures. Fail gracefully with partial context.

## Performance Considerations

### Git Status Collection

Git subprocess calls can be slow in large repositories. Strategies:

1. **Async execution:** Use `asyncio.to_thread()` to avoid blocking
2. **Timeout:** 2-second timeout for git commands
3. **Caching:** Memoize git status per workspace for conversation lifetime (optional)
4. **Skip on chitchat:** Don't collect git status for simple queries

### Token Budget Management

Each section has soft token limits:

| Section | Max Tokens | Truncation Strategy |
|---------|------------|---------------------|
| ENVIRONMENT | ~50 | Fixed size, no truncation needed |
| WORKSPACE | ~200 | Truncate git status to 20 lines, commits to 5 |
| THREAD | ~100 | Summarize goals, limit conversation turns |
| PROTOCOLS | ~100 | List protocols only, skip detailed state |

## Testing Strategy

### Unit Tests

**File:** `tests/unit/test_system_prompt_xml_sections.py`

```python
def test_build_environment_section_format():
    """Verify <SOOTHE_ENVIRONMENT> tag structure."""
    middleware = SystemPromptOptimizationMiddleware(config)
    section = middleware._build_environment_section()
    assert "<SOOTHE_ENVIRONMENT>" in section
    assert "</SOOTHE_ENVIRONMENT>" in section
    assert "Platform:" in section

def test_build_workspace_section_git_repo():
    """Verify git status appears in workspace section."""
    section = middleware._build_workspace_section(Path("/git/repo"))
    assert "Current branch:" in section
    assert "Recent commits:" in section

def test_build_workspace_section_non_git():
    """Verify graceful handling of non-git directory."""
    section = middleware._build_workspace_section(Path("/tmp"))
    assert "<SOOTHE_WORKSPACE>" in section
    assert "Is a git repository: false" in section

def test_classification_sections_mapping():
    """Verify correct sections for each complexity."""
    # chitchat → no sections
    # medium → environment + workspace
    # complex → all four
```

### Integration Tests

**File:** `tests/integration/test_dynamic_context_injection.py`

```python
async def test_full_flow_context_injection():
    """Verify XML sections appear in actual model request."""
    agent = create_soothe_agent(config)
    # Mock classification as complex
    # Run astream
    # Inspect system message for all four SOOTHE_ tags

async def test_concurrent_threads_isolated_context():
    """Verify different workspaces don't leak across threads."""
    # Thread A: workspace = /project-a
    # Thread B: workspace = /project-b
    # Run concurrently
    # Verify each receives correct workspace in system prompt
```

### Manual Verification

1. Start daemon with debug logging
2. Connect from `/project-a`, send "list the files"
3. Verify system prompt contains `<SOOTHE_WORKSPACE>` with correct cwd
4. Send greeting "hello", verify minimal prompt (no XML sections)
5. Send complex query, verify all four sections present

## Implementation Scope

| Component | Change Type | Lines Est. |
|-----------|-------------|------------|
| `system_prompt_optimization.py` | Modify | ~80-100 |
| `workspace.py` git status helper | Add | ~40-50 |
| `models.py` knowledge cutoffs | Add | ~15 |
| `_runner_phases.py` protocol state injection | Modify | ~20 |
| Unit tests | Add | ~150 |
| Integration tests | Add | ~80 |

**Total:** ~300-350 lines of new/modified code

## Open Questions

None. All decisions finalized through brainstorming session.

## References

- Claude Code workspace context: `../claude-code/workspace-context-analysis.md`
- RFC-0023: Layer 1 CoreAgent runtime
- RFC-103: Thread-aware workspace (draft)
- Existing: `src/soothe/middleware/system_prompt_optimization.py`
- Existing: `src/soothe/config/prompts.py`