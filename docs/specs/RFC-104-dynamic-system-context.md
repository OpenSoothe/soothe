# RFC-104: Dynamic System Context Injection

**RFC Number**: RFC-104
**Kind**: Implementation Interface Design
**Status**: Implemented
**Created**: 2026-03-31
**Author**: Platonic brainstorming session
**Design Draft**: [2026-03-31-dynamic-system-context-design.md](../drafts/2026-03-31-dynamic-system-context-design.md)
**Depends On**: RFC-100 (CoreAgent Runtime), RFC-101 (Tool Interface), RFC-103 (Thread-Aware Workspace)

## Abstract

This RFC proposes a dynamic system context injection system that enriches LLM system prompts with structured workspace, environment, thread, and protocol state information using `<SOOTHE_*>` XML tags. The injection is classification-driven, adapting context depth based on task complexity.

## Motivation

### Problem: Static System Prompts

Soothe agents receive static system prompts set at agent creation time. The LLM lacks awareness of:

1. **Workspace context**: Current working directory, git branch, recent commits
2. **Environment context**: Platform, shell, model, knowledge cutoff
3. **Thread context**: Thread ID, active goals, conversation history
4. **Protocol state**: Context/memory/planner availability and status

This limits the agent's ability to make context-aware decisions, especially for:
- File path resolution (relative vs absolute)
- Git-aware operations (branch context, PR targeting)
- Goal tracking and plan continuation
- Protocol-aware behavior (memory recall, context references)

### Reference: Claude Code Approach

Claude Code injects workspace context directly into system prompts via an Environment section, enabling correct tool argument generation. The system prompt includes:

```
# Environment
You have been invoked in the following environment:
 - Primary working directory: /Users/chenxm/Workspace/claude-code
 - Is a git repository: true
 - Platform: darwin
 - Shell: zsh
 - OS Version: Darwin 25.2.0
```

This multi-layered approach ensures the LLM can correctly generate tool arguments.

### Design Goals

1. **LLM comprehension**: Structured XML tags help LLM distinguish context sources
2. **Classification-driven**: Adaptive injection based on task complexity
3. **Unified handling**: Extend existing SystemPromptOptimizationMiddleware
4. **Fail gracefully**: Never block execution due to context collection failures
5. **Thread-safe**: Workspace from ContextVar, thread state from runner state

### Non-Goals

- **Real-time context updates**: Context injected once per request, not mid-stream
- **Custom XML tag schemas**: Fixed tag structure, not user-extensible
- **Context from tool output**: Only runner-collected context, not tool-derived

## Guiding Principles

### Principle 1: XML Tagging for LLM Comprehension

Structured `<SOOTHE_*>` XML tags provide clear boundaries and semantic meaning. The LLM can parse and reference context explicitly: "Based on `<SOOTHE_WORKSPACE>`, the current branch is develop."

### Principle 2: Classification-Driven Adaptation

Injection depth adapts to task complexity:

| Complexity | Sections | Token Budget |
|------------|----------|--------------|
| chitchat | None | ~50 |
| medium | ENVIRONMENT + WORKSPACE | ~300 |
| complex | All four sections | ~600 |

### Principle 3: Extend Existing Middleware

SystemPromptOptimizationMiddleware already selects prompts based on complexity. Extending it to inject XML sections keeps all prompt manipulation unified.

### Principle 4: Runner Collects, Middleware Injects

Runner assembles context during pre-stream and injects into `request.state`. Middleware reads from state and builds XML sections. Clean separation of concerns.

## Architecture

### XML Tag Structure

Four context sections with dedicated tags:

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
    7f7d076 fix: replace os.getcwd()
    878c1ad fix: convert logging f-strings
</SOOTHE_WORKSPACE>

<SOOTHE_THREAD>
  Thread ID: thread-abc123
  Active goals: ["Implement RFC-103", "Write tests"]
  Conversation turns: 5
  Current plan: Phase 2 - Implementation
</SOOTHE_THREAD>

<SOOTHE_PROTOCOLS>
  Context: VectorContext (8 entries, 1200 tokens)
  Memory: KeywordMemory (3 items recalled)
  Planner: ClaudePlanner (active)
  Policy: ConfigDrivenPolicy (profile: default)
</SOOTHE_PROTOCOLS>
```

### Section Content Specifications

#### SOOTHE_ENVIRONMENT

Static environment information available at middleware initialization:

| Field | Type | Source | Required |
|-------|------|--------|----------|
| Platform | string | `platform.system()` | Yes |
| Shell | string | `$SHELL` env var | Yes |
| OS Version | string | `platform.platform()` | Yes |
| Model | string | `config.resolve_model("default")` | Yes |
| Knowledge cutoff | string | Model-specific constant | Yes |

#### SOOTHE_WORKSPACE

Dynamic workspace information collected per-request:

| Field | Type | Source | Required |
|-------|------|--------|----------|
| Primary working directory | string | ContextVar or `Path.cwd()` | Yes |
| Is a git repository | boolean | `.git` existence check | Yes |
| Current branch | string | `git branch --show-current` | If git |
| Main branch | string | `git symbolic-ref refs/remotes/origin/HEAD` | If git |
| Status | string | `git status --short` (max 20 lines) | If git |
| Recent commits | string | `git log --oneline -n 5` | If git |

#### SOOTHE_THREAD

Thread-specific state from runner state:

| Field | Type | Source | Required |
|-------|------|--------|----------|
| Thread ID | string | `state.thread_id` | Yes |
| Active goals | list | `state.active_goals` | If present |
| Conversation turns | int | Message count from state | Yes |
| Current plan | string | `state.plan` summary | If present |

#### SOOTHE_PROTOCOLS

Protocol availability and state:

| Field | Type | Source | Required |
|-------|------|--------|----------|
| Context | string | `agent.context` type + stats | If active |
| Memory | string | `agent.memory` type + stats | If active |
| Planner | string | `agent.planner` type + status | If active |
| Policy | string | `agent.policy` type + profile | If active |

### Data Flow

```
┌─────────────────────────────────────────────────────────────────┐
│  SootheRunner.astream()                                          │
│  - tier-1: UnifiedClassification (complexity)                   │
│  - tier-2: Pre-stream (memory recall, context project)          │
│  - Collect: workspace, git status, thread state, protocols      │
│  - Inject into request.state:                                   │
│      state["workspace"] = current_workspace                     │
│      state["git_status"] = git_info                             │
│      state["thread_context"] = thread_info                      │
│      state["protocol_summary"] = protocol_info                  │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  SystemPromptOptimizationMiddleware.modify_request()             │
│  - Read classification.task_complexity from state               │
│  - Select base prompt (existing logic)                          │
│  - Build XML sections based on complexity:                      │
│      chitchat: none                                             │
│      medium: _build_environment() + _build_workspace()          │
│      complex: all four _build_*() methods                       │
│  - Append sections with "\n\n" separator                        │
│  - Return request.override(system_message=...)                  │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  Model receives enriched system prompt                           │
│  - Base behavioral instructions                                 │
│  - Structured context in <SOOTHE_*> XML tags                   │
│  - LLM parses and references context explicitly                 │
└─────────────────────────────────────────────────────────────────┘
```

## Specification

### 1. SystemPromptOptimizationMiddleware Extension

**Location**: `src/soothe/middleware/system_prompt_optimization.py`

Add section building methods:

```python
def _build_environment_section(self) -> str:
    """Build <SOOTHE_ENVIRONMENT> section.

    Returns:
        Formatted XML section string.
    """
    import platform
    import os

    platform_name = platform.system()
    shell = os.environ.get("SHELL", "unknown")
    os_version = platform.platform()
    model = self._config.resolve_model("default")
    cutoff = self._get_knowledge_cutoff(model)

    content = [
        f"Platform: {platform_name}",
        f"Shell: {shell}",
        f"OS Version: {os_version}",
        f"Model: {model}",
        f"Knowledge cutoff: {cutoff}",
    ]
    return "<SOOTHE_ENVIRONMENT>\n" + "\n".join(content) + "\n</SOOTHE_ENVIRONMENT>"

def _build_workspace_section(self, workspace: Path | None, git_status: dict | None) -> str:
    """Build <SOOTHE_WORKSPACE> section.

    Args:
        workspace: Current workspace path (from ContextVar or cwd).
        git_status: Git repository status dict (from runner).

    Returns:
        Formatted XML section string.
    """
    from pathlib import Path

    cwd = str(workspace or Path.cwd())
    is_git = git_status is not None

    content = [
        f"Primary working directory: {cwd}",
        f"Is a git repository: {is_git}",
    ]

    if git_status:
        content.append(f"Current branch: {git_status.get('branch', 'unknown')}")
        content.append(f"Main branch: {git_status.get('main_branch', 'main')}")
        status = git_status.get('status', '')
        if status:
            content.append(f"Status:\n{status}")
        commits = git_status.get('recent_commits', '')
        if commits:
            content.append(f"Recent commits:\n{commits}")

    return "<SOOTHE_WORKSPACE>\n" + "\n".join(content) + "\n</SOOTHE_WORKSPACE>"

def _build_thread_section(self, thread_context: dict) -> str:
    """Build <SOOTHE_THREAD> section.

    Args:
        thread_context: Thread state dict from runner.

    Returns:
        Formatted XML section string.
    """
    thread_id = thread_context.get("thread_id", "unknown")
    goals = thread_context.get("active_goals", [])
    turns = thread_context.get("conversation_turns", 0)
    plan = thread_context.get("current_plan")

    content = [
        f"Thread ID: {thread_id}",
        f"Conversation turns: {turns}",
    ]

    if goals:
        content.append(f"Active goals: {json.dumps(goals)}")
    if plan:
        content.append(f"Current plan: {plan}")

    return "<SOOTHE_THREAD>\n" + "\n".join(content) + "\n</SOOTHE_THREAD>"

def _build_protocols_section(self, protocol_summary: dict) -> str:
    """Build <SOOTHE_PROTOCOLS> section.

    Args:
        protocol_summary: Protocol state dict from runner.

    Returns:
        Formatted XML section string.
    """
    content = []

    for proto_name, proto_info in protocol_summary.items():
        if proto_info:
            proto_type = proto_info.get("type", "unknown")
            stats = proto_info.get("stats", "")
            content.append(f"{proto_name}: {proto_type} ({stats})")

    if not content:
        return ""  # Skip empty section

    return "<SOOTHE_PROTOCOLS>\n" + "\n".join(content) + "\n</SOOTHE_PROTOCOLS>"
```

Modify `_get_prompt_for_complexity()`:

```python
def _get_prompt_for_complexity(self, complexity: str, state: dict) -> str:
    """Get prompt with XML context sections for complexity level.

    Args:
        complexity: One of "chitchat", "medium", "complex".
        state: Request state with context information.

    Returns:
        Base prompt with appended XML sections.
    """
    base_prompt = self._get_base_prompt_for_complexity(complexity)

    if complexity == "chitchat":
        return base_prompt  # No context injection

    sections = []

    # Always add environment for medium and complex
    sections.append(self._build_environment_section())

    # Workspace section (uses ContextVar or cwd)
    workspace = state.get("workspace")
    git_status = state.get("git_status")
    sections.append(self._build_workspace_section(workspace, git_status))

    if complexity == "complex":
        # Thread and protocols only for complex
        thread_context = state.get("thread_context", {})
        if thread_context:
            sections.append(self._build_thread_section(thread_context))

        protocol_summary = state.get("protocol_summary", {})
        if protocol_summary:
            proto_section = self._build_protocols_section(protocol_summary)
            if proto_section:
                sections.append(proto_section)

    return base_prompt + "\n\n" + "\n\n".join(sections)
```

Update `modify_request()`:

```python
def modify_request(self, request: ModelRequest) -> ModelRequest:
    """Replace system prompt with context-enriched version.

    Args:
        request: Model request to modify.

    Returns:
        Modified request with enriched system message.
    """
    if not self._should_optimize(request):
        return request

    classification = request.state.get("unified_classification")
    complexity = classification.task_complexity if classification else "medium"

    enriched_prompt = self._get_prompt_for_complexity(complexity, request.state)
    return request.override(system_message=SystemMessage(content=enriched_prompt))
```

### 2. Git Status Collection Helper

**Location**: `src/soothe/safety/workspace.py`

Add async git status collection:

```python
import asyncio
from pathlib import Path
import subprocess

async def get_git_status(workspace: Path) -> dict | None:
    """Collect git repository status for workspace.

    Runs git commands asynchronously with timeout.
    Returns None if not a git repository or git unavailable.

    Args:
        workspace: Workspace directory to check.

    Returns:
        Dict with keys: branch, main_branch, status, recent_commits.
        None if not a git repository.
    """
    if not (workspace / ".git").exists():
        return None

    def run_git(args: list[str], timeout: float = 2.0) -> str:
        """Run git command with timeout."""
        try:
            result = subprocess.run(
                ["git"] + args,
                cwd=str(workspace),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return result.stdout.strip()
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return ""

    try:
        branch = await asyncio.to_thread(run_git, ["branch", "--show-current"])
        main_ref = await asyncio.to_thread(run_git, ["symbolic-ref", "refs/remotes/origin/HEAD"])
        status = await asyncio.to_thread(run_git, ["status", "--short"])
        commits = await asyncio.to_thread(run_git, ["log", "--oneline", "-n", "5"])

        # Parse main branch from symbolic-ref output
        main_branch = "main"
        if main_ref and "refs/remotes/origin/" in main_ref:
            main_branch = main_ref.split("/")[-1]

        # Truncate status to 20 lines
        status_lines = status.split("\n")[:20]
        status = "\n".join(line for line in status_lines if line)

        return {
            "branch": branch or "unknown",
            "main_branch": main_branch,
            "status": status,
            "recent_commits": commits,
        }
    except Exception:
        return None
```

### 3. Knowledge Cutoff Constants

**Location**: `src/soothe/config/models.py`

Add model knowledge cutoff mapping:

```python
MODEL_KNOWLEDGE_CUTOFFS: dict[str, str] = {
    "claude-opus-4-6": "2025-05",
    "claude-sonnet-4-6": "2025-05",
    "claude-haiku-4-5": "2025-10",
    "claude-3-5-sonnet": "2025-04",
    "claude-3-5-haiku": "2025-04",
    "claude-3-opus": "2025-02",
    # OpenAI models
    "gpt-4o": "2025-03",
    "gpt-4-turbo": "2025-01",
    # Default fallback
    "default": "2025-01",
}

def get_knowledge_cutoff(model_id: str) -> str:
    """Get knowledge cutoff date for model.

    Args:
        model_id: Model identifier string.

    Returns:
        Knowledge cutoff date string (YYYY-MM).
    """
    # Handle provider:model format
    if ":" in model_id:
        model_id = model_id.split(":")[-1]

    return MODEL_KNOWLEDGE_CUTOFFS.get(model_id, MODEL_KNOWLEDGE_CUTOFFS["default"])
```

### 4. Runner State Injection

**Location**: `src/soothe/core/runner/_runner_phases.py`

Modify `_pre_stream_independent()` to collect context for injection:

```python
async def _pre_stream_independent(
    self,
    user_input: str,
    state: Any,
    complexity: str | None = None,
) -> AsyncGenerator[StreamChunk]:
    """Pre-stream with context collection for system prompt injection."""
    # ... existing code ...

    # Collect context for system prompt injection
    if complexity in ("medium", "complex"):
        # Workspace from ContextVar (set by WorkspaceContextMiddleware)
        from soothe.safety import FrameworkFilesystem
        workspace = FrameworkFilesystem.get_current_workspace()

        # Git status (async collection)
        if workspace:
            from soothe.safety.workspace import get_git_status
            git_status = await get_git_status(workspace)
            state.git_status = git_status

        # Thread context
        state.thread_context = {
            "thread_id": state.thread_id,
            "active_goals": getattr(state, "active_goals", []),
            "conversation_turns": len(state.seen_message_ids) if hasattr(state, "seen_message_ids") else 0,
            "current_plan": str(state.plan) if hasattr(state, "plan") and state.plan else None,
        }

        # Protocol summary
        state.protocol_summary = {
            "context": {"type": type(self._context).__name__} if self._context else None,
            "memory": {"type": type(self._memory).__name__} if self._memory else None,
            "planner": {"type": type(self._planner).__name__} if self._planner else None,
            "policy": {"type": type(self._policy).__name__} if self._policy else None,
        }
```

Modify `_stream_phase()` to pass context in stream input:

```python
async def _stream_phase(self, user_input: str, state: Any) -> AsyncGenerator[StreamChunk]:
    """Stream with context injected into agent state."""
    stream_input: dict[str, Any] = {"messages": enriched_messages}

    # Existing classification injection
    if state.unified_classification:
        stream_input["unified_classification"] = state.unified_classification

    # NEW: Context for system prompt injection
    if hasattr(state, "workspace"):
        stream_input["workspace"] = state.workspace
    if hasattr(state, "git_status"):
        stream_input["git_status"] = state.git_status
    if hasattr(state, "thread_context"):
        stream_input["thread_context"] = state.thread_context
    if hasattr(state, "protocol_summary"):
        stream_input["protocol_summary"] = state.protocol_summary

    # ... rest of implementation ...
```

## Error Handling

| Failure | Behavior | Logging |
|---------|----------|---------|
| Git unavailable | Skip WORKSPACE section git fields | Debug: "Git status collection failed" |
| No workspace ContextVar | Use `Path.cwd()` | Debug: "Using cwd as workspace" |
| Thread state empty | Skip THREAD section | Debug: "No thread context" |
| Protocols None | Skip PROTOCOLS section | Debug: "No protocol summary" |
| Classification missing | Default to "medium" | Debug: "No classification" |
| Git timeout | Skip git fields, show workspace only | Debug: "Git command timed out" |

**Principle**: Never block execution. Fail gracefully with partial context.

## Token Budget Management

Soft limits for each section:

| Section | Max Tokens | Truncation Strategy |
|---------|------------|---------------------|
| ENVIRONMENT | 50 | Fixed size, no truncation |
| WORKSPACE | 200 | Git status max 20 lines, commits max 5 |
| THREAD | 100 | Goals list max 5 items, plan max 50 chars |
| PROTOCOLS | 100 | List types only, skip detailed stats |

Total budget for complex: ~450-500 tokens.

## Testing Requirements

### Unit Tests

1. `_build_environment_section()` format validation
2. `_build_workspace_section()` with/without git
3. `_build_thread_section()` with/without goals
4. `_build_protocols_section()` with/without protocols
5. Complexity-to-sections mapping correctness
6. Token truncation behavior

### Integration Tests

1. Full flow: classification → middleware → system message XML sections
2. Git status collection in real repository
3. Concurrent threads with different workspaces
4. Fallback behavior when context unavailable

## Implementation Scope

| Component | Change Type | Lines |
|-----------|-------------|-------|
| `system_prompt_optimization.py` | Modify | ~100 |
| `workspace.py` git helper | Add | ~50 |
| `models.py` cutoff constants | Add | ~20 |
| `_runner_phases.py` state injection | Modify | ~30 |
| Unit tests | Add | ~150 |
| Integration tests | Add | ~80 |

**Total**: ~350-400 lines

## Migration Path

1. Add knowledge cutoff constants (no behavior change)
2. Add git status helper (standalone utility)
3. Extend middleware with section builders (no activation yet)
4. Modify runner to inject context into state
5. Update middleware to read from state and build sections
6. Add tests for each phase

All phases backward compatible. Context injection only activates when all components ready.

## Success Criteria

- [ ] `<SOOTHE_ENVIRONMENT>` appears in system prompt for medium/complex tasks
- [ ] `<SOOTHE_WORKSPACE>` shows correct cwd and git status
- [ ] `<SOOTHE_THREAD>` shows thread ID and goals when present
- [ ] `<SOOTHE_PROTOCOLS>` shows active protocols when present
- [ ] No sections for chitchat complexity
- [ ] Git status collection doesn't block on slow repos (timeout works)
- [ ] Concurrent threads receive correct isolated workspace context

## Open Questions

None. All decisions finalized through brainstorming session.

## References

- Design Draft: [2026-03-31-dynamic-system-context-design.md](../drafts/2026-03-31-dynamic-system-context-design.md)
- Claude Code Analysis: `../claude-code/workspace-context-analysis.md`
- RFC-100: CoreAgent Runtime
- RFC-101: Tool Interface
- RFC-103: Thread-Aware Workspace
- RFC-102: Security Filesystem Policy

---

*This RFC enables context-aware LLM behavior through structured XML injection, aligned with classification-driven optimization.*