"""Concrete InformationSource implementations.

Each source wraps existing Soothe tools behind the uniform
InformationSource protocol so the InquiryEngine can orchestrate
them without knowing implementation details.
"""

from __future__ import annotations

from .academic import AcademicSource
from .browser import BrowserSource
from .cli import CLISource
from .document import DocumentSource
from .filesystem import FilesystemSource
from .web import WebSource

__all__ = [
    "AcademicSource",
    "BrowserSource",
    "CLISource",
    "DocumentSource",
    "FilesystemSource",
    "WebSource",
]
