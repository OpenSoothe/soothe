"""Unified deferred skill search (substring + optional Skillify semantic)."""

from __future__ import annotations

import logging
from collections.abc import Sequence

from langchain_core.messages import HumanMessage

from soothe_nano.skills.index import SkillIndexEntry
from soothe_nano.skills.registry import ProgressiveSkillRegistry

logger = logging.getLogger(__name__)


def _progressive_skills_settings(config: object):
    """Resolve progressive-skills settings from SootheConfig or test mocks."""
    from soothe_nano.config import SootheConfig
    from soothe_nano.config.models import ProgressiveSkillsConfig

    if isinstance(config, SootheConfig):
        return config.progressive_skills
    ps = getattr(config, "progressive_skills", None)
    if ps is not None:
        return ps
    return ProgressiveSkillsConfig()


def entry_from_skill_record(
    *,
    name: str,
    description: str,
    path: str,
    tags: list[str] | None = None,
) -> SkillIndexEntry:
    """Build a catalog entry from Skillify vector metadata."""
    tag_str = ", ".join(tags) if tags else ""
    return SkillIndexEntry(
        name=name,
        description=description,
        tags=tag_str,
        source="user",
        path=path,
        mtime=0.0,
    )


def merge_search_results(
    substring_matches: Sequence[SkillIndexEntry],
    semantic_matches: Sequence[tuple[float, SkillIndexEntry]],
    *,
    limit: int,
) -> list[SkillIndexEntry]:
    """Merge substring and semantic hits; substring order first, then by score."""
    out: list[SkillIndexEntry] = []
    seen: set[str] = set()
    for entry in substring_matches:
        if entry.name in seen:
            continue
        seen.add(entry.name)
        out.append(entry)
        if len(out) >= limit:
            return out
    ranked = sorted(semantic_matches, key=lambda item: (-item[0], item[1].name.lower()))
    for _score, entry in ranked:
        if entry.name in seen:
            continue
        seen.add(entry.name)
        out.append(entry)
        if len(out) >= limit:
            break
    return out


def prefetch_core_skills_from_corpus(
    goal: str,
    core_entries: Sequence[SkillIndexEntry],
    *,
    discovered: set[str],
    limit: int,
    registry: ProgressiveSkillRegistry,
) -> list[SkillIndexEntry]:
    """Match core skills by name/tags in the goal text only (no semantic search).

    Used for turn-0 core auto-invoke so unrelated builtin skills are not pulled
    in via Skillify semantic fill when ``intent_prefetch_top_k`` > 1.
    """
    return registry.match_deferred_in_corpus(
        goal,
        core_entries,
        discovered=discovered,
        limit=limit,
    )


async def prefetch_skills_from_goal(
    goal: str,
    entries: Sequence[SkillIndexEntry],
    *,
    discovered: set[str],
    limit: int,
    registry: ProgressiveSkillRegistry,
    config: object,
    catalog_by_name: dict[str, SkillIndexEntry],
) -> list[SkillIndexEntry]:
    """Match skills from a user goal (name/tag corpus match + substring + optional semantic)."""
    corpus_matches = registry.match_deferred_in_corpus(
        goal,
        entries,
        discovered=discovered,
        limit=limit,
    )
    discovered_with_corpus = discovered | {entry.name for entry in corpus_matches}
    searched = await search_deferred_skills(
        goal,
        entries,
        discovered=discovered_with_corpus,
        limit=limit,
        registry=registry,
        config=config,
        catalog_by_name=catalog_by_name,
    )
    return merge_search_results(
        corpus_matches,
        [(0.0, entry) for entry in searched],
        limit=limit,
    )


async def prefetch_deferred_skills(
    goal: str,
    deferred: Sequence[SkillIndexEntry],
    *,
    discovered: set[str],
    limit: int,
    registry: ProgressiveSkillRegistry,
    config: object,
    catalog_by_name: dict[str, SkillIndexEntry],
) -> list[SkillIndexEntry]:
    """Discover deferred skills from a user goal (corpus name match + optional semantic)."""
    return await prefetch_skills_from_goal(
        goal,
        deferred,
        discovered=discovered,
        limit=limit,
        registry=registry,
        config=config,
        catalog_by_name=catalog_by_name,
    )


async def search_deferred_skills(
    query: str,
    deferred: Sequence[SkillIndexEntry],
    *,
    discovered: set[str],
    limit: int,
    registry: ProgressiveSkillRegistry,
    config: object,
    catalog_by_name: dict[str, SkillIndexEntry],
) -> list[SkillIndexEntry]:
    """Search deferred skills via substring and optional Skillify semantic backend."""
    from soothe_nano.config import SootheConfig

    ps = _progressive_skills_settings(config)
    allowed_names = {entry.name for entry in deferred}

    substring = registry.search_deferred(
        query,
        deferred,
        discovered=discovered,
        limit=limit,
    )

    if not ps.semantic_search_enabled:
        return substring

    if len(substring) >= limit:
        return substring[:limit]

    service = None
    try:
        from soothe_nano.skillify import start_skillify_service

        if not isinstance(config, SootheConfig):
            return substring
        service = await start_skillify_service(config)
    except Exception:
        logger.debug("[Skill] Skillify import failed", exc_info=True)
        return substring

    if service is None:
        return substring

    try:
        bundle = await service.retrieve(query, top_k=limit)
    except Exception:
        logger.debug("[Skill] Skillify retrieve failed", exc_info=True)
        return substring

    if bundle.query.startswith("[Indexing in progress]") or bundle.query.startswith(
        "[Embedding unavailable]"
    ):
        return substring

    semantic: list[tuple[float, SkillIndexEntry]] = []
    min_score = float(ps.semantic_search_min_score)
    for result in bundle.results:
        name = result.record.name
        if name not in allowed_names:
            continue
        if name in discovered:
            continue
        if result.score < min_score:
            continue
        entry = catalog_by_name.get(name)
        if entry is None:
            entry = entry_from_skill_record(
                name=result.record.name,
                description=result.record.description,
                path=result.record.path,
                tags=result.record.tags,
            )
        semantic.append((result.score, entry))

    remaining = max(0, limit - len(substring))
    if remaining == 0:
        return substring
    merged = merge_search_results(substring, semantic, limit=limit)
    return merged


def latest_human_text(state: dict) -> str | None:
    """Return text from the most recent human message in agent state."""
    from soothe_nano.utils.loop_messages import LoopHumanMessage

    messages = state.get("messages") or []
    for msg in reversed(messages):
        if not isinstance(msg, (HumanMessage, LoopHumanMessage)):
            continue
        content = msg.content
        if isinstance(content, str):
            text = content.strip()
            if text:
                return text
        elif isinstance(content, list):
            parts: list[str] = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(str(block.get("text", "")))
                elif isinstance(block, str):
                    parts.append(block)
            text = " ".join(parts).strip()
            if text:
                return text
    return None
