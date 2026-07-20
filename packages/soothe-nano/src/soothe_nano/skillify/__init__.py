"""Daemon-shared Skillify skill warehouse indexing and semantic retrieval."""

from soothe_nano.config.models import SkillifyConfig

from . import events as _events  # noqa: F401 — register soothe.skillify.* wire types
from .models import SkillBundle, SkillRecord, SkillSearchResult
from .retriever import SkillRetriever, configure_vector_search_concurrency
from .service import (
    SkillifyService,
    get_skillify_service,
    resolve_warehouse_paths,
    start_skillify_service,
    stop_skillify_service,
)

__all__ = [
    "SkillBundle",
    "SkillRecord",
    "SkillRetriever",
    "SkillSearchResult",
    "SkillifyConfig",
    "SkillifyService",
    "configure_vector_search_concurrency",
    "get_skillify_service",
    "resolve_warehouse_paths",
    "start_skillify_service",
    "stop_skillify_service",
]
