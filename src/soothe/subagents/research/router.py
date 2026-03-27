"""SourceRouter -- deterministic source selection for the research engine.

Uses ``InformationSource.relevance_score()`` to rank sources per query
without any LLM calls.  Supports profile-based filtering so the caller
can restrict which source types are eligible.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .protocol import InformationSource, ResearchConfig, SourceType

logger = logging.getLogger(__name__)

_MIN_RELEVANCE: float = 0.1


class SourceRouter:
    """Select the best information sources for a given query.

    The router scores every registered source using its deterministic
    ``relevance_score`` method and returns the top candidates.

    Args:
        sources: All available InformationSource instances.
        config: ResearchConfig controlling max_sources_per_query, profiles, etc.
    """

    def __init__(
        self,
        sources: list[InformationSource],
        config: ResearchConfig | None = None,
    ) -> None:
        """Initialize the router with sources and optional config."""
        from .protocol import ResearchConfig

        self._sources = list(sources)
        self._config = config or ResearchConfig()

    # -- Public API ----------------------------------------------------------

    def select(
        self,
        query: str,
        *,
        domain: str | None = None,
        max_sources: int | None = None,
    ) -> list[InformationSource]:
        """Pick the best source(s) for *query*.

        Args:
            query: The search query to route.
            domain: Optional domain hint (e.g. ``"web"``, ``"code"``, ``"deep"``).
                When ``"auto"`` or ``None``, all enabled source types are eligible.
                Otherwise, the domain is resolved through ``source_profiles``.
            max_sources: Override ``config.max_sources_per_query``.

        Returns:
            Ordered list of best-matching sources (highest score first).
        """
        eligible = self._filter_by_domain(domain)
        if not eligible:
            logger.warning("No sources available for domain=%s, falling back to all", domain)
            eligible = self._sources

        scored: list[tuple[InformationSource, float]] = []
        for src in eligible:
            try:
                score = src.relevance_score(query)
            except Exception:
                logger.debug("relevance_score failed for %s", src.name, exc_info=True)
                score = 0.0
            scored.append((src, score))

        scored.sort(key=lambda t: t[1], reverse=True)

        limit = max_sources or self._config.max_sources_per_query
        selected = [src for src, score in scored[:limit] if score >= _MIN_RELEVANCE]

        if not selected and scored:
            selected = [scored[0][0]]

        logger.debug(
            "Router selected %d source(s) for query '%.60s': %s",
            len(selected),
            query,
            [(s.name, f"{sc:.2f}") for s, sc in scored[: len(selected)]],
        )
        return selected

    def available_source_types(self) -> list[SourceType]:
        """Return the distinct source types among registered sources."""
        seen: set[SourceType] = set()
        ordered: list[SourceType] = []
        for src in self._sources:
            st = src.source_type
            if st not in seen:
                seen.add(st)
                ordered.append(st)
        return ordered

    # -- Internals -----------------------------------------------------------

    def _filter_by_domain(self, domain: str | None) -> list[InformationSource]:
        """Restrict sources to those matching the domain profile."""
        if domain is None or domain == "auto":
            allowed: set[SourceType] = set(self._config.enabled_sources)
        else:
            profile_types = self._config.source_profiles.get(domain)
            if profile_types is not None:
                allowed = set(profile_types)
            else:
                allowed = set(self._config.enabled_sources)
                logger.warning("Unknown domain '%s', using all enabled sources", domain)

        return [s for s in self._sources if s.source_type in allowed]
