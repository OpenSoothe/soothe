"""Shared heuristic scoring utilities for InformationSource implementations.

Provides lightweight keyword/pattern-based relevance scoring that avoids
LLM calls.  Each source uses these helpers in its ``relevance_score`` method
so the SourceRouter can make fast, deterministic routing decisions.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Keyword sets
# ---------------------------------------------------------------------------

_ACADEMIC_KEYWORDS: frozenset[str] = frozenset(
    {
        "paper",
        "papers",
        "research",
        "study",
        "studies",
        "journal",
        "arxiv",
        "thesis",
        "dissertation",
        "algorithm",
        "theorem",
        "proof",
        "hypothesis",
        "peer-reviewed",
        "citation",
        "citations",
        "published",
        "conference",
        "proceedings",
        "survey",
        "literature",
        "meta-analysis",
        "empirical",
        "methodology",
        "quantitative",
        "qualitative",
    }
)

_ENCYCLOPEDIC_KEYWORDS: frozenset[str] = frozenset(
    {
        "what is",
        "who is",
        "who was",
        "define",
        "definition",
        "history of",
        "overview of",
        "biography",
        "wikipedia",
        "encyclopedia",
        "concept of",
        "meaning of",
    }
)

_CODE_KEYWORDS: frozenset[str] = frozenset(
    {
        "function",
        "class",
        "method",
        "module",
        "import",
        "implementation",
        "codebase",
        "source code",
        "repository",
        "variable",
        "interface",
        "struct",
        "enum",
        "decorator",
        "annotation",
    }
)

_CLI_KEYWORDS: frozenset[str] = frozenset(
    {
        "git log",
        "git history",
        "git blame",
        "process",
        "running",
        "installed",
        "version",
        "system info",
        "disk usage",
        "environment",
        "env var",
        "port",
        "network",
        "service",
        "docker",
        "container",
    }
)

_DOCUMENT_KEYWORDS: frozenset[str] = frozenset(
    {
        "pdf",
        "docx",
        "document",
        "report",
        "specification",
        "manual",
        "readme",
        "changelog",
    }
)

_BROWSER_KEYWORDS: frozenset[str] = frozenset(
    {
        "login",
        "sign in",
        "form",
        "dashboard",
        "interactive",
        "javascript",
        "spa",
        "single page",
        "dynamic content",
        "captcha",
        "screenshot",
    }
)

# Patterns
_FILE_PATH_PATTERN = re.compile(
    r"(?:^|[\s\"'])"
    r"(?:\.{0,2}/[\w./-]+|[\w-]+\.(?:py|js|ts|rs|go|java|c|cpp|h|rb|sh|yaml|yml|toml|json|md|txt))"
)
_URL_PATTERN = re.compile(r"https?://\S+")


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------


def keyword_score(query: str, keywords: frozenset[str], *, weight: float = 0.15) -> float:
    """Score a query against a keyword set.

    Args:
        query: The search query (lowered by caller for efficiency).
        keywords: Set of indicator keywords/phrases.
        weight: Score contribution per matched keyword.

    Returns:
        Cumulative score (not clamped -- caller should clamp to [0, 1]).
    """
    q = query.lower()
    return sum(weight for kw in keywords if kw in q)


def has_file_path(query: str) -> bool:
    """Return True if the query contains something that looks like a file path."""
    return bool(_FILE_PATH_PATTERN.search(query))


def has_url(query: str) -> bool:
    """Return True if the query contains an HTTP(S) URL."""
    return bool(_URL_PATTERN.search(query))
