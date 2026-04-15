"""Tests for PaperScout data models."""

from datetime import datetime

from soothe_community.paperscout.models import (
    ArxivPaper,
    DateRange,
    EmailContent,
    NotificationRecord,
    ScoredPaper,
)


def test_arxiv_paper_creation(sample_arxiv_paper):
    """Test ArxivPaper model creation."""
    assert sample_arxiv_paper.title == "Attention Is All You Need"
    assert sample_arxiv_paper.arxiv_id == "1706.03762"
    assert len(sample_arxiv_paper.authors) == 3
    assert sample_arxiv_paper.score == 0.0  # Default value
    assert sample_arxiv_paper.code_url is None  # Optional field


def test_arxiv_paper_extra_fields():
    """Test that ArxivPaper allows extra fields."""
    paper = ArxivPaper(
        title="Test Paper",
        summary="Test summary",
        authors=["Author One"],
        arxiv_id="1234.5678",
        pdf_url="https://arxiv.org/pdf/1234.5678.pdf",
        published_date=datetime.now(),
        custom_field="custom_value",  # Should be allowed
    )

    assert paper.custom_field == "custom_value"


def test_zotero_paper_creation(sample_zotero_paper):
    """Test ZoteroPaper model creation."""
    assert sample_zotero_paper.zotero_item_key == "ABC123"
    assert sample_zotero_paper.title == "BERT: Pre-training of Deep Bidirectional Transformers"
    assert sample_zotero_paper.abstract is not None
    assert len(sample_zotero_paper.authors) == 2


def test_scored_paper_creation(sample_arxiv_paper):
    """Test ScoredPaper model creation."""
    scored = ScoredPaper(
        paper=sample_arxiv_paper,
        score=8.5,
        relevance_factors={"corpus_similarity": 8.5, "corpus_size": 100},
    )

    assert scored.paper == sample_arxiv_paper
    assert scored.score == 8.5
    assert scored.relevance_factors["corpus_similarity"] == 8.5


def test_email_content_creation():
    """Test EmailContent model creation."""
    email = EmailContent(
        subject="PaperScout Digest 2024/03/25",
        html_body="<html><body>Test</body></html>",
        text_body="Test",
        papers=[],
    )

    assert email.subject == "PaperScout Digest 2024/03/25"
    assert email.html_body == "<html><body>Test</body></html>"
    assert email.text_body == "Test"
    assert email.papers == []


def test_notification_record_creation():
    """Test NotificationRecord model creation."""
    from datetime import date

    record = NotificationRecord(
        date=date.today(),
        papers_count=10,
        recipient="user@example.com",
        arxiv_ids=["1234.5678", "8765.4321"],
        sent_at=datetime.now(),
        success=True,
    )

    assert record.success is True
    assert record.papers_count == 10
    assert len(record.arxiv_ids) == 2


def test_date_range_creation():
    """Test DateRange model creation."""
    from datetime import date

    date_range = DateRange(
        start_date=date(2024, 3, 1),
        end_date=date(2024, 3, 7),
        category="cs.AI",
    )

    assert date_range.category == "cs.AI"
    assert date_range.start_date == date(2024, 3, 1)
    assert date_range.end_date == date(2024, 3, 7)
