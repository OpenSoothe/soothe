"""Direct model invocations for ``intent_hint`` loop_input turns (no Soothe agent)."""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import HumanMessage

from soothe_daemon.image_understanding import _build_vision_invoke_config

logger = logging.getLogger(__name__)


def _build_direct_invoke_config(
    config: Any,
    *,
    purpose: str,
    component: str,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Langfuse-traced RunnableConfig for direct daemon LLM calls."""
    try:
        from soothe.utils.observability.langfuse import build_traced_config

        return build_traced_config(
            config,
            purpose=purpose,
            component=component,
            phase="direct-invoke",
            session_id=session_id,
            run_name=f"soothe:{purpose}",
        )
    except Exception:
        return {}


async def run_image_to_text_turn(
    config: Any,
    *,
    user_text: str,
    attachments: list[dict[str, str]],
    session_id: str | None = None,
) -> str:
    """Run the configured ``image`` role chat model on images plus user instructions.

    Args:
        config: ``SootheConfig`` instance.
        user_text: User instructions (may be empty; images are still required upstream).
        attachments: Normalized ``{"mime_type", "data"}`` entries (base64 ``data``).
        session_id: Optional LangGraph checkpoint id for Langfuse session correlation.

    Returns:
        Model response text (non-empty; falls back to a short placeholder if the model
        returns only whitespace).

    Raises:
        Exception: Propagated from the underlying model provider.
    """
    if not attachments:
        msg = "run_image_to_text_turn requires at least one attachment"
        raise ValueError(msg)

    model = config.create_chat_model("image")
    instruction = (user_text or "").strip() or (
        "Describe the attached image(s) and answer any implied questions."
    )
    blocks: list[str | dict[str, Any]] = [{"type": "text", "text": instruction}]
    for att in attachments:
        mime = att["mime_type"]
        b64 = att["data"]
        blocks.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})

    msg = HumanMessage(content=blocks)
    invoke_cfg = _build_vision_invoke_config(config, session_id=session_id)
    response = await model.ainvoke([msg], config=invoke_cfg)
    out = str(response.content).strip()
    if not out:
        out = "(Image model returned empty content.)"
    return out


async def run_direct_llm_turn(
    config: Any,
    *,
    user_text: str,
    model: str | None = None,
    model_params: dict[str, Any] | None = None,
    session_id: str | None = None,
) -> str:
    """Run the configured ``default`` role model (or an explicit ``provider:model`` spec).

    Args:
        config: ``SootheConfig`` instance.
        user_text: User message (must be non-empty; enforced by caller).
        model: Optional ``provider:model`` override (same wire field as agent turns).
        model_params: Optional extra kwargs for ``init_chat_model`` when using override.
        session_id: Optional Langfuse session id.

    Returns:
        Stripped model text, or a short placeholder if empty.

    Raises:
        Exception: Propagated from the underlying model provider.
    """
    stripped = (user_text or "").strip()
    if not stripped:
        msg = "run_direct_llm_turn requires non-empty user_text"
        raise ValueError(msg)

    m = model.strip() if isinstance(model, str) and model.strip() else None
    if m:
        chat = config.create_chat_model_for_spec(m, model_params=model_params or {})
    else:
        chat = config.create_chat_model("default")

    invoke_cfg = _build_direct_invoke_config(
        config,
        purpose="direct_llm",
        component="daemon.direct_llm",
        session_id=session_id,
    )
    response = await chat.ainvoke([HumanMessage(content=stripped)], config=invoke_cfg)
    out = str(response.content).strip()
    if not out:
        out = "(Model returned empty content.)"
    return out
