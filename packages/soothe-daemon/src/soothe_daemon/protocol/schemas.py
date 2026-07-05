"""Pydantic param models for all protocol-1 message types (RFC-450 §6.2).

Each model defines the *params* schema for a ``(type, method)`` pair in the
wire envelope.  The models are registered in ``PARAMS_REGISTRY``, which the
transport layer consults at the validation boundary (before router dispatch).

Design notes
------------
- All models allow extra fields (``model_config = {"extra": "allow"}``) so
  the envelope's ``type``/``method``/``request_id`` keys and any
  forward-compatible fields pass through without being rejected.
- Required string identifiers (``loop_id``, ``job_id``, ``goal``, ``content``,
  ``skill``, ``cmd``) use ``min_length=1`` so empty strings are caught here
  instead of inside handlers.
- Models are intentionally permissive about optional fields — the handler is
  the authority on domain semantics (e.g. whether ``autonomous`` is honoured).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

__all__ = [
    # Base
    "ParamsBase",
    "EmptyParams",
    # Loop RPC
    "LoopNewParams",
    "LoopGetParams",
    "LoopListParams",
    "LoopTreeParams",
    "LoopPruneParams",
    "LoopDeleteParams",
    "LoopReattachParams",
    "LoopInputParams",
    "LoopMessagesParams",
    "LoopStateGetParams",
    "LoopStateUpdateParams",
    "LoopCardsFetchParams",
    "LoopDetachParams",
    # Job RPC
    "JobCreateParams",
    "JobStatusParams",
    "JobPauseParams",
    "JobResumeParams",
    "JobCancelParams",
    "JobDagParams",
    "JobGuidanceParams",
    # Daemon & config
    "DaemonStatusParams",
    "DaemonShutdownParams",
    "ConfigGetParams",
    "ConfigReloadParams",
    # Skills & models
    "SkillsListParams",
    "ModelsListParams",
    "InvokeSkillParams",
    "McpStatusParams",
    # Auth
    "AuthParams",
    "AuthRefreshParams",
    # Command
    "CommandParams",
    "CommandRequestParams",
    # Subscription / connection
    "SubscribeParams",
    "AutopilotSubscribeParams",
    "AutopilotUnsubscribeParams",
    "ConnectionInitParams",
    "DisconnectParams",
    "PingParams",
    "PongParams",
    # Cron RPC (RFC-229)
    "CronAddParams",
    "CronListParams",
    "CronShowParams",
    "CronCancelParams",
    # Registry
    "PARAMS_REGISTRY",
]


# ---------------------------------------------------------------------------
# Base models
# ---------------------------------------------------------------------------


class ParamsBase(BaseModel):
    """Base for all param models — allows extra fields for forward compat.

    The protocol envelope carries ``proto``, ``type``, ``method``,
    ``request_id``, and ``id`` alongside the operation-specific fields.  All
    models validate against the *whole* message dict (or the nested
    ``params`` dict) so extra keys must be tolerated.
    """

    model_config = {"extra": "allow"}


class EmptyParams(ParamsBase):
    """Params model for messages that carry no required fields."""


# ---------------------------------------------------------------------------
# Loop RPC param models
# ---------------------------------------------------------------------------


class LoopNewParams(ParamsBase):
    """Params for method=loop_new, type=request."""

    workspace: str | None = None
    user_id: str | None = None
    client_workspace_id: str | None = None
    is_ephemeral: bool = False


class LoopGetParams(ParamsBase):
    """Params for method=loop_get, type=request."""

    loop_id: str = Field(..., min_length=1, description="Loop identifier")
    verbose: bool = Field(default=False, description="Include verbose details")
    tree: bool = Field(default=False, description="Include checkpoint tree")


class LoopListParams(ParamsBase):
    """Params for method=loop_list, type=request."""

    status: str | None = None
    limit: int | None = None


class LoopTreeParams(ParamsBase):
    """Params for method=loop_tree, type=request."""

    loop_id: str = Field(..., min_length=1)


class LoopPruneParams(ParamsBase):
    """Params for method=loop_prune, type=request."""

    loop_id: str = Field(..., min_length=1)
    keep_latest: int = Field(default=1, ge=1)


class LoopDeleteParams(ParamsBase):
    """Params for method=loop_delete, type=request."""

    loop_id: str = Field(..., min_length=1)


class LoopReattachParams(ParamsBase):
    """Params for method=loop_reattach, type=request."""

    loop_id: str = Field(..., min_length=1)


class LoopInputParams(ParamsBase):
    """Params for method=loop_input, type=request or notification."""

    loop_id: str = Field(..., min_length=1)
    content: str | dict[str, Any] = Field(..., description="User input text or structured content")
    autonomous: bool = False
    max_iterations: int | None = Field(default=None, gt=0)
    preferred_subagent: str | None = None
    model: str | None = None  # Provider:model string; handler does the validation
    model_params: dict[str, Any] | None = None
    attachments: list[dict[str, str]] | None = None
    intent_hint: str | None = None
    response_schema: dict[str, Any] | None = None
    response_schema_name: str | None = None
    response_schema_strict: bool | None = None
    clarification_mode: Any = None  # Handler normalizes to auto/manual or None
    clarification_answer: bool = False
    clarification_answers: list[str] | None = None


class LoopMessagesParams(ParamsBase):
    """Params for method=loop_messages, type=request."""

    loop_id: str = Field(..., min_length=1)
    limit: int = Field(default=100, ge=1)
    offset: int = Field(default=0, ge=0)


class LoopStateGetParams(ParamsBase):
    """Params for method=loop_state_get, type=request."""

    loop_id: str = Field(..., min_length=1)
    keys: list[str] | None = None


class LoopStateUpdateParams(ParamsBase):
    """Params for method=loop_state_update, type=request."""

    loop_id: str = Field(..., min_length=1)
    values: dict[str, Any]


class LoopCardsFetchParams(ParamsBase):
    """Params for method=loop_cards_fetch, type=request."""

    loop_id: str = Field(..., min_length=1)
    since: str | None = None


class LoopDetachParams(ParamsBase):
    """Params for method=loop_detach (legacy flat type)."""

    loop_id: str = Field(..., min_length=1)


# ---------------------------------------------------------------------------
# Job RPC param models
# ---------------------------------------------------------------------------


class JobCreateParams(ParamsBase):
    """Params for method=job_create, type=request."""

    goal: str = Field(..., min_length=1, description="Job goal text")
    workspace: str | None = None
    user_id: str | None = None
    autonomous: bool = False
    max_iterations: int | None = Field(default=None, gt=0)
    guidance: str | None = None
    intent_hint: str | None = None


class JobStatusParams(ParamsBase):
    """Params for method=job_status, type=request."""

    job_id: str = Field(..., min_length=1)


class JobPauseParams(ParamsBase):
    """Params for method=job_pause, type=request."""

    job_id: str = Field(..., min_length=1)


class JobResumeParams(ParamsBase):
    """Params for method=job_resume, type=request."""

    job_id: str = Field(..., min_length=1)


class JobCancelParams(ParamsBase):
    """Params for method=job_cancel, type=request."""

    job_id: str = Field(..., min_length=1)


class JobDagParams(ParamsBase):
    """Params for method=job_dag, type=request."""

    job_id: str = Field(..., min_length=1)


class JobGuidanceParams(ParamsBase):
    """Params for method=job_guidance, type=request.

    The canonical field name for the guidance text is ``content`` (RFC-450
    §10.1).
    """

    job_id: str = Field(..., min_length=1)
    content: str = Field(..., min_length=1, description="Guidance text")

    @model_validator(mode="after")
    def _ensure_content(self) -> JobGuidanceParams:
        if not self.content:
            raise ValueError("content is required")
        return self


# ---------------------------------------------------------------------------
# Daemon & config param models
# ---------------------------------------------------------------------------


class DaemonStatusParams(EmptyParams):
    """Params for method=daemon_status, type=request (no required fields)."""


class DaemonShutdownParams(EmptyParams):
    """Params for method=daemon_shutdown, type=request (no required fields)."""


class ConfigGetParams(ParamsBase):
    """Params for method=config_get, type=request."""

    section: str | None = None


class ConfigReloadParams(EmptyParams):
    """Params for method=config_reload, type=request (no required fields)."""


# ---------------------------------------------------------------------------
# Skills & models param models
# ---------------------------------------------------------------------------


class SkillsListParams(EmptyParams):
    """Params for method=skills_list, type=request (no required fields)."""


class ModelsListParams(EmptyParams):
    """Params for method=models_list, type=request (no required fields)."""


class InvokeSkillParams(ParamsBase):
    """Params for method=invoke_skill, type=request."""

    skill: str = Field(..., min_length=1)
    args: str = ""
    clarification_mode: Any = None  # Handler normalizes to auto/manual or None


class McpStatusParams(EmptyParams):
    """Params for method=mcp_status, type=request (no required fields)."""


# ---------------------------------------------------------------------------
# Auth param models
# ---------------------------------------------------------------------------


class AuthParams(ParamsBase):
    """Params for method=auth, type=request.

    ``access_key`` and ``secret_key`` are optional at the wire level so the
    handler can return a domain-specific ``missing_credentials`` error rather
    than a generic ``-32602 INVALID_PARAMS``.
    """

    access_key: str = ""
    secret_key: str = ""


class AuthRefreshParams(ParamsBase):
    """Params for method=auth_refresh, type=request.

    ``refresh_token`` is optional at the wire level so the handler can return
    a domain-specific ``missing_token`` error.
    """

    refresh_token: str = ""


# ---------------------------------------------------------------------------
# Command param models
# ---------------------------------------------------------------------------


class CommandParams(ParamsBase):
    """Params for legacy type=command (slash command)."""

    cmd: str = Field(..., min_length=1)


class CommandRequestParams(ParamsBase):
    """Params for legacy type=command_request (structured RPC command)."""


# ---------------------------------------------------------------------------
# Subscription & connection param models
# ---------------------------------------------------------------------------


class SubscribeParams(ParamsBase):
    """Params for type=subscribe, method=loop_events (protocol-1 envelope)."""

    loop_id: str = Field(..., min_length=1)
    stream_delivery: Literal["batch", "adaptive", "streaming"] = "adaptive"
    wire_tier: Literal["full", "compact"] = "full"


class AutopilotSubscribeParams(ParamsBase):
    """Params for type=autopilot_subscribe (legacy flat) or
    (subscribe, autopilot_events) in protocol-1 envelope.
    """

    job_id: str | None = None
    filters: dict[str, Any] | None = None


class AutopilotUnsubscribeParams(ParamsBase):
    """Params for type=autopilot_unsubscribe (legacy flat)."""


class ConnectionInitParams(ParamsBase):
    """Params for type=connection_init (protocol-1 handshake)."""

    client_version: str | None = None
    client_name: str | None = None
    accept_proto: list[str] | None = None
    capabilities: list[str] | None = None


class DisconnectParams(EmptyParams):
    """Params for type=disconnect / type=detach (no required fields)."""


class PingParams(EmptyParams):
    """Params for type=ping (no required fields)."""


class PongParams(EmptyParams):
    """Params for type=pong (no required fields)."""


# ---------------------------------------------------------------------------
# Cron RPC param models (RFC-229)
# ---------------------------------------------------------------------------


class CronAddParams(ParamsBase):
    """Params for method=cron_add, type=request.

    Natural language scheduling request.
    """

    text: str = Field(..., min_length=1, description="Natural language scheduling request")
    priority: int | None = Field(default=None, ge=1, le=100)


class CronListParams(ParamsBase):
    """Params for method=cron_list, type=request."""

    status: str | None = None


class CronShowParams(ParamsBase):
    """Params for method=cron_show, type=request."""

    job_id: str = Field(..., min_length=1)


class CronCancelParams(ParamsBase):
    """Params for method=cron_cancel, type=request."""

    job_id: str = Field(..., min_length=1)


# ---------------------------------------------------------------------------
# Wire schema registry — maps (type, method_or_None) → params model.
# Wire schema registry — maps (type, method_or_None) → params model.
#
# The key is ``(msg_type, method)`` where ``method`` is ``None`` for messages
# that use only the ``type`` field (legacy flat format).  In the protocol-1
# envelope, the key is ``(type, method)`` — e.g. ``("request", "loop_get")``.
#
# Both legacy flat keys (``(msg_type, None)``) and protocol-1 envelope keys
# (``(type, method)``) are registered so the same registry serves both wire
# formats during the migration window.
# ---------------------------------------------------------------------------

PARAMS_REGISTRY: dict[tuple[str, str | None], type[BaseModel]] = {
    # -- Non-envelope control types (type-only) ---------------------------
    ("connection_init", None): ConnectionInitParams,
    ("ping", None): PingParams,
    ("pong", None): PongParams,
    # -- Protocol-1 envelope keys (type, method) --------------------------
    # Canonical RFC-450 §6.2 registry entries for the
    # ``{proto, type, method, params, id}`` envelope. The daemon accepts
    # envelope-form only; legacy flat-form messages are rejected at dispatch.
    ("request", "loop_new"): LoopNewParams,
    ("request", "loop_get"): LoopGetParams,
    ("request", "loop_list"): LoopListParams,
    ("request", "loop_tree"): LoopTreeParams,
    ("request", "loop_prune"): LoopPruneParams,
    ("request", "loop_delete"): LoopDeleteParams,
    ("request", "loop_reattach"): LoopReattachParams,
    ("request", "loop_detach"): LoopDetachParams,
    ("request", "loop_input"): LoopInputParams,
    ("notification", "loop_input"): LoopInputParams,
    ("request", "loop_messages"): LoopMessagesParams,
    ("request", "loop_state_get"): LoopStateGetParams,
    ("request", "loop_state_update"): LoopStateUpdateParams,
    ("request", "loop_cards_fetch"): LoopCardsFetchParams,
    ("request", "job_create"): JobCreateParams,
    ("request", "job_status"): JobStatusParams,
    ("request", "job_pause"): JobPauseParams,
    ("request", "job_resume"): JobResumeParams,
    ("request", "job_cancel"): JobCancelParams,
    ("request", "job_dag"): JobDagParams,
    ("request", "job_guidance"): JobGuidanceParams,
    ("request", "daemon_status"): DaemonStatusParams,
    ("request", "daemon_shutdown"): DaemonShutdownParams,
    ("request", "config_get"): ConfigGetParams,
    ("request", "config_reload"): ConfigReloadParams,
    ("request", "skills_list"): SkillsListParams,
    ("request", "invoke_skill"): InvokeSkillParams,
    ("request", "models_list"): ModelsListParams,
    ("request", "mcp_status"): McpStatusParams,
    ("request", "auth"): AuthParams,
    ("request", "auth_refresh"): AuthRefreshParams,
    ("request", "rpc_command"): CommandRequestParams,
    ("notification", "slash_command"): CommandParams,
    ("notification", "disconnect"): DisconnectParams,
    ("subscribe", "loop_events"): SubscribeParams,
    ("subscribe", "autopilot_events"): AutopilotSubscribeParams,
    ("unsubscribe", None): AutopilotUnsubscribeParams,
    # Cron RPC (RFC-229)
    ("request", "cron_add"): CronAddParams,
    ("request", "cron_list"): CronListParams,
    ("request", "cron_show"): CronShowParams,
    ("request", "cron_cancel"): CronCancelParams,
}
