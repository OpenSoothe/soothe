"""Per-hop model role routing for CoreAgent ReAct loop (IG-545)."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage

from soothe_nano.config.models import ModelRole

if TYPE_CHECKING:
    from soothe_nano.config import SootheConfig

logger = logging.getLogger(__name__)


def model_hop_index_since_user(messages: list[AnyMessage]) -> int:
    """Count completed model hops since the last user message.

    Each ``AIMessage`` after the last ``HumanMessage`` is one completed hop.
    The current (in-flight) call uses this count as its hop index.

    Args:
        messages: Conversation messages on the model request (no system message).

    Returns:
        Non-negative hop index for the upcoming model call.
    """
    last_human_idx = -1
    for i, msg in enumerate(messages):
        if isinstance(msg, HumanMessage):
            last_human_idx = i
    segment = messages[last_human_idx + 1 :] if last_human_idx >= 0 else messages
    return sum(1 for msg in segment if isinstance(msg, AIMessage))


def resolve_model_role_for_request(
    request: ModelRequest[Any],
    *,
    orchestration_model_role: ModelRole,
    generation_model_role: ModelRole,
    max_orchestration_hops: int,
) -> ModelRole:
    """Pick router role for a single CoreAgent model hop.

    Args:
        request: In-flight model request after upstream middleware.
        orchestration_model_role: Role for tool-orchestration hops.
        generation_model_role: Role for synthesis and capped hops.
        max_orchestration_hops: Orchestration role while hop index is below this.

    Returns:
        Resolved ``ModelRole`` for this hop.
    """
    tools = request.tools or []
    if not tools:
        return generation_model_role

    tool_choice = request.tool_choice
    if tool_choice == "none":
        return generation_model_role

    hop_index = model_hop_index_since_user(request.messages)
    if hop_index >= max_orchestration_hops:
        return generation_model_role

    return orchestration_model_role


class RoleRoutingMiddleware(AgentMiddleware):
    """Swap ``request.model`` per hop using ``ModelRouter`` roles."""

    name = "RoleRoutingMiddleware"

    def __init__(self, config: SootheConfig) -> None:
        """Cache role-specific chat models on the middleware instance.

        Args:
            config: ``SootheConfig`` with ``agent.runtime.role_routing``.
        """
        super().__init__()
        self._config = config
        self._models_by_role: dict[ModelRole, BaseChatModel] = {}

    def _model_for_role(self, role: ModelRole) -> BaseChatModel:
        from soothe_nano.utils.runtime import get_stream_router_profile

        overlay = get_stream_router_profile()
        # Overlay can change between turns on a reused runner; do not reuse
        # a chat model created under a different (or absent) profile.
        if overlay:
            return self._config.create_chat_model(role)
        cached = self._models_by_role.get(role)
        if cached is not None:
            return cached
        model = self._config.create_chat_model(role)
        self._models_by_role[role] = model
        return model

    def _maybe_override_request(self, request: ModelRequest[Any]) -> ModelRequest[Any]:
        routing = self._config.agent.runtime.role_routing
        if not routing.enabled:
            return request

        role = resolve_model_role_for_request(
            request,
            orchestration_model_role=routing.orchestration_model_role,
            generation_model_role=routing.generation_model_role,
            max_orchestration_hops=routing.max_orchestration_hops,
        )
        try:
            model = self._model_for_role(role)
        except Exception:
            logger.exception("Role routing failed for role %s; using base model", role)
            return request
        logger.debug(
            "Role routing: hop=%d role=%s tools=%d",
            model_hop_index_since_user(request.messages),
            role,
            len(request.tools or []),
        )
        return request.override(model=model)

    def wrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], ModelResponse[Any]],
    ) -> ModelResponse[Any]:
        return handler(self._maybe_override_request(request))

    async def awrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], Awaitable[ModelResponse[Any]]],
    ) -> ModelResponse[Any]:
        return await handler(self._maybe_override_request(request))
