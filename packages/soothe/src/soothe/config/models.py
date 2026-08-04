"""Pydantic configuration models for Soothe.

Shared (nano-owned) schema classes are re-exported from ``soothe_nano.config.models``.
Host-only overlays (StrangeLoop, Autopilot, cron, skillify, clarification, veritas)
live in this module. ``AgentConfig`` subclasses nano's slim CoreAgent config.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

# Re-export facade — canonical source: soothe_nano.config.models
from soothe_nano.config.models import (  # noqa: F401
    MODEL_KNOWLEDGE_CUTOFFS,
    AgentRuntimeConfig,
    CodeInterpreterConfig,
    ConsoleLoggingConfig,
    CoreAgentMiddlewareConfig,
    DeepxivToolsConfig,
    DurabilityProtocolConfig,
    EmbeddingProfile,
    ExecutionToolsConfig,
    FailureIntentConfig,
    FileLoggingConfig,
    FilesystemMiddlewareConfig,
    GlobalHistoryConfig,
    HttpRequestsToolsConfig,
    LangfuseIntegrationConfig,
    LLMRateLimitConfig,
    LoopToolOutputConfig,
    MCPAuthHeaders,
    MCPServerConfig,
    MCPTransport,
    MemUConfig,
    ModelProviderConfig,
    ModelRole,
    ModelRouter,
    ObservabilityConfig,
    OptimizationConfig,
    PersistenceConfig,
    PlannerProtocolConfig,
    PluginConfig,
    PolicyProtocolConfig,
    PostgresPoolConfig,
    ProgressiveMCPConfig,
    ProgressiveSkillsConfig,
    ProgressiveToolsConfig,
    ProtocolsConfig,
    ReportOutputConfig,
    RoleRoutingConfig,
    RouterProfile,
    SecurityConfig,
    SqliteRuntimeConfig,
    StructuredPlanConfig,
    SubagentConfig,
    ThreadLoggingConfig,
    ToolCallLimitConfig,
    ToolConfig,
    ToolRetryConfig,
    ToolsConfig,
    ToolTimeoutConfig,
    UIConfig,
    UpdateConfig,
    VectorStoreProviderConfig,
    VectorStoreRouter,
    WebSearchConfig,
    WorkspaceMountConfig,
    get_knowledge_cutoff,
)
from soothe_nano.config.models import (
    AgentConfig as NanoAgentConfig,
)

from soothe.config.constants import (
    DEFAULT_MAX_ITERATIONS,
    DEFAULT_MAX_TOOL_CALLS_PER_STEP,
)
from soothe.sloop.clarification.origins import DEFAULT_FORCE_MANUAL_ORIGINS

AgenticFinalResponseMode = Literal["auto", "always_synthesize"]


AgenticGoalCompletionMode = Literal["llm_only", "heuristic_only", "hybrid"]


ExecuteDeliverableAssessMode = Literal["auto", "always", "never"]


def normalize_agentic_final_response_mode(value: Any) -> Any:
    """Normalize ``final_response``; ``adaptive`` is a deprecated alias for ``auto``."""
    if value == "adaptive":
        return "auto"
    return value


class DreamingModeConfig(BaseModel):
    """Per-mode dreaming configuration (RFC-625 §13).

    Args:
        enabled: Whether this dreaming mode is enabled.
        max_episodes: Maximum episodes to distill (episodic mode only).
        min_success_rate: Minimum success rate for procedure extraction (procedure mode only).
    """

    enabled: bool = True
    max_episodes: int = Field(
        default=10, ge=1, le=100, description="Max episodes for episodic mode"
    )
    min_success_rate: float = Field(
        default=0.8, ge=0.0, le=1.0, description="Min success rate for procedure mode"
    )


class DreamingModesConfig(BaseModel):
    """Dreaming modes configuration container (RFC-625 §13).

    Args:
        episodic: Episodic memory distillation config.
        procedure: Procedure/skill extraction config.
        semantic: Project MEMORY.md update config.
        profile: User profile extraction config.
    """

    episodic: DreamingModeConfig = Field(
        default_factory=lambda: DreamingModeConfig(max_episodes=10)
    )
    procedure: DreamingModeConfig = Field(
        default_factory=lambda: DreamingModeConfig(min_success_rate=0.8)
    )
    semantic: DreamingModeConfig = Field(default_factory=DreamingModeConfig)
    profile: DreamingModeConfig = Field(default_factory=DreamingModeConfig)


class AutopilotConfig(BaseModel):
    """Autopilot scheduling and self-running configuration.

    Controls 24/7 self-running behavior for both goal-level and daemon-level.

    Args:
        enabled: Whether the AutopilotService scheduling loop is enabled.
            When False, the daemon constructs the service but does not start
            the scheduling loop. HTTP /autopilot/submit endpoints are available
            but goals won't be dispatched automatically. Default is False.
        max_iterations: Maximum iterations per autopilot thread (goal-level).
        max_retries: Maximum retries per goal on failure.
        max_total_goals: Maximum goals allowed (RFC-0007 §5.6).
        max_goal_depth: Maximum hierarchy depth (RFC-0007 §5.6).
        max_parallel_goals: Maximum goals running simultaneously.
        enable_dynamic_goals: Enable/disable dynamic creation (RFC-0007 §5.4).

        max_send_backs: Per-goal send-back budget for consensus validation (daemon-level).
        checkpoint_interval: Iterations between periodic checkpoints.
        dreaming_enabled: Enter dreaming mode when all goals complete.
        dreaming_consolidation_interval: Seconds between memory consolidation during dreaming.
        dreaming_health_check_interval: Seconds between health checks during dreaming.
        monitor_model_role: Router role for AutopilotMonitor LLM reasoners (backoff,
            DAG verification, dreaming distillation). Defaults to ``think``.
        consensus_model_role: Router role for RFC-204 goal consensus validation.
            Defaults to ``think``; daemon uses ``create_chat_model`` with automatic
            fallback to ``default`` on instantiation failure.
        webhooks: Webhook URLs by event type (e.g., on_goal_completed).
    """

    # === Autopilot scheduling (daemon-level) ===
    enabled: bool = Field(
        default=False,
        description=(
            "Enable the AutopilotService scheduling loop. When True, the daemon "
            "starts the scheduling loop on startup for 24/7 autonomous operation. "
            "When False (default), the service is constructed but the scheduling loop does not "
            "start automatically; goals must be dispatched manually."
        ),
    )
    max_iterations: int = 10
    max_retries: int = 2
    max_total_goals: int = Field(default=50, ge=1, le=500)
    max_goal_depth: int = Field(default=5, ge=1, le=10)
    max_parallel_goals: int = Field(default=3, ge=1, le=10)
    enable_dynamic_goals: bool = Field(default=True)
    # Concurrency cap for parallel goal execution. Enforced in two places:
    # 1. ConcurrencyController in the runner (runner-side semaphore)
    # 2. AutopilotService._execution_semaphore (service-side semaphore, RFC-222)
    # Independent of `max_loops`: loops can be reused for lineage, so the
    # number of in-flight executions can be lower than the loop pool size.

    # === Orchestration (from old autopilot) ===
    max_send_backs: int = Field(default=3, ge=1, le=10)
    checkpoint_interval: int = Field(default=10, ge=1, le=100)

    # === Dreaming ===
    dreaming_enabled: bool = True
    dreaming_consolidation_interval: int = Field(default=300, ge=10)
    dreaming_health_check_interval: int = Field(default=60, ge=5)

    monitor_model_role: ModelRole = Field(
        default="think",
        description=(
            "Router model role for AutopilotMonitor LLM reasoners "
            "(backoff, DAG verification, dreaming distillation)."
        ),
    )

    consensus_model_role: ModelRole = Field(
        default="think",
        description="Router model role for RFC-204 goal consensus validation.",
    )

    default_rail: str | None = Field(
        default=None,
        description=(
            "Optional LoopRail id applied when submit omits rail_id and the "
            "workspace has no .soothe/rails/.rail-default. Empty/None = no rail."
        ),
    )

    # RFC-625: AutopilotMonitor settings
    verify_interval: int = Field(
        default=30,
        ge=5,
        le=300,
        description="Background verification loop interval (seconds)",
    )
    """Seconds between DAG health verification cycles."""

    dreaming_interval: int = Field(
        default=300,
        ge=60,
        le=3600,
        description="Time-based dreaming trigger interval (seconds)",
    )
    """Seconds between time-triggered dreaming mode entries."""

    dreaming_scope: Literal["loop", "workspace", "topic"] = Field(
        default="workspace",
        description="Cross-loop dreaming scope for memory distillation",
    )
    """Scope for dreaming: loop (current), workspace (all goals), topic (tagged goals)."""

    dreaming_modes: DreamingModesConfig = Field(
        default_factory=lambda: DreamingModesConfig(),
        description="Per-mode dreaming distillation config",
    )
    """Configuration for each dreaming distillation mode."""

    webhooks: dict[str, str | None] = Field(default_factory=dict)

    # === Loop pool (RFC-222) ===
    # Distinct from `max_parallel_goals`: `max_loops` caps worker capacity in
    # the StrangeLoop pool (loops can be reused for parent→child lineage), while
    # `max_parallel_goals` caps the number of goals actively scheduled at once.
    # They can differ — e.g. max_loops=8 for lineage reuse, max_parallel_goals=4.
    max_loops: int = Field(
        default=4,
        ge=1,
        le=32,
        description="Maximum concurrent StrangeLoop workers in the autopilot pool",
    )
    loop_idle_timeout: int = Field(
        default=300,
        ge=10,
        description="Seconds an idle loop is kept before release",
    )
    poll_interval: int = Field(
        default=5,
        ge=1,
        description="AutopilotService scheduling-loop tick interval, seconds",
    )
    dreaming_poll_interval: int = Field(
        default=60,
        ge=5,
        description="Reduced polling cadence when in dreaming mode, seconds",
    )
    # RFC-222 H5: wall-clock budget per dispatched goal. None disables.
    goal_deadline_seconds: float | None = Field(
        default=1_209_600.0,
        description=(
            "Wall-clock budget per dispatched autopilot goal in seconds; "
            "the AutopilotService monitor cancels the worker on overrun (RFC-222 H5). "
            "None disables deadline enforcement (default 14d)."
        ),
    )
    # === Context projection (RFC-222 revised) ===
    # Bounds the GoalDispatchContextBundle that the daemon's ContextProjector
    # builds for each dispatched goal. Keeps cross-process IPC bounded and
    # caps memory of the GoalDispatchContextStore in durability.
    context_projection: ContextProjectionConfig = Field(
        default_factory=lambda: ContextProjectionConfig(),
        description="Bounds for GoalDispatchContextBundle merging",
    )

    # === Workspace reservation (RFC-222 revised) ===
    # Scheduling-time conflict gate. Refuses to dispatch two goals whose
    # workspace prefixes overlap. Supersedes per-path FileLockMiddleware for v1.
    workspace_reservation: WorkspaceReservationConfig = Field(
        default_factory=lambda: WorkspaceReservationConfig(),
        description="Workspace-prefix conflict gate config",
    )


class ContextProjectionConfig(BaseModel):
    """Bounds for GoalDispatchContextBundle merging (RFC-222 revised).

    The ContextProjector unions parents' GoalDispatchContextContributions,
    deduplicates, and truncates to these caps. Bundle stays small enough to
    ship over IPC cheaply (~100 KB).

    Args:
        max_findings: Max LLM-synthesized findings per bundle.
        max_files: Max file touchpoints per bundle.
        max_plan_steps: Max prior plan steps per bundle.
        context_retention_hours: After a root goal reaches a terminal state,
            its DAG's contributions become evictable from the store this many
            hours later. Default 168 (1 week). LRU-evict if quota exceeded.
        max_context_entries: Hard cap on the number of goal contributions
            held by the in-memory fallback store. When exceeded, the oldest
            entries (by write time) are evicted. Default 1000. Set to 0 for
            unbounded (not recommended for production).
    """

    max_findings: int = Field(default=20, ge=1, le=200)
    max_files: int = Field(default=50, ge=1, le=500)
    max_plan_steps: int = Field(default=30, ge=1, le=300)
    context_retention_hours: int = Field(default=168, ge=1)
    max_context_entries: int = Field(default=1000, ge=0)


class WorkspaceReservationConfig(BaseModel):
    """Workspace-prefix conflict gate config (RFC-222 revised).

    Args:
        enabled: When false, autopilot does not check for workspace overlap
            (allows multiple goals on overlapping paths). Default true.
        strict_overlap: When true, any prefix overlap counts as conflict
            (`/foo/bar` conflicts with `/foo/bar/baz`). Default true.
    """

    enabled: bool = True
    strict_overlap: bool = True


class LoopWorkingMemoryConfig(BaseModel):
    """Agentic loop working memory (RFC-203).

    In-memory scratchpad for the agentic loop; large entries spill under
    ``SOOTHE_HOME/data/threads/{thread_id}/working_memory/``.

    Args:
        enabled: Enable working memory for Layer 2 Reason prompts.
        max_inline_chars: Max size of the aggregated block injected into Reason.
        max_entry_chars_before_spill: Per-step output larger than this is written to disk.
    """

    enabled: bool = Field(default=True, description="Enable working memory")
    max_inline_chars: int = Field(
        default=4000,
        ge=400,
        le=100_000,
        description="Max chars for working-memory block in Reason prompt",
    )
    max_entry_chars_before_spill: int = Field(
        default=1500,
        ge=200,
        le=50_000,
        description="Spill step output to disk under SOOTHE_HOME/data/threads/{thread_id}/working_memory/ when longer than this",
    )


class GoalContextConfig(BaseModel):
    """Goal context injection configuration (RFC-217).

    Args:
        plan_limit: Number of previous goals to inject into Plan phase.
        execute_limit: Number of previous goals for Execute briefing on thread switch.
        enabled: Enable goal context injection.
    """

    plan_limit: int = Field(
        default=10, ge=1, le=50, description="Number of previous goals for Plan phase"
    )
    execute_limit: int = Field(
        default=10, ge=1, le=50, description="Number of previous goals for Execute briefing"
    )
    enabled: bool = Field(default=True, description="Enable goal context injection")


class PlanPromptLedgerConfig(BaseModel):
    """Caps for RFC-214 ledger copies sent to plan-assess / plan-generate (IG-380).

    All limits use 0 to mean unlimited (preserve legacy behavior: full ledger, no copies).
    When any limit is positive, the plan phase uses deep-copied, trimmed messages only.
    """

    plan_ledger_max_messages: int = Field(
        default=40,
        ge=0,
        le=500,
        description="Max ledger messages tail for plan prompts (0 = unlimited)",
    )
    plan_ledger_max_total_chars: int = Field(
        default=24000,
        ge=0,
        le=2_000_000,
        description=(
            "Max total extracted characters for plan ledger projection "
            "(0 = unlimited; IG-671 default 24000)"
        ),
    )
    plan_ledger_max_message_chars: int = Field(
        default=3000,
        ge=0,
        le=500_000,
        description=(
            "Max extracted characters per ledger message in plan projection "
            "(0 = unlimited; IG-671 default 3000)"
        ),
    )


class PlanEvaluatePromptConfig(BaseModel):
    """Evaluate-station prompt assembly knobs (inventory + assess; IG-557 / IG-672)."""

    ledger_max_messages: int = Field(
        default=24,
        ge=0,
        le=500,
        description="Max execute AI ledger rows for evaluate projection (0 = unlimited)",
    )
    execute_ai_max_chars: int = Field(
        default=2048,
        ge=0,
        le=50_000,
        description=(
            "Per execute AI row char cap in evaluate inventory/assess projection "
            "(0 = unlimited). Oversized rows keep head+tail so deliverable tables "
            "and closing notes survive."
        ),
    )
    keep_head_tail_execute_ai: bool = Field(
        default=True,
        description="Preserve first-wave + recent execute AI when tail-truncating",
    )
    omit_prior_progress_hint: bool = Field(
        default=True,
        description="Omit derived_progress_hint from evaluate PRIOR PROGRESS block",
    )
    include_plan_coverage: bool = Field(
        default=True,
        description="Inject deterministic PLAN COVERAGE block when a plan exists",
    )


class ExecutePromptLedgerConfig(BaseModel):
    """Caps for execute-step CoreAgent ledger projection (IG-542)."""

    cross_goal_completion_tail: int = Field(
        default=3,
        ge=0,
        le=10,
        description="Prior-goal completion units at goal boundary (0 = disable Slice A)",
    )
    predecessor_max_messages: int = Field(
        default=96,
        ge=0,
        le=500,
        description="Max predecessor execute_step ledger rows for Slice B (0 = unlimited)",
    )
    execute_ai_ledger_max_tokens: int = Field(
        default=65536,
        ge=0,
        le=100_000,
        description=(
            "Max tokens for execute_step AI rows at ledger write time via langchain "
            "trim_messages (0 = store full text)"
        ),
    )


class LoopCheckpointConfig(BaseModel):
    """Loop checkpoint and recovery configuration (RFC-203, IG-670).

    Args:
        progressive: Save checkpoint after each step/goal completion.
        auto_resume_on_start: Auto-resume incomplete solo loops on daemon start.
        auto_resume_max_loops: Max loops to auto-resume concurrently at startup.
        auto_resume_max_age_hours: Skip incomplete loops older than this many hours.
        auto_resume_clarifications: How to treat clarification-parked loops
            (``skip`` = leave parked for a human; ``reannounce`` = resume graph
            so clarification is re-emitted without auto-answering).
    """

    progressive: bool = True
    auto_resume_on_start: bool = False
    auto_resume_max_loops: int = Field(default=4, ge=1, le=64)
    auto_resume_max_age_hours: float = Field(default=24.0, ge=0.0, le=720.0)
    auto_resume_clarifications: Literal["skip", "reannounce"] = "skip"


class LoopCheckpointAsyncConfig(BaseModel):
    """Async checkpoint write configuration (RFC-803 Phase 6, IG-550).

    Checkpoint writes are always coalesced and non-blocking. PostgreSQL uses the
    process-scoped persistence writer; SQLite uses a per-manager flush worker.

    Args:
        flush_interval: Periodic forced write interval (seconds).
        close_timeout_seconds: Max seconds to wait for persist on manager close.
        durable_flush_timeout: Max seconds for goal-boundary durable flush.
    """

    flush_interval: float = Field(
        default=5.0,
        ge=1.0,
        le=60.0,
        description="Periodic forced write interval (seconds). Bounds crash data loss window.",
    )
    close_timeout_seconds: float = Field(
        default=30.0,
        ge=1.0,
        le=300.0,
        description="Bounded wait for checkpoint flush during StrangeLoopStateManager.close()",
    )
    durable_flush_timeout: float = Field(
        default=10.0,
        ge=1.0,
        le=120.0,
        description="Bounded wait for durable goal-boundary checkpoint flush",
    )


class LoopConcurrencyConfig(BaseModel):
    """Loop execution concurrency and scheduling controls.

    Args:
        max_parallel_goals: Maximum goals running simultaneously (autonomous mode).
        max_parallel_steps: Maximum plan steps running concurrently per execute batch.
        max_parallel_subagents: Maximum subagents running simultaneously.
        global_max_llm_calls: Cross-level circuit breaker for concurrent LLM calls.
        step_parallelism: Scheduling strategy for plan steps (sequential/dependency/max).
        max_parallel_tools: Maximum concurrent tool calls per thread.
    """

    max_parallel_goals: int = Field(
        default=4, ge=0, description="Maximum parallel goals (0=unlimited)"
    )
    max_parallel_steps: int = Field(
        default=4,
        ge=0,
        description="Max concurrent plan steps per batch; 0=unlimited; multiple batches per execute",
    )
    max_parallel_subagents: int = Field(
        default=4, ge=0, description="Maximum parallel subagents (0=unlimited)"
    )
    global_max_llm_calls: int = Field(
        default=10, ge=0, description="Global LLM call cap (0=unlimited)"
    )
    step_parallelism: Literal["sequential", "dependency", "max"] = Field(
        default="dependency", description="Step scheduling strategy"
    )
    max_parallel_tools: int = Field(
        default=99, ge=0, description="Maximum concurrent tool calls per thread (0=unlimited)"
    )
    checkpoint: LoopCheckpointAsyncConfig = Field(
        default_factory=LoopCheckpointAsyncConfig,
        description="Async checkpoint write configuration (RFC-803 Phase 6)",
    )


class OutputStreamingConfig(BaseModel):
    """Configuration for output streaming behavior (RFC-614).

    Controls how goal_completion synthesis and other assistant outputs are
    delivered from daemon to client.

    Three delivery modes (IG-441):

    - ``batch``: Buffer the entire goal_completion synthesis. Emit a single
      ``AIMessageChunk`` with ``chunk_position="last"`` when the agent loop
      completes. Pure single-shot delivery; the client sees nothing during the
      synthesis. Intended for headless automation that does not need real-time
      progress.

    - ``adaptive`` (default, two-phase):

      1. *Streaming phase* — while cumulative goal_completion chars are below
         ``adaptive_threshold_chars`` every incoming chunk is forwarded
         individually, giving the lowest possible first-token latency.
      2. *Chunked-streaming phase* — once the threshold is crossed the
         coalescer buffers incoming text and flushes intermediate
         ``AIMessageChunk`` frames whenever the buffer reaches
         ``adaptive_block_chars`` characters or ``adaptive_block_interval_ms``
         milliseconds have elapsed since the last block flush, whichever
         happens first. The final block carries ``chunk_position="last"``.
         This keeps the user informed of progress on long outputs while
         reducing wire frame count vs. raw passthrough.

    - ``streaming``: Raw passthrough at the LLM's native generation speed.
      Every goal_completion chunk is forwarded immediately with no buffering.
      Highest wire-frame count and lowest latency — intended for local /
      low-latency clients that want token-level fidelity.

    If ``file_output_threshold_chars`` is set (> 0) goal_completion reverts to
    pure-batch buffering regardless of mode so the final file_output decision
    sees the complete text.

    Args:
        mode: Delivery mode (``batch`` | ``adaptive`` | ``streaming``).
        streaming_interval_ms: Daemon WebSocket batching interval (milliseconds).
        tui_flush_interval_ms: TUI rendering flush interval (milliseconds).
        tui_first_flush_interval_ms: TUI flush interval for the first tokens (milliseconds).
        adaptive_threshold_chars: Cumulative chars at which adaptive switches
            from streaming phase to chunked-streaming phase.
        adaptive_block_chars: Chars per block in chunked-streaming phase.
        adaptive_block_interval_ms: Max ms between block flushes in
            chunked-streaming phase.
        file_output_threshold_chars: Threshold to write goal_completion to file (0 = never).
        file_output_preview_chars: Preview chars in TUI when output saved to file.
        file_output_dir: Directory for output files (default: current workspace root/.soothe/output).
        message_coalesce_enabled: When true, coalesce plain assistant text chunks per namespace.
        tool_batch_enabled: Debounce tool invocation wire into ``tool_call_updates_batch``.
        tool_batch_interval_ms: Max wait before flushing a debounced tool batch (milliseconds).
        suppress_redundant_stream_tool_updates: Drop ``soothe.stream.tool_call.update`` when batched.
        skip_redundant_tool_message_wire: Drop empty tool-result wire frames (off by default).
    """

    mode: Literal["batch", "adaptive", "streaming"] = Field(
        default="adaptive",
        description=(
            "Delivery mode. batch: buffer entire goal_completion and emit one frame "
            "at strange_loop.completed. adaptive: stream until adaptive_threshold_chars, "
            "then emit block-sized AIMessageChunk frames. streaming: raw passthrough "
            "at the LLM's native generation rate (no buffering)."
        ),
    )
    streaming_interval_ms: int = Field(
        default=100,
        ge=50,
        le=1000,
        description=(
            "Daemon WebSocket batching interval (milliseconds). "
            "IG-534 Phase 3: 100ms default for TUI clients (faster perceived response); "
            "use 300 for headless consumers to reduce network overhead."
        ),
    )
    tui_flush_interval_ms: int = Field(
        default=200,
        ge=50,
        le=1000,
        description="TUI markdown stream flush interval (milliseconds)",
    )
    tui_first_flush_interval_ms: int = Field(
        default=50,
        ge=10,
        le=500,
        description=(
            "TUI flush interval for the first tokens of a reply (milliseconds). "
            "Gives fast perceived first-token, then switches to tui_flush_interval_ms "
            "after ~500 chars."
        ),
    )
    adaptive_threshold_chars: int = Field(
        default=500,
        ge=100,
        le=10000,
        description=(
            "Cumulative chars at which adaptive switches from per-chunk streaming "
            "to chunked-streaming (block-buffered) goal_completion delivery"
        ),
    )
    adaptive_block_chars: int = Field(
        default=500,
        ge=128,
        le=16384,
        description=(
            "Chars per intermediate block in adaptive chunked-streaming phase "
            "(IG-441). Higher values reduce frame count; lower values smooth UX. "
            "Default 500 aligns with adaptive_threshold_chars so the first block "
            "after cutover is the same size as one streamed chunk window."
        ),
    )
    adaptive_block_interval_ms: int = Field(
        default=250,
        ge=50,
        le=2000,
        description=(
            "Max milliseconds between intermediate block flushes in adaptive "
            "chunked-streaming phase (IG-441). Time-based fallback so slow streams "
            "still show progress before adaptive_block_chars accumulates."
        ),
    )
    file_output_threshold_chars: int = Field(
        default=0,
        ge=0,
        le=100000,
        description="Chars threshold to write goal_completion to file",
    )
    file_output_preview_chars: int = Field(
        default=500,
        ge=0,
        le=5000,
        description="Preview chars when output saved to file",
    )
    file_output_dir: str | None = Field(
        default=None,
        description="Directory for output files (default: current workspace root/.soothe/output)",
    )
    message_coalesce_enabled: bool = Field(
        default=True,
        description="Coalesce plain assistant AIMessageChunk text before WebSocket broadcast",
    )
    tool_batch_enabled: bool = Field(
        default=True,
        description="Debounce tool invocation metadata into tool_call_updates_batch events",
    )
    tool_batch_interval_ms: int = Field(
        default=500,
        ge=50,
        le=1000,
        description="Debounce window for tool_call_updates_batch (milliseconds)",
    )
    suppress_redundant_stream_tool_updates: bool = Field(
        default=True,
        description="Suppress soothe.stream.tool_call.update when covered by a pending batch",
    )
    skip_redundant_tool_message_wire: bool = Field(
        default=True,
        description="Suppress empty ToolMessage wire frames (keep false for full wire debug)",
    )


class ContextEngineConfig(BaseModel):
    """Context Engine integration for StrangeLoop (RFC-624 Phase 4).

    ContextEngine is always active and replaces PlanManager, LoopWorkingMemory,
    and GoalContextManager as the internal state backend. The existing prompt
    pipeline, executor, and LangGraph topology remain unchanged.

    The persistence backend follows ``persistence.default_backend`` — no
    separate ``persistence_backend`` knob is needed. When the global backend
    is ``postgresql``, CE uses PgsqlContextPersistence with the same DSN.
    When ``sqlite``, CE uses SqliteContextPersistence (default). If
    ``postgresql`` is configured but ``psycopg`` is unavailable, CE
    falls back to SQLite automatically.

    Args:
        projection_max_goals: Max goals in projection output.
        projection_max_steps_per_goal: Max steps per goal in projection output.
        projection_max_ledger_chars: Max total chars for ledger summary in projection.
        projection_max_ledger_messages: Max messages in projection ledger output.
        projection_max_lineage_chars: Max chars for lineage context in projection.
        projection_max_project_instructions_chars: Max chars for project instructions.
    """

    projection_max_goals: int = Field(
        default=5,
        ge=1,
        le=50,
        description="Max goals in CE projection output",
    )
    projection_max_steps_per_goal: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Max steps per goal in CE projection output",
    )
    projection_max_ledger_chars: int = Field(
        default=4000,
        ge=0,
        le=500_000,
        description="Max total chars for ledger summary in CE projection (0 = unlimited)",
    )
    projection_max_ledger_messages: int = Field(
        default=20,
        ge=0,
        le=500,
        description="Max messages in CE projection ledger output (0 = unlimited)",
    )
    projection_max_lineage_chars: int = Field(
        default=2000,
        ge=0,
        le=100_000,
        description="Max chars for lineage context in CE projection (0 = unlimited)",
    )
    projection_max_project_instructions_chars: int = Field(
        default=8000,
        ge=0,
        le=500_000,
        description="Max chars for project instructions in CE projection (0 = unlimited)",
    )

    def to_projection_config(self) -> ProjectionConfig:
        """Build a ``ProjectionConfig`` from these settings."""
        return ProjectionConfig(
            max_goals=self.projection_max_goals,
            max_steps_per_goal=self.projection_max_steps_per_goal,
            max_ledger_chars=self.projection_max_ledger_chars,
            max_ledger_messages=self.projection_max_ledger_messages,
            max_lineage_chars=self.projection_max_lineage_chars,
            max_project_instructions_chars=self.projection_max_project_instructions_chars,
        )


class ProjectionConfig(BaseModel):
    """Limits for bounded CE projection (local nano stub)."""

    max_goals: int = 5
    max_steps_per_goal: int = 10
    max_ledger_chars: int = 4000
    max_ledger_messages: int = 20
    max_lineage_chars: int = 2000
    max_project_instructions_chars: int = 8000


class CompletionRulesConfig(BaseModel):
    """Declarative completion heuristics (RFC-624)."""

    dag_dependency_threshold: int = Field(default=3, ge=1)
    low_success_rate_threshold: float = Field(default=0.6, ge=0.0, le=1.0)
    simple_ledger_direct_max_steps: int = Field(default=1, ge=1)
    ledger_direct_max_tool_calls: int = Field(
        default=50,
        ge=0,
        description=(
            "Max tool calls in the last execute wave for ledger_direct eligibility "
            "(0 = no cap; structural gate only)"
        ),
    )


class ScenarioRulesConfig(BaseModel):
    """Declarative scenario classifier fast-path rules."""

    skip_llm_when_single_step: bool = True
    skip_llm_when_all_failed: bool = True
    high_step_count_threshold: int = Field(default=4, ge=2)
    low_evidence_volume_threshold: int = Field(default=2000, ge=0)


class PlanSafetyRulesConfig(BaseModel):
    """Declarative plan step safety rules."""

    banned_step_patterns: list[str] = Field(
        default_factory=lambda: [
            r"^(wrap up|conclude|terminate|stop|halt|cease|end process|close|exit|quit|"
            r"finish up|complete process|final step|last step|the end)$"
        ]
    )
    simple_evidence_min_chars: int = Field(default=200, ge=0)
    no_tool_evidence_retry_limit: int = Field(
        default=2,
        ge=1,
        description=(
            "Consecutive successful verify-only steps with zero tool calls before "
            "plan_assess stops replanning and routes to goal completion."
        ),
    )


class StrangeLoopRulesConfig(BaseModel):
    """Declarative StrangeLoop routing and completion rules."""

    completion: CompletionRulesConfig = Field(default_factory=CompletionRulesConfig)
    scenario: ScenarioRulesConfig = Field(default_factory=ScenarioRulesConfig)
    plan_safety: PlanSafetyRulesConfig = Field(default_factory=PlanSafetyRulesConfig)


class StrangeLoopConfig(BaseModel):
    """Configuration for agent loop execution mode (RFC-201, IG-407: unified config).

    Unified configuration consolidating agentic behavior fields and loop execution controls.
    Behavior fields are placed directly under loop.* for easy access.

    Args:
        enabled: Enable agent loop mode.
        max_iterations: Maximum agent loop iterations.
        max_subagent_tasks_per_wave: Cap ``task`` tool completions per Act wave (0 = unlimited).
        general_purpose_subagent: When false (default), hide/block deepagents ``general-purpose``
            on CoreAgent ``task`` even if nano ``agent.runtime.general_purpose_subagent`` is true.
        max_tool_calls_per_step: Cap tool results consumed per execute step from the Act stream (0 = unlimited).
        dispatch_idle_seconds: Deadlock detector — max seconds of stream inactivity when no
            root-level tool is pending. Nested subgraph messages do not clear parent activity.
        dispatch_tool_timeout_seconds: Optional wall-clock cap for a root tool wave (dispatch
            until all pending ToolMessages). 0 disables (use ``agent.middleware.tool_timeout``).
        execute_action_retry_max: Extra Execute passes when the step deliverable gate fails (0 = disabled).
        execute_min_answer_chars: Minimum final assistant text length for deliverable satisfaction.
        execute_deliverable_assess: Fast LLM assess mode when structural deliverable checks are inconclusive.
        strange_loop_output_contract_enabled: Append anti-repetition instructions to sequential Act prompts.
        final_response: Whether to always synthesize a final CoreAgent report, reuse last Execute
            assistant text when structurally eligible, or use auto heuristics (IG-199, IG-580).
        working_memory: Working memory / spill configuration (RFC-203).
        goal_context: Goal context injection for Plan/Execute phases (RFC-217).
        report_output: Goal report display and synthesis limits.
        output_streaming: Enable streaming mode for all AI outputs (true=stream, false=batch).
        goal_completion_mode: How planner completion (`require_goal_completion`) combines with
            execution heuristics when the goal is assessed as done (IG-298).
        plan_prompt_ledger: Ledger projection caps for Plan-phase LLM prompts (IG-380).
        checkpoint: Progressive checkpoint persistence and startup resume (RFC-203).
        concurrency: Parallelism caps and step scheduling strategy.
        plan_evaluate_assess_model_role: Router role for evaluate assess LLM calls (default ``fast``).
        plan_evaluate_gap_model_role: Router role for evaluate inventory LLM calls (default ``fast``).
        plan_generate_model_role: Router role for plan-generate LLM calls (default ``think``).
        plan_generate_model_role_simple: Role for simple/lightweight generate (default ``fast``).
        plan_generate_model_role_near_gap: Role for near-gap generate (default ``fast``).
        plan_structural_keep_enabled: Skip evaluate/generate when in-flight plan is healthy.
        plan_structural_keep_max_streak: Force full evaluate after N consecutive structural keeps.
        plan_evaluate_gap_mode: Inventory strategy inside evaluate (``sequential`` | ``parallel``).
        plan_evaluate_gap_max_concurrency: Max parallel inventory legs.
        plan_evaluate_gap_min_facets: Parallel only when seeded facets >= this.
        plan_evaluate_gap_wall_clock_seconds: Soft wall budget for inventory phase.
        plan_evaluate_gap_leg_timeout_seconds: Soft timeout per parallel inventory leg.
        plan_evaluate_prompt: Evaluate projection/envelope knobs (inventory + assess).
        goal_synthesis_model_role: Router role for goal-completion synthesis streaming (default ``default``).

    Note: Performance optimizations (intent/routing classification pipeline, optimize_system_prompts,
    parallel_pre_stream) are always enabled by design and not configurable.
    """

    enabled: bool = Field(
        default=True,
        description="Enable agent loop mode",
    )

    max_iterations: int = Field(
        default=DEFAULT_MAX_ITERATIONS,
        description="Maximum agent loop iterations",
        ge=1,
        le=500,
    )

    max_plan_steps_per_wave: int = Field(
        default=10,
        description="Maximum plan-generate steps emitted per planning wave (all iterations)",
        ge=1,
        le=50,
    )

    max_subagent_tasks_per_wave: int = Field(
        default=4,
        description="Max completed subagent ``task`` tool results per Execute wave (0 = no limit)",
        ge=0,
        le=20,
    )

    general_purpose_subagent: bool = Field(
        default=False,
        description=(
            "When true, allow CoreAgent task→general-purpose when nano runtime also enables it. "
            "When false (default), general-purpose is hidden and blocked for StrangeLoop hosts."
        ),
    )

    max_tool_calls_per_step: int = Field(
        default=DEFAULT_MAX_TOOL_CALLS_PER_STEP,
        description=(
            "Max tool results consumed per execute step from the CoreAgent Act stream "
            "(0 = unlimited)"
        ),
        ge=0,
        le=10_000,
    )

    @model_validator(mode="before")
    @classmethod
    def _reject_nano_middleware_and_legacy_keys(cls, data: Any) -> Any:
        """Keep nano middleware knobs out of ``agent.loop`` (IG-631 / IG-681)."""
        if not isinstance(data, dict):
            return data
        banned_middleware = (
            "tool_output",
            "tool_call_limit",
            "tool_retry",
            "tool_timeout",
            "llm_rate_limit",
        )
        found_mw = [key for key in banned_middleware if key in data]
        if found_mw:
            joined = ", ".join(found_mw)
            raise ValueError(f"agent.loop keys moved to nano.yml agent.middleware: {joined}")
        if "dispatch_timeout_seconds" in data:
            raise ValueError(
                "agent.loop.dispatch_timeout_seconds removed; use "
                "dispatch_idle_seconds and dispatch_tool_timeout_seconds"
            )
        return data

    dispatch_idle_seconds: float = Field(
        default=300.0,
        description=(
            "Deadlock detector: max seconds of stream inactivity when no root-level "
            "tool is pending. Resets on every real chunk (including nested subgraph "
            "progress). Idle fires only after the last root ToolMessage until the "
            "next LLM hop — the hang class from loop 9e20. Parallel tool waves keep "
            "idle suppressed until every pending tool_call id completes. Default "
            "300s (5 min). Set to 0 to disable (not recommended; the idle sentinel "
            "cap provides a 1-hour secondary safety net when no tools are pending)."
        ),
        ge=0,
        le=86_400,
    )

    dispatch_tool_timeout_seconds: float = Field(
        default=0.0,
        description=(
            "Optional wall-clock cap for a root tool wave (from first pending "
            "dispatch until the pending set empties). 0 disables this cap and "
            "relies on agent.middleware.tool_timeout per-tool middleware instead. "
            "Set > 0 only when you need a graph-stream-level bound in addition to "
            "middleware. When the cap fires, the step fails with "
            "DispatchTimeoutError(reason='tool_wall_clock')."
        ),
        ge=0,
        le=86_400,
    )

    execute_action_retry_max: int = Field(
        default=1,
        description=(
            "Extra Execute passes when the step deliverable gate reports incomplete (0 = disabled)"
        ),
        ge=0,
        le=5,
    )

    execute_min_answer_chars: int = Field(
        default=20,
        description="Minimum final assistant text length for execute deliverable satisfaction",
        ge=0,
        le=500,
    )

    execute_deliverable_assess: ExecuteDeliverableAssessMode = Field(
        default="auto",
        description=(
            "Fast LLM step-deliverable assess: auto when structural checks are inconclusive, "
            "always on incomplete, never (structural only)"
        ),
    )

    step_completion_report_max_words: int = Field(
        default=50,
        description="Target word limit for execute-step completion cognition summaries (LLM prompt only)",
        ge=5,
        le=100,
    )

    strange_loop_output_contract_enabled: bool = Field(
        default=True,
        description="Instruct CoreAgent not to paste full tool outputs again during StrangeLoop Execute phase",
    )

    final_response: AgenticFinalResponseMode = Field(
        default="auto",
        description=(
            "On goal completion: auto uses structural heuristics to choose ledger direct vs "
            "a final CoreAgent report; always_synthesize always runs the report. "
            "Legacy alias: adaptive → auto."
        ),
    )

    @field_validator("final_response", mode="before")
    @classmethod
    def _normalize_final_response(cls, value: Any) -> Any:
        return normalize_agentic_final_response_mode(value)

    goal_completion_mode: AgenticGoalCompletionMode = Field(
        default="llm_only",
        description=(
            "When the planner marks the goal done: llm_only trusts StatusAssessment only; "
            "heuristic_only uses execution heuristics only; hybrid uses LLM first with heuristic fallback"
        ),
    )

    step_brief_hydration_enabled: bool = Field(
        default=True,
        description=(
            "When true, dependent steps with vague full_description are hydrated "
            "between execute waves using predecessor evidence (LLM when available)."
        ),
    )

    prior_conversation_limit: int = Field(
        default=10,
        description=(
            "Maximum prior messages to format for Plan prompts when Execute phase uses isolated threads"
        ),
        ge=1,
        le=50,
    )

    context_window_limit: int = Field(
        default=200_000,
        description="Model context window token limit for percentage calculation",
        ge=10_000,
        le=1_000_000,
    )

    # RFC-224: Automatic context window management
    context_overflow_threshold_pct: float = Field(
        default=0.80,
        ge=0.5,
        le=0.95,
        description=(
            "Percentage of context_window_limit at which automatic "
            "in-place compaction is triggered."
        ),
    )
    """RFC-224: Trigger threshold for context compaction (0.80 = 80%)."""

    context_compaction_target_pct: float = Field(
        default=0.60,
        ge=0.30,
        le=0.70,
        description=(
            "Target context percentage after compaction. "
            "Provides buffer for subsequent execute waves."
        ),
    )
    """RFC-224: Compaction target (0.60 = 60% of context_limit)."""

    step_context_check_enabled: bool = Field(
        default=False,
        description=(
            "Check context on step threads (loop_id__step_{step_id}). "
            "Usually unnecessary; step threads are short-lived."
        ),
    )
    """RFC-224: Enable step thread context checking."""

    output_streaming: OutputStreamingConfig = Field(
        default_factory=OutputStreamingConfig,
        description="Output streaming configuration",
    )

    loop_orchestrator_evidence_validate: bool = Field(
        default=True,
        description=(
            "Enable plan evidence validation node in the loop orchestrator (RFC-220; currently a no-op)."
        ),
    )

    working_memory: LoopWorkingMemoryConfig = Field(
        default_factory=LoopWorkingMemoryConfig,
        description="Loop working memory",
    )

    goal_context: GoalContextConfig = Field(
        default_factory=GoalContextConfig,
        description="Goal context injection for Plan/Execute phases",
    )

    report_output: ReportOutputConfig = Field(
        default_factory=ReportOutputConfig,
        description="Terminal/file behavior for synthesized goal reports",
    )

    plan_prompt_ledger: PlanPromptLedgerConfig = Field(
        default_factory=PlanPromptLedgerConfig,
        description="Plan-phase ledger projection limits; zeros = full ledger passthrough",
    )

    plan_evaluate_prompt: PlanEvaluatePromptConfig = Field(
        default_factory=PlanEvaluatePromptConfig,
        description="Evaluate inventory/assess projection and envelope settings (IG-672).",
    )

    execute_prompt_ledger: ExecutePromptLedgerConfig = Field(
        default_factory=ExecutePromptLedgerConfig,
        description="Execute-step CoreAgent ledger projection (IG-542)",
    )

    checkpoint: LoopCheckpointConfig = Field(
        default_factory=LoopCheckpointConfig,
        description="Progressive checkpoint persistence and startup resume",
    )

    concurrency: LoopConcurrencyConfig = Field(
        default_factory=LoopConcurrencyConfig,
        description="Parallelism caps and step scheduling strategy",
    )

    plan_evaluate_assess_model_role: ModelRole = Field(
        default="fast",
        description=(
            "Router model role for evaluate assess structured LLM calls "
            "(status assessment and continuation routing; IG-672)."
        ),
    )

    plan_evaluate_gap_model_role: ModelRole = Field(
        default="fast",
        description=(
            "Router model role for evaluate inventory (gap) structured LLM calls "
            "(coverage map before assess; IG-672)."
        ),
    )

    plan_generate_model_role: ModelRole = Field(
        default="think",
        description="Router model role for plan-generate structured LLM calls.",
    )

    plan_generate_model_role_simple: ModelRole = Field(
        default="fast",
        description=(
            "Router model role for simple/lightweight plan-generate and approved-plan "
            "implement handoff (IG-671)."
        ),
    )

    plan_generate_model_role_near_gap: ModelRole = Field(
        default="fast",
        description=(
            "Router model role for plan-generate when gap distance is near/at_goal "
            "and the last execute wave succeeded (IG-671)."
        ),
    )

    plan_structural_keep_enabled: bool = Field(
        default=True,
        description=(
            "When true, mid-loop iterations with a healthy in-flight plan skip "
            "evaluate/generate and reuse remaining steps (IG-671)."
        ),
    )

    plan_structural_keep_max_streak: int = Field(
        default=3,
        ge=0,
        le=50,
        description=(
            "Force a full evaluate path after this many consecutive structural "
            "keeps (0 = no streak cap; IG-671)."
        ),
    )

    plan_evaluate_gap_mode: Literal["sequential", "parallel"] = Field(
        default="sequential",
        description=(
            "Inventory strategy inside the evaluate station: one PlanGapAnalysis "
            "call (sequential) or per-facet fan-out (parallel; IG-672)."
        ),
    )

    plan_evaluate_gap_max_concurrency: int = Field(
        default=4,
        ge=1,
        le=8,
        description="Max concurrent inventory legs when plan_evaluate_gap_mode=parallel.",
    )

    plan_evaluate_gap_min_facets: int = Field(
        default=2,
        ge=2,
        le=8,
        description=(
            "Use parallel inventory only when seeded facet count is at least this; "
            "otherwise fall back to sequential (IG-672)."
        ),
    )

    plan_evaluate_gap_wall_clock_seconds: float = Field(
        default=90.0,
        ge=5.0,
        le=300.0,
        description="Soft wall-clock budget for the evaluate inventory phase (IG-672).",
    )

    plan_evaluate_gap_leg_timeout_seconds: float = Field(
        default=45.0,
        ge=5.0,
        le=180.0,
        description="Soft timeout per parallel inventory leg (IG-672).",
    )

    goal_synthesis_model_role: ModelRole = Field(
        default="default",
        description="Router model role for goal-completion synthesis streaming.",
    )

    context_engine: ContextEngineConfig = Field(
        default_factory=lambda: ContextEngineConfig(),
        description="Context Engine integration",
    )

    rules: StrangeLoopRulesConfig = Field(
        default_factory=StrangeLoopRulesConfig,
        description="Declarative completion, scenario, and plan-safety thresholds",
    )


class ClarificationConfig(BaseModel):
    """RFC-622: configuration for the clarification relay.

    Only structured ``ask_user`` LangGraph interrupts are detected. Plain-text
    questions in assistant messages are NOT treated as clarifications —
    callers that want a clarification must emit an ``ask_user`` interrupt.
    """

    auto_policy: Literal["veritas"] = "veritas"
    """Auto-mode policy. Only ``veritas`` is supported today."""

    auto_min_confidence: float = Field(default=0.4, ge=0.0, le=1.0)
    """Below this confidence, ``AutoClarificationPolicy`` defers rather than answers."""

    max_defer_age_hours: int = Field(default=168, ge=1)
    """Autopilot scrubs goals stuck in ``awaiting_clarification`` past this age."""

    default_mode: Literal["auto", "manual"] = "auto"
    """Mode used when a request payload does not specify ``clarification_mode``.

    ``auto`` routes clarifications through the veritas auto-answerer.
    ``manual`` routes them through the TUI relay (interactive policy).
    Autopilot always forces ``auto`` regardless of this setting.
    """

    force_manual_origins: list[
        Literal[
            "execute",
            "generate_plan",
            "evaluate",
            "planner_subagent_review",
            # dual-read persisted / pre-IG-672 origin strings
            "plan_generate",
            "plan_assess",
            "plan_gap_analysis",
            "assess",
            "analyze_gaps",
        ]
    ] = Field(
        default_factory=lambda: list(DEFAULT_FORCE_MANUAL_ORIGINS),
        description=(
            "Clarification origins that never use veritas auto-answer, even when "
            "``default_mode`` / wire ``clarification_mode`` is ``auto``. "
            "With a human attached, the interactive TUI relay is used; otherwise "
            "the loop defers. Default is ``planner_subagent_review`` only — the "
            "planner *subagent* Approve/Reject/Comments gate (RFC-633). This is "
            "not StrangeLoop ``plan_generate`` / ``plan_assess``."
        ),
    )


class VeritasConfig(BaseModel):
    """RFC-622: configuration for the veritas auto-answerer subagent."""

    model_role: Literal["default", "fast", "think", "image", "ocr", "embedding"] = "think"
    """Which ``ModelRole`` to use for veritas calls; defaults to ``think``."""

    max_context_steps: int = Field(default=8, ge=0)
    """How many recent step outputs to include in the veritas user prompt."""


class SkillifyConfig(BaseModel):
    """Configuration for the daemon-shared Skillify semantic skill search service."""

    enabled: bool = False
    model_role: ModelRole = Field(
        default="embedding",
        description="Router model role used for Skillify embedding calls.",
    )
    warehouse_paths: list[str] = Field(
        default_factory=list,
        description=(
            "Extra SKILL.md roots for vector indexing. "
            "Defaults (~/.soothe/skills and ~/.agents/skills) are always prepended when absent."
        ),
    )
    index_collection: str = "soothe_skillify"
    index_interval_seconds: int = 300
    retrieval_top_k: int = 10


class CronConfig(BaseModel):
    """RFC-229: configuration for the cron service.

    Natural language scheduled job submission for Autopilot.

    Args:
        max_jobs: Maximum scheduled jobs per user.
        poll_interval: Seconds between due-job monitoring ticks.
        extraction_model: LLM role for natural language extraction.
        extraction_timeout: Timeout for LLM extraction calls.
        default_priority: Default job priority when not specified.
    """

    max_jobs: int = Field(default=100, ge=1, le=1000, description="Max scheduled jobs per user")
    poll_interval: int = Field(
        default=60, ge=10, le=3600, description="Monitoring tick interval in seconds"
    )
    extraction_model: Literal["default", "fast", "think", "image", "ocr", "embedding"] = Field(
        default="fast", description="LLM role for NL extraction"
    )
    extraction_timeout: int = Field(
        default=30, ge=5, le=120, description="Extraction timeout in seconds"
    )
    default_priority: int = Field(default=50, ge=1, le=100, description="Default job priority")
    timezone: str = Field(
        default="local",
        description=(
            "Timezone for cron/at wall-clock schedules: 'local' (system), 'UTC', "
            "or an IANA name such as 'Asia/Shanghai'"
        ),
    )


class AgentConfig(NanoAgentConfig):
    """Host agent configuration: nano CoreAgent fields plus orchestration overlays.

    Adds StrangeLoop/Autopilot/clarification/veritas and goal-completion behavior
    on top of nano ``AgentConfig`` (identity, protocols, runtime, middleware).
    """

    goal_completion_mode: AgenticGoalCompletionMode = Field(
        default="llm_only",
        description=(
            "When planner marks goal done: llm_only trusts StatusAssessment only; "
            "heuristic_only uses execution heuristics only; hybrid uses LLM first with fallback"
        ),
    )
    """How planner completion (require_goal_completion) combines with execution heuristics."""

    final_response: AgenticFinalResponseMode = Field(
        default="auto",
        description=(
            "On goal completion: auto uses structural heuristics to choose ledger direct vs "
            "a final CoreAgent report; always_synthesize always runs the report. "
            "Legacy alias: adaptive → auto."
        ),
    )
    """Whether to always synthesize a final CoreAgent report or use auto heuristics."""

    @field_validator("final_response", mode="before")
    @classmethod
    def _normalize_agent_final_response(cls, value: Any) -> Any:
        return normalize_agentic_final_response_mode(value)

    autopilot: AutopilotConfig = Field(
        default_factory=AutopilotConfig,
        description="Autopilot scheduling and self-running configuration",
    )
    """Controls 24/7 self-running behavior for both goal-level and daemon-level."""

    loop: StrangeLoopConfig = Field(
        default_factory=StrangeLoopConfig,
        description="StrangeLoop configuration (unified agentic+execution)",
    )
    """Internal tuning for the agent loop execution mode."""

    clarification: ClarificationConfig = Field(
        default_factory=ClarificationConfig,
        description="Clarification relay configuration",
    )
    """How CoreAgent clarification questions are routed (manual TUI vs auto/veritas)."""

    veritas: VeritasConfig = Field(
        default_factory=VeritasConfig,
        description="Veritas auto-answerer configuration",
    )
    """Settings for the intent-grounded clarification answerer."""
