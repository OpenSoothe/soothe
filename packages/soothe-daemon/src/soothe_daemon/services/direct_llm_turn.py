"""Direct model invocations for ``intent_hint`` loop_input turns (no Soothe agent)."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from langchain_core.messages import HumanMessage
from soothe.utils.llm.structured import StructuredOutputError, invoke_structured_chat
from soothe.utils.text_preview import log_preview

from soothe_daemon.protocol.intent_hints import (
    EMBED,
    IMAGE_TO_TEXT,
    OCR,
    TEXT_COMPLETION,
)
from soothe_daemon.services.image_understanding import _build_vision_invoke_config

logger = logging.getLogger(__name__)

_LOG_PREVIEW_CHARS = 800

_DEFAULT_VISION_INSTRUCTION = "Describe the attached image(s) and answer any implied questions."
_DEFAULT_OCR_INSTRUCTION = "Extract all visible text from the attached image(s)."


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


def _build_multimodal_message(
    *,
    user_text: str,
    attachments: list[dict[str, str]],
    default_instruction: str,
) -> HumanMessage:
    instruction = (user_text or "").strip() or default_instruction
    blocks: list[str | dict[str, Any]] = [{"type": "text", "text": instruction}]
    for att in attachments:
        mime = att["mime_type"]
        b64 = att["data"]
        blocks.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})
    return HumanMessage(content=blocks)


async def _invoke_chat_turn(
    config: Any,
    *,
    purpose: str,
    role: str,
    messages: list[HumanMessage],
    model: str | None = None,
    model_params: dict[str, Any] | None = None,
    session_id: str | None = None,
    response_schema: dict[str, Any] | None = None,
    response_schema_name: str | None = None,
    response_schema_strict: bool | None = None,
    empty_fallback: str,
    invoke_config_override: dict[str, Any] | None = None,
) -> str:
    m = model.strip() if isinstance(model, str) and model.strip() else None
    if m:
        chat = config.create_chat_model_for_spec(m, model_params=model_params or {})
        model_label = m
    else:
        chat = config.create_chat_model(role)
        model_label = role

    invoke_cfg = invoke_config_override or _build_direct_invoke_config(
        config,
        purpose=purpose,
        component=f"daemon.{purpose}",
        session_id=session_id,
    )
    structured = response_schema is not None
    strict = True if response_schema_strict is None else bool(response_schema_strict)

    logger.info(
        "[intent_hint %s] request session_id=%s model=%s structured=%s",
        purpose,
        session_id,
        model_label,
        structured,
    )

    if structured:
        try:
            data = await invoke_structured_chat(
                chat,
                messages,
                json_schema=response_schema,
                schema_name=response_schema_name,
                strict=strict,
                config=invoke_cfg,
            )
            out = json.dumps(data, ensure_ascii=False)
        except StructuredOutputError:
            raise
        except Exception as exc:
            msg = f"structured {purpose} failed: {exc}"
            raise StructuredOutputError(msg) from exc
    else:
        response = await chat.ainvoke(messages, config=invoke_cfg)
        out = str(response.content).strip()
        if not out:
            out = empty_fallback

    logger.info(
        "[intent_hint %s] response session_id=%s model=%s structured=%s content=%s",
        purpose,
        session_id,
        model_label,
        structured,
        log_preview(out, chars=_LOG_PREVIEW_CHARS),
    )
    return out


async def run_text_completion_turn(
    config: Any,
    *,
    user_text: str,
    model: str | None = None,
    model_params: dict[str, Any] | None = None,
    session_id: str | None = None,
    response_schema: dict[str, Any] | None = None,
    response_schema_name: str | None = None,
    response_schema_strict: bool | None = None,
) -> str:
    """Run the configured ``default`` role model on text (no attachments)."""
    stripped = (user_text or "").strip()
    if not stripped:
        msg = "text_completion requires non-empty user_text"
        raise ValueError(msg)

    return await _invoke_chat_turn(
        config,
        purpose=TEXT_COMPLETION,
        role="default",
        messages=[HumanMessage(content=stripped)],
        model=model,
        model_params=model_params,
        session_id=session_id,
        response_schema=response_schema,
        response_schema_name=response_schema_name,
        response_schema_strict=response_schema_strict,
        empty_fallback="(Model returned empty content.)",
    )


async def run_image_to_text_turn(
    config: Any,
    *,
    user_text: str,
    attachments: list[dict[str, str]],
    session_id: str | None = None,
    response_schema: dict[str, Any] | None = None,
    response_schema_name: str | None = None,
    response_schema_strict: bool | None = None,
) -> str:
    """Run the configured ``image`` role model on image attachments."""
    if not attachments:
        msg = "image_to_text requires at least one attachment"
        raise ValueError(msg)

    msg = _build_multimodal_message(
        user_text=user_text,
        attachments=attachments,
        default_instruction=_DEFAULT_VISION_INSTRUCTION,
    )
    att_meta = [
        {"mime_type": a["mime_type"], "data_chars": len(a.get("data", ""))} for a in attachments
    ]
    logger.info(
        "[intent_hint image_to_text] vision request session_id=%s attachments=%s",
        session_id,
        att_meta,
    )

    vision_cfg = _build_vision_invoke_config(config, session_id=session_id)
    return await _invoke_chat_turn(
        config,
        purpose=IMAGE_TO_TEXT,
        role="image",
        messages=[msg],
        session_id=session_id,
        response_schema=response_schema,
        response_schema_name=response_schema_name,
        response_schema_strict=response_schema_strict,
        empty_fallback="(Image model returned empty content.)",
        invoke_config_override=vision_cfg,
    )


async def run_ocr_turn(
    config: Any,
    *,
    user_text: str,
    attachments: list[dict[str, str]],
    session_id: str | None = None,
    response_schema: dict[str, Any] | None = None,
    response_schema_name: str | None = None,
    response_schema_strict: bool | None = None,
) -> str:
    """Run the configured ``ocr`` role model on image attachments."""
    if not attachments:
        msg = "ocr requires at least one attachment"
        raise ValueError(msg)

    msg = _build_multimodal_message(
        user_text=user_text,
        attachments=attachments,
        default_instruction=_DEFAULT_OCR_INSTRUCTION,
    )
    return await _invoke_chat_turn(
        config,
        purpose=OCR,
        role="ocr",
        messages=[msg],
        session_id=session_id,
        response_schema=response_schema,
        response_schema_name=response_schema_name,
        response_schema_strict=response_schema_strict,
        empty_fallback="(OCR model returned empty content.)",
    )


async def run_embed_turn(
    config: Any,
    *,
    user_text: str,
    session_id: str | None = None,
) -> str:
    """Embed user text with the configured ``embedding`` role model."""
    stripped = (user_text or "").strip()
    if not stripped:
        msg = "embed requires non-empty user_text"
        raise ValueError(msg)

    embedder = config.create_embedding_model()
    logger.info(
        "[intent_hint embed] request session_id=%s text=%s",
        session_id,
        log_preview(stripped, chars=_LOG_PREVIEW_CHARS),
    )
    if hasattr(embedder, "aembed_query"):
        vector = await embedder.aembed_query(stripped)
    else:
        vector = await asyncio.to_thread(embedder.embed_query, stripped)

    payload = {"embedding": vector, "dimensions": len(vector)}
    out = json.dumps(payload, ensure_ascii=False)
    logger.info(
        "[intent_hint embed] response session_id=%s dimensions=%s",
        session_id,
        len(vector),
    )
    return out


async def run_intent_hint_turn(
    config: Any,
    *,
    intent_hint: str,
    user_text: str,
    model: str | None = None,
    model_params: dict[str, Any] | None = None,
    session_id: str | None = None,
    attachments: list[dict[str, str]] | None = None,
    response_schema: dict[str, Any] | None = None,
    response_schema_name: str | None = None,
    response_schema_strict: bool | None = None,
) -> str:
    """Dispatch a daemon direct-model turn by normalized ``intent_hint``."""
    att = list(attachments or [])
    if intent_hint == TEXT_COMPLETION:
        return await run_text_completion_turn(
            config,
            user_text=user_text,
            model=model,
            model_params=model_params,
            session_id=session_id,
            response_schema=response_schema,
            response_schema_name=response_schema_name,
            response_schema_strict=response_schema_strict,
        )
    if intent_hint == IMAGE_TO_TEXT:
        return await run_image_to_text_turn(
            config,
            user_text=user_text,
            attachments=att,
            session_id=session_id,
            response_schema=response_schema,
            response_schema_name=response_schema_name,
            response_schema_strict=response_schema_strict,
        )
    if intent_hint == OCR:
        return await run_ocr_turn(
            config,
            user_text=user_text,
            attachments=att,
            session_id=session_id,
            response_schema=response_schema,
            response_schema_name=response_schema_name,
            response_schema_strict=response_schema_strict,
        )
    if intent_hint == EMBED:
        return await run_embed_turn(config, user_text=user_text, session_id=session_id)
    msg = f"unsupported intent_hint for direct model turn: {intent_hint}"
    raise ValueError(msg)
