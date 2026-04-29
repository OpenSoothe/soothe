# RFC-614: Unified Daemon → Client Streaming Messaging Framework

**RFC**: 614
**Title**: Unified Daemon → Client Streaming Messaging Framework
**Status**: Draft
**Kind**: Architecture Design
**Created**: 2026-04-27
**Dependencies**: RFC-000, RFC-001, RFC-450, RFC-401, RFC-403
**Extends**: RFC-450 (Daemon Communication), RFC-401 (Event Processing)

## Abstract

This RFC defines a unified streaming messaging framework for daemon-to-client output delivery, with explicit separation between execution telemetry and user-facing final output text. The framework standardizes output events, configuration-driven display behavior, and content concatenation with whitespace boundary preservation.

### IG-304 / IG-317 Amendment (current)

Daemon output emission owns suppression boundaries for AgentLoop execution:

1. Execute-phase assistant prose is suppressed at daemon emission and is not streamed as user-visible output.
2. Message-mode forwarding carries **tool UI** (`ToolMessage` + AI tool-call metadata) **and** loop-tagged assistant completion chunks (`phase` in `goal_completion`, `chitchat`, `quiz`, `autonomous_goal`).
3. User-facing completion text uses the **`messages`** stream with **`phase`** (IG-317); it is **not** modeled as parallel `soothe.output.goal_completion.*` custom events.
4. Clients consume the normalized output contract; they should not be the primary suppression authority for execute-phase prose.

**Key Design Principles**:
1. **Single assistant-text wire**: Prefer loop-tagged `messages` chunks over duplicate custom `soothe.output.*` payloads for core-loop answers.
2. **Configuration-driven**: Global enable/disable plus streaming/batch display mode for goal-completion **message** streaming.
3. **Boundary preservation**: Maintain whitespace for markdown formatting during concatenation.
4. **Namespace isolation**: Prevent interleaving concurrent streams from parallel subagents.
5. **Hard cut where required**: Remove legacy dual paths that duplicate the same assistant text.

## Problem Statement

### Current Limitations

**IG-119 Filtering Barrier**:
The runner's IG-119 filtering logic (`_runner_agentic.py` lines 541-545) blocks plain AIMessage chunks to prevent duplicate stdout in multi-step execution. Only tool-related chunks (ToolMessage + AI tool_invocation metadata) pass through.

**Special-Case Workaround**:
`final_report_stream` is hard-coded special case (lines 547-570) that:
- Extracts AI text from messages chunks
- Wraps as custom events to bypass filtering
- Only works for synthesis phase (final report generation)

**Resolved (IG-317)**:
- Goal completion, chitchat, quiz, and autonomous summaries stream as **`messages`** chunks with an explicit **`phase`** field instead of bespoke `soothe.output.*` assistant events.
- Execute-phase assistant prose (CoreAgent Act narration) remains suppressed by daemon contract.
- Optional ancillary `soothe.output.*` events (for example library line capture) are orthogonal to the assistant answer contract.

**User Experience**:
Users see tool telemetry during execute and receive final / phased assistant text through the **`messages`** wire; execute-phase narration stays suppressed by design.

### Goals

1. **Contracted streaming**: Stream tool UI telemetry plus loop-tagged **`messages`** assistant chunks (`phase`); do not stream execute-phase prose
2. **Configuration control**: Global enable/disable and streaming/batch display mode
3. **Proper concatenation**: Whitespace boundary preservation for markdown formatting
4. **Concurrency safety**: Namespace-based isolation for parallel subagent streams
5. **Extensibility**: Additional UX may attach to the same `messages` + `phase` pattern or emit optional `soothe.output.*` **progress** events (not duplicate assistant bodies).
6. **Performance**: Minimal overhead when disabled, config-driven filtering

### Non-Goals

- Real-time event filtering (already covered by RFC-401 verbosity filtering)
- Transport layer changes (WebSocket already bidirectional, RFC-450)
- Event naming taxonomy (RFC-403 covers naming conventions)
- UI display logic (CLI/TUI implementation details, RFC-500)
- Client-side suppression as primary correctness boundary for AgentLoop execute-phase prose

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
│ Runner layer (stream generation)                             │
│ • IG-119-safe forwarding of tool UI + loop-tagged assistant   │
│   `messages` chunks (`stream_event` → client `mode="messages"`)│
│ • Config-aware suppression for execute-phase prose           │
└─────────────────────────────────────────────────────────────┘
                          ↓ Multiplexed stream tuples
┌─────────────────────────────────────────────────────────────┐
│ Daemon / client layer (transport & display)                  │
│ • EventBus broadcast: Priority-aware overflow (RFC-401)       │
│ • SDK `loop_stream` helpers: Recognize assistant `phase`      │
│ • StreamingTextAccumulator: Concatenation with boundaries     │
│ • Namespace isolation: Concurrent stream tracking             │
└─────────────────────────────────────────────────────────────┘
```

**Layer responsibilities**:
- **Configuration**: Output streaming enable/disable and display mode (streaming vs batch) for goal-completion **message** streaming.
- **Runner**: Forwards tool UI `messages` chunks and loop-tagged assistant `messages` chunks (`phase`); suppresses execute-phase prose.
- **Daemon / client**: Broadcasts stream tuples; clients accumulate and render assistant text from **`messages` + `phase`** using shared SDK helpers.

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
- Optional `soothe.output.*` names remain valid for **ancillary** progress telemetry.
- **Assistant answer bodies** for the main loop use **`messages` + `phase`**, not `soothe.output.goal_completion.*` types.

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
    """Backward-compatibility field; execute-phase prose remains daemon-suppressed by contract."""

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

#### Runner forwarding (`stream_event` → client tuples)

Early RFC-614 drafts described a `_wrap_streaming_output()` helper that re-published AI text as **`soothe.output.*`** custom events. **IG-317 removed that path** for core-loop assistant text: the runner now forwards loop-tagged assistant chunks on the existing **`mode="messages"`** stream (plus tool UI chunks), while still applying IG-119 / IG-304 suppression for execute-phase prose.

**Design checklist**:
1. Config: honor `OutputStreamingConfig` for **goal-completion message** streaming vs batch display on the client.
2. Extraction: collect plain text from AI message / chunk payloads when forwarding is allowed.
3. Loop tags: preserve `phase` metadata so clients can classify `goal_completion`, `chitchat`, `quiz`, and `autonomous_goal`.
4. Namespace: carry LangGraph namespace through to the client so concurrent subgraphs do not interleave text.

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
    - Preserve whitespace boundaries and stitch unsafe cross-chunk boundaries
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
        - is_chunk=True: Return chunk content with boundary-safe stitching
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
2. **Chunk handling**: Accumulate content, apply minimal boundary stitching, return display chunk
3. **Final message**: Mark inactive, return full accumulated text
4. **Finalization**: Mark inactive, prevent further accumulation
5. **Clear**: Remove state after final display

#### SDK: loop-tagged `messages` stream (IG-317)

Public client helpers live in `packages/soothe-sdk/src/soothe_sdk/ux/loop_stream.py`:

- `LOOP_ASSISTANT_OUTPUT_PHASES` — allowed `phase` values on assistant payloads.
- `assistant_output_phase(msg)` — returns `phase` when a wire-serialized AI message dict/object carries loop assistant output.

CLI/TUI `EventProcessor` paths use these helpers to treat **`mode="messages"`** chunks as user-visible assistant text for goal completion (and related phases), instead of consulting a removed `soothe.output.*` registry.

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

**Primary modules**:
1. `packages/soothe/src/soothe/core/runner/_runner_agentic.py` — multiplex `stream_event` into client `mode="messages"` / `custom`, enforce IG-119 / IG-304 suppression, forward loop-tagged assistant chunks for configured phases.
2. `packages/soothe/src/soothe/cognition/agent_loop/core/agent_loop.py` — emit `stream_event` tuples consumed by the runner.

**Forwarding contract** (summary): forward **tool UI** `messages` chunks; forward **loop assistant** `messages` chunks when `assistant_output_phase(...)` is non-null; suppress plain execute-phase assistant prose.

### Phase 3: SDK (`soothe-sdk`)

**Module**: `packages/soothe-sdk/src/soothe_sdk/ux/loop_stream.py` — documents allowed `phase` values and provides `assistant_output_phase()`.

### Phase 4: Daemon Layer (Broadcast)

**`query_engine.py`**: forwards runner chunks to WebSocket clients; **full-response** aggregation for persisted transcripts uses **`mode="messages"`** AI text extraction (not custom `soothe.output.*` assistant events).

### Phase 5: Client Layer (Display & Concatenation)

**Primary modules**:
1. `packages/soothe-cli/src/soothe_cli/shared/event_processor.py` — `StreamingTextAccumulator` keyed by internal namespace for **`phase=goal_completion`** message streaming; `_handle_messages_event` uses `assistant_output_phase`.
2. `packages/soothe-cli/src/soothe_cli/tui/textual_adapter.py` — mirrors the same `messages` + `phase` behavior for the TUI.

**Goal-completion accumulation** (conceptual):
```python
# Pseudocode — see EventProcessor for the concrete implementation
if assistant_output_phase(msg) == "goal_completion":
    display_text = accumulator.accumulate(internal_key, text, namespace=ns, is_chunk=is_chunk)
    ...
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
3. **Manual scenarios**: Config testing, execute-phase suppression + tool telemetry, goal-completion streaming, batch mode

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
  execution_streaming: true   # Backward-compatible field; execute prose remains daemon-suppressed
  synthesis_streaming: true   # Stream synthesis phase (final report generation)
  tool_response_streaming: false  # Experimental: stream tool result processing
```

**Default Values**:
- `enabled: true` - Maintain current behavior (backward compatibility)
- `mode: streaming` - Real-time chunks (existing user expectation)
- `execution_streaming: true` - Backward-compatible field (no execute-prose forwarding effect)
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
2. Runner multiplexes `stream_event` → client `mode="messages"` / `custom`
   ↓ (goal completion: AI chunk + phase="goal_completion", is_chunk metadata)
3. QueryEngine._broadcast() → EventBus.publish
   ↓ (topic: "thread:{thread_id}", event: {...})
4. EventBus → ClientSession.event_queue (priority-aware overflow)
   ↓ (WebSocket JSON transport, RFC-450)
5. WebSocketClient.read_event() → EventProcessor.process_event()
   ↓
6. `assistant_output_phase(msg)` (SDK `loop_stream`) → decide assistant display path
   ↓
7. StreamingTextAccumulator.accumulate() → Boundary-preserving accumulation (internal keys)
   ↓
8. RendererProtocol.on_assistant_text() → Display (CLI/TUI)
```

### Namespace Isolation Flow

```
Main Agent:
  namespace: ()
  → streams[(internal_goal_completion_key, ())] → AccumState A

Subagent Browser:
  namespace: ("browser",)
  → streams[(internal_goal_completion_key, ("browser",))] → AccumState B

Concurrent execution: A and B isolated (no chunk interleaving)
```

**Key**: Accumulator state is keyed by **(logical stream id, namespace)** so concurrent subgraphs never mix chunks.

## Compatibility Notes (IG-317)

### Event Semantics

- **`soothe.cognition.agent_loop.completed`**: lifecycle / progress only (no parallel requirement to ship final answer text on this event).
- **Removed for assistant bodies**: `soothe.output.goal_completion.*`, `soothe.output.chitchat.responded`, `soothe.output.quiz.responded`, and related autonomous output-domain duplicates — **replaced by `messages` + `phase`.**

**Integrator guidance**:
- Clients must consume **`mode="messages"`** chunks and inspect **`phase`** (via `soothe_sdk.ux.loop_stream`) for user-visible loop answers.
- Treat historical `soothe.output.*` assistant event names as **documentation debt** outside optional ancillary telemetry.

### Default Behavior

**Config Defaults**:
- `enabled: true` - Current behavior (streaming already hardcoded)
- `mode: streaming` - Current CLI/TUI behavior
- Performance impact minimal when disabled (early config check)

**Message chunk forwarding**:
- Tool/UI chunks are forwarded from daemon.
- Execute-phase prose is suppressed at daemon emission and is not forwarded as user output.

## Performance Considerations

### Minimal Overhead When Disabled

**Config check pattern**:
- When streaming is disabled, the client skips incremental assistant emission for goal-completion **message** chunks and may defer to batch / final-only display logic.
- Daemon-side suppression for execute-phase prose remains independent of this toggle.

**Impact analysis**:
- Disabled: client short-circuits incremental assistant rendering for configured phases.
- Enabled: normal incremental accumulation + rendering for loop-tagged assistant `messages` chunks.

### Priority-Aware Overflow (RFC-401, IG-258)

**Streaming Event Priority**:
- Goal-completion streaming: `EventPriority.NORMAL`
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

### Plugin integration

Plugins that need **user-visible assistant text in the main loop** should participate in the same contract as core Soothe: emit **loop-tagged LangGraph `messages` chunks** with a `phase` that clients recognize (extend phases only with coordinated SDK + client updates).

Plugins may still emit **ancillary** `soothe.output.*` **custom** events for progress or side channels; those are **not** interpreted as main-loop assistant answers by current CLI/TUI processors.

### Future extensions

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
1. Goal-completion streaming enabled (chunks emitted)
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
   - Run agentic query → verify execute-phase prose is suppressed
   - Verify tool telemetry still streams during execution

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
   - Only contracted user-facing outputs stream when enabled
   - Config controls streaming globally and by display mode
   - CLI flags override daemon config
   - Whitespace boundaries preserved for markdown
   - Concurrent streams isolated (no interleaving)
   - Batch mode works correctly

2. **Performance Requirements**:
   - Minimal overhead when disabled (< 5ms per chunk)
   - No network overhead beyond existing transport
   - Priority overflow handling preserves critical events

3. **Compatibility Requirements**:
   - Historical `soothe.output.*` assistant payloads may still appear in archived logs but are **not** required for core-loop UX after IG-317.
   - Config defaults preserve streaming/batch expectations for **message-mode** goal completion.

4. **Extensibility Requirements**:
   - New loop phases require coordinated runner + SDK `loop_stream` + client updates.
   - Ancillary `soothe.output.*` telemetry remains naming-extensible under RFC-403.

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

**Consuming loop assistant output (client)**:
```python
from soothe_sdk.ux.loop_stream import assistant_output_phase

phase = assistant_output_phase(msg)  # e.g. "goal_completion"
```

**Emitting loop assistant output (runner / AgentLoop)**:
- Forward `stream_event` tuples that already include loop-tagged AI `messages` payloads with `phase` set; avoid reintroducing duplicate `soothe.output.goal_completion.*` custom events for the same text.

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
- v1.2 (2026-04-29): Consistency polish — aligned examples/config semantics with daemon-side execute-phase suppression and goal-completion streaming contract
- v1.1 (2026-04-28): IG-304 amendment — daemon-side suppression isolation, tool-only message forwarding, goal-completion output contract
- v1.0 (2026-04-27): Initial RFC draft for unified streaming framework

---

**End of RFC-614**