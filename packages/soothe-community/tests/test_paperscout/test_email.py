"""Tests for PaperScout email formatting."""

from soothe_community.paperscout.email import (
    construct_email_content,
    create_empty_email_html,
    create_paper_html,
    get_stars_html,
)
from soothe_community.paperscout.models import ScoredPaper


def test_get_stars_html_low_score():
    """Test star rating for low score."""
    stars = get_stars_html(5.0)
    assert stars == ""


def test_get_stars_html_high_score():
    """Test star rating for high score."""
    stars = get_stars_html(8.5)
    assert "⭐" in stars


def test_get_stars_html_max_score():
    """Test star rating for max score."""
    stars = get_stars_html(10.0)
    assert stars.count("⭐") == 5


def test_create_paper_html(sample_arxiv_paper):
    """Test creating HTML for a paper."""
    scored_paper = ScoredPaper(
        paper=sample_arxiv_paper,
        score=7.5,
        relevance_factors={"test": 7.5},
    )

    html = create_paper_html(scored_paper)

    assert "Attention Is All You Need" in html
    assert "1706.03762" in html
    assert "Ashish Vaswani" in html


def test_create_empty_email_html():
    """Test creating empty email HTML."""
    html = create_empty_email_html()

    assert "No Papers Today" in html
    assert "Take a Rest" in html


def test_construct_email_content_empty():
    """Test constructing email with no papers."""
    email_content = construct_email_content([])

    assert "No Papers Today" in email_content.subject
    assert email_content.html_body is not None
    assert len(email_content.papers) == 0


def test_construct_email_content_with_papers(sample_arxiv_paper):
    """Test constructing email with papers."""
    scored_paper = ScoredPaper(
        paper=sample_arxiv_paper,
        score=7.5,
        relevance_factors={"test": 7.5},
    )

    email_content = construct_email_content([scored_paper])

    assert "PaperScout Digest" in email_content.subject
    assert "Attention Is All You Need" in email_content.html_body
    assert len(email_content.papers) == 1
