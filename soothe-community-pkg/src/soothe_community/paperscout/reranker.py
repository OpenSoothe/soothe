"""PaperScout paper reranking with sentence embeddings.

Reranks ArXiv papers by relevance to user's Zotero library using
sentence transformer embeddings and time-decay weighting.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime

import numpy as np

from soothe_community.paperscout.models import ArxivPaper, ScoredPaper, ZoteroPaper

logger = logging.getLogger(__name__)


class PaperReranker:
    """Paper reranking system with sentence transformer embeddings.

    Features:
    - Sentence Transformer embeddings (using GIST-small-Embedding-v0)
    - Time-decay weighting for corpus recency
    - Batch processing for efficiency
    - Error handling and fallback scoring
    """

    def __init__(
        self,
        papers: list[ArxivPaper],
        corpus: list[ZoteroPaper],
        cache_dir: str | None = None,
    ):
        """Initialize the reranker.

        Args:
            papers: List of ArXiv papers to rank.
            corpus: User's Zotero library for comparison.
            cache_dir: Directory for caching sentence transformer models.
        """
        self.papers = papers
        self.corpus = corpus
        self.cache_dir = cache_dir or os.environ.get(
            "SENTENCE_TRANSFORMERS_HOME",
            "/tmp/soothe_models",
        )

        if not self.papers:
            logger.warning("No papers provided for reranking")
        if not self.corpus:
            logger.warning("Empty corpus provided for reranking")

    def rerank(
        self,
        model_name: str = "avsolatorio/GIST-small-Embedding-v0",
        batch_size: int = 32,
        show_progress: bool = False,
    ) -> list[ScoredPaper]:
        """Rerank papers using sentence transformers.

        Args:
            model_name: Sentence transformer model to use.
            batch_size: Batch size for encoding.
            show_progress: Show progress bar during encoding.

        Returns:
            List of scored papers sorted by relevance (highest first).
        """
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as e:
            msg = "SentenceTransformer is not installed. Install with: pip install soothe[paperscout]"
            raise ImportError(msg) from e

        if not self.papers:
            logger.warning("No papers to rerank")
            return []

        if not self.corpus:
            logger.warning("Empty corpus, returning papers with default scores")
            return [
                ScoredPaper(
                    paper=paper,
                    score=5.0,
                    relevance_factors={"default": 5.0},
                )
                for paper in self.papers
            ]

        try:
            logger.info(f"Loading sentence transformer model: {model_name}")
            encoder = SentenceTransformer(model_name, cache_folder=self.cache_dir)

            # Sort corpus by date (newest first)
            sorted_corpus = []
            for item in self.corpus:
                if item.date_added:
                    sorted_corpus.append(item)

            sorted_corpus.sort(key=lambda x: x.date_added or datetime.min, reverse=True)

            if not sorted_corpus:
                logger.warning("No valid corpus items after filtering")
                return [
                    ScoredPaper(
                        paper=paper,
                        score=5.0,
                        relevance_factors={"fallback": 5.0},
                    )
                    for paper in self.papers
                ]

            # Time-decay weighting: newer papers weighted higher
            time_decay_weight = 1 / (1 + np.log10(np.arange(len(sorted_corpus)) + 1))
            time_decay_weight = time_decay_weight / time_decay_weight.sum()

            # Extract corpus abstracts
            corpus_texts = []
            valid_corpus_indices = []
            for idx, paper in enumerate(sorted_corpus):
                abstract = paper.abstract
                if abstract and len(abstract.strip()) > 0:
                    corpus_texts.append(abstract)
                    valid_corpus_indices.append(idx)

            if not corpus_texts:
                logger.warning("No valid abstracts in corpus")
                return [
                    ScoredPaper(
                        paper=paper,
                        score=5.0,
                        relevance_factors={"no_corpus_text": 5.0},
                    )
                    for paper in self.papers
                ]

            # Update time decay weights for valid corpus items
            time_decay_weight = time_decay_weight[valid_corpus_indices]
            time_decay_weight = time_decay_weight / time_decay_weight.sum()

            logger.info(f"Encoding {len(corpus_texts)} corpus abstracts")
            corpus_embeddings = encoder.encode(
                corpus_texts,
                batch_size=batch_size,
                show_progress_bar=show_progress,
                convert_to_tensor=False,
                normalize_embeddings=True,  # Normalize for cosine similarity
            )

            # Extract paper summaries
            paper_texts = []
            valid_papers = []
            for paper in self.papers:
                if paper.summary and len(paper.summary.strip()) > 0:
                    paper_texts.append(paper.summary)
                    valid_papers.append(paper)
                else:
                    logger.warning(f"Paper {paper.arxiv_id} has no summary, skipping")

            if not paper_texts:
                logger.warning("No valid paper summaries to rank")
                return []

            logger.info(f"Encoding {len(paper_texts)} paper summaries")
            paper_embeddings = encoder.encode(
                paper_texts,
                batch_size=batch_size,
                show_progress_bar=show_progress,
                convert_to_tensor=False,
                normalize_embeddings=True,
            )

            # Calculate similarity scores (cosine similarity)
            from sklearn.metrics.pairwise import cosine_similarity

            similarities = cosine_similarity(paper_embeddings, corpus_embeddings)

            # Calculate weighted scores with time decay
            scores = (similarities * time_decay_weight).sum(axis=1) * 10

            # Create scored papers
            scored_papers = []
            for paper, score, sim_vector in zip(valid_papers, scores, similarities):
                scored_paper = ScoredPaper(
                    paper=paper,
                    score=float(score),
                    relevance_factors={
                        "corpus_similarity": float(score),
                        "corpus_size": len(corpus_texts),
                        "max_similarity": float(sim_vector.max()),
                        "mean_similarity": float(sim_vector.mean()),
                    },
                )
                scored_papers.append(scored_paper)

            # Sort by score (highest first)
            scored_papers.sort(key=lambda x: x.score, reverse=True)

            logger.info(f"Successfully reranked {len(scored_papers)} papers")
            return scored_papers

        except Exception as e:
            logger.error(f"Error during reranking: {e}")
            # Fallback to basic scoring
            logger.info("Using fallback scoring")
            return [
                ScoredPaper(
                    paper=paper,
                    score=5.0,
                    relevance_factors={"error_fallback": 5.0},
                )
                for paper in self.papers
            ]


__all__ = ["PaperReranker"]
