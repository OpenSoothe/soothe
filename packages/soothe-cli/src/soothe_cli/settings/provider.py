"""Auto-detect LLM provider from model name."""

from __future__ import annotations

from soothe_cli.settings.core import _get_settings


def detect_provider(model_name: str) -> str | None:
    """Auto-detect provider from model name."""
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
