"""Prefetched static prompt fragments for cache optimization (IG-183).

This module loads static XML fragments at import time to maximize prompt cache hit rate.
All fragments are read once and cached as module constants.

Cache Strategy (RFC-104, IG-183):
- Static fragments loaded at module init (0 file I/O per request)
- Module constants reused across all agent invocations
- Estimated cache hit rate: >95% for static content
- Estimated savings: -5-10ms per request, -200-400 tokens

Jinja2 templates under ``instructions/`` (e.g. ``synthesis_report_system.xml``) are
loaded on demand via ``prompts.loader.load_prompt_fragment``.

StrangeLoop-specific fragments (plan_assess, plan_generate, continuation,
gap_analysis, execution_policies, structured_plan_parse, intake classifiers)
live in ``soothe.sloop.prompts.fragments`` (migrated in HCD-02).
"""

# Re-export facade — canonical source: soothe_nano.prompts.fragments
# (nano owns the identity / system-prompt body / complexity fragments
#  re-exported below; host-only XML files loaded further down are local).

from pathlib import Path

from soothe_nano.prompts.fragments import (
    ASSISTANT_IDENTITY_FRAGMENT,
    DEFAULT_SYSTEM_PROMPT_BODY_FRAGMENT,
    MEDIUM_SYSTEM_PROMPT_FRAGMENT,
    SIMPLE_SYSTEM_PROMPT_FRAGMENT,
)

_FRAGMENTS_DIR = Path(__file__).parent


def _read(relative: str, *, strip: bool = False) -> str:
    text = _FRAGMENTS_DIR.joinpath(relative).read_text(encoding="utf-8")
    return text.strip() if strip else text


# ---------------------------------------------------------------------------
# System prompt fragments
# (consumed by ``soothe.prompts.system_templates`` / host loop builders).
# Byte-for-byte preserved from previous Python literals — do not ``.strip()``.
# ---------------------------------------------------------------------------

PROMPT_TIMESTAMP_FRAGMENT = _read("system/prompt_timestamp.xml", strip=True)


# ---------------------------------------------------------------------------
# Classifier prompts (synthesis scenario — shared systemwide)
# Intake classifier fragments live in ``soothe.sloop.prompts.fragments``.
# ---------------------------------------------------------------------------

SCENARIO_CLASSIFIER_SYSTEM_FRAGMENT = _read(
    "classifiers/scenario_classifier_system.xml", strip=True
)
SCENARIO_CLASSIFIER_USER_FRAGMENT = _read("classifiers/scenario_classifier_user.xml", strip=True)


__all__ = [
    "ASSISTANT_IDENTITY_FRAGMENT",
    "DEFAULT_SYSTEM_PROMPT_BODY_FRAGMENT",
    "MEDIUM_SYSTEM_PROMPT_FRAGMENT",
    "PROMPT_TIMESTAMP_FRAGMENT",
    "SCENARIO_CLASSIFIER_SYSTEM_FRAGMENT",
    "SCENARIO_CLASSIFIER_USER_FRAGMENT",
    "SIMPLE_SYSTEM_PROMPT_FRAGMENT",
]
