"""Prefetched static StrangeLoop prompt fragments.

All fragments are read once at import time to maximize prompt cache hit rate.
Cache Strategy (RFC-104):
- Static fragments loaded at module init (0 file I/O per request)
- Module constants reused across all StrangeLoop invocations
- Estimated cache hit rate: >95% for static content

Asset layout: ``intake/`` (plan-phase fragments removed after RFC-904).

Jinja2 templates (e.g. ``synthesis_report_system.xml``) are loaded on demand via
``soothe.prompts.loader.load_prompt_fragment`` (shared systemwide loader).
"""

from pathlib import Path

_FRAGMENTS_DIR = Path(__file__).parent


def _read(relative: str, *, strip: bool = False) -> str:
    text = _FRAGMENTS_DIR.joinpath(relative).read_text(encoding="utf-8")
    return text.strip() if strip else text


INTAKE_PASS1_SYSTEM_FRAGMENT = _read("intake/pass1_system.xml", strip=True)
INTAKE_PASS1_SOCIAL_REPLY_FRAGMENT = _read("intake/pass1_social_reply.xml", strip=True)


__all__ = [
    "INTAKE_PASS1_SOCIAL_REPLY_FRAGMENT",
    "INTAKE_PASS1_SYSTEM_FRAGMENT",
]
