"""Tests for PaperScout reranker."""

import pytest

from soothe_community.paperscout.models import ArxivPaper, ZoteroPaper
from soothe_community.paperscout.reranker import PaperReranker


def test_reranker_initialization(sample_arxiv_paper, sample_zotero_paper):
    """Test PaperReranker initialization."""
    reranker = PaperReranker(
        papers=[sample_arxiv_paper],
        corpus=[sample_zotero_paper],
    )

    assert reranker is not None
    assert len(reranker.papers) == 1
    assert len(reranker.corpus) == 1


def test_reranker_empty_papers(sample_zotero_paper):
    """Test reranker with empty papers list."""
    reranker = PaperReranker(
        papers=[],
        corpus=[sample_zotero_paper],
    )

    scored = reranker.rerank()
    assert scored == []


def test_reranker_empty_corpus(sample_arxiv_paper):
    """Test reranker with empty corpus (should use default scores)."""
    reranker = PaperReranker(
        papers=[sample_arxiv_paper],
        corpus=[],
    )

    scored = reranker.rerank()
    assert len(scored) == 1
    assert scored[0].score == 5.0  # Default fallback score


@pytest.mark.skip(reason="Requires sentence-transformers model download")
def test_reranker_basic_scoring(sample_arxiv_paper, sample_zotero_paper):
    """Test basic paper scoring (integration test, requires model)."""
    reranker = PaperReranker(
        papers=[sample_arxiv_paper],
        corpus=[sample_zotero_paper],
    )

    scored = reranker.rerank()
    assert len(scored) == 1
    assert scored[0].score > 0.0
    assert "corpus_similarity" in scored[0].relevance_factors
