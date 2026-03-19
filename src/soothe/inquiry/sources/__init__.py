"""Concrete InformationSource implementations.

Each source wraps existing Soothe tools behind the uniform
InformationSource protocol so the InquiryEngine can orchestrate
them without knowing implementation details.
"""

from __future__ import annotations

from soothe.inquiry.sources.academic import AcademicSource
from soothe.inquiry.sources.browser import BrowserSource
from soothe.inquiry.sources.cli import CLISource
from soothe.inquiry.sources.document import DocumentSource
from soothe.inquiry.sources.filesystem import FilesystemSource
from soothe.inquiry.sources.web import WebSource

__all__ = [
    "AcademicSource",
    "BrowserSource",
    "CLISource",
    "DocumentSource",
    "FilesystemSource",
    "WebSource",
]
