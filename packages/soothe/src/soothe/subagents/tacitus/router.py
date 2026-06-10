"""PublicSemanticRouter — capability selection via sentence embeddings."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from soothe.utils.similarity import embedding_model_ready_without_download, semantic_similarity
from soothe.utils.text_preview import log_preview

if TYPE_CHECKING:
    from .protocol import CapabilityId, PublicInformationSource, SourceType, TacitusConfig

logger = logging.getLogger(__name__)

_MIN_RELEVANCE: float = 0.1
_URL_PATTERN = re.compile(r"https?://\S+")
_ARXIV_ID_PATTERN = re.compile(
    r"\b(?:arxiv:)?(\d{4}\.\d{4,5}(?:v\d+)?)\b",
    re.IGNORECASE,
)

# Maps deprecated domain hints to profile keys
_DOMAIN_ALIASES: dict[str, str] = {
    "auto": "public",
    "deep": "public",
    "code": "public",
}


class PublicSemanticRouter:
    """Select public sources using semantic similarity to capability descriptions."""

    def __init__(
        self,
        sources: list[PublicInformationSource],
        config: TacitusConfig | None = None,
    ) -> None:
        from .protocol import TacitusConfig

        self._sources = list(sources)
        self._config = config or TacitusConfig()
        self._capability_embeddings: dict[CapabilityId, list[float]] = {}
        self._embeddings_precomputed = False

    def _precompute_embeddings(self) -> None:
        if not embedding_model_ready_without_download():
            return
        for src in self._sources:
            cid = src.capability_id
            if cid in self._capability_embeddings:
                continue
            try:
                score = semantic_similarity(src.capability_description, src.capability_description)
                if score > 0:
                    self._capability_embeddings[cid] = self._embed_text(src.capability_description)
            except Exception:
                logger.debug("Failed to precompute embedding for %s", cid, exc_info=True)

    @staticmethod
    def _embed_text(text: str) -> list[float]:
        from soothe.utils.similarity import encode_texts, get_embedding_model

        model = get_embedding_model()
        if model is None:
            return []
        vectors = encode_texts(model, [text[:256]])
        return vectors[0] if vectors else []

    def _ensure_embeddings(self) -> None:
        if not self._embeddings_precomputed:
            self._precompute_embeddings()
            self._embeddings_precomputed = True

    def select(
        self,
        query: str,
        *,
        domain: str | None = None,
        max_sources: int | None = None,
    ) -> list[PublicInformationSource]:
        """Pick the best source(s) for *query*."""
        self._ensure_embeddings()
        eligible = self._filter_by_domain(domain)
        if not eligible:
            logger.warning("No sources for domain=%s, using all", domain)
            eligible = self._sources

        scored = self._score_sources(query, eligible)
        scored.sort(key=lambda t: t[1], reverse=True)

        limit = max_sources or self._config.max_sources_per_query
        threshold = self._config.routing.semantic_threshold
        selected = [src for src, sc in scored[:limit] if sc >= max(_MIN_RELEVANCE, threshold)]

        if not selected and scored:
            selected = [scored[0][0]]

        logger.debug(
            "Tacitus router selected %d for '%s': %s",
            len(selected),
            log_preview(query, 60),
            [(s.capability_id, f"{sc:.2f}") for s, sc in scored[: len(selected) or 1]],
        )
        return selected

    def _score_sources(
        self,
        query: str,
        eligible: list[PublicInformationSource],
    ) -> list[tuple[PublicInformationSource, float]]:
        fast_path_boosts = self._fast_path_boosts(query)
        fallback = self._config.routing.fallback_score

        if embedding_model_ready_without_download():
            query_vec = self._embed_text(query[:256])
            if query_vec:
                scored: list[tuple[PublicInformationSource, float]] = []
                for src in eligible:
                    cid = src.capability_id
                    cap_vec = self._capability_embeddings.get(cid)
                    if not cap_vec:
                        cap_vec = self._embed_text(src.capability_description[:256])
                        if cap_vec:
                            self._capability_embeddings[cid] = cap_vec
                    if cap_vec:
                        from soothe.utils.similarity import cosine_similarity

                        base = cosine_similarity(query_vec, cap_vec)
                    else:
                        base = fallback
                    boost = fast_path_boosts.get(cid, 0.0)
                    scored.append((src, min(1.0, base + boost)))
                return scored

        # No local embeddings: uniform score + fast-path boosts
        return [
            (src, min(1.0, fallback + fast_path_boosts.get(src.capability_id, 0.0)))
            for src in eligible
        ]

    @staticmethod
    def _fast_path_boosts(query: str) -> dict[CapabilityId, float]:
        boosts: dict[str, float] = {}
        if _URL_PATTERN.search(query):
            boosts["url_crawl"] = 0.4
        if _ARXIV_ID_PATTERN.search(query):
            boosts["academic_search"] = 0.35
        return boosts  # type: ignore[return-value]

    def _filter_by_domain(self, domain: str | None) -> list[PublicInformationSource]:
        raw = (domain or self._config.default_domain).strip().lower()
        profile_key = _DOMAIN_ALIASES.get(raw, raw)
        profile = self._config.capability_profiles.get(profile_key)
        if profile is None:
            profile = self._config.capability_profiles.get("public", [])
            if profile_key not in ("public", "web", "academic"):
                logger.warning("Unknown domain '%s', using public profile", domain)

        allowed = set(profile)
        enabled = set(self._config.enabled_capabilities)
        allowed &= enabled
        return [s for s in self._sources if s.capability_id in allowed]

    def available_source_types(self) -> list[SourceType]:
        seen: set[SourceType] = set()
        ordered: list[SourceType] = []
        for src in self._sources:
            st = src.source_type
            if st not in seen:
                seen.add(st)
                ordered.append(st)
        return ordered
