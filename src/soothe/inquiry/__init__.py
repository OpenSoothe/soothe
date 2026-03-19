"""Tool-agnostic Inquiry Engine for iterative research across information sources.

The inquiry engine generalises the research paradigm (query -> gather -> reflect
-> iterate -> synthesise) to work with any information source: web search, local
files, CLI tools, browser, documents, etc.

Core abstractions:

- ``InformationSource`` -- protocol for any queryable information source
- ``InquiryEngine`` -- LangGraph-based iterative research loop
- ``SourceRouter`` -- deterministic routing to pick best sources per query
"""

from __future__ import annotations

from soothe.inquiry.protocol import (
    GatherContext,
    InformationSource,
    InquiryConfig,
    SourceResult,
)

__all__ = [
    "GatherContext",
    "InformationSource",
    "InquiryConfig",
    "SourceResult",
]
