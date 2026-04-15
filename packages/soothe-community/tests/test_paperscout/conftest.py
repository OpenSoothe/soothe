"""Test fixtures for PaperScout plugin."""

from datetime import datetime
from unittest.mock import MagicMock

import pytest

from soothe_community.paperscout.models import ArxivPaper, ZoteroPaper
from soothe_community.paperscout.state import PaperScoutConfig, SmtpConfig, ZoteroConfig


@pytest.fixture
def sample_arxiv_paper():
    """Sample ArXiv paper for testing."""
    return ArxivPaper(
        title="Attention Is All You Need",
        summary="The dominant sequence transduction models are based on complex recurrent or convolutional neural networks...",
        authors=["Ashish Vaswani", "Noam Shazeer", "Niki Parmar"],
        arxiv_id="1706.03762",
        pdf_url="https://arxiv.org/pdf/1706.03762.pdf",
        published_date=datetime(2017, 6, 12),
    )


@pytest.fixture
def sample_zotero_paper():
    """Sample Zotero paper for testing."""
    return ZoteroPaper(
        zotero_item_key="ABC123",
        title="BERT: Pre-training of Deep Bidirectional Transformers",
        authors=["Jacob Devlin", "Ming-Wei Chang"],
        abstract="We introduce a new language representation model called BERT...",
        date_added=datetime(2019, 5, 24),
    )


@pytest.fixture
def mock_persist_store():
    """Mock PersistStore for testing."""
    store = MagicMock()
    store.get.return_value = None
    store.set.return_value = None
    return store


@pytest.fixture
def sample_config():
    """Sample PaperScout configuration."""
    return PaperScoutConfig(
        arxiv_categories=["cs.AI", "cs.LG"],
        max_papers=10,
        max_papers_queried=100,
        send_email=False,  # Disable email for tests
        smtp=SmtpConfig(
            host="smtp.example.com",
            port=587,
            user="test@example.com",
            password="testpass",
        ),
        zotero=ZoteroConfig(
            api_key="test_key",
            library_id="test_library",
        ),
    )
