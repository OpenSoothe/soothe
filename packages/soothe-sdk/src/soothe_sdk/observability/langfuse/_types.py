"""Typing helpers for Langfuse integration in shared SDK."""

from __future__ import annotations

from typing import Protocol


class LangfuseConfigLike(Protocol):
    """Minimal Langfuse config surface consumed by SDK helpers."""

    enabled: bool
    public_key: str | None
    secret_key: str | None
    host: str | None
    environment: str | None
    release: str | None
    sample_rate: float | None
    trace_name: str | None
    tags: list[str] | None
    user_id: str | None


class ObservabilityConfigLike(Protocol):
    """Minimal observability surface containing Langfuse settings."""

    langfuse: LangfuseConfigLike


class SootheConfigLike(Protocol):
    """Minimal config shape required by shared Langfuse helpers."""

    observability: ObservabilityConfigLike
