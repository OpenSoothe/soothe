"""Unified deferred skill search (substring / corpus matching)."""

from __future__ import annotations

from collections.abc import Sequence

from langchain_core.messages import HumanMessage

from soothe_nano.skills.index import SkillIndexEntry
from soothe_nano.skills.registry import ProgressiveSkillRegistry


def merge_search_results(
    substring_matches: Sequence[SkillIndexEntry],
    semantic_matches: Sequence[tuple[float, SkillIndexEntry]],
    *,
    limit: int,
) -> list[SkillIndexEntry]:
    """Merge primary and secondary hits; primary order first, then by score."""
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
    """Match core skills by name/tags in the goal text only (no semantic search)."""
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
    """Match skills from a user goal (name/tag corpus match + substring)."""
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
    """Discover deferred skills from a user goal (corpus name match + substring)."""
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
    """Search deferred skills via substring matching.

    Semantic Skillify search is owned by the daemon service and is not invoked
    from CoreAgent.
    """
    del config, catalog_by_name
    return registry.search_deferred(
        query,
        deferred,
        discovered=discovered,
        limit=limit,
    )


def latest_human_text(state: dict) -> str | None:
    """Return text from the most recent human message in agent state."""
    messages = state.get("messages") or []
    for msg in reversed(messages):
        if not isinstance(msg, HumanMessage):
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
