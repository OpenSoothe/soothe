"""Direct model invocations for ``intent_hint`` loop_input turns (no Soothe agent)."""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.messages import HumanMessage
from soothe.utils.llm.structured_invoke import StructuredOutputError, invoke_structured_chat
from soothe.utils.text_preview import log_preview

from soothe_daemon.services.image_understanding import _build_vision_invoke_config

logger = logging.getLogger(__name__)

_LOG_PREVIEW_CHARS = 800

_DEFAULT_VISION_INSTRUCTION = "Describe the attached image(s) and answer any implied questions."


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


async def _run_direct_vision_turn(
    config: Any,
    *,
    user_text: str,
    attachments: list[dict[str, str]],
    session_id: str | None = None,
) -> str:
    """Run the configured ``image`` role model on images plus user instructions."""
    if not attachments:
        msg = "direct_llm vision path requires at least one attachment"
        raise ValueError(msg)

    model = config.create_chat_model("image")
    instruction = (user_text or "").strip() or _DEFAULT_VISION_INSTRUCTION
    blocks: list[str | dict[str, Any]] = [{"type": "text", "text": instruction}]
    for att in attachments:
        mime = att["mime_type"]
        b64 = att["data"]
        blocks.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})

    att_meta = [
        {"mime_type": a["mime_type"], "data_chars": len(a.get("data", ""))} for a in attachments
    ]
    logger.info(
        "[intent_hint direct_llm] vision request session_id=%s instruction=%s attachments=%s",
        session_id,
        log_preview(instruction, chars=_LOG_PREVIEW_CHARS),
        att_meta,
    )

    msg = HumanMessage(content=blocks)
    invoke_cfg = _build_vision_invoke_config(config, session_id=session_id)
    response = await model.ainvoke([msg], config=invoke_cfg)
    out = str(response.content).strip()
    if not out:
        out = "(Image model returned empty content.)"
    logger.info(
        "[intent_hint direct_llm] vision response session_id=%s content=%s",
        session_id,
        log_preview(out, chars=_LOG_PREVIEW_CHARS),
    )
    return out


async def run_image_to_text_turn(
    config: Any,
    *,
    user_text: str,
    attachments: list[dict[str, str]],
    session_id: str | None = None,
) -> str:
    """Deprecated alias for ``run_direct_llm_turn`` with ``attachments``.

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
    return await run_direct_llm_turn(
        config,
        user_text=user_text,
        attachments=attachments,
        session_id=session_id,
    )


async def run_direct_llm_turn(
    config: Any,
    *,
    user_text: str,
    model: str | None = None,
    model_params: dict[str, Any] | None = None,
    session_id: str | None = None,
    attachments: list[dict[str, str]] | None = None,
    response_schema: dict[str, Any] | None = None,
    response_schema_name: str | None = None,
    response_schema_strict: bool | None = None,
) -> str:
    """Run a configured chat model directly (no Soothe agent graph).

    Text-only turns use the ``default`` role (or an explicit ``provider:model`` spec).
    When ``attachments`` are present, the configured ``image`` role vision model is used
    instead (``model`` / ``model_params`` overrides are ignored on the vision path).

    Args:
        config: ``SootheConfig`` instance.
        user_text: User message. Required for text-only turns; optional when attachments
            are present (a default vision instruction is used when empty).
        model: Optional ``provider:model`` override for text-only turns.
        model_params: Optional extra kwargs for ``init_chat_model`` when using override.
        session_id: Optional Langfuse session id.
        attachments: Optional normalized image attachments for vision turns.
        response_schema: Optional client JSON Schema for structured text-only output.
        response_schema_name: Optional provider schema name override.
        response_schema_strict: When set, controls strict json_schema mode (default True).

    Returns:
        Stripped model text, or canonical JSON string when ``response_schema`` is set.

    Raises:
        ValueError: When input is invalid (empty text and no attachments, or structured
            output requested with attachments).
        StructuredOutputError: When structured output was requested but could not be produced.
        Exception: Propagated from the underlying model provider.
    """
    att = list(attachments or [])
    stripped = (user_text or "").strip()

    if att:
        if response_schema is not None:
            msg = "response_schema is not supported with direct_llm image attachments"
            raise ValueError(msg)
        return await _run_direct_vision_turn(
            config,
            user_text=user_text,
            attachments=att,
            session_id=session_id,
        )

    if not stripped:
        msg = "run_direct_llm_turn requires non-empty user_text or attachments"
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
    model_label = m if m else "default"
    structured = response_schema is not None
    strict = True if response_schema_strict is None else bool(response_schema_strict)
    logger.info(
        "[intent_hint direct_llm] request session_id=%s model=%s structured=%s user_text=%s",
        session_id,
        model_label,
        structured,
        log_preview(stripped, chars=_LOG_PREVIEW_CHARS),
    )

    if structured:
        # Some providers (e.g. Dashscope) require the word "json" when using json response_format.
        structured_prompt = stripped
        if "json" not in stripped.lower():
            structured_prompt = f"{stripped}\n\nRespond with JSON matching the provided schema."
        try:
            data = await invoke_structured_chat(
                chat,
                [HumanMessage(content=structured_prompt)],
                json_schema=response_schema,
                schema_name=response_schema_name,
                strict=strict,
                config=invoke_cfg,
            )
            out = json.dumps(data, ensure_ascii=False)
        except StructuredOutputError:
            raise
        except Exception as exc:
            msg = f"structured direct_llm failed: {exc}"
            raise StructuredOutputError(msg) from exc
    else:
        response = await chat.ainvoke([HumanMessage(content=stripped)], config=invoke_cfg)
        out = str(response.content).strip()
        if not out:
            out = "(Model returned empty content.)"

    logger.info(
        "[intent_hint direct_llm] response session_id=%s model=%s structured=%s content=%s",
        session_id,
        model_label,
        structured,
        log_preview(out, chars=_LOG_PREVIEW_CHARS),
    )
    return out
