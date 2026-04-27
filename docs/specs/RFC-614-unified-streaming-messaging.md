# RFC-614: Unified Daemon → Client Streaming Messaging Framework

**RFC**: 614
**Title**: Unified Daemon → Client Streaming Messaging Framework
**Status**: Draft
**Kind**: Architecture Design
**Created**: 2026-04-27
**Dependencies**: RFC-000, RFC-001, RFC-450, RFC-401, RFC-403
**Extends**: RFC-450 (Daemon Communication), RFC-401 (Event Processing)

## Abstract

This RFC defines a unified streaming messaging framework enabling real-time transmission of all AI outputs (not just final reports) from daemon to client. The framework generalizes the proven `final_report_stream` pattern through a reusable streaming wrapper helper, configuration-driven behavior control, and proper content concatenation with whitespace boundary preservation. This eliminates the current limitation where IG-119 filtering blocks plain AIMessage chunks, preventing users from seeing execution progress in real-time.

**Key Design Principles**:
1. **Unified streaming wrapper**: Reuse custom event pattern to bypass IG-119 filtering
2. **Configuration-driven**: Global enable/disable, streaming/batch modes, per-phase control
3. **Boundary preservation**: Maintain whitespace for markdown formatting during concatenation
4. **Namespace isolation**: Prevent interleaving concurrent streams from parallel subagents
5. **Backward compatibility**: Preserve existing event semantics while extending capabilities

## Problem Statement

### Current Limitations

**IG-119 Filtering Barrier**:
The runner's IG-119 filtering logic (`_runner_agentic.py` lines 541-545) blocks plain AIMessage chunks to prevent duplicate stdout in multi-step execution. Only tool-related chunks (ToolMessage + AI tool_invocation metadata) pass through.

**Special-Case Workaround**:
`final_report_stream` is hard-coded special case (lines 547-570) that:
- Extracts AI text from messages chunks
- Wraps as custom events to bypass filtering
- Only works for synthesis phase (final report generation)

**Missing Streaming for Other Phases**:
- Execution phase AI responses (CoreAgent responses during Act): No streaming
- Tool result processing: No streaming
- Chitchat/quiz responses: Final-only (no intermediate chunks)
- Custom plugin outputs: No streaming infrastructure

**User Experience Gap**:
Users cannot see agent execution progress in real-time. All intermediate AI reasoning appears at completion, reducing transparency for long-running workflows.

### Goals

1. **Universal streaming**: Enable streaming for ALL AI outputs (execution, synthesis, tool responses)
2. **Configuration control**: Global enable/disable, streaming/batch modes, per-phase flags
3. **Proper concatenation**: Whitespace boundary preservation for markdown formatting
4. **Concurrency safety**: Namespace-based isolation for parallel subagent streams
5. **Extensibility**: Plugin-friendly registration mechanism for custom streaming events
6. **Performance**: Minimal overhead when disabled, config-driven filtering

### Non-Goals

- Real-time event filtering (already covered by RFC-401 verbosity filtering)
- Transport layer changes (WebSocket already bidirectional, RFC-450)
- Event naming taxonomy (RFC-403 covers naming conventions)
- UI display logic (CLI/TUI implementation details, RFC-500)

## Architectural Design

### Three-Layer Streaming Architecture

```
┌─────────────────────────────────────────────────────────────┐
│ Layer 3: Configuration Layer (Control Plane)                 │
│ • OutputStreamingConfig: Global enable/disable, mode control │
│ • CLI override flags: Per-session streaming control          │
│ • Daemon config propagation: Runner behavior configuration    │
└─────────────────────────────────────────────────────────────┘
                          ↓ Config propagation
┌─────────────────────────────────────────────────────────────┐
│ Layer 2: Runner Layer (Stream Generation)                    │
│ • _wrap_streaming_output(): Unified wrapper helper            │
│ • Config-aware IG-119 filtering: Enable/disable forwarding    │
│ • Execution/Synthesis/Tool streaming: Event generation        │
└─────────────────────────────────────────────────────────────┘
                          ↓ Custom events (bypass filter)
┌─────────────────────────────────────────────────────────────┐
│ Layer 1: Daemon/Client Layer (Transport & Display)           │
│ • EventBus broadcast: Priority-aware overflow (RFC-401)       │
│ • SDK output_events registry: Single source of truth          │
│ • StreamingTextAccumulator: Concatenation with boundaries     │
│ • Namespace isolation: Concurrent stream tracking             │
└─────────────────────────────────────────────────────────────┘
```

**Layer Responsibilities**:
- **Layer 3**: Configuration determines whether streaming enabled, mode (streaming/batch), and per-phase flags
- **Layer 2**: Runner generates streaming events using unified wrapper, respects IG-119 filtering config
- **Layer 1**: Daemon broadcasts via EventBus, Client accumulates with boundary preservation

### Integration with Existing RFCs

**RFC-450 (Daemon Communication)**:
- Uses existing WebSocket bidirectional transport (no changes)
- Leverages EventBus pub/sub routing (topic: `thread:{thread_id}`)
- Preserves priority-aware overflow strategy (IG-258)

**RFC-401 (Event Processing)**:
- Extends EventProcessor with StreamingTextAccumulator
- Uses existing RendererProtocol for display abstraction
- Maintains verbosity filtering integration

**RFC-403 (Unified Event Naming)**:
- Follows 4-segment naming: `soothe.output.<phase>.streaming`
- New domains: `execution.streaming`, `synthesis.streaming`, `tool_response.streaming`

### Core Abstractions

#### OutputStreamingConfig (Configuration Model)

```python
class OutputStreamingConfig(BaseModel):
    """Unified streaming configuration.

    Controls streaming behavior across daemon and client layers.
    Propagated from daemon config to runner, with CLI override capability.
    """

    enabled: bool = True
    """Global streaming enable/disable. When False, all outputs are final-only."""

    mode: Literal["streaming", "batch"] = "streaming"
    """Display mode: streaming (real-time chunks) or batch (accumulate silently)."""

    execution_streaming: bool = True
    """Stream execution phase AI text (CoreAgent responses during Act)."""

    synthesis_streaming: bool = True
    """Stream synthesis phase AI text (final report generation)."""

    tool_response_streaming: bool = False
    """Stream tool result processing (experimental, may cause UI fragmentation)."""
```

**Config Propagation Flow**:
1. `config.yml` → `SootheConfig.output_streaming` (daemon)
2. CLI flags (`--streaming/--no-streaming`, `--streaming-mode`) → override daemon config
3. `SootheRunner` receives config → passes to runner functions
4. Client fetches effective config via daemon RPC + applies CLI overrides

#### _wrap_streaming_output() (Unified Wrapper Helper)

```python
def _wrap_streaming_output(
    chunk: StreamChunk,
    event_type: str,
    *,
    config: SootheConfig | None = None,
    namespace: tuple[str, ...] = (),
) -> StreamChunk | None:
    """Wrap streaming AI text chunks as custom output events.

    Architecture Pattern:
    - Extracts AI text from LangGraph messages-mode chunks
    - Wraps as custom events: ((), "custom", {"type": event_type, ...})
    - Custom events bypass IG-119 filtering (mode="custom")
    - Config-driven: returns None if streaming disabled

    Reuses proven pattern from final_report_stream logic (RFC-200).

    Args:
        chunk: Raw stream chunk from LangGraph astream (namespace, mode, data).
        event_type: Custom event type following RFC-403 naming convention.
        config: SootheConfig to check streaming enabled flag.
        namespace: Namespace tuple for concurrent stream isolation.

    Returns:
        Custom event chunk if streaming enabled and has text, None otherwise.
    """
```

**Design Pattern**:
1. Config check: Early return if `config.output_streaming.enabled == False`
2. AI text extraction: Use `extract_text_from_message_content()` from stream normalization
3. Boundary preservation: Preserve raw content (no preprocessing)
4. Custom event wrapping: Use `_custom()` helper (RFC-450 pattern)
5. Namespace tracking: Include namespace in event data for client isolation

#### StreamingTextAccumulator (State Machine)

```python
@dataclass
class StreamingAccumState:
    """State for a single streaming output stream."""
    accumulated_text: str = ""
    chunk_count: int = 0
    is_active: bool = True
    namespace: tuple[str, ...] = ()

@dataclass
class StreamingTextAccumulator:
    """Unified streaming text accumulation with boundary preservation.

    Architecture Pattern (mirrors tool call accumulation from RFC-211):
    - Track by (event_type + namespace) to prevent interleaving
    - Preserve whitespace boundaries for markdown formatting
    - Finalize on non-chunk event or turn completion
    - Clear state after finalization

    Attributes:
        streams: Dict mapping (event_type, namespace) → StreamingAccumState.
        boundary_preserve_enabled: Preserve leading/trailing whitespace.
    """

    streams: dict[tuple[str, tuple[str, ...]], StreamingAccumState] = field(
        default_factory=dict
    )
    boundary_preserve_enabled: bool = True

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

    def finalize_stream(
        self,
        event_type: str,
        namespace: tuple[str, ...],
    ) -> str | None:
        """Finalize stream and return accumulated text."""

    def finalize_all(self) -> None:
        """Finalize all active streams (call on turn end)."""

    def clear(self) -> None:
        """Clear accumulated state (call after finalizing)."""
```

**State Machine Logic**:
1. **Initialization**: Create new `StreamingAccumState` for unseen (event_type, namespace)
2. **Chunk handling**: Accumulate content, preserve boundaries, return raw chunk
3. **Final message**: Mark inactive, return full accumulated text
4. **Finalization**: Mark inactive, prevent further accumulation
5. **Clear**: Remove state after final display

#### SDK Output Events Registry (Single Source of Truth)

**Existing Pattern** (`output_events.py`, IG-254):
```python
_OUTPUT_EVENT_REGISTRY: dict[str, Callable[[dict], str | None]] = {}

def register_output_event(event_type: str, extractor: Callable[[dict], str | None]) -> None:
    """Register output event type with content extraction function."""

def extract_output_text(event_type: str, data: dict) -> str | None:
    """Extract user-visible text from output event."""
```

**Extension for Streaming Events**:
```python
# Execution streaming
register_output_event(
    "soothe.output.execution.streaming",
    lambda data: data.get("content", ""),  # Preserve boundaries
)

# Synthesis streaming (replaces final_report.streaming)
register_output_event(
    "soothe.output.synthesis.streaming",
    lambda data: data.get("content", ""),
)

# Tool response streaming (experimental)
register_output_event(
    "soothe.output.tool_response.streaming",
    lambda data: data.get("content", ""),
)

# Backward compatibility: Keep existing final_report.streaming
register_output_event(
    "soothe.output.final_report.streaming",
    lambda data: data.get("content", ""),
)
```

**Registry Design Principles**:
1. **Single source**: Both CLI and TUI query registry (no duplicate logic)
2. **Boundary preservation**: Raw content extraction (no preprocessing in SDK)
3. **Client filtering**: Final filtering applied in EventProcessor (flexible)
4. **Extensibility**: Plugins can register custom streaming events

## Implementation Specification

### Phase 1: Configuration Layer

**Files Modified**:
1. `packages/soothe/src/soothe/config/models.py` - Add `OutputStreamingConfig` model
2. `packages/soothe/src/soothe/config/settings.py` - Add `output_streaming` field to `SootheConfig`
3. `packages/soothe/src/soothe/config/config.yml` - Add streaming section
4. `config/config.dev.yml` - Add streaming defaults (synchronized)
5. `packages/soothe-cli/src/soothe_cli/config/cli_config.py` - Add override fields
6. `packages/soothe-cli/src/soothe_cli/cli/main.py` - Add CLI flags

**Config Pattern**: Follow `AgenticLoopConfig` structure (RFC-001 lines 563-646).

**CRITICAL**: Both `config.yml` and `config.dev.yml` must be updated synchronously per CLAUDE.md rule.

### Phase 2: Runner Layer (Stream Generation)

**Files Modified**:
1. `packages/soothe/src/soothe/core/runner/_runner_shared.py` - Add `_wrap_streaming_output()` helper
2. `packages/soothe/src/soothe/core/runner/_runner_agentic.py` - Refactor IG-119 filtering, use wrapper
3. `packages/soothe/src/soothe/cognition/agent_loop/agent_loop.py` - Execution streaming

**Unified Wrapper Pattern**:
- Reuse `_custom()` helper from `_runner_shared.py` line 16-18
- Mirror `final_report_stream` extraction logic (`_runner_agentic.py` lines 547-570)
- Config-aware: Check `config.output_streaming.enabled` before wrapping

**IG-119 Filtering Refactor**:
```python
def _forward_messages_chunk_for_tool_ui(
    chunk: object,
    *,
    config: SootheConfig | None = None,
) -> bool:
    """Config-aware forwarding.

    When streaming disabled: Only forward tool-related chunks (existing behavior).
    When streaming enabled: Forward ALL chunks (wrapper will filter).
    """
```

### Phase 3: SDK Registry Extension

**Files Modified**:
1. `packages/soothe-sdk/src/soothe_sdk/ux/output_events.py` - Register all streaming events

**Naming Convention** (RFC-403):
- `soothe.output.execution.streaming` - Execution phase AI text
- `soothe.output.synthesis.streaming` - Synthesis phase AI text
- `soothe.output.tool_response.streaming` - Tool result processing (experimental)
- Preserve `soothe.output.final_report.streaming` for backward compatibility

### Phase 4: Daemon Layer (Broadcast)

**Files Modified**:
1. `packages/soothe/src/soothe/daemon/query_engine.py` - Update `extract_custom_output_text()`
2. `packages/soothe/src/soothe/daemon/client_session.py` - Config override support

**Extraction Simplification**:
Delegate to SDK registry (single source of truth):
```python
@staticmethod
def extract_custom_output_text(data: dict[str, Any]) -> str | None:
    """Extract output text via SDK registry."""
    from soothe_sdk.ux.output_events import extract_output_text
    event_type = str(data.get("type", ""))
    return extract_output_text(event_type, data)
```

### Phase 5: Client Layer (Display & Concatenation)

**Files Modified**:
1. `packages/soothe-cli/src/soothe_cli/shared/stream_accumulator.py` - NEW: State machine
2. `packages/soothe-cli/src/soothe_cli/shared/event_processor.py` - Integrate accumulator
3. `packages/soothe-cli/src/soothe_cli/shared/processor_state.py` - Add accumulator field
4. `packages/soothe-cli/src/soothe_cli/shared/renderer_protocol.py` - Add `on_streaming_output()`
5. `packages/soothe-cli/src/soothe_cli/cli/renderer.py` - Implement streaming display
6. `packages/soothe-cli/src/soothe_cli/tui/textual_adapter.py` - Implement with namespace tracking

**Accumulator Integration**:
```python
# EventProcessor output event handling
elif is_output_event(etype):
    streaming_config = self._get_effective_streaming_config()

    if not self._should_stream_event_type(etype, streaming_config):
        return

    content = extract_output_text(etype, data)
    is_streaming_chunk = etype.endswith(".streaming") and data.get("is_chunk", True)
    namespace = tuple(self._state.current_namespace or [])

    display_text = self._state.streaming_accumulator.accumulate(
        etype, content, namespace=namespace, is_chunk=is_streaming_chunk
    )

    if display_text:
        cleaned = self._clean_assistant_text(display_text, is_streaming=is_streaming_chunk)
        self._emit_assistant_text(cleaned, is_main=True, is_streaming=is_streaming_chunk)

    if not is_streaming_chunk:
        self._presentation.mark_final_answer_locked()
        self._state.streaming_accumulator.finalize_stream(etype, namespace)
```

**Boundary Preservation Pattern**:
Use existing `DisplayPolicy.filter_content(preserve_boundary_whitespace=True)` pattern (RFC-502):
```python
def _clean_assistant_text(self, text: str, is_streaming: bool) -> str:
    """Clean text with boundary preservation for streaming chunks."""
    return self._policy.filter_content(
        text,
        preserve_boundary_whitespace=is_streaming  # Preserve for chunks
    )
```

### Phase 6: Testing & Verification

**Test Coverage**:
1. **Unit tests**: Accumulator state machine, boundary preservation, namespace isolation
2. **Integration tests**: Config propagation, event generation, end-to-end streaming
3. **Manual scenarios**: Config testing, execution/synthesis streaming, batch mode

**Verification**:
Run `./scripts/verify_finally.sh` (formatting + linting + 900+ unit tests).

## Configuration Schema

### Global Configuration (config.yml)

```yaml
# =============================================================================
# Output Streaming Configuration (RFC-614)
# =============================================================================
output_streaming:
  enabled: true        # Global streaming enable/disable
  mode: streaming      # streaming or batch display mode
  execution_streaming: true   # Stream execution phase (CoreAgent Act responses)
  synthesis_streaming: true   # Stream synthesis phase (final report generation)
  tool_response_streaming: false  # Experimental: stream tool result processing
```

**Default Values**:
- `enabled: true` - Maintain current behavior (backward compatibility)
- `mode: streaming` - Real-time chunks (existing user expectation)
- `execution_streaming: true` - New capability (enabled by default)
- `synthesis_streaming: true` - Replaces `final_report_stream` (backward compatible)
- `tool_response_streaming: false` - Experimental (may cause UI fragmentation)

### CLI Override Flags

```bash
# Global streaming control
soothe --streaming "query"        # Enable streaming (default)
soothe --no-streaming "query"     # Disable streaming (batch mode)

# Mode override
soothe --streaming-mode streaming "query"  # Real-time chunks
soothe --streaming-mode batch "query"      # Accumulate silently
```

**Override Logic**:
1. CLI flags → `CLIConfig.output_streaming_enabled/mode`
2. Client fetches daemon config via RPC
3. Merge: `daemon_config + cli_overrides` → effective config
4. Pass to EventProcessor for display behavior

## Event Flow Architecture

### Daemon → Client Event Path

```
1. LangGraph.astream() → (namespace, mode, data) chunks
   ↓
2. Runner._wrap_streaming_output() → Custom event wrapping
   ↓ (event_type: "soothe.output.execution.streaming", content: "text", is_chunk: True)
3. QueryEngine._broadcast() → EventBus.publish
   ↓ (topic: "thread:{thread_id}", event: {...})
4. EventBus → ClientSession.event_queue (priority-aware overflow)
   ↓ (WebSocket JSON transport, RFC-450)
5. WebSocketClient.read_event() → EventProcessor.process_event()
   ↓
6. SDK output_events.extract_output_text() → Raw content extraction
   ↓
7. StreamingTextAccumulator.accumulate() → Boundary-preserving accumulation
   ↓
8. RendererProtocol.on_assistant_text() → Display (CLI/TUI)
```

### Namespace Isolation Flow

```
Main Agent:
  namespace: ()
  → streams["soothe.output.execution.streaming", ()] → AccumState A

Subagent Browser:
  namespace: ("browser",)
  → streams["soothe.output.execution.streaming", ("browser",)] → AccumState B

Concurrent execution: A and B isolated (no chunk interleaving)
```

**Key**: Stream key = (event_type + namespace) ensures concurrent streams don't mix chunks.

## Backward Compatibility

### Existing Event Semantics

**Preserved Events**:
- `soothe.output.final_report.streaming` - Keep registered, backward compatibility
- `soothe.output.chitchat.responded` - Final-only (no changes)
- `soothe.output.quiz.responded` - Final-only (no changes)
- `soothe.cognition.agent_loop.completed` - Final stdout message (no changes)

**New Events** (Preferred):
- `soothe.output.execution.streaming` - Execution phase (RFC-614)
- `soothe.output.synthesis.streaming` - Synthesis phase (RFC-614)

**Migration Path**:
- Existing code expecting `final_report_stream` continues working
- New code should use `synthesis.streaming` naming
- Gradual migration, no breaking changes

### Default Behavior

**Config Defaults**:
- `enabled: true` - Current behavior (streaming already hardcoded)
- `mode: streaming` - Current CLI/TUI behavior
- Performance impact minimal when disabled (early config check)

**IG-119 Filtering**:
- When `enabled: false` - Existing behavior (only tool-related chunks)
- When `enabled: true` - Forward all chunks (wrapper filters)

## Performance Considerations

### Minimal Overhead When Disabled

**Config Check Pattern**:
```python
def _wrap_streaming_output(..., config: SootheConfig | None = None):
    if config and not config.output_streaming.enabled:
        return None  # Early return, minimal overhead
```

**Impact Analysis**:
- Disabled: Single `enabled` check, no extraction/wrapping
- Enabled: Extraction + wrapping overhead (acceptable for streaming use case)

### Priority-Aware Overflow (RFC-401, IG-258)

**Streaming Event Priority**:
- Execution/synthesis streaming: `EventPriority.NORMAL`
- Tool response streaming: `EventPriority.LOW` (experimental, may drop on overflow)
- Final events: `EventPriority.HIGH` (never dropped)

**Queue Management**:
- Existing EventBus priority overflow strategy (IG-258 Phase 1)
- 80% threshold for LOW priority dropping
- CRITICAL events block until space available

### Network Overhead

**Existing Verbosity Filtering** (RFC-401):
- Daemon-side filtering by verbosity level
- Streaming events: `VerbosityTier.QUIET` (always visible)
- Batch mode: Same events, accumulated silently

**No Additional Transport Overhead**:
- WebSocket already bidirectional (RFC-450)
- Same JSON message format
- EventBus routing unchanged

## Extensibility

### Plugin Integration

**Custom Streaming Events**:
```python
from soothe_sdk.ux.output_events import register_output_event

register_output_event(
    "soothe.plugin.my_plugin.streaming",
    lambda data: data.get("content", ""),
)
```

**Runner Integration**:
```python
wrapped = _wrap_streaming_output(
    chunk=item,
    event_type="soothe.plugin.my_plugin.streaming",
    config=self.config,
    namespace=("plugin", "my_plugin"),
)
```

**Registry Benefits**:
- Single registration point (SDK)
- Both CLI and TUI automatically support custom events
- No duplicate logic in client processors

### Future Extensions

**Potential Extensions**:
1. Subagent streaming isolation (namespace tracking already in place)
2. Multi-modal streaming (images, files via content_blocks)
3. Streaming annotations (metadata about chunks)
4. Adaptive streaming (chunk size optimization)

## Testing Requirements

### Unit Tests

**Accumulator State Machine** (`test_stream_accumulator.py`):
1. Boundary preservation (whitespace chunks)
2. Namespace isolation (concurrent streams)
3. Batch mode (silent accumulation, final display)
4. Finalization logic (non-chunk events)
5. State clearing (turn completion)

**Config Propagation** (`test_streaming_config.py`):
1. Daemon config parsing
2. CLI override logic
3. Effective config merge
4. Per-phase flag behavior

### Integration Tests

**End-to-End Streaming** (`test_unified_streaming.py`):
1. Execution streaming enabled (chunks emitted)
2. Streaming disabled (no custom streaming events)
3. Config override behavior (CLI flags override daemon)
4. Boundary preservation end-to-end (markdown formatting)
5. Namespace isolation (concurrent subagents)

### Manual Testing Scenarios

1. **Config Testing**:
   - Edit `config.yml`: `enabled: false` → verify no streaming
   - Edit `config.yml`: `mode: batch` → verify final output only
   - CLI override: `--no-streaming` → verify override works

2. **Execution Streaming**:
   - Run agentic query → verify execution phase streams
   - Run with concurrent subagents → verify no interleaving

3. **Synthesis Streaming**:
   - Run query requiring synthesis → verify final report streams
   - Compare with old `final_report_stream` → backward compatibility

4. **Boundary Preservation**:
   - Query returning markdown → verify whitespace preserved
   - Multi-line output → verify line breaks maintained

5. **Batch Mode**:
   - Set `mode: batch` → verify silent accumulation
   - Verify final output appears at completion

## Success Criteria

1. **Functional Requirements**:
   - All AI outputs stream when enabled
   - Config controls streaming globally and per-phase
   - CLI flags override daemon config
   - Whitespace boundaries preserved for markdown
   - Concurrent streams isolated (no interleaving)
   - Batch mode works correctly

2. **Performance Requirements**:
   - Minimal overhead when disabled (< 5ms per chunk)
   - No network overhead beyond existing transport
   - Priority overflow handling preserves critical events

3. **Compatibility Requirements**:
   - Existing events continue working (backward compatibility)
   - Existing tests pass (no breaking changes)
   - Config defaults maintain current behavior

4. **Extensibility Requirements**:
   - Plugins can register custom streaming events
   - Single source of truth in SDK registry
   - Client processors support new events automatically

5. **Testing Requirements**:
   - Unit tests for accumulator pass (state machine validation)
   - Integration tests for end-to-end streaming pass
   - Manual testing scenarios verified
   - `./scripts/verify_finally.sh` passes (900+ tests)

## Security Considerations

### No Additional Security Risks

**Existing Security** (RFC-450):
- CORS validation for WebSocket connections
- Client isolation enforced
- No built-in authentication (external services)

**Streaming Events**:
- Same JSON message format (no new attack vectors)
- Same EventBus routing (no new privilege escalation)
- Same transport layer (no new protocol vulnerabilities)

**Config Control**:
- Admin controls streaming via `config.yml`
- User cannot bypass config via CLI (override only affects own session)

## Migration Guide

### For Developers

**Using Streaming Events**:
```python
# Runner: Wrap streaming output
from soothe.core.runner._runner_shared import _wrap_streaming_output

wrapped = _wrap_streaming_output(
    chunk=item,
    event_type="soothe.output.execution.streaming",
    config=self.config,
)

# Client: Process streaming events
from soothe_sdk.ux.output_events import extract_output_text

content = extract_output_text(event_type, data)
```

**Registering Custom Streaming Events**:
```python
from soothe_sdk.ux.output_events import register_output_event

register_output_event(
    "soothe.plugin.custom.streaming",
    lambda data: data.get("content", ""),
)
```

### For Users

**Configuration**:
```yaml
# Enable streaming (default)
output_streaming:
  enabled: true
  mode: streaming

# Disable streaming (batch mode)
output_streaming:
  enabled: false
```

**CLI Usage**:
```bash
# Real-time streaming (default)
soothe "Write a report"

# Batch mode (final output only)
soothe --no-streaming "Write a report"
```

## References

### Related RFCs

- **RFC-000**: System Conceptual Design (three-layer architecture)
- **RFC-001**: Core Modules Architecture (protocol patterns)
- **RFC-450**: Daemon Communication Protocol (WebSocket transport, EventBus)
- **RFC-401**: Event Processing (EventProcessor, RendererProtocol)
- **RFC-403**: Unified Event Naming (4-segment naming convention)
- **RFC-502**: Unified Presentation Engine (boundary preservation)

### Implementation History

- **IG-119**: IG-119 filtering logic (prevents duplicate stdout)
- **IG-254**: Unified output events registry (single source of truth)
- **IG-258**: Priority-aware EventBus overflow (performance optimization)
- **IG-268**: Final report streaming (special-case implementation)

## Document History

**Created**: 2026-04-27
**Status**: Draft
**Authors**: Soothe Team

**Revision History**:
- v1.0 (2026-04-27): Initial RFC draft for unified streaming framework

---

**End of RFC-614**