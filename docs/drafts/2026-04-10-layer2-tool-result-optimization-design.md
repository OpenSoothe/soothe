---
title: Layer 2 Tool Result Optimization Design
description: Optimize Layer 2 message handling by minimizing data transfer and shifting final report generation to Layer 1 CoreAgent
created: 2026-04-10
status: draft
scope: Layer 1/Layer 2 message flow optimization
---

# Layer 2 Tool Result Optimization Design

**Date**: 2026-04-10
**Author**: Platonic Brainstorming
**Status**: Draft
**Target**: RFC-201 (Layer 2 Agentic Goal Execution), RFC-100 (Layer 1 CoreAgent Runtime)

## Problem Statement

Layer 2's message handling has four critical inefficiencies affecting performance and architectural clarity:

1. **Layer 2 Reason context bloat**: Tool results (often 200KB+) are passed to Layer 2 Reason phase, causing token limit issues
2. **Storage duplication**: Same tool result stored in both Layer 1 LangGraph checkpoint and Layer 2 checkpoint
3. **Network/memory transfer cost**: Moving large tool result strings between layers is slow
4. **Layer 2's inability to access full context when needed**: Current truncation (200 chars) loses information Layer 2 might need

**Root cause**: Layer 2 receives full tool result contents when it only needs progress indicators for goal-level reasoning.

## Architectural Insight: Responsibility Shift

**Key realization**: Layer 1 CoreAgent owns execution history, so it should own final report generation.

**Current responsibility distribution**:
- Layer 2: Goal progress assessment + step planning + **final report generation** ❌ (misplaced)
- Layer 1: Tool execution + conversation management

**Proposed responsibility distribution**:
- Layer 2: Goal progress assessment + step planning only (no content aggregation)
- Layer 1: Tool execution + conversation management + **final report generation** ✅

**Impact**: Layer 2 becomes purely a **goal progress assessor and step planner**, never needing full tool result contents.

## Solution: Hybrid Approach with Minimal Data Contract

### Core Principle

**Layer 2 needs outcome signals, not content details.**

### Data Flow Architecture

```
Tool Execution:
  Tool generates structured outcome metadata
  ↓
Layer 1 CoreAgent:
  → ToolMessage(content="full result", tool_call_id="call_abc123")
  → LangGraph checkpoint (full content)
  → File cache (if >50KB): ~/.soothe/runs/{thread_id}/tool_results/{tool_call_id}.json
  ↓
Layer 2 Loop Agent:
  → StepResult(outcome={type, tool_call_id, entities, success_indicators})
  → Layer 2 checkpoint (metadata only)
  → Reason phase uses outcome for decisions
  ↓
Final Report:
  Layer 1 synthesizes from full checkpoint history when Layer 2 signals "done"
```

### Minimal Data Contract

**Layer 2 receives from Layer 1**:

```python
class StepResult(BaseModel):
    step_id: str
    success: bool
    outcome: dict  # Structured metadata (NEW)
    error: str | None = None
    error_type: str | None = None
    duration_ms: int
    thread_id: str
    tool_call_count: int = 0
    subagent_task_completions: int = 0
    hit_subagent_cap: bool = False
```

**Outcome metadata schema**:

```python
{
    "type": "file_read" | "file_write" | "web_search" | "code_exec" | "subagent",
    "tool_call_id": "call_abc123",  # Unique identifier
    "tool_name": "read_file",
    "success_indicators": {
        # Tool-specific success metrics
        "lines": 245,
        "files_found": 3,
        "exit_code": 0,
        "results_count": 12
    },
    "entities": ["config.yml", "async_patterns.py"],  # Key resources found
    "size_bytes": 2048,
    "file_ref": "call_abc123.json" | None  # Only if result >50KB
}
```

**What changed**:
- ❌ REMOVED: `output: str` (full tool result content)
- ✅ ADDED: `outcome: dict` (structured metadata)
- ✅ PRESERVED: All metrics and progress indicators

### Tool Call Uniqueness

**Mechanism**: LangChain's `tool_call_id` guarantees uniqueness per invocation.

**Example**:
```
AIMessage.tool_calls = [
    {name: "read_file", args: {path: "config.yml"}, id: "call_abc123"},
    {name: "read_file", args: {path: "other.txt"}, id: "call_def456"}
]

ToolMessage(tool_call_id="call_abc123", content="...", name="read_file")
ToolMessage(tool_call_id="call_def456", content="...", name="read_file")
```

**File cache naming**: `{tool_call_id}.json` ensures no collisions even for same tool called multiple times in parallel.

## Implementation Components

### 1. Tool Metadata Generator

**Purpose**: Generate structured outcome metadata from tool results.

**File**: `src/soothe/tools/metadata_generator.py` (new)

```python
"""Generate structured metadata from tool results for Layer 2 reasoning."""

from typing import Any


def generate_outcome_metadata(tool_name: str, result: Any, tool_call_id: str) -> dict:
    """Generate structured outcome metadata from tool result.

    Args:
        tool_name: Name of the tool that was executed
        result: Tool execution result (string, dict, or list)
        tool_call_id: Unique identifier for this tool invocation

    Returns:
        Structured metadata dict for Layer 2 reasoning
    """
    outcome = {
        "tool_call_id": tool_call_id,
        "tool_name": tool_name,
    }

    # Dispatch to tool-specific metadata extractors
    if tool_name in ["read_file", "ls", "grep", "glob"]:
        outcome["type"] = "file_read"
        outcome.update(_extract_file_metadata(result))
    elif tool_name in ["write_file", "edit_file"]:
        outcome["type"] = "file_write"
        outcome.update(_extract_file_write_metadata(result))
    elif tool_name in ["web_search", "tavily_search", "duckduckgo_search"]:
        outcome["type"] = "web_search"
        outcome.update(_extract_search_metadata(result))
    elif tool_name == "execute":
        outcome["type"] = "code_exec"
        outcome.update(_extract_exec_metadata(result))
    elif tool_name == "task":
        outcome["type"] = "subagent"
        outcome.update(_extract_subagent_metadata(result))
    else:
        outcome["type"] = "generic"
        outcome.update(_extract_generic_metadata(result))

    # Calculate size
    content_str = result if isinstance(result, str) else str(result)
    outcome["size_bytes"] = len(content_str.encode("utf-8"))

    return outcome


def _extract_file_metadata(result: Any) -> dict:
    """Extract metadata from file operation results."""
    content = result if isinstance(result, str) else str(result)

    lines = content.count("\n") + 1 if content else 0

    # Extract file paths mentioned in result
    entities = _extract_file_paths(content)

    return {
        "success_indicators": {
            "lines": lines,
            "files_found": len(entities),
            "has_content": bool(content)
        },
        "entities": entities[:10]  # Limit to top 10
    }


def _extract_file_write_metadata(result: Any) -> dict:
    """Extract metadata from file write results."""
    content = result if isinstance(result, str) else str(result)

    # Parse success message
    success = "success" in content.lower() or "wrote" in content.lower()

    entities = _extract_file_paths(content)

    return {
        "success_indicators": {
            "written": success,
            "files_written": len(entities)
        },
        "entities": entities[:10]
    }


def _extract_search_metadata(result: Any) -> dict:
    """Extract metadata from web search results."""
    content = result if isinstance(result, str) else str(result)

    # Count results (rough heuristic)
    result_count = content.count("http://") + content.count("https://")

    # Extract domains
    import re
    domains = re.findall(r'https?://([^/]+)', content)
    unique_domains = list(set(domains))[:5]

    # Extract key terms
    entities = _extract_key_terms(content)

    return {
        "success_indicators": {
            "results_count": result_count,
            "domains_found": len(unique_domains)
        },
        "entities": unique_domains + entities[:5]
    }


def _extract_exec_metadata(result: Any) -> dict:
    """Extract metadata from code execution results."""
    content = result if isinstance(result, str) else str(result)

    # Parse exit code if present
    exit_code = 0
    if "exit code:" in content.lower():
        import re
        match = re.search(r'exit code:\s*(\d+)', content, re.IGNORECASE)
        if match:
            exit_code = int(match.group(1))

    # Count output lines
    stdout_lines = content.count("\n") + 1

    # Detect errors
    has_error = exit_code != 0 or "error" in content.lower()

    return {
        "success_indicators": {
            "exit_code": exit_code,
            "stdout_lines": stdout_lines,
            "has_error": has_error
        },
        "entities": []
    }


def _extract_subagent_metadata(result: Any) -> dict:
    """Extract metadata from subagent delegation results."""
    content = result if isinstance(result, str) else str(result)

    # Extract artifacts mentioned
    entities = _extract_file_paths(content)

    # Detect completion status
    completed = "completed" in content.lower() or "finished" in content.lower()

    return {
        "success_indicators": {
            "completed": completed,
            "artifacts_created": len(entities)
        },
        "entities": entities[:10]
    }


def _extract_generic_metadata(result: Any) -> dict:
    """Extract generic metadata for unknown tool types."""
    content = result if isinstance(result, str) else str(result)

    return {
        "success_indicators": {
            "has_output": bool(content)
        },
        "entities": []
    }


def _extract_file_paths(text: str) -> list[str]:
    """Extract file paths from text."""
    import re

    # Match file paths (simplified pattern)
    patterns = [
        r'/[\w\-./]+\.\w+',  # Absolute paths
        r'[\w\-./]+\.\w+',   # Relative paths with extension
    ]

    paths = []
    for pattern in patterns:
        paths.extend(re.findall(pattern, text))

    return list(set(paths))[:10]


def _extract_key_terms(text: str) -> list[str]:
    """Extract key terms/entities from text."""
    import re

    # Extract quoted strings
    quoted = re.findall(r'"([^"]+)"', text)
    quoted.extend(re.findall(r"'([^']+)'", text))

    return quoted[:5]
```

### 2. Large Result Cache

**Purpose**: Cache large tool results (>50KB) to file system.

**File**: `src/soothe/cognition/loop_agent/result_cache.py` (new)

```python
"""File system cache for large tool results."""

from __future__ import annotations

import json
import logging
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from soothe.config import SOOTHE_HOME

logger = logging.getLogger(__name__)


class ToolResultCache:
    """Manages file system cache for large tool results.

    Cache location: ~/.soothe/runs/{thread_id}/tool_results/{tool_call_id}.json

    File naming uses tool_call_id to guarantee uniqueness even when the same
    tool is called multiple times in a single run.
    """

    def __init__(self, thread_id: str, size_threshold: int = 50_000) -> None:
        """Initialize cache for a specific thread.

        Args:
            thread_id: Thread identifier for cache directory
            size_threshold: Minimum size (bytes) to trigger caching (default: 50KB)
        """
        self.thread_id = thread_id
        self.size_threshold = size_threshold
        self.cache_dir = Path(SOOTHE_HOME).expanduser() / "runs" / thread_id / "tool_results"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def should_cache(self, size_bytes: int) -> bool:
        """Check if result should be cached based on size.

        Args:
            size_bytes: Size of the result in bytes

        Returns:
            True if result should be cached
        """
        return size_bytes > self.size_threshold

    def save(self, tool_call_id: str, content: str, metadata: dict[str, Any]) -> str | None:
        """Save large result to file cache.

        Args:
            tool_call_id: Unique identifier for this tool call
            content: Full tool result content
            metadata: Tool metadata (tool_name, type, etc.)

        Returns:
            File reference if cached, None if not cached
        """
        size_bytes = len(content.encode("utf-8"))

        if not self.should_cache(size_bytes):
            logger.debug(
                "Tool result %s not cached (size %d < threshold %d)",
                tool_call_id,
                size_bytes,
                self.size_threshold
            )
            return None

        file_path = self.cache_dir / f"{tool_call_id}.json"

        cache_data = {
            "tool_call_id": tool_call_id,
            "tool_name": metadata.get("tool_name", "unknown"),
            "timestamp": datetime.now(UTC).isoformat(),
            "content": content,
            "metadata": {
                "size_bytes": size_bytes,
                "type": metadata.get("type", "generic")
            }
        }

        try:
            file_path.write_text(json.dumps(cache_data, indent=2, ensure_ascii=False), encoding="utf-8")
            logger.info(
                "Cached large tool result %s to %s (size: %d bytes)",
                tool_call_id,
                file_path,
                size_bytes
            )
            return f"{tool_call_id}.json"
        except OSError:
            logger.exception("Failed to cache tool result %s", tool_call_id)
            return None

    def load(self, tool_call_id: str) -> dict[str, Any] | None:
        """Load cached result by tool_call_id.

        Args:
            tool_call_id: Unique identifier for the tool call

        Returns:
            Cached data dict or None if not found
        """
        file_path = self.cache_dir / f"{tool_call_id}.json"

        if not file_path.exists():
            logger.debug("Cache miss for tool result %s", tool_call_id)
            return None

        try:
            data = json.loads(file_path.read_text(encoding="utf-8"))
            logger.debug("Cache hit for tool result %s", tool_call_id)
            return data
        except (json.JSONDecodeError, OSError):
            logger.exception("Failed to load cached tool result %s", tool_call_id)
            return None

    def cleanup(self) -> None:
        """Remove entire cache directory for this thread.

        Called when thread completes or is deleted.
        """
        if self.cache_dir.exists():
            try:
                shutil.rmtree(self.cache_dir)
                logger.info("Cleaned up tool result cache for thread %s", self.thread_id)
            except OSError:
                logger.exception("Failed to cleanup cache for thread %s", self.thread_id)

    def get_cache_stats(self) -> dict[str, Any]:
        """Get cache statistics for this thread.

        Returns:
            Dict with file count, total size, etc.
        """
        if not self.cache_dir.exists():
            return {"file_count": 0, "total_bytes": 0}

        files = list(self.cache_dir.glob("*.json"))
        total_bytes = sum(f.stat().st_size for f in files)

        return {
            "file_count": len(files),
            "total_bytes": total_bytes,
            "cache_dir": str(self.cache_dir)
        }
```

### 3. Executor Enhancement

**Purpose**: Extract tool_call_id, generate metadata, and cache large results.

**File**: `src/soothe/cognition/loop_agent/executor.py` (modify existing)

**Changes to `_stream_and_collect` method**:

```python
async def _stream_and_collect(
    self,
    stream: AsyncGenerator,
    *,
    budget: _ActStreamBudget | None = None,
) -> AsyncGenerator[tuple[str | None, StreamEvent | None, int], None]:
    """Stream events while collecting outcome metadata for Layer 2.

    Enhanced to extract tool_call_id and generate structured metadata
    instead of collecting full content strings.

    Args:
        stream: Async iterator from agent.astream()
        budget: Optional Act wave budget (subagent task cap, IG-130).

    Yields:
        Tuple of (output, event, tool_call_count):
        - When event is not None: yield (None, event, 0) for immediate display
        - At end: yield (combined_output, None, tool_call_count) for final result
    """
    from langchain_core.messages import AIMessage, ToolMessage

    from soothe.cognition.loop_agent.result_cache import ToolResultCache
    from soothe.tools.metadata_generator import generate_outcome_metadata

    # Initialize cache for this thread
    cache = ToolResultCache(budget.thread_id if budget else "unknown")

    chunks: list[str] = []  # Still collect for Layer 1 final report
    outcomes: list[dict] = []  # NEW: Collect outcome metadata for Layer 2
    tool_call_count = 0

    def _maybe_cap_subagent_tasks(msg: ToolMessage) -> bool:
        """Return True if the stream must stop (cap exceeded)."""
        if budget is None:
            return False
        if getattr(msg, "name", "") != "task":
            return False
        budget.subagent_task_completions += 1
        cap = budget.max_subagent_tasks_per_wave
        if cap > 0 and budget.subagent_task_completions > cap:
            budget.hit_subagent_cap = True
            logger.warning(
                "Subagent task cap reached (%s > %s); stopping Act stream consumption",
                budget.subagent_task_completions,
                cap,
            )
            return True
        return False

    async for chunk in stream:
        # Handle tuple format (namespace, mode, data) - deepagents canonical
        if isinstance(chunk, tuple) and len(chunk) == _TUPLE_LEN:
            namespace, mode, data = chunk

            # Yield event immediately for real-time display
            yield None, chunk, 0

            # Extract content and metadata
            if mode == "messages" and not namespace:
                if isinstance(data, tuple) and len(data) >= _MSG_TUPLE_LEN:
                    msg, _metadata = data
                    if isinstance(msg, ToolMessage):
                        tool_call_count += 1
                        tool_call_id = msg.tool_call_id
                        tool_name = msg.name or "unknown"

                        if _maybe_cap_subagent_tasks(msg):
                            break

                        # Extract content for Layer 1 (still needed for final report)
                        content = msg.content
                        if isinstance(content, str) and content:
                            chunks.append(content)
                        elif isinstance(content, list):
                            for c in content:
                                if isinstance(c, str):
                                    chunks.append(c)
                                elif isinstance(c, dict) and "text" in c:
                                    chunks.append(c["text"])

                        # NEW: Generate structured metadata for Layer 2
                        outcome = generate_outcome_metadata(
                            tool_name,
                            content,
                            tool_call_id
                        )

                        # NEW: Cache large results
                        content_str = content if isinstance(content, str) else str(content)
                        file_ref = cache.save(tool_call_id, content_str, outcome)
                        if file_ref:
                            outcome["file_ref"] = file_ref

                        outcomes.append(outcome)

                        logger.debug(
                            "Tool %s (id=%s) executed, outcome type=%s, size=%d bytes",
                            tool_name,
                            tool_call_id,
                            outcome.get("type"),
                            outcome.get("size_bytes", 0)
                        )

                    elif isinstance(msg, AIMessage):
                        # Extract AI response content (for Layer 1 final report)
                        if isinstance(msg.content, str) and msg.content:
                            chunks.append(msg.content)
                        elif isinstance(msg.content, list):
                            for c in msg.content:
                                if isinstance(c, str):
                                    chunks.append(c)
                                elif isinstance(c, dict) and "text" in c:
                                    chunks.append(c["text"])

        # Handle dict chunks (standard LangGraph format)
        elif isinstance(chunk, dict):
            if "model" in chunk:
                model_data = chunk["model"]
                if isinstance(model_data, dict) and "messages" in model_data:
                    cap_break = False
                    for msg in model_data["messages"]:
                        if isinstance(msg, ToolMessage):
                            tool_call_count += 1
                            tool_call_id = msg.tool_call_id
                            tool_name = msg.name or "unknown"

                            if _maybe_cap_subagent_tasks(msg):
                                cap_break = True
                                break

                            # Extract content and generate metadata
                            content = msg.content
                            if isinstance(content, str) and content:
                                chunks.append(content)
                            elif isinstance(content, list):
                                for c in content:
                                    if isinstance(c, str):
                                        chunks.append(c)
                                    elif isinstance(c, dict) and "text" in c:
                                        chunks.append(c["text"])

                            # Generate outcome metadata
                            outcome = generate_outcome_metadata(
                                tool_name,
                                content,
                                tool_call_id
                            )

                            # Cache large results
                            content_str = content if isinstance(content, str) else str(content)
                            file_ref = cache.save(tool_call_id, content_str, outcome)
                            if file_ref:
                                outcome["file_ref"] = file_ref

                            outcomes.append(outcome)

                    if cap_break:
                        break

            elif "content" in chunk:
                chunks.append(str(chunk["content"]))
            elif "output" in chunk:
                chunks.append(str(chunk["output"]))
            elif "text" in chunk:
                chunks.append(str(chunk["text"]))

        elif hasattr(chunk, "content"):
            chunks.append(str(chunk.content))

    # Final yield with combined output and outcome metadata
    # Layer 1 still gets full content for final report generation
    # Layer 2 will receive outcome metadata via StepResult
    yield "".join(chunks), None, tool_call_count
```

**Note**: The executor still collects full content for Layer 1 final report generation. The outcome metadata is extracted separately and will be passed to StepResult.

### 4. StepResult Schema Update

**Purpose**: Replace `output` string with `outcome` metadata dict.

**File**: `src/soothe/cognition/loop_agent/schemas.py` (modify existing)

```python
class StepResult(BaseModel):
    """Result from executing a single step.

    Attributes:
        step_id: ID of the step
        success: Whether execution succeeded
        outcome: Structured metadata from tool execution (NEW)
        error: Error message (if failed)
        error_type: Error classification
        duration_ms: Execution duration in milliseconds
        thread_id: Thread used for execution
        tool_call_count: Number of tool calls made during execution
        subagent_task_completions: Completed ``task`` tool results at graph root (IG-130).
        hit_subagent_cap: True when streaming stopped early due to subagent task cap (IG-130).
    """

    step_id: str
    success: bool
    outcome: dict = Field(default_factory=dict)  # NEW: replaces output
    error: str | None = None
    error_type: Literal["execution", "tool", "timeout", "policy", "unknown", "fatal"] | None = None
    duration_ms: int
    thread_id: str
    tool_call_count: int = 0
    subagent_task_completions: int = 0
    hit_subagent_cap: bool = False

    def to_evidence_string(self, *, truncate: bool = True) -> str:
        """Convert to evidence string for Layer 2 reasoning.

        Uses outcome metadata to generate concise, informative summaries
        without exposing full tool result content.

        Args:
            truncate: If True, generate concise summary.
                     If False, return detailed summary for final response.

        Returns:
            Human-readable evidence string
        """
        if not self.success:
            return f"Step {self.step_id}: ✗ Error: {self.error}"

        # Extract key information from outcome metadata
        outcome_type = self.outcome.get("type", "unknown")
        tool_name = self.outcome.get("tool_name", "tool")
        success_indicators = self.outcome.get("success_indicators", {})
        entities = self.outcome.get("entities", [])

        # Generate summary based on outcome type
        if outcome_type == "file_read":
            lines = success_indicators.get("lines", 0)
            files_found = success_indicators.get("files_found", 0)
            entity_preview = ", ".join(entities[:3]) if entities else "files"

            if truncate:
                return f"Step {self.step_id}: ✓ {tool_name} ({lines} lines, {files_found} files) - {entity_preview}"
            else:
                return f"Step {self.step_id}: ✓ Read {lines} lines from {files_found} files: {entity_preview}"

        elif outcome_type == "file_write":
            files_written = success_indicators.get("files_written", 0)
            entity_preview = ", ".join(entities[:3]) if entities else "files"

            return f"Step {self.step_id}: ✓ {tool_name} ({files_written} files) - {entity_preview}"

        elif outcome_type == "web_search":
            results_count = success_indicators.get("results_count", 0)
            domains = entities[:3] if entities else []

            if truncate:
                return f"Step {self.step_id}: ✓ {tool_name} ({results_count} results)"
            else:
                return f"Step {self.step_id}: ✓ Found {results_count} results from domains: {', '.join(domains)}"

        elif outcome_type == "code_exec":
            exit_code = success_indicators.get("exit_code", 0)
            stdout_lines = success_indicators.get("stdout_lines", 0)

            status = "success" if exit_code == 0 else f"exit code {exit_code}"
            return f"Step {self.step_id}: ✓ {tool_name} ({status}, {stdout_lines} lines)"

        elif outcome_type == "subagent":
            completed = success_indicators.get("completed", False)
            artifacts = success_indicators.get("artifacts_created", 0)
            entity_preview = ", ".join(entities[:3]) if entities else "artifacts"

            status = "completed" if completed else "in progress"
            return f"Step {self.step_id}: ✓ Subagent {status} ({artifacts} artifacts) - {entity_preview}"

        else:
            # Generic fallback
            size = self.outcome.get("size_bytes", 0)
            return f"Step {self.step_id}: ✓ {tool_name} (size: {size} bytes)"
```

### 5. Executor Output Collection Update

**Purpose**: Update executor to create StepResult with outcome metadata.

**File**: `src/soothe/cognition/loop_agent/executor.py` (modify existing)

**Changes to `_execute_step_collecting_events`**:

```python
async def _execute_step_collecting_events(
    self,
    step: StepAction,
    thread_id: str,
    workspace: str | None = None,
) -> tuple[list[StreamEvent], StepResult]:
    """Execute single step, collecting events and outcome metadata.

    Args:
        step: StepAction with description and optional hints
        thread_id: Thread ID for execution
        workspace: Thread-specific workspace path (RFC-103)

    Returns:
        Tuple of (collected events, StepResult with outcome metadata)
    """
    from langchain_core.messages import HumanMessage

    from soothe.cognition.loop_agent.result_cache import ToolResultCache
    from soothe.tools.metadata_generator import generate_outcome_metadata

    start = time.perf_counter()
    events: list[StreamEvent] = []
    output = ""
    budget = _ActStreamBudget(max_subagent_tasks_per_wave=self._max_subagent_tasks_per_wave())
    outcomes: list[dict] = []  # Collect all tool outcomes

    # Initialize cache
    cache = ToolResultCache(thread_id)

    try:
        logger.debug(
            "Executing step %s: %s [hints: tools=%s, subagent=%s]",
            step.id,
            step.description[:100],
            step.tools,
            step.subagent,
        )

        configurable: dict[str, Any] = {
            "thread_id": thread_id,
            "soothe_step_tools": step.tools,
            "soothe_step_subagent": step.subagent,
            "soothe_step_expected_output": step.expected_output,
        }
        if workspace:
            configurable["workspace"] = workspace
        config = {"configurable": configurable}

        step_body = f"Execute: {step.description}{self._layer2_output_contract_suffix()}"
        stream = self.core_agent.astream(
            {"messages": [HumanMessage(content=step_body)]},
            config=config,
            stream_mode=["messages", "updates", "custom"],
            subgraphs=True,
        )

        # Stream events and collect outcome metadata
        tool_call_count = 0
        async for final_output, event, tc_count in self._stream_and_collect(stream, budget=budget):
            if event is not None:
                events.append(event)
            elif final_output is not None:
                output = final_output
                tool_call_count = tc_count

        duration_ms = int((time.perf_counter() - start) * 1000)

        # Aggregate outcomes from all tools in this step
        # For now, use the first outcome as primary (future: merge multiple)
        primary_outcome = outcomes[0] if outcomes else {
            "type": "generic",
            "tool_name": "unknown",
            "tool_call_id": f"step_{step.id}",
            "success_indicators": {},
            "entities": [],
            "size_bytes": len(output.encode('utf-8'))
        }

        logger.info(
            "Step %s completed successfully in %dms (hints: tools=%s, tool_calls: %d, subagent_cap_hit=%s)",
            step.id,
            duration_ms,
            step.tools or "none",
            tool_call_count,
            budget.hit_subagent_cap,
        )

        return events, StepResult(
            step_id=step.id,
            success=True,
            outcome=primary_outcome,  # NEW: outcome metadata
            duration_ms=duration_ms,
            thread_id=thread_id,
            tool_call_count=tool_call_count,
            subagent_task_completions=budget.subagent_task_completions,
            hit_subagent_cap=budget.hit_subagent_cap,
        )

    except Exception as e:
        duration_ms = int((time.perf_counter() - start) * 1000)
        logger.exception(
            "Step %s failed after %dms [hints: tools=%s, subagent=%s]",
            step.id,
            duration_ms,
            step.tools,
            step.subagent,
        )

        error_msg = self._extract_error_message(e, "Step execution failed")

        return events, StepResult(
            step_id=step.id,
            success=False,
            outcome={"type": "error", "error": error_msg},  # NEW: error outcome
            error=error_msg,
            error_type=self._classify_error_severity(e),
            duration_ms=duration_ms,
            thread_id=thread_id,
            subagent_task_completions=0,
            hit_subagent_cap=False,
        )
```

### 6. Layer 1 Final Report Generation

**Purpose**: Generate final report from Layer 1 checkpoint when Layer 2 signals "done".

**File**: `src/soothe/core/runner/_runner_phases.py` (modify existing)

**Add new function**:

```python
async def generate_final_report_from_checkpoint(
    thread_id: str,
    goal: str,
    checkpointer: Any,
) -> str:
    """Generate final report from Layer 1 checkpoint.

    Layer 1 CoreAgent owns execution history and synthesizes final report
    from full ToolMessage contents when Layer 2 signals goal is done.

    Args:
        thread_id: Thread identifier
        goal: Goal description for context
        checkpointer: LangGraph checkpointer instance

    Returns:
        Synthesized final report string
    """
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

    # Load full thread state from checkpointer
    state = await checkpointer.aget_state({"configurable": {"thread_id": thread_id}})

    if not state or not state.values:
        return "No execution results available."

    messages = state.values.get("messages", [])

    # Extract tool results and AI responses
    tool_results = []
    ai_responses = []

    for msg in messages:
        if isinstance(msg, ToolMessage):
            tool_results.append(msg.content)
        elif isinstance(msg, AIMessage) and msg.content:
            ai_responses.append(msg.content)

    # Check for cached large results
    from soothe.cognition.loop_agent.result_cache import ToolResultCache

    cache = ToolResultCache(thread_id)
    cache_stats = cache.get_cache_stats()

    # If we have cached results, load them
    if cache_stats["file_count"] > 0:
        logger.info(
            "Final report includes %d cached tool results (%d bytes)",
            cache_stats["file_count"],
            cache_stats["total_bytes"]
        )

    # Synthesize final report
    # Strategy: Concatenate meaningful tool results and AI responses
    report_parts = []

    if ai_responses:
        # Use last AI response as primary content
        report_parts.append(ai_responses[-1])

    if tool_results:
        # Add tool results that haven't been summarized by AI
        for result in tool_results[-3:]:  # Last 3 tool results
            if isinstance(result, str) and len(result) > 200:
                report_parts.append(f"\n\n**Tool Output:**\n{result[:1000]}...")

    if not report_parts:
        return "Goal completed successfully."

    return "\n".join(report_parts)
```

**Integration in Layer 2 loop completion**:

```python
# In loop_agent.py, after reason_result.is_done()

if reason_result.is_done():
    # Layer 1 generates final report
    from soothe.core.runner._runner_phases import generate_final_report_from_checkpoint

    final_report = await generate_final_report_from_checkpoint(
        thread_id=state.thread_id,
        goal=state.goal,
        checkpointer=self.core_agent.graph.checkpointer
    )

    # Update reason_result with Layer 1 generated report
    reason_result = reason_result.model_copy(update={"full_output": final_report})

    # Continue with existing completion logic
    state.previous_reason = reason_result
    ...
```

### 7. Configuration

**File**: `config/config.yml` (add new section)

```yaml
execution:
  tool_result_cache:
    enabled: true
    size_threshold_bytes: 50000  # 50KB - results larger than this are cached to file
    cleanup_on_completion: true  # Remove cache after goal completes
    cleanup_after_days: 7  # Remove old caches after 7 days
```

### 8. Migration Strategy

**Phase 1: Add new components (non-breaking)**
1. Implement `ToolResultCache` class
2. Implement `generate_outcome_metadata` function
3. Add `outcome` field to `StepResult` (with default empty dict for backward compat)
4. Update `to_evidence_string` to use outcome when available

**Phase 2: Update executor (non-breaking)**
1. Modify `_stream_and_collect` to extract tool_call_id and generate metadata
2. Cache large results to file system
3. Populate `outcome` field in StepResult
4. Keep `output` field temporarily for backward compatibility

**Phase 3: Remove deprecated fields (breaking)**
1. Remove `output` field from StepResult
2. Update all StepResult consumers to use `outcome`
3. Remove output string handling from executor

**Phase 4: Layer 1 final report generation**
1. Implement `generate_final_report_from_checkpoint`
2. Update Layer 2 loop completion to use Layer 1 report
3. Remove synthesis phase from Layer 2

## Benefits

### Performance

1. **Layer 2 context reduction**: ~90% reduction in token usage for Reason phase
   - Before: 200KB+ tool results in evidence
   - After: ~1KB structured metadata per tool call

2. **Transfer cost**: No large string movement between layers
   - Before: Full tool result copied to StepResult.output
   - After: Only metadata dict (10-20 fields)

3. **Storage optimization**: Large results cached separately
   - Before: All in LangGraph checkpoint
   - After: Checkpoint + optional file cache for large results

### Architecture

1. **Clean separation**: Layer 1 owns content, Layer 2 owns progress
2. **Responsibility alignment**: Final report generated by Layer 1 (owns history)
3. **Scalability**: File cache handles arbitrarily large tool results
4. **Maintainability**: Structured metadata easier to reason about than truncated strings

### Functionality

1. **Better decisions**: Structured outcome data enables smarter reasoning
2. **No information loss**: File cache preserves full results when needed
3. **Unique identification**: tool_call_id guarantees no collisions
4. **Easy cleanup**: Cache directory per thread, automatic cleanup on completion

## Testing Strategy

### Unit Tests

1. **Test tool_call_id uniqueness**: Multiple invocations of same tool produce different IDs
2. **Test outcome metadata generation**: Each tool type generates correct metadata
3. **Test file cache**: Large results cached, small results not cached
4. **Test evidence string generation**: Outcome-based summaries are informative
5. **Test cache cleanup**: Files removed when thread completes

### Integration Tests

1. **Test Layer 2 reasoning**: Decisions made correctly with outcome metadata only
2. **Test final report generation**: Layer 1 synthesizes from full history
3. **Test large result handling**: 100KB+ tool results cached and retrieved
4. **Test parallel execution**: Multiple tools in parallel, correct tool_call_id correlation

### Performance Tests

1. **Measure Layer 2 Reason token usage**: Compare before/after
2. **Measure transfer time**: StepResult creation time
3. **Measure cache performance**: Hit rate, retrieval time
4. **Measure checkpoint size**: Compare before/after

## Success Criteria

1. ✅ All 900+ existing tests pass
2. ✅ Layer 2 Reason token usage reduced by >80%
3. ✅ Large tool results (>50KB) cached to file system
4. ✅ File names use tool_call_id (guaranteed unique)
5. ✅ Layer 2 never receives full tool result content
6. ✅ Final report generated by Layer 1 from checkpoint
7. ✅ Cleanup removes cache files after thread completion
8. ✅ No breaking changes to Layer 1 checkpoint format

## RFC Alignment

- **RFC-201**: Layer 2 Agentic Goal Execution (message handling update)
- **RFC-100**: Layer 1 CoreAgent Runtime (final report generation)
- **RFC-205**: Layer 2 Checkpoint (metadata-only storage)
- **RFC-207**: Message Type Separation (outcome metadata structure)

## Future Enhancements

1. **Adaptive caching**: Machine learning to predict which results will be needed
2. **Compression**: Compress cached results for storage savings
3. **Outcome schema standardization**: Formal JSON Schema for each tool type
4. **Cross-thread caching**: Share common results across threads
5. **Streaming outcomes**: Generate outcome metadata incrementally for long-running tools

## Rollback Plan

If issues arise:
1. Revert StepResult to use `output` field
2. Remove outcome metadata generation
3. Disable file cache
4. Restore Layer 2 synthesis phase

All changes are backward compatible in Phase 1-2, making rollback straightforward.

---

**Document Status**: Draft - Ready for User Review
**Next Phase**: Platonic Coding Phase 1 RFC Formalization (after approval)