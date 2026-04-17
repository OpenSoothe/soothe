"""Prefetched static prompt fragments for cache optimization (IG-183).

This module loads static XML fragments at import time to maximize prompt cache hit rate.
All fragments are read once and cached as module constants.

Cache Strategy (RFC-104, IG-183):
- Static fragments loaded at module init (0 file I/O per request)
- Module constants reused across all agent invocations
- Estimated cache hit rate: >95% for static content
- Estimated savings: -5-10ms per request, -200-400 tokens
"""

from pathlib import Path

_FRAGMENTS_DIR = Path(__file__).parent

# Prefetch static instruction fragments (IG-183 unified structure)
PLAN_EXECUTE_INSTRUCTIONS_FRAGMENT = (
    _FRAGMENTS_DIR.joinpath("instructions/plan_execute_instructions.xml")
    .read_text(encoding="utf-8")
    .strip()
)

# Prefetch static policy fragments (IG-183 merged policies)
EXECUTION_POLICIES_FRAGMENT = (
    _FRAGMENTS_DIR.joinpath("system/policies/execution_policies.xml")
    .read_text(encoding="utf-8")
    .strip()
)

__all__ = [
    "PLAN_EXECUTE_INSTRUCTIONS_FRAGMENT",
    "EXECUTION_POLICIES_FRAGMENT",
]
