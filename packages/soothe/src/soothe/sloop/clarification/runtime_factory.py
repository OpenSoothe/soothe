"""Bridge from ``SootheConfig`` + runtime mode to a ``ClarificationPolicy``.

The selector in :mod:`soothe.sloop.clarification.selector` is config-agnostic.
This module knits together the config's ``ClarificationConfig`` /
``VeritasConfig`` blocks with the veritas implementation so runners do not have
to repeat the wiring.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Literal

from soothe.sloop.clarification.interactive import EmitFn, InteractiveClarificationPolicy
from soothe.sloop.clarification.protocol import (
    ClarificationPolicy,
    ClarificationRequest,
)
from soothe.sloop.clarification.selector import build_default_clarification_policy
from soothe.sloop.clarification.tool_approval_pipeline import ToolApprovalPipeline
from soothe.subagents.veritas import answer as veritas_answer

if TYPE_CHECKING:
    from soothe.config.models import SootheConfig
    from soothe.subagents.veritas.schemas import VeritasAnswerSchema

logger = logging.getLogger(__name__)


def resolve_clarification_mode(
    requested: str | None,
    config: SootheConfig,
) -> Literal["auto", "manual"]:
    """Pick the effective mode from the request value and the config default.

    Args:
        requested: Per-request mode (typically from the wire payload).
            ``None`` or unrecognized values fall back to the config default.
        config: Active ``SootheConfig`` with ``agent.clarification.default_mode``.

    Returns:
        ``"auto"`` or ``"manual"``.
    """
    cleaned = (requested or "").strip().lower()
    if cleaned in ("auto", "manual"):
        return cleaned  # type: ignore[return-value]
    return config.agent.clarification.default_mode


def build_clarification_policy_for_runner(
    config: SootheConfig,
    *,
    mode: str | None = None,
    emit: EmitFn | None = None,
    human_attached: bool = False,
    thread_id: str | None = None,
    loop_id: str | None = None,
) -> ClarificationPolicy:
    """Build the policy a runner injects into ``LoopRuntimeContext``.

    Args:
        config: Soothe configuration providing the clarification and veritas
            sub-blocks plus the chat-model factory.
        mode: Optional per-request mode (``"auto"`` / ``"manual"``). When
            unset, falls back to ``config.agent.clarification.default_mode``.
        emit: Optional emit function for early UI notification. The durable
            pause path uses LangGraph ``interrupt(...)`` regardless.
        human_attached: When ``True`` and ``mode`` resolves to ``"auto"``,
            wire an :class:`InteractiveClarificationPolicy` as the
            ``interactive_fallback`` (RFC-623). Veritas structured-output
            failures then degrade to a TUI prompt instead of terminating the
            loop. Headless callers (autopilot) pass ``False`` and keep the
            hard-defer path on veritas failure.
        thread_id: Loop thread id used as the Langfuse ``session_id`` for the
            veritas LLM call so the span correlates with the parent loop trace.
        loop_id: Loop id forwarded to Langfuse for trace correlation.

    Returns:
        A ``ClarificationPolicy`` ready to attach to a goal run. The veritas
        chat model is only instantiated when ``mode`` resolves to ``"auto"``
        — manual mode skips the model construction entirely. In manual mode
        the tool-approval pipeline (when enabled) still pre-filters
        ``tool_approval`` requests: deny/safety stages auto-reject, allow
        rules auto-approve only under ``manual_scope: ambiguous_only``.
    """
    resolved_mode = resolve_clarification_mode(mode, config)
    clar_cfg = config.agent.clarification
    ta_cfg = clar_cfg.tool_approval

    tool_approval_pipeline: ToolApprovalPipeline | None = None
    if ta_cfg.enabled:
        tool_approval_pipeline = ToolApprovalPipeline(
            config=ta_cfg,
            security_config=config.security,
        )

    if resolved_mode == "manual":
        # RFC-622 §9b: pipeline pre-filters the human relay in manual mode —
        # deny/safety stages always auto-reject dangerous actions; allow
        # rules auto-approve only when manual_scope is ambiguous_only.
        return build_default_clarification_policy(
            mode="manual",
            emit=emit,
            tool_approval_pipeline=tool_approval_pipeline,
            manual_allow_rules=(ta_cfg.manual_scope == "ambiguous_only"),
        )

    veritas_cfg = config.agent.veritas
    veritas_model = config.create_chat_model(veritas_cfg.model_role)

    # RFC-622 §9b: fast model for tool-approval fallback, think for intent.
    ta_fallback_cfg = ta_cfg.veritas_fallback
    tool_approval_model = veritas_model
    if (
        ta_cfg.enabled
        and ta_fallback_cfg.enabled
        and ta_fallback_cfg.model_role != veritas_cfg.model_role
    ):
        tool_approval_model = config.create_chat_model(ta_fallback_cfg.model_role)

    async def _veritas(request: ClarificationRequest) -> VeritasAnswerSchema:
        if request.origin_node == "tool_approval" and ta_cfg.enabled and ta_fallback_cfg.enabled:
            return await veritas_answer(
                request,
                model=tool_approval_model,
                max_context_steps=ta_fallback_cfg.max_context_steps,
                soothe_config=config,
                thread_id=thread_id,
                loop_id=loop_id,
                max_retries=veritas_cfg.max_retries,
                retry_backoff_seconds=veritas_cfg.retry_backoff_seconds,
                coerced_confidence=veritas_cfg.coerced_confidence,
            )
        return await veritas_answer(
            request,
            model=veritas_model,
            max_context_steps=veritas_cfg.max_context_steps,
            soothe_config=config,
            thread_id=thread_id,
            loop_id=loop_id,
            max_retries=veritas_cfg.max_retries,
            retry_backoff_seconds=veritas_cfg.retry_backoff_seconds,
            coerced_confidence=veritas_cfg.coerced_confidence,
        )

    interactive_fallback: ClarificationPolicy | None = (
        InteractiveClarificationPolicy(emit=emit) if human_attached else None
    )

    return build_default_clarification_policy(
        mode="auto",
        veritas_answer=_veritas,
        emit=emit,
        min_confidence=clar_cfg.auto_min_confidence,
        interactive_fallback=interactive_fallback,
        force_manual_origins=list(clar_cfg.force_manual_origins or ()),
        degrade_low_confidence=clar_cfg.degrade_to_manual_on_low_confidence,
        tool_approval_pipeline=tool_approval_pipeline,
    )


def bind_clarification_emit(
    policy: ClarificationPolicy | None,
    emit: EmitFn,
) -> None:
    """Wire runtime ``emit`` into interactive clarification legs (RFC-623).

    Runners build the policy before the graph ``emit`` closure exists. Call
    this once ``emit`` is available so auto→manual upgrades
    (``answer_as_manual_fallback``) can re-notify the TUI before
    ``interrupt(...)`` pauses the graph.
    """
    if policy is None:
        return
    from soothe.sloop.clarification.auto import AutoClarificationPolicy
    from soothe.sloop.clarification.interactive import InteractiveClarificationPolicy

    if isinstance(policy, InteractiveClarificationPolicy):
        policy.bind_emit(emit)
        return
    if isinstance(policy, AutoClarificationPolicy):
        fallback = policy._interactive_fallback  # noqa: SLF001
        if isinstance(fallback, InteractiveClarificationPolicy):
            fallback.bind_emit(emit)


__all__ = [
    "bind_clarification_emit",
    "build_clarification_policy_for_runner",
    "resolve_clarification_mode",
]
