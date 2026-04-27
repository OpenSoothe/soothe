# IG-272: Unified Daemon → Client Streaming Framework Implementation

**Status**: Draft
**Date**: 2026-04-27
**RFC Reference**: RFC-614 (Unified Streaming Messaging Framework)
**Related IGs**: IG-268 (Response Length Control), IG-269 (Final Output Mode), IG-270 (Boundary Preservation)
**Estimated Effort**: 15-18 hours (2-3 days)

---

## Overview

Implement RFC-614's unified streaming framework enabling real-time transmission of ALL AI outputs (execution, synthesis, tool responses) from daemon to client. This generalizes the proven `final_report_stream` pattern through reusable helper, config-driven behavior, and proper content concatenation.

**Key Deliverables**:
1. Configuration system with global streaming control + CLI overrides
2. Unified streaming wrapper helper bypassing IG-119 filtering
3. SDK output_events registry extension for all streaming events
4. Client-side StreamingTextAccumulator with boundary preservation
5. Namespace isolation for concurrent subagent streams
6. Comprehensive test coverage (unit + integration)

---

## Implementation Phases

### Phase 1: Configuration Layer (Foundation)

**Goal**: Add unified streaming configuration with global enable/disable, mode control, and CLI override capability.

**Files Modified**: 6 files

#### Step 1.1: Add OutputStreamingConfig Model

**File**: `packages/soothe/src/soothe/config/models.py`

**Action**: Add new config model after line 800 (following `AgenticLoopConfig` pattern):

```python
class OutputStreamingConfig(BaseModel):
    """Configuration for unified output streaming behavior.

    Args:
        enabled: Enable streaming mode for all AI outputs (not just final reports).
            When False, outputs are emitted as complete messages only.
        mode: Display mode - "streaming" shows real-time chunks, "batch" accumulates
            silently and shows final output.
        execution_streaming: Stream execution phase AI text (CoreAgent responses during Act).
        synthesis_streaming: Stream synthesis phase AI text (final report generation).
        tool_response_streaming: Stream tool result processing AI text (experimental).
    """

    enabled: bool = True
    """Enable streaming mode for all AI outputs."""

    mode: Literal["streaming", "batch"] = "streaming"
    """Display mode - streaming shows chunks, batch shows final output only."""

    execution_streaming: bool = True
    """Stream execution phase AI text."""

    synthesis_streaming: bool = True
    """Stream synthesis phase AI text."""

    tool_response_streaming: bool = False
    """Stream tool result processing AI text (experimental)."""
```

**Pattern**: Follow `AgenticLoopConfig` structure (lines 563-646 in same file).

**Import**: Add `Literal` from `typing` if not present.

#### Step 1.2: Add output_streaming Field to SootheConfig

**File**: `packages/soothe/src/soothe/config/settings.py`

**Action**: Add field to `SootheConfig` class after line 100:

```python
output_streaming: OutputStreamingConfig = Field(
    default_factory=OutputStreamingConfig,
    description="Unified output streaming configuration for daemon and client",
)
```

**Import**: Add at top (around line 36):

```python
from soothe.config.models import (
    AgenticLoopConfig,
    ContextConfig,
    MemoryConfig,
    PlannerConfig,
    PolicyConfig,
    DurabilityConfig,
    RemoteAgentConfig,
    OutputStreamingConfig,  # ADD THIS
    # ... other imports
)
```

**Verification**: Config should parse without errors. Test with:
```bash
python -c "from soothe.config import SootheConfig; c = SootheConfig(); print(c.output_streaming)"
```

#### Step 1.3: Update Config YAML Files

**Files**:
- `packages/soothe/src/soothe/config/config.yml`
- `config/config.dev.yml`

**CRITICAL**: Must update BOTH files per CLAUDE.md rule #2.

**Action**: Add streaming section after `agentic` section in both files:

```yaml
# =============================================================================
# Output Streaming Configuration (RFC-614)
# =============================================================================
output_streaming:
  enabled: true        # Enable streaming for all outputs
  mode: streaming      # streaming or batch display mode
  execution_streaming: true   # Stream during execution phase
  synthesis_streaming: true   # Stream during synthesis phase
  tool_response_streaming: false  # Experimental: stream tool responses
```

**Pattern**: Follow existing YAML structure, maintain comments for clarity.

#### Step 1.4: Add CLI Override Flags

**File**: `packages/soothe-cli/src/soothe_cli/config/cli_config.py`

**Action**: Add fields to `CLIConfig` dataclass (around line 16):

```python
@dataclass
class CLIConfig:
    daemon_host: str = "127.0.0.1"
    daemon_port: int = 8765
    verbosity: str = "normal"
    final_output_mode: str = "streaming"  # Existing
    output_format: str = "text"           # Existing

    # ADD THESE:
    output_streaming_enabled: bool | None = None
    """Override daemon streaming enabled setting."""

    output_streaming_mode: str | None = None
    """Override daemon streaming mode: 'streaming' or 'batch'."""
```

**File**: `packages/soothe-cli/src/soothe_cli/cli/main.py`

**Action**: Add CLI flags to `main()` callback (after line 84, following `output_format` pattern):

```python
output_format: Annotated[
    str,
    typer.Option("--format", "-f", help="Output format for headless mode: text or jsonl.")
] = "text",

# ADD THESE:
streaming: Annotated[
    bool | None,
    typer.Option("--streaming/--no-streaming", help="Enable/disable output streaming."),
] = None,

streaming_mode: Annotated[
    str | None,
    typer.Option("--streaming-mode", help="Streaming mode: 'streaming' or 'batch'"),
] = None,
```

**Action**: Update execution logic to pass flags to CLIConfig (after config loading):

```python
# After config loading (around line 120)
cli_config.output_streaming_enabled = streaming
cli_config.output_streaming_mode = streaming_mode
```

**Pattern**: Follow existing `output_format` handling pattern.

**Phase 1 Verification**:
```bash
# Test config parsing
python -c "from soothe.config import SootheConfig; print(SootheConfig().output_streaming)"

# Test CLI flags (requires daemon running)
soothe --streaming "hello"
soothe --no-streaming "hello"
```

---

### Phase 2: Runner Layer (Stream Generation)

**Goal**: Create unified streaming wrapper helper and refactor IG-119 filtering to be config-aware.

**Files Modified**: 3 files

#### Step 2.1: Create Unified Streaming Wrapper Helper

**File**: `packages/soothe/src/soothe/core/runner/_runner_shared.py`

**Action**: Add helper function after `_custom()` (line 19):

```python
from soothe.config import SootheConfig
from soothe.cognition.agent_loop.stream_chunk_normalize import (
    extract_text_from_message_content,
    iter_messages_for_act_aggregation,
)
from langchain_core.messages import AIMessage, AIMessageChunk


def _wrap_streaming_output(
    chunk: StreamChunk,
    event_type: str,
    *,
    config: SootheConfig | None = None,
    namespace: tuple[str, ...] = (),
) -> StreamChunk | None:
    """Wrap streaming AI text chunks as custom output events.

    Architecture Pattern (RFC-614):
    - Extracts AI text from LangGraph messages-mode chunks
    - Wraps as custom events: ((), "custom", {"type": event_type, ...})
    - Custom events bypass IG-119 filtering (mode="custom")
    - Config-driven: returns None if streaming disabled

    Reuses proven pattern from final_report_stream logic (_runner_agentic.py).

    Args:
        chunk: Raw stream chunk from LangGraph astream (namespace, mode, data).
        event_type: Custom event type following RFC-403 naming convention.
        config: SootheConfig to check streaming enabled flag.
        namespace: Namespace tuple for concurrent stream isolation.

    Returns:
        Custom event chunk if streaming enabled and has text, None otherwise.
    """
    # Config check: Early return if streaming disabled (minimal overhead)
    if config and not config.output_streaming.enabled:
        return None

    # Extract AI text from messages-mode chunks
    # chunk is (namespace, mode, data) from LangGraph astream
    for msg in iter_messages_for_act_aggregation(chunk):
        if isinstance(msg, (AIMessage, AIMessageChunk)):
            text = extract_text_from_message_content(msg.content)
            if text:  # Allow whitespace chunks for boundary preservation
                # Stream as custom output event (bypasses IG-119 filter)
                return _custom({
                    "type": event_type,
                    "content": text,
                    "is_chunk": isinstance(msg, AIMessageChunk),
                    "namespace": list(namespace),  # Preserve namespace context
                })

    return None
```

**Pattern**: Reuse `_custom()` helper, mirror `final_report_stream` extraction logic.

#### Step 2.2: Refactor IG-119 Filtering Logic

**File**: `packages/soothe/src/soothe/core/runner/_runner_agentic.py`

**Action**: Update `_forward_messages_chunk_for_tool_ui()` signature and logic (line 299):

```python
def _forward_messages_chunk_for_tool_ui(
    chunk: object,
    *,
    config: SootheConfig | None = None,
) -> bool:
    """Whether to forward a stream_event messages chunk.

    IG-119: Forward tool results and AI tool-call metadata.
    When streaming enabled, forward ALL chunks (wrapper filters empty text).

    Config-driven behavior:
    - disabled: Only tool-related chunks (existing behavior)
    - enabled: All chunks (wrapper handles filtering)
    """
    # When streaming disabled, only forward tool-related chunks
    if config and not config.output_streaming.enabled:
        return _is_tool_stream_chunk(chunk) or _is_ai_tool_invocation_messages_chunk(chunk)

    # When streaming enabled, forward all chunks (wrapper will filter empty text)
    return True
```

**Action**: Update usage in `_run_agentic_loop()` (line 544):

```python
elif event_type == "stream_event":
    # Config-driven forwarding
    if _forward_messages_chunk_for_tool_ui(event_data, config=self.config):
        yield event_data
```

**Pattern**: Add config parameter, make filtering logic config-aware.

#### Step 2.3: Use Wrapper for Execution Streaming

**File**: `packages/soothe/src/soothe/cognition/agent_loop/agent_loop.py`

**Action**: Import helper at top:

```python
from soothe.core.runner._runner_shared import _custom, _wrap_streaming_output
```

**Action**: Update execution phase streaming (around line 558):

```python
async for item in run_executor.execute(decision=decision, state=state):
    if isinstance(item, tuple) and len(item) == _STREAM_CHUNK_LEN:
        # Wrap execution streaming as custom output event
        wrapped = _wrap_streaming_output(
            chunk=item,
            event_type="soothe.output.execution.streaming",
            config=self.config,
            namespace=(),  # Main agent namespace
        )
        if wrapped:
            yield wrapped
        # Also yield raw stream_event for tool UI (existing behavior)
        yield ("stream_event", item)
    else:
        step_results.append(item)
```

**Rationale**: Dual yield ensures tool UI gets metadata while streaming events reach client.

#### Step 2.4: Refactor Final Report Streaming

**File**: `packages/soothe/src/soothe/core/runner/_runner_agentic.py`

**Action**: Replace hardcoded `final_report_stream` logic (lines 547-570) with unified wrapper:

```python
elif event_type == "final_report_stream":
    # Use unified streaming wrapper (RFC-614)
    wrapped = _wrap_streaming_output(
        chunk=event_data,
        event_type="soothe.output.synthesis.streaming",
        config=self.config,
        namespace=(),
    )
    if wrapped:
        yield wrapped
```

**Benefit**: Simpler, config-driven, removes duplication.

**Phase 2 Verification**:
```bash
# Run unit tests for runner
pytest packages/soothe/tests/unit/core/runner/ -v

# Check IG-119 filtering respects config
# (manual test: run query with streaming disabled, verify no custom streaming events)
```

---

### Phase 3: SDK Registry Extension

**Goal**: Register all streaming output events as single source of truth.

**Files Modified**: 1 file

#### Step 3.1: Register All Streaming Events

**File**: `packages/soothe-sdk/src/soothe_sdk/ux/output_events.py`

**Action**: Update `_register_builtin_output_events()` function (line 43):

```python
def _register_builtin_output_events() -> None:
    """Register core Soothe output events on module load."""

    # Existing registrations...
    register_output_event(
        "soothe.output.chitchat.responded",
        lambda data: strip_internal_tags(data.get("content", "")),
    )

    register_output_event(
        "soothe.output.quiz.responded",
        lambda data: strip_internal_tags(data.get("content", "")),
    )

    # ADD THESE (RFC-614):
    # Execution streaming
    register_output_event(
        "soothe.output.execution.streaming",
        lambda data: data.get("content", ""),  # Preserve raw boundaries
    )

    # Synthesis streaming (replaces final_report.streaming)
    register_output_event(
        "soothe.output.synthesis.streaming",
        lambda data: data.get("content", ""),  # Preserve boundaries
    )

    # Tool response streaming (experimental)
    register_output_event(
        "soothe.output.tool_response.streaming",
        lambda data: data.get("content", ""),
    )

    # Keep existing for backward compatibility
    register_output_event(
        "soothe.output.final_report.streaming",
        lambda data: data.get("content", ""),
    )

    # ...existing final events (agent_loop.completed, autonomous final_report)...
```

**Pattern**: Preserve raw content (no preprocessing), let client apply final filtering.

**Phase 3 Verification**:
```python
# Test registry
from soothe_sdk.ux.output_events import is_output_event, extract_output_text

assert is_output_event("soothe.output.execution.streaming")
assert is_output_event("soothe.output.synthesis.streaming")

# Test extraction preserves boundaries
data = {"content": "Hello ", "is_chunk": True}
text = extract_output_text("soothe.output.execution.streaming", data)
assert text == "Hello "  # Preserves trailing space
```

---

### Phase 4: Daemon Layer (Broadcast)

**Goal**: Update daemon to use SDK registry for extraction and support config overrides.

**Files Modified**: 2 files

#### Step 4.1: Update extract_custom_output_text()

**File**: `packages/soothe/src/soothe/daemon/query_engine.py`

**Action**: Replace lines 805-826 with SDK registry delegation:

```python
@staticmethod
def extract_custom_output_text(data: dict[str, Any]) -> str | None:
    """Extract assistant-visible output text from custom protocol events.

    Handles both final events and streaming chunks:
    - Final events: strip internal tags for clean display
    - Streaming chunks: preserve raw boundaries for client concatenation

    Delegates to SDK registry (single source of truth).
    """
    from soothe_sdk.ux.output_events import extract_output_text

    event_type = str(data.get("type", ""))
    # Use SDK registry for all output events (both final and streaming)
    # Registry handles boundary preservation logic per event type
    return extract_output_text(event_type, data)
```

**Benefit**: Simpler, eliminates duplicate logic, single source of truth.

#### Step 4.2: Config Override Support (Optional Enhancement)

**File**: `packages/soothe/src/soothe/daemon/client_session.py`

**Action**: Add method if client needs effective config:

```python
async def get_effective_streaming_config(
    self,
    cli_overrides: dict[str, Any] | None = None
) -> OutputStreamingConfig:
    """Get effective streaming config with CLI overrides.

    Args:
        cli_overrides: Optional dict with output_streaming_enabled, output_streaming_mode

    Returns:
        Effective OutputStreamingConfig with overrides applied.
    """
    config = self._config.output_streaming

    if cli_overrides:
        # Apply CLI overrides (per-session override)
        if cli_overrides.get("output_streaming_enabled") is not None:
            config.enabled = cli_overrides["output_streaming_enabled"]
        if cli_overrides.get("output_streaming_mode") is not None:
            config.mode = cli_overrides["output_streaming_mode"]

    return config
```

**Pattern**: Similar to existing config override handling in daemon.

**Phase 4 Verification**:
```bash
# Run daemon integration tests
pytest packages/soothe/tests/integration/daemon/ -v
```

---

### Phase 5: Client Layer (Display & Concatenation)

**Goal**: Implement StreamingTextAccumulator state machine and integrate into EventProcessor.

**Files Modified**: 6 files + 1 new file

#### Step 5.1: Create StreamingTextAccumulator Class

**File**: `packages/soothe-cli/src/soothe_cli/shared/stream_accumulator.py` (NEW FILE)

**Action**: Create state machine class following tool call accumulation pattern:

```python
"""Unified streaming text accumulator with boundary preservation."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class StreamingAccumState:
    """State for a single streaming output stream."""

    accumulated_text: str = ""
    """Accumulated content from all chunks."""

    chunk_count: int = 0
    """Number of chunks received."""

    is_active: bool = True
    """Stream is still active (expecting more chunks)."""

    namespace: tuple[str, ...] = ()
    """Namespace for this stream (avoid interleaving)."""


@dataclass
class StreamingTextAccumulator:
    """Accumulates streaming text chunks with boundary preservation.

    Architecture Pattern (RFC-614, mirrors tool call accumulation from RFC-211):
    - Track by (event_type + namespace) to prevent interleaving concurrent streams
    - Preserve whitespace boundaries for markdown formatting
    - Finalize on non-chunk event or turn completion
    - Clear state after finalization

    Attributes:
        streams: Dict mapping (event_type, namespace) -> StreamingAccumState
        boundary_preserve_enabled: Whether to preserve leading/trailing whitespace
    """

    streams: dict[tuple[str, tuple[str, ...]], StreamingAccumState] = field(
        default_factory=dict
    )

    boundary_preserve_enabled: bool = True
    """Preserve whitespace boundaries for proper concatenation."""

    def accumulate(
        self,
        event_type: str,
        content: str,
        *,
        namespace: tuple[str, ...] = (),
        is_chunk: bool = True,
    ) -> str | None:
        """Accumulate streaming chunk and return displayable text.

        Boundary Preservation:
        - is_chunk=True: Return raw content (preserve boundaries)
        - is_chunk=False: Return accumulated text (final message)

        Args:
            event_type: Event type string (RFC-403 naming).
            content: Raw content chunk (may have boundary whitespace).
            namespace: Namespace tuple for concurrent stream isolation.
            is_chunk: True if partial chunk, False if final message.

        Returns:
            Displayable text with preserved boundaries, or None if empty.
        """
        key = (event_type, namespace)

        # Initialize new stream if needed
        if key not in self.streams:
            self.streams[key] = StreamingAccumState(namespace=namespace)

        state = self.streams[key]

        # Handle final message (non-chunk)
        if not is_chunk:
            state.is_active = False
            # Accumulate final content
            if content:
                state.accumulated_text += content
                state.chunk_count += 1
            # Return full accumulated text
            return state.accumulated_text.strip() if state.accumulated_text else None

        # Handle streaming chunk
        if not state.is_active:
            return None  # Stream already finalized

        # Accumulate chunk content
        if content:
            state.accumulated_text += content
            state.chunk_count += 1

            # Return chunk with boundary preservation
            if self.boundary_preserve_enabled:
                return content  # Preserve raw boundaries
            else:
                return content.strip()  # Clean boundaries

        return None

    def finalize_stream(
        self,
        event_type: str,
        *,
        namespace: tuple[str, ...] = (),
    ) -> str | None:
        """Finalize stream and return final accumulated text.

        Args:
            event_type: Event type string.
            namespace: Namespace tuple.

        Returns:
            Final accumulated text or None if stream empty.
        """
        key = (event_type, namespace)
        if key not in self.streams:
            return None

        state = self.streams[key]
        state.is_active = False

        return state.accumulated_text.strip() if state.accumulated_text else None

    def finalize_all(self) -> None:
        """Finalize all active streams (call on turn end)."""
        for state in self.streams.values():
            state.is_active = False

    def clear(self) -> None:
        """Clear all accumulated state (call after finalizing)."""
        self.streams.clear()
```

**Pattern**: Mirrors `accumulate_tool_call_chunks()` from `message_processing.py` lines 23-85.

#### Step 5.2: Add Accumulator to ProcessorState

**File**: `packages/soothe-cli/src/soothe_cli/shared/processor_state.py`

**Action**: Add field to `ProcessorState` dataclass:

```python
from soothe_cli.shared.stream_accumulator import StreamingTextAccumulator


@dataclass
class ProcessorState:
    seen_message_ids: set[str] = field(default_factory=set)
    pending_tool_calls: dict[str, dict] = field(default_factory=dict)
    name_map: dict[str, str] = field(default_factory=dict)
    current_plan: Plan | None = None
    thread_id: str = ""
    multi_step_active: bool = False

    # ADD THIS:
    streaming_accumulator: StreamingTextAccumulator = field(
        default_factory=StreamingTextAccumulator
    )
    """Unified streaming text accumulator with namespace isolation."""
```

#### Step 5.3: Integrate into EventProcessor

**File**: `packages/soothe-cli/src/soothe_cli/shared/event_processor.py`

**Action**: Import accumulator and config model:

```python
from soothe_cli.shared.stream_accumulator import StreamingTextAccumulator
from soothe.config.models import OutputStreamingConfig
```

**Action**: Update output event handling (lines 733-755):

```python
elif is_output_event(etype):
    # Get effective streaming config
    streaming_config = self._get_effective_streaming_config()

    # Skip if streaming disabled for this event type
    if not self._should_stream_event_type(etype, streaming_config):
        return

    content = extract_output_text(etype, data)
    if content and self._presentation.tier_visible(VerbosityTier.QUIET, self._verbosity):
        # Determine if this is a streaming chunk
        is_streaming_chunk = etype.endswith(".streaming") and data.get("is_chunk", True)

        # Use unified accumulator
        namespace = tuple(self._state.current_namespace or [])
        display_text = self._state.streaming_accumulator.accumulate(
            etype,
            content,
            namespace=namespace,
            is_chunk=is_streaming_chunk,
        )

        if display_text:
            # Clean and display
            cleaned = self._clean_assistant_text(
                display_text,
                is_streaming=is_streaming_chunk,
            )
            if cleaned:
                self._emit_assistant_text(
                    cleaned,
                    is_main=True,
                    is_streaming=is_streaming_chunk,
                )

        # Lock final answer for non-streaming final events
        if not is_streaming_chunk:
            self._presentation.mark_final_answer_locked()
            # Finalize stream
            self._state.streaming_accumulator.finalize_stream(etype, namespace=namespace)

    return
```

**Action**: Add helper methods to EventProcessor class:

```python
def _get_effective_streaming_config(self) -> OutputStreamingConfig:
    """Get effective streaming config from daemon + CLI overrides."""
    # Fetch from daemon config cache or use defaults
    daemon_config = self._state.cli_config._daemon_config_cache.get("output_streaming", {})

    config = OutputStreamingConfig()
    if daemon_config:
        config.enabled = daemon_config.get("enabled", True)
        config.mode = daemon_config.get("mode", "streaming")
        config.execution_streaming = daemon_config.get("execution_streaming", True)
        config.synthesis_streaming = daemon_config.get("synthesis_streaming", True)

    # Apply CLI overrides
    if self._state.cli_config.output_streaming_enabled is not None:
        config.enabled = self._state.cli_config.output_streaming_enabled
    if self._state.cli_config.output_streaming_mode is not None:
        config.mode = self._state.cli_config.output_streaming_mode

    return config

def _should_stream_event_type(self, etype: str, config: OutputStreamingConfig) -> bool:
    """Check if event type should be streamed based on config."""
    if not config.enabled:
        return False

    # Check specific streaming flags
    if etype == "soothe.output.execution.streaming":
        return config.execution_streaming
    if etype == "soothe.output.synthesis.streaming":
        return config.synthesis_streaming
    if etype == "soothe.output.tool_response.streaming":
        return config.tool_response_streaming

    # Default: stream all .streaming events when enabled
    return etype.endswith(".streaming")
```

**Action**: Update `on_turn_end()` method:

```python
def on_turn_end(self) -> None:
    """Handle turn completion."""
    # Finalize all streaming outputs
    self._state.streaming_accumulator.finalize_all()
    self._state.streaming_accumulator.clear()
    # Call renderer
    self._renderer.on_turn_end()
```

#### Step 5.4: Add Streaming Output Method to RendererProtocol

**File**: `packages/soothe-cli/src/soothe_cli/shared/renderer_protocol.py`

**Action**: Add method after `on_assistant_text` (around line 42):

```python
def on_streaming_output(
    self,
    event_type: str,
    text: str,
    *,
    is_chunk: bool,
    namespace: tuple[str, ...],
) -> None:
    """Streaming output chunk from unified framework.

    Args:
        event_type: Event type string (e.g., "soothe.output.execution.streaming").
        text: Text content (may be chunk or final).
        is_chunk: True if partial chunk, False if final.
        namespace: Namespace tuple for stream context.

    Note:
        This is optional - default implementation may delegate to on_assistant_text.
        Implementations may choose different display styles for different event types.
    """
    ...
```

#### Step 5.5: Implement in CLI Renderer

**File**: `packages/soothe-cli/src/soothe_cli/cli/renderer.py`

**Action**: Add default implementation:

```python
def on_streaming_output(
    self,
    event_type: str,
    text: str,
    *,
    is_chunk: bool,
    namespace: tuple[str, ...],
) -> None:
    """Default: delegate to on_assistant_text."""
    self.on_assistant_text(text, is_main=True, is_streaming=is_chunk)
```

#### Step 5.6: Implement in TUI Adapter

**File**: `packages/soothe-cli/src/soothe_cli/tui/textual_adapter.py`

**Action**: Add namespace tracking field:

```python
streaming_outputs_by_namespace: dict[tuple, str] = {}
"""Track streaming outputs per (event_type, namespace) to avoid interleaving."""
```

**Action**: Add implementation:

```python
def on_streaming_output(
    self,
    event_type: str,
    text: str,
    *,
    is_chunk: bool,
    namespace: tuple[str, ...],
) -> None:
    """Handle streaming output with namespace isolation.

    Track per namespace to avoid interleaving concurrent streams.
    """
    # Use existing namespace tracking pattern
    key = (event_type, namespace)

    # Accumulate per namespace (similar to pending_text_by_namespace)
    if key not in self.streaming_outputs_by_namespace:
        self.streaming_outputs_by_namespace[key] = ""

    self.streaming_outputs_by_namespace[key] += text

    # Display current chunk
    if is_chunk:
        # Stream to appropriate assistant message widget
        self._stream_assistant_text(text, namespace=namespace)
    else:
        # Final message - display full accumulated text
        final_text = self.streaming_outputs_by_namespace[key]
        self._display_final_assistant_text(final_text, namespace=namespace)
        # Clean up
        del self.streaming_outputs_by_namespace[key]
```

**Phase 5 Verification**:
```bash
# Run CLI/TUI tests
pytest packages/soothe-cli/tests/unit/ -v

# Manual test: run query, check streaming display
soothe "Write a short report about AI"
```

---

### Phase 6: Testing & Verification

**Goal**: Comprehensive test coverage and manual verification.

**Files Created**: 2 new test files

#### Step 6.1: Unit Tests for Accumulator

**File**: `packages/soothe-cli/tests/unit/ux/test_stream_accumulator.py` (NEW)

**Action**: Create test file:

```python
"""Unit tests for StreamingTextAccumulator."""

import pytest
from soothe_cli.shared.stream_accumulator import StreamingTextAccumulator


def test_accumulate_chunks_with_boundaries():
    """Test boundary preservation during accumulation."""
    accum = StreamingTextAccumulator(boundary_preserve_enabled=True)

    # Accumulate chunks with boundary whitespace
    t1 = accum.accumulate(
        "soothe.output.execution.streaming",
        "Hello ",
        namespace=(),
        is_chunk=True,
    )
    assert t1 == "Hello "  # Preserves trailing space

    t2 = accum.accumulate(
        "soothe.output.execution.streaming",
        " world",
        namespace=(),
        is_chunk=True,
    )
    assert t2 == " world"  # Preserves leading space

    # Final message
    t3 = accum.accumulate(
        "soothe.output.execution.streaming",
        "!",
        namespace=(),
        is_chunk=False,
    )
    assert t3 == "Hello  world!"  # Full accumulated text

    # State check
    state = accum.streams[("soothe.output.execution.streaming", ())]
    assert state.chunk_count == 3
    assert not state.is_active


def test_namespace_isolation():
    """Test concurrent streams don't interleave."""
    accum = StreamingTextAccumulator()

    # Stream 1: main agent
    accum.accumulate("soothe.output.execution.streaming", "Main ", namespace=())

    # Stream 2: subagent
    accum.accumulate(
        "soothe.output.execution.streaming",
        "Sub ",
        namespace=("browser",),
    )

    # Verify separate state
    assert len(accum.streams) == 2
    assert accum.streams[("soothe.output.execution.streaming", ())].accumulated_text == "Main "
    assert accum.streams[("soothe.output.execution.streaming", ("browser",))].accumulated_text == "Sub "


def test_batch_mode_boundary_cleaning():
    """Test batch mode: boundaries cleaned."""
    accum = StreamingTextAccumulator(boundary_preserve_enabled=False)

    # Chunks return cleaned text (stripped)
    t1 = accum.accumulate("test.streaming", "  chunk1  ", is_chunk=True)
    assert t1 == "chunk1"

    # Internal state has full text
    state = accum.streams[("test.streaming", ())]
    assert state.accumulated_text == "  chunk1  "


def test_finalization():
    """Test stream finalization."""
    accum = StreamingTextAccumulator()

    accum.accumulate("test.streaming", "text", is_chunk=True)
    assert accum.streams[("test.streaming", ())].is_active

    # Finalize
    final = accum.finalize_stream("test.streaming", namespace=())
    assert final == "text"
    assert not accum.streams[("test.streaming", ())].is_active

    # Further chunks rejected
    result = accum.accumulate("test.streaming", "more", is_chunk=True)
    assert result is None


def test_clear_state():
    """Test state clearing."""
    accum = StreamingTextAccumulator()

    accum.accumulate("test.streaming", "text", is_chunk=True)
    assert len(accum.streams) == 1

    accum.clear()
    assert len(accum.streams) == 0
```

**Run tests**:
```bash
pytest packages/soothe-cli/tests/unit/ux/test_stream_accumulator.py -v
```

#### Step 6.2: Integration Tests

**File**: `packages/soothe/tests/integration/core/streaming/test_unified_streaming.py` (NEW)

**Action**: Create integration test file:

```python
"""Integration tests for unified streaming framework."""

import pytest
from soothe.config import SootheConfig
from soothe.core.runner import SootheRunner


@pytest.mark.asyncio
async def test_execution_streaming_enabled():
    """Test execution phase streaming with config enabled."""
    config = SootheConfig(
        output_streaming={
            "enabled": True,
            "mode": "streaming",
            "execution_streaming": True,
        }
    )

    runner = SootheRunner(config=config)

    # Run query with streaming
    chunks = []
    async for chunk in runner.astream("Test goal"):
        if chunk[1] == "custom":
            data = chunk[2]
            if data.get("type") == "soothe.output.execution.streaming":
                chunks.append(data)

    # Verify streaming chunks emitted
    assert len(chunks) > 0
    assert all("content" in c for c in chunks)
    assert all("is_chunk" in c for c in chunks)


@pytest.mark.asyncio
async def test_streaming_disabled():
    """Test streaming disabled: no custom streaming events."""
    config = SootheConfig(
        output_streaming={
            "enabled": False,
        }
    )

    runner = SootheRunner(config=config)

    chunks = []
    async for chunk in runner.astream("Test goal"):
        if chunk[1] == "custom":
            data = chunk[2]
            if data.get("type", "").endswith(".streaming"):
                chunks.append(data)

    # No streaming events when disabled
    assert len(chunks) == 0


@pytest.mark.asyncio
async def test_boundary_preservation():
    """Test whitespace boundaries preserved in streaming."""
    config = SootheConfig(output_streaming={"enabled": True})
    runner = SootheRunner(config=config)

    # Mock LLM that emits chunks with boundary whitespace
    # ...test implementation...

    # Verify client receives chunks with preserved boundaries
```

**Run tests**:
```bash
pytest packages/soothe/tests/integration/core/streaming/ -v
```

#### Step 6.3: Manual Testing Scenarios

**Test Matrix**:

1. **Config Testing**:
   ```bash
   # Edit config.yml
   # Set: output_streaming.enabled: false
   soothe "hello"  # Should see final output only, no streaming chunks

   # Set: output_streaming.mode: batch
   soothe "write report"  # Should accumulate silently, display at end

   # CLI override
   soothe --no-streaming "hello"  # Override config
   ```

2. **Execution Streaming**:
   ```bash
   soothe "Analyze this codebase"  # Should stream execution phase AI reasoning
   ```

3. **Synthesis Streaming**:
   ```bash
   soothe "Write a detailed report"  # Should stream final report generation
   ```

4. **Boundary Preservation**:
   ```bash
   soothe "Format this as markdown list"  # Should preserve whitespace for formatting
   ```

5. **Namespace Isolation**:
   ```bash
   soothe "Use browser and research subagents"  # Concurrent streams shouldn't interleave
   ```

**Final Verification**:
```bash
# Run full verification suite
./scripts/verify_finally.sh

# Expected: All formatting + linting + 900+ tests pass
```

---

## Success Criteria Checklist

- [ ] **Phase 1**: Config models compile, YAML files parse, CLI flags work
- [ ] **Phase 2**: Runner wrapper extracts AI text, IG-119 filtering config-aware
- [ ] **Phase 3**: SDK registry recognizes all streaming events
- [ ] **Phase 4**: Daemon extraction uses SDK registry, config override works
- [ ] **Phase 5**: Accumulator preserves boundaries, namespace isolation works, renderers display correctly
- [ ] **Phase 6**: Unit tests pass, integration tests pass, manual scenarios verified
- [ ] `./scripts/verify_finally.sh` passes (all checks)
- [ ] Backward compatibility maintained (existing tests pass)
- [ ] Performance acceptable when streaming disabled (<5ms overhead)

---

## Post-Implementation Tasks

1. **Update CLAUDE.md**: Reference RFC-614 in recent changes section
2. **Create PR**: Include RFC-614 + IG-272 in PR description
3. **Manual QA**: Test all scenarios with real daemon/CLI
4. **Performance profiling**: Verify minimal overhead when disabled
5. **Documentation**: Update user guide with streaming config options

---

## Notes

- **Critical**: Both `config.yml` and `config.dev.yml` must stay synchronized (CLAUDE.md rule #2)
- **Pattern reuse**: Follow existing patterns (AgenticLoopConfig, tool call accumulation, boundary preservation)
- **Testing**: All existing tests must pass (backward compatibility)
- **Verification**: Run `./scripts/verify_finally.sh` before committing

---

**End of IG-272**