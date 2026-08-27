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
    GeneralPurposeSubagentMode,
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
    DEFAULT_READ_ONLY_STREAK_LIMIT,
    GOAL_COMPLETION_REPORT_MAX_CHARS,
    GOAL_COMPLETION_REPORT_MAX_MESSAGES,
    GOAL_COMPLETION_REPORT_MAX_PER_MESSAGE_CHARS,
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


class AssistantIdentity(BaseModel):
    """Configurable assistant persona for identity blocks and intake replies.

    All fields default to the original hardcoded values so existing
    deployments see zero behavior change. Override via
    ``agent.assistant_identity`` in ``soothe.yml``.

    Args:
        creator: Attribution line rendered as "invented by {creator}".
        role_description: Short role clause rendered after the assistant name.
        vendor_denylist: Model/vendor names the assistant must never claim
            to be (rendered as a readable "never X, Y, Z" list).
    """

    creator: str = Field(
        default="Dr. Xiaming Chen",
        description="Attribution rendered as 'invented by {creator}' in identity blocks.",
    )
    role_description: str = Field(
        default="a helpful AI assistant",
        description="Short role clause rendered after the assistant name.",
    )
    vendor_denylist: list[str] = Field(
        default_factory=lambda: [
            "Claude",
            "ChatGPT",
            "Gemini",
            "Anthropic",
            "OpenAI",
            "Google",
        ],
        description="Model/vendor names the assistant must never claim to be.",
    )


class NotifyTargetConfig(BaseModel):
    """One delivery destination for job lifecycle notify (IG-713).

    ``kind`` selects the sink address space (``email``, ``feishu_chat_id``,
    ``feishu_open_id``, ``webhook_url``, …).
    """

    kind: str = Field(description="Address space / sink target kind")
    to_address: str = Field(description="Recipient address in that space")


class NotifyEventsConfig(BaseModel):
    """Which job-root lifecycle intents to emit.

    All events are enabled by default. To suppress a specific event,
    add its kind string (e.g. ``"sla.overdue"``) to the ``disabled``
    denylist. This replaces the previous four-boolean flag pattern,
    which was fully redundant — every flag defaulted to ``True``.
    """

    disabled: set[str] = Field(
        default_factory=set,
        description="Notify kinds to suppress (e.g. {'sla.overdue'}). "
        "All kinds are enabled by default.",
    )

    def is_enabled(self, kind: str) -> bool:
        """True when ``kind`` is not in the disabled denylist."""
        return kind not in self.disabled


class EmailNotifySinkConfig(BaseModel):
    """Outbound SMTP settings for ``EmailNotifySink`` (not IMAP chat).

    Sensitive fields (``smtp_username``, ``smtp_password``) accept a plain string
    or ``${ENV_VAR}`` (same dual rule as ``providers[].api_key``).
    """

    enabled: bool = False
    smtp_host: str = ""
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_username: str = Field(
        default="",
        description="SMTP username; plain string or ${ENV_VAR}",
    )
    smtp_password: str = Field(
        default="",
        description="SMTP password; plain string or ${ENV_VAR}",
    )
    smtp_use_tls: bool = True
    smtp_use_ssl: bool = False
    from_address: str = ""
    connect_timeout_seconds: float = Field(default=30.0, gt=0)
    max_retries: int = Field(default=2, ge=0, le=5)
    rate_limit_seconds: float = Field(
        default=5.0,
        ge=0.0,
        le=300.0,
        description="Minimum seconds between sends to the same recipient "
        "(per job+kind+address key); 0 disables rate-limiting",
    )
    targets: list[NotifyTargetConfig] = Field(default_factory=list)


class WebhookNotifySinkConfig(BaseModel):
    """HTTP POST URLs keyed by intent kind (``job_completed``, …)."""

    enabled: bool = False
    urls: dict[str, str | None] = Field(default_factory=dict)
    timeout_seconds: float = Field(default=15.0, gt=0)


class FeishuNotifySinkConfig(BaseModel):
    """Feishu/Lark IM notify sink (Phase 1 stub; live send follow-up).

    ``app_id`` and ``app_secret`` accept a plain string or ``${ENV_VAR}``.
    """

    enabled: bool = False
    app_id: str = Field(
        default="",
        description="Feishu app id; plain string or ${ENV_VAR}",
    )
    app_secret: str = Field(
        default="",
        description="Feishu app secret; plain string or ${ENV_VAR}",
    )
    targets: list[NotifyTargetConfig] = Field(default_factory=list)


class NotifySinksConfig(BaseModel):
    """Pluggable delivery sinks registered by the daemon NotifyDispatcher."""

    email: EmailNotifySinkConfig = Field(default_factory=EmailNotifySinkConfig)
    webhook: WebhookNotifySinkConfig = Field(default_factory=WebhookNotifySinkConfig)
    feishu: FeishuNotifySinkConfig = Field(default_factory=FeishuNotifySinkConfig)


class SlaConfig(BaseModel):
    """SLA monitoring thresholds for overdue gap items.

    When enabled, the AutopilotService watchdog tick scans active goals
    for unresolved gap items (from ``last_gap_analysis``) that have
    persisted past these thresholds. Each threshold crossing emits an
    ``sla.overdue`` notify intent at the corresponding severity tier.

    Set a threshold to ``0`` to disable that tier.
    """

    enabled: bool = False
    warning_seconds: int = Field(
        default=3600,
        ge=0,
        description="Seconds before first warning alert for unresolved gaps (default 1h).",
    )
    critical_seconds: int = Field(
        default=7200,
        ge=0,
        description="Seconds before critical (error) alert (default 2h). Must be >= warning_seconds.",
    )
    breach_seconds: int = Field(
        default=14400,
        ge=0,
        description="Seconds before final breach alert (default 4h). Must be >= critical_seconds.",
    )

    @model_validator(mode="after")
    def _validate_tier_order(self) -> SlaConfig:
        """Ensure critical >= warning and breach >= critical (when both > 0)."""
        w, c, b = self.warning_seconds, self.critical_seconds, self.breach_seconds
        if c > 0 and w > 0 and c < w:
            msg = f"critical_seconds ({c}) must be >= warning_seconds ({w})"
            raise ValueError(msg)
        if b > 0 and c > 0 and b < c:
            msg = f"breach_seconds ({b}) must be >= critical_seconds ({c})"
            raise ValueError(msg)
        return self


class AutopilotNotifyConfig(BaseModel):
    """Job lifecycle notify push (IG-713).

    Host router emits channel-agnostic intents; daemon sinks deliver
    (email, webhook, Feishu, …).
    """

    enabled: bool = False
    suspend_after_seconds: int = Field(
        default=2700,
        ge=60,
        description="Emit job.suspended_timeout after this many seconds suspended",
    )
    suspend_escalation_multiplier: float = Field(
        default=2.0,
        ge=1.0,
        le=10.0,
        description="Multiply suspend_after_seconds by this factor to escalate "
        "severity from warning to error (e.g. 2.0 means 2x threshold = error)",
    )
    dedup_ttl_seconds: int = Field(
        default=86400,
        ge=0,
        description="TTL for dedup keys in seconds; 0 means no expiry (keys persist "
        "indefinitely). Prevents stale dedup keys from suppressing legitimate "
        "re-notifications for long-running jobs.",
    )
    events: NotifyEventsConfig = Field(default_factory=NotifyEventsConfig)
    targets: list[NotifyTargetConfig] = Field(
        default_factory=list,
        description="Global default targets; sinks may add their own",
    )
    sinks: NotifySinksConfig = Field(default_factory=NotifySinksConfig)
    sla: SlaConfig = Field(
        default_factory=SlaConfig,
        description="SLA monitoring thresholds for overdue gap items.",
    )


class AutopilotConfig(BaseModel):
    """Autopilot scheduling and self-running configuration.

    Controls 24/7 self-running behavior for both goal-level and daemon-level.

    Args:
        enabled: Whether the AutopilotService scheduling loop is enabled.
            When False, the daemon constructs the service but does not start
            the scheduling loop. HTTP /autopilot/submit endpoints are available
            but goals won't be dispatched automatically. Default is True.
        max_retries: Maximum retries per goal on failure.
        max_total_goals: Maximum goals allowed (RFC-0007 §5.6).
        max_goal_depth: Maximum hierarchy depth (RFC-0007 §5.6).
        max_parallel_goals: Maximum goals running simultaneously.

        max_send_backs: Per-goal send-back budget for report-commit judgment.
        max_engine_recoveries: Max engine-driven recoveries per failed goal (deadlock backstop).
        checkpoint_interval: Iterations between periodic checkpoints.
        dreaming_enabled: Enter dreaming mode when all goals complete.
        monitor_model_role: Router role for AutopilotMonitor LLM reasoners (backoff,
            DAG verification). Defaults to ``think``.
        consensus_model_role: Router role for RFC-204 report-commit judgment.
            Defaults to ``think``; daemon uses ``create_chat_model`` with automatic
            fallback to ``default`` on instantiation failure.
        judge_allow_structural_dag_ops: Allowlisted structural judge ops
            (``spawn_goal`` / ``cancel_goal``). Empty = deny (LoopRail owns fan-out).
        intake_scope: Forced StrangeLoop intake scope for dispatched goals
            (``minimal``|``simple``|``complex``). Default ``None`` lets the
            loop run intake classification.
        verify_periodic_enabled: Master switch for periodic DAG health verification.
            When ``False`` (default), the monitor's background health tick is
            skipped entirely — no structural heuristics, no LLM. Event-driven
            verification (post-completion, backoff reasoning) still runs. The
            resource watchdog tick still runs on the same cadence.
        verify_interval: Background verification tick while non-terminal goals exist.
            Only used while ``verify_periodic_enabled`` is ``True``.
        verify_idle_interval: Tick when DAG empty/complete (``0`` reuses
            ``verify_interval``); health LLM is skipped while idle.
        verify_llm_enabled: Kill-switch for periodic health LLM. Only consulted
            while ``verify_periodic_enabled`` is ``True``.
        verify_llm_min_nonterminal: Min non-terminal goals before health LLM runs.
        verify_llm_debounce: Skip health LLM when DAG fingerprint unchanged.
        webhooks: Webhook URLs by event type (legacy; prefer ``notify.sinks.webhook``).
        notify: Job lifecycle multi-channel notify (IG-713).

    Note:
        StrangeLoop iteration budget is shared via ``agent.loop.max_iterations`` —
        Autopilot does not redefine it. Dynamic goal creation (decomposition,
        rails, directives) is always enabled.
    """

    # === Autopilot scheduling (daemon-level) ===
    enabled: bool = Field(
        default=True,
        description=(
            "Enable the AutopilotService scheduling loop. When True (default), the "
            "daemon starts the scheduling loop on startup for 24/7 autonomous "
            "operation. When False, the service is constructed but the scheduling "
            "loop does not start automatically; goals must be dispatched manually."
        ),
    )
    max_retries: int = 2
    max_total_goals: int = Field(default=99, ge=1, le=500)
    max_goal_depth: int = Field(default=5, ge=1, le=10)
    max_parallel_goals: int = Field(default=3, ge=1, le=32)
    # Cap on goals scheduled at once (``AutopilotService._schedule_via_worker_pool``).
    # Independent of ``max_loops`` (WorkerPool capacity). Autopilot owns goal
    # fan-out; StrangeLoop runners are single-goal workers.

    # === Goal GC (orphan reclamation) ===
    gc_enabled: bool = Field(
        default=True,
        description=(
            "Enable the periodic goal-GC scan. When True (default), the "
            "autopilot watchdog cancels non-terminal goals whose job root is "
            "already terminal (completed/cancelled/failed), so orphaned "
            "children cannot linger forever under a dead job."
        ),
    )
    gc_interval_seconds: int = Field(
        default=120,
        ge=10,
        le=3600,
        description=(
            "Minimum interval between goal-GC scans. The scan piggybacks on "
            "the monitor watchdog tick, so the effective cadence is the "
            "larger of this and verify_interval/verify_idle_interval."
        ),
    )

    # === Orchestration (from old autopilot) ===
    max_send_backs: int = Field(default=3, ge=1, le=10)
    max_engine_recoveries: int = Field(
        default=2,
        ge=0,
        le=10,
        description=(
            "Max engine-driven recoveries per failed goal (deadlock/health "
            "backstop). Separate from max_retries and max_send_backs."
        ),
    )
    checkpoint_interval: int = Field(default=10, ge=1, le=100)

    # === Dreaming ===
    dreaming_enabled: bool = True

    monitor_model_role: ModelRole = Field(
        default="think",
        description=(
            "Router model role for AutopilotMonitor LLM reasoners (backoff, DAG verification)."
        ),
    )

    consensus_model_role: ModelRole = Field(
        default="think",
        description="Router model role for RFC-204 report-commit judgment.",
    )
    judge_allow_structural_dag_ops: list[str] = Field(
        default_factory=list,
        description=(
            "Allowlisted structural dag_ops from report-commit judgment "
            "(spawn_goal, cancel_goal). Empty denies both — LoopRail owns "
            "structural fan-out."
        ),
    )

    default_rail: str | None = Field(
        default=None,
        description=(
            "Optional LoopRail id applied when submit omits rail_id and the "
            "workspace has no .soothe/rails/.rail-default. Empty/None = no rail."
        ),
    )

    rail_auto_pick: bool = Field(
        default=True,
        description=(
            "When True and submit omits rail_id, run structured LLM auto-pick "
            "over the merged LoopRail catalog before workspace/config defaults "
            "(RFC-231 §10 / IG-728)."
        ),
    )
    rail_auto_pick_min_confidence: float = Field(
        default=0.6,
        ge=0.0,
        le=1.0,
        description="Minimum confidence to accept an LLM rail pick or abstain.",
    )
    rail_auto_pick_model_role: ModelRole | None = Field(
        default=None,
        description=("Router model role for rail auto-pick. Null uses monitor_model_role."),
    )
    rail_auto_pick_timeout_s: float = Field(
        default=120.0,
        ge=1.0,
        le=300.0,
        description="Timeout seconds for the rail auto-pick LLM call.",
    )
    rail_auto_pick_deny: list[str] = Field(
        default_factory=list,
        description=(
            "Extra rail ids excluded from auto-pick candidates (still selectable "
            "via explicit rail_id / --rail). Rails with YAML ``auto_pick: false`` "
            "are omitted without listing them here."
        ),
    )
    rail_auto_pick_max_candidates: int = Field(
        default=32,
        ge=1,
        le=128,
        description=(
            "If filtered catalog size exceeds this, skip LLM and use deterministic fallbacks."
        ),
    )
    rail_auto_pick_skip_if_workspace_default: bool = Field(
        default=False,
        description=(
            "When True and workspace .rail-default exists, skip LLM and use "
            "the marker (operator-pinned workspace)."
        ),
    )
    rail_auto_pick_abstain_overrides_defaults: bool = Field(
        default=True,
        description=(
            "When True, high-confidence LLM abstain (rail_id null) skips "
            ".rail-default and default_rail."
        ),
    )
    rail_pause_auto_clarify: bool = Field(
        default=True,
        description=(
            "When True, LoopRail pause_for_user runs Veritas auto-clarification "
            "before CE-suspending the job root. PROCEED skips suspend and fires "
            "user_intervention; defer/deny keeps suspend. When False, always "
            "suspend (legacy operator gate)."
        ),
    )

    # Forced StrangeLoop intake scope for dispatched goals (RFC-630 / loop_input).
    # null (default) = intake classification; minimal|simple|complex skip the intake LLM.
    intake_scope: Literal["minimal", "simple", "complex"] | None = Field(
        default=None,
        description=(
            "Forced StrangeLoop intake scope for autopilot-dispatched goals "
            "(minimal|simple|complex). Null (default) lets the loop classify "
            "intake. Set simple/minimal/complex to skip the intake LLM."
        ),
    )

    # RFC-625 / IG-743: AutopilotMonitor verification cadence + LLM gating
    verify_periodic_enabled: bool = Field(
        default=False,
        description=(
            "Master switch for periodic DAG health verification. When False "
            "(default), the monitor's background health tick is skipped entirely "
            "— no structural heuristics, no LLM. Event-driven verification "
            "(post-completion, backoff reasoning) still runs; the resource "
            "watchdog tick still runs on the same cadence."
        ),
    )
    verify_interval: int = Field(
        default=120,
        ge=5,
        le=300,
        description=("Background verification tick when non-terminal goals exist (seconds)"),
    )
    """Seconds between DAG health ticks while work is open."""

    verify_idle_interval: int = Field(
        default=300,
        ge=0,
        le=3600,
        description=(
            "Verification tick when the DAG is empty or all goals are terminal. "
            "Zero reuses verify_interval. Health LLM is skipped while idle; "
            "structural deadlock merge and resource watchdogs still run."
        ),
    )
    verify_llm_enabled: bool = Field(
        default=True,
        description="When False, periodic DAG health never calls the monitor LLM.",
    )
    verify_llm_min_nonterminal: int = Field(
        default=1,
        ge=0,
        le=500,
        description=(
            "Minimum non-terminal goals required before the periodic health LLM runs. "
            "Below this threshold, only structural/heuristic health applies."
        ),
    )
    verify_llm_debounce: bool = Field(
        default=True,
        description=(
            "When True, skip the health LLM if the DAG fingerprint is unchanged "
            "since the last LLM health call."
        ),
    )

    dreaming_interval: int = Field(
        default=300,
        ge=60,
        le=3600,
        description="Time-based dreaming trigger interval (seconds)",
    )
    """Seconds between time-triggered dreaming mode entries."""

    webhooks: dict[str, str | None] = Field(default_factory=dict)
    notify: AutopilotNotifyConfig = Field(
        default_factory=AutopilotNotifyConfig,
        description="Job lifecycle multi-channel notify push (IG-713)",
    )

    # === Loop pool (RFC-222) ===
    # Distinct from `max_parallel_goals`: `max_loops` caps worker capacity in
    # the StrangeLoop pool (loops can be reused for parent→child lineage), while
    # `max_parallel_goals` caps the number of goals actively scheduled at once.
    # They can differ — e.g. max_loops=16 (pool) with max_parallel_goals=8 (schedule).
    max_loops: int = Field(
        default=16,
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

    # === Lifecycle reclamation ===
    # Tearing down a goal's runtime resources (spawned background processes,
    # slice worktrees) when the goal reaches a terminal state so jobs do not
    # leak grandchildren or stale worktrees. The drain runs in the runner
    # before the completion chunk is emitted; worktree recycle runs on merge
    # and on job completion.
    lifecycle_drain_grace_seconds: float = Field(
        default=2.0,
        ge=0.0,
        description=(
            "Grace period (SIGTERM → SIGKILL) when draining a goal's "
            "spawned background processes at completion/cancel."
        ),
    )
    lifecycle_worktree_recycle_enabled: bool = Field(
        default=True,
        description=(
            "When True (default), remove slice/job worktrees under "
            ".soothe/worktrees/ once their branch is merged or the job "
            "completes. Set False to retain worktrees for forensics."
        ),
    )

    # === Cancel escalation (RFC-222 H8 revised) ===
    # Goal cancel / deadline paths first request cooperative cancellation
    # (``runner.cancel()``), then poll ``runner.is_idle()``; if the worker
    # does not go idle within the retry budget, escalate to
    # ``runner.force_kill()`` so a worker blocked mid-LLM-call or in sync code
    # is guaranteed terminated rather than orphaned. Mirrors the query engine's
    # ``_cancel_loop`` ladder (SootheDaemonConfig.cancel_* knobs).
    cancel_retry_count: int = Field(
        default=3,
        ge=1,
        le=10,
        description=(
            "Cooperative-cancel retry attempts before escalating to force-kill "
            "on goal cancel / deadline."
        ),
    )
    cancel_retry_interval_seconds: float = Field(
        default=2.0,
        ge=0.1,
        le=30.0,
        description=(
            "Base seconds between cooperative-cancel retries; exponential "
            "backoff is applied (same scheme as the query engine)."
        ),
    )
    cancel_force_kill_timeout_seconds: float = Field(
        default=10.0,
        ge=1.0,
        le=60.0,
        description=(
            "Seconds to wait for worker process death during force-kill after "
            "cooperative cancel fails."
        ),
    )


class ContextProjectionConfig(BaseModel):
    """Bounds for GoalDispatchContextBundle merging (RFC-222 revised).

    The ContextProjector unions parents' GoalDispatchContextContributions,
    deduplicates, and truncates to these caps. Bundle stays small enough to
    ship over IPC cheaply (~100 KB).

    Args:
        max_findings: Max LLM-synthesized findings per bundle.
        max_effects: Max GoalEffect claims per bundle (IG-712).
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
    max_effects: int = Field(default=50, ge=1, le=500)
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
    """Caps for RFC-214 ledger copies sent to plan-assess / plan-generate.

    All limits use 0 to mean unlimited (preserve legacy behavior: full ledger, no copies).
    When any limit is positive, the plan phase uses deep-copied, trimmed messages only.
    """

    plan_ledger_max_messages: int = Field(
        default=GOAL_COMPLETION_REPORT_MAX_MESSAGES,
        ge=0,
        le=500,
        description="Max ledger messages tail for plan prompts (0 = unlimited)",
    )
    plan_ledger_max_total_chars: int = Field(
        default=GOAL_COMPLETION_REPORT_MAX_CHARS,
        ge=0,
        le=2_000_000,
        description=("Max total extracted characters for plan ledger projection (0 = unlimited)"),
    )
    plan_ledger_max_message_chars: int = Field(
        default=GOAL_COMPLETION_REPORT_MAX_PER_MESSAGE_CHARS,
        ge=0,
        le=500_000,
        description=(
            "Max extracted characters per ledger message in plan projection (0 = unlimited)"
        ),
    )
    preamble_max_turns: int = Field(
        default=12,
        ge=0,
        le=50,
        description=(
            "Max ancestor (user/ai) preamble turns projected into intake, execute, "
            "and synthesis prompts (0 = disable preamble projection)"
        ),
    )
    prior_goal_tail: int = Field(
        default=0,
        ge=0,
        le=1000,
        description=(
            "Max prior-goal terminal units projected into intake and synthesis "
            "prompts (0 = unlimited, project all prior-goal terminal units)"
        ),
    )


class ExecutePromptLedgerConfig(BaseModel):
    """Caps for execute-step CoreAgent ledger projection."""

    cross_goal_completion_tail: int = Field(
        default=0,
        ge=0,
        le=1000,
        description=(
            "Prior-goal completion units at goal boundary "
            "(0 = unlimited, project all; negative = disable Slice A)"
        ),
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
    """Loop checkpoint and recovery configuration (RFC-203).

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
    auto_resume_max_loops: int = Field(default=16, ge=1, le=64)
    auto_resume_max_age_hours: float = Field(default=24.0, ge=0.0, le=720.0)
    auto_resume_clarifications: Literal["skip", "reannounce"] = "skip"


class LoopCheckpointAsyncConfig(BaseModel):
    """Async checkpoint write configuration (RFC-803 Phase 6).

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

    Goal fan-out is owned by ``agent.autopilot.max_parallel_goals`` (Autopilot
    scheduler). Each StrangeLoop worker runs one goal; do not reintroduce a
    loop-level ``max_parallel_goals`` here.

    Args:
        max_parallel_steps: Maximum plan steps running concurrently per execute batch.
        max_parallel_subagents: Maximum subagents running simultaneously.
        global_max_llm_calls: Cross-level circuit breaker for concurrent LLM calls.
        step_parallelism: Scheduling strategy for plan steps (sequential/dependency/max).
        max_parallel_tools: Maximum concurrent tool calls per thread.
    """

    max_parallel_steps: int = Field(
        default=3,
        ge=0,
        description="Max concurrent plan steps per batch; 0=unlimited; multiple batches per execute",
    )
    max_parallel_subagents: int = Field(
        default=3, ge=0, description="Maximum parallel subagents (0=unlimited)"
    )
    global_max_llm_calls: int = Field(
        default=8, ge=0, description="Global LLM call cap (0=unlimited)"
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

    Three delivery modes:

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
            "Phase 3: 100ms default for TUI clients (faster perceived response); "
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
            ". Higher values reduce frame count; lower values smooth UX. "
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
            "chunked-streaming phase. Time-based fallback so slow streams "
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
    """


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


class StrangeLoopRulesConfig(BaseModel):
    """Declarative StrangeLoop routing and completion rules."""

    completion: CompletionRulesConfig = Field(default_factory=CompletionRulesConfig)
    scenario: ScenarioRulesConfig = Field(default_factory=ScenarioRulesConfig)


class DecomposeLoopConfig(BaseModel):
    """Recursive step decomposition budgets (RFC-904 / IG-751).

    Decomposition is always on for StrangeLoop step THREADS; this object only
    holds budgets and reconcile model role.
    """

    max_depth: int = Field(
        default=3,
        ge=1,
        le=20,
        description="Max parent_step_id lineage depth per goal.",
    )
    max_steps: int = Field(
        default=30,
        ge=1,
        le=500,
        description="Max total StepNodes per goal (including superseded).",
    )
    max_recompose: int = Field(
        default=2,
        ge=0,
        le=20,
        description="Max B-lazy recompose attempts per lineage replacement chain.",
    )
    max_waves: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Max recursive action-dispatch waves for the decompose path.",
    )
    max_branch_root: int = Field(
        default=5,
        ge=1,
        le=50,
        description="Max children per root-level decompose_task proposal.",
    )
    max_branch_inner: int = Field(
        default=3,
        ge=1,
        le=50,
        description="Max children per non-root decompose_task proposal.",
    )
    reconcile_model_role: str = Field(
        default="fast",
        description="Router model role for conflict-triggered CE reconcile LLM.",
    )


class EvalLoopConfig(BaseModel):
    """Coverage Eval thread limits (RFC-905)."""

    max_eval_rounds: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Maximum Eval coverage rounds per goal.",
    )


class StrangeLoopConfig(BaseModel):
    """Configuration for agent loop execution mode (RFC-201, unified config).

    Unified configuration consolidating agentic behavior fields and loop execution controls.
    Behavior fields are placed directly under loop.* for easy access.

    Args:
        enabled: Enable agent loop mode.
        max_iterations: Maximum StrangeLoop iterations per run (shared with Autopilot
            workers; default ``DEFAULT_MAX_ITERATIONS`` / 99). Autopilot does not
            define a separate budget.
        max_subagent_tasks_per_wave: Cap ``task`` tool completions per Act wave (0 = unlimited).
        general_purpose_subagent: GP subagent mode (off/full/readonly/per_step). ``off`` (default)
            disables GP; ``per_step`` routes full GP on agent-mode steps (incl. Eval) and read-only
            GP on plan/ask steps.
        max_tool_calls_per_step: Cap tool results consumed per execute step from the Act stream (0 = unlimited).
        dispatch_idle_seconds: Deadlock detector — max seconds of stream inactivity when no
            root-level tool is pending. Nested subgraph messages do not clear parent activity.
        dispatch_tool_timeout_seconds: Optional wall-clock cap for a root tool wave (dispatch
            until all pending ToolMessages). 0 disables (use ``agent.middleware.tool_timeout``).
        execute_action_retry_max: Extra Execute passes when the step deliverable gate fails (0 = disabled).
        execute_min_answer_chars: Minimum final assistant text length for deliverable satisfaction.
        execute_deliverable_assess: Fast LLM assess mode when structural deliverable checks are inconclusive.
        strange_loop_output_contract_enabled: Append anti-repetition instructions to sequential Act prompts.
        final_response: Whether to always synthesize a final CoreAgent report (default),
            reuse last Execute assistant text when structurally eligible, or use auto heuristics.
        working_memory: Working memory / spill configuration (RFC-203).
        goal_context: Goal context injection for Plan/Execute phases (RFC-217).
        report_output: Goal report display and synthesis limits.
        output_streaming: Enable streaming mode for all AI outputs (true=stream, false=batch).
        goal_completion_mode: How goal completion (`require_goal_completion`) combines with
            execution heuristics when the goal is assessed as done.
        plan_prompt_ledger: Ledger projection caps for Plan-phase LLM prompts.
        execute_prompt_ledger: Caps for execute-step CoreAgent ledger projection.
        checkpoint: Progressive checkpoint persistence and startup resume (RFC-203).
        concurrency: Parallelism caps and step scheduling strategy.
        goal_synthesis_model_role: Router role for goal-completion synthesis streaming (default ``default``).
        rules: Declarative completion and scenario thresholds.
        decompose: Recursive step decomposition budgets (RFC-904); always on.
        eval: Coverage Eval thread limits (RFC-905); always on when required.

    Note: Performance optimizations (intent/routing classification pipeline, optimize_system_prompts,
    parallel_pre_stream) are always enabled by design and not configurable.
    """

    enabled: bool = Field(
        default=True,
        description="Enable agent loop mode",
    )

    max_iterations: int = Field(
        default=DEFAULT_MAX_ITERATIONS,
        description=(
            "Maximum StrangeLoop iterations per run. Shared by interactive loops and "
            "Autopilot workers (Autopilot has no separate max_iterations)."
        ),
        ge=1,
        le=500,
    )

    max_subagent_tasks_per_wave: int = Field(
        default=4,
        description="Max completed subagent ``task`` tool results per Execute wave (0 = no limit)",
        ge=0,
        le=20,
    )

    general_purpose_subagent: GeneralPurposeSubagentMode = Field(
        default="off",
        description=(
            "General-purpose subagent mode. ``off`` (default) disables GP for StrangeLoop "
            "hosts; ``full`` registers a single GP variant with full filesystem access; "
            "``readonly`` restricts it to read-only tools (ls, read_file, file_info, glob, "
            "grep) with write-deny permissions (research-only delegation; mutations happen "
            "via DISPATCH→EXECUTE); ``per_step`` registers both variants and a host "
            "middleware routes full GP on agent-mode steps (incl. Eval) and read-only GP "
            "on plan/ask steps. Propagated to nano ``agent.runtime.general_purpose_subagent``."
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

    read_only_streak_limit: int = Field(
        default=DEFAULT_READ_ONLY_STREAK_LIMIT,
        description=(
            "Max consecutive read-only tool calls (grep/glob/read_file/ls) "
            "without a mutating call (edit/write/delete/run_command/"
            "decompose_task) before the Act stream is stopped. Prevents "
            "infinite evidence-gathering loops (a85d: 666 read-only calls)."
        ),
        ge=10,
        le=500,
    )

    @model_validator(mode="before")
    @classmethod
    def _reject_nano_middleware_and_legacy_keys(cls, data: Any) -> Any:
        """Keep nano middleware knobs out of ``agent.loop``."""
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
        default="always_synthesize",
        description=(
            "On goal completion: always_synthesize always runs a final CoreAgent report; "
            "auto uses structural heuristics to choose ledger direct vs a final CoreAgent "
            "report. Legacy alias: adaptive → auto."
        ),
    )

    @field_validator("final_response", mode="before")
    @classmethod
    def _normalize_final_response(cls, value: Any) -> Any:
        return normalize_agentic_final_response_mode(value)

    goal_completion_mode: AgenticGoalCompletionMode = Field(
        default="llm_only",
        description=(
            "When the loop marks the goal done: llm_only trusts PlanResult.status only; "
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
            "Check context on step threads ({main_thread_id}__{hex5}). "
            "Usually unnecessary; step threads are short-lived."
        ),
    )
    """RFC-224: Enable step thread context checking."""

    output_streaming: OutputStreamingConfig = Field(
        default_factory=OutputStreamingConfig,
        description="Output streaming configuration",
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

    execute_prompt_ledger: ExecutePromptLedgerConfig = Field(
        default_factory=ExecutePromptLedgerConfig,
        description="Execute-step CoreAgent ledger projection ",
    )

    checkpoint: LoopCheckpointConfig = Field(
        default_factory=LoopCheckpointConfig,
        description="Progressive checkpoint persistence and startup resume",
    )

    concurrency: LoopConcurrencyConfig = Field(
        default_factory=LoopConcurrencyConfig,
        description="Parallelism caps and step scheduling strategy",
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
        description="Declarative completion and scenario thresholds",
    )

    decompose: DecomposeLoopConfig = Field(
        default_factory=DecomposeLoopConfig,
        description="Recursive step decomposition budgets (RFC-904; always on).",
    )
    eval: EvalLoopConfig = Field(
        default_factory=EvalLoopConfig,
        description="Coverage Eval thread limits (RFC-905; required predicates only).",
    )


# ---------------------------------------------------------------------------
# RFC-622 §9b: Multi-stage tool-approval pipeline config
# (defined before ClarificationConfig so the field type resolves)
# ---------------------------------------------------------------------------


class ToolApprovalRule(BaseModel):
    """One deny or allow rule for tool-action approval (RFC-622 §9b).

    Pattern syntax (adapted from Claude Code's ``shellRuleMatching``):

    - ``"exact"`` — exact string match (e.g. ``"git status"``)
    - ``"prefix:*"`` — prefix match (e.g. ``"grep:*"`` matches ``"grep -r foo"``)
    - ``"wildcard*"`` — wildcard match, ``*`` = any sequence (e.g. ``"pytest*"``)

    Path patterns support ``**`` recursive matching via ``pathspec``
    (gitignore-style). The ``<workspace>`` token expands to the per-request
    workspace root from ``LoopStateView.workspace_summary``.
    """

    tool: Literal["edit_file", "write_file", "delete", "run_command"]
    pattern: str


class VeritasFallbackConfig(BaseModel):
    """Stage 4: veritas LLM fallback for ambiguous tool approvals (RFC-622 §9b)."""

    enabled: bool = True
    model_role: Literal["default", "fast", "think", "image", "ocr", "embedding"] = "fast"
    max_context_steps: int = Field(default=0, ge=0)
    inline_project_instructions: bool = False


class ToolApprovalAuditConfig(BaseModel):
    """Audit logging for tool-approval pipeline decisions (RFC-622 §9b)."""

    log_decisions: bool = True
    log_level: Literal["debug", "info", "warning"] = "info"


def _default_deny_rules() -> list[ToolApprovalRule]:
    """Default deny rules for Stage 1 of the tool-approval pipeline."""
    return [
        ToolApprovalRule(tool="run_command", pattern="rm -rf *"),
        ToolApprovalRule(tool="run_command", pattern="sudo *"),
        ToolApprovalRule(tool="run_command", pattern="chmod 777 *"),
        ToolApprovalRule(tool="run_command", pattern="git push --force*"),
        ToolApprovalRule(tool="run_command", pattern="git push -f*"),
        ToolApprovalRule(tool="run_command", pattern="dd if=*"),
        ToolApprovalRule(tool="run_command", pattern="mkfs*"),
        ToolApprovalRule(tool="edit_file", pattern="/etc/**"),
        ToolApprovalRule(tool="write_file", pattern="/etc/**"),
    ]


def _default_allow_rules() -> list[ToolApprovalRule]:
    """Default allow rules for Stage 3 of the tool-approval pipeline."""
    return [
        ToolApprovalRule(tool="edit_file", pattern="<workspace>/**"),
        ToolApprovalRule(tool="write_file", pattern="<workspace>/**"),
        ToolApprovalRule(tool="run_command", pattern="ls *"),
        ToolApprovalRule(tool="run_command", pattern="cat *"),
        ToolApprovalRule(tool="run_command", pattern="grep *"),
        ToolApprovalRule(tool="run_command", pattern="find *"),
        ToolApprovalRule(tool="run_command", pattern="pytest*"),
        ToolApprovalRule(tool="run_command", pattern="python -m pytest*"),
        ToolApprovalRule(tool="run_command", pattern="ruff *"),
        ToolApprovalRule(tool="run_command", pattern="mypy *"),
        ToolApprovalRule(tool="run_command", pattern="git status"),
        ToolApprovalRule(tool="run_command", pattern="git diff*"),
        ToolApprovalRule(tool="run_command", pattern="git log*"),
    ]


class ToolApprovalConfig(BaseModel):
    """Multi-stage tool-approval pipeline config (RFC-622 §9b).

    When ``enabled``, deterministic deny → safety → allow stages resolve most
    ``tool_approval`` interrupts without an LLM call. Veritas remains the
    final guard for ambiguous cases (Stage 4). When ``disabled``, all
    ``tool_approval`` interrupts go directly to veritas (pre-§9b behavior).
    """

    enabled: bool = True
    deny_rules: list[ToolApprovalRule] = Field(default_factory=_default_deny_rules)
    allow_rules: list[ToolApprovalRule] = Field(default_factory=_default_allow_rules)
    veritas_fallback: VeritasFallbackConfig = Field(default_factory=VeritasFallbackConfig)
    audit: ToolApprovalAuditConfig = Field(default_factory=ToolApprovalAuditConfig)


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

    degrade_to_manual_on_low_confidence: bool = True
    """When True and a human is attached, route low-confidence veritas results to
    the interactive TUI relay (auto→manual upgrade) instead of a hard defer.
    Mirrors the structured_output_failed fallback path. Ignored for autopilot
    (headless) runs which always hard-defer."""

    max_defer_age_hours: int = Field(default=168, ge=1)
    """Autopilot scrubs goals stuck in ``awaiting_clarification`` past this age."""

    default_mode: Literal["auto", "manual"] = "auto"
    """Mode used when a request payload does not specify ``clarification_mode``.

    ``auto`` routes clarifications through the veritas auto-answerer and is the
    default. ``manual`` routes them through the TUI relay (interactive policy).
    Autopilot always forces ``auto`` regardless of this setting.
    """

    force_manual_origins: list[
        Literal[
            "execute",
            "plan_mode_review",
            "rail_pause",
            "tool_approval",
        ]
    ] = Field(
        default_factory=lambda: list(DEFAULT_FORCE_MANUAL_ORIGINS),
        description=(
            "Clarification origins that never use veritas auto-answer, even when "
            "``default_mode`` / wire ``clarification_mode`` is ``auto``. "
            "With a human attached, the interactive TUI relay is used; otherwise "
            "the loop defers. Default is ``plan_mode_review`` only — ``tool_approval`` "
            "is evaluated by the multi-stage pipeline (§9b) in auto mode so safe "
            "tool calls auto-approve without an LLM. Re-add ``tool_approval`` to "
            "force a human on every tool action."
        ),
    )

    tool_approval: ToolApprovalConfig = Field(default_factory=ToolApprovalConfig)
    """RFC-622 §9b: multi-stage tool-approval pipeline. When enabled,
    deterministic deny → safety → allow stages resolve most tool_approval
    interrupts without an LLM. Veritas remains the final guard for ambiguous
    cases."""


class VeritasConfig(BaseModel):
    """RFC-622: configuration for the veritas auto-answerer subagent."""

    model_role: Literal["default", "fast", "think", "image", "ocr", "embedding"] = "think"
    """Which ``ModelRole`` to use for veritas calls; defaults to ``think``."""

    max_context_steps: int = Field(default=8, ge=0)
    """How many recent step outputs to include in the veritas user prompt."""

    max_retries: int = Field(default=2, ge=0)
    """Max retry attempts for transient infrastructure failures (rate limit,
    timeout, connection error). ``StructuredOutputError`` (model output
    malformed) still defers immediately. Set to ``0`` to disable retries."""

    retry_backoff_seconds: float = Field(default=2.0, ge=0.0)
    """Base backoff for exponential retry (``backoff * 2**attempt``)."""

    coerced_confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    """Confidence value assigned when the model returns answers but omits
    ``confidence``. Replaces the historical hardcoded ``0.7``."""


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
        enable_builtin_jobs: When true, seed built-in recurring maintenance
            jobs on daemon startup.
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
    enable_builtin_jobs: bool = Field(
        default=True,
        description=("When true, seed built-in recurring maintenance jobs on startup."),
    )


class AgentConfig(NanoAgentConfig):
    """Host agent configuration: nano CoreAgent fields plus orchestration overlays.

    Adds StrangeLoop/Autopilot/clarification/veritas and goal-completion behavior
    on top of nano ``AgentConfig`` (identity, protocols, runtime, middleware).
    """

    assistant_identity: AssistantIdentity = Field(
        default_factory=AssistantIdentity,
        description="Configurable persona: creator, role, vendor denylist.",
    )
    """Configurable assistant identity for prompt blocks and intake replies."""

    goal_completion_mode: AgenticGoalCompletionMode = Field(
        default="llm_only",
        description=(
            "When loop marks goal done: llm_only trusts PlanResult.status only; "
            "heuristic_only uses execution heuristics only; hybrid uses LLM first with fallback"
        ),
    )
    """How goal completion (require_goal_completion) combines with execution heuristics."""

    final_response: AgenticFinalResponseMode = Field(
        default="always_synthesize",
        description=(
            "On goal completion: always_synthesize always runs a final CoreAgent report; "
            "auto uses structural heuristics to choose ledger direct vs a final CoreAgent "
            "report. Legacy alias: adaptive → auto."
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
