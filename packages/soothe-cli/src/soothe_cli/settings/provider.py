"""Auto-detect LLM provider from model name."""

from __future__ import annotations

from soothe_cli.settings.core import _get_settings


def detect_provider(model_name: str) -> str | None:
    """Auto-detect provider from model name.

    Intentionally duplicates a subset of LangChain's
    `_attempt_infer_model_provider` because we need to resolve the provider
    **before** calling `init_chat_model` in order to:

    1. Build provider-specific kwargs (API base URLs, headers, etc.) that are
    passed *into* `init_chat_model`.
    2. Validate credentials early to surface user-friendly errors.

    Args:
    model_name: Model name to detect provider from.

    Returns:
    Provider name (openai, anthropic, google_genai, google_vertexai,
    nvidia) or `None` if the provider cannot be determined from the
    name alone.
    """
    model_lower = model_name.lower()

    if model_lower.startswith(("gpt-", "o1", "o3", "o4", "chatgpt")):
        return "openai"

    if model_lower.startswith("claude"):
        s = _get_settings()
        if not s.has_anthropic and s.has_vertex_ai:
            return "google_vertexai"
        return "anthropic"

    if model_lower.startswith("gemini"):
        s = _get_settings()
        if s.has_vertex_ai and not s.has_google:
            return "google_vertexai"
        return "google_genai"

    if model_lower.startswith(("nemotron", "nvidia/")):
        return "nvidia"

    return None
