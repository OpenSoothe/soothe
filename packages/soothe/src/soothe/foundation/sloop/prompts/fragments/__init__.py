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
"""

from pathlib import Path

_FRAGMENTS_DIR = Path(__file__).parent


def _read(relative: str, *, strip: bool = False) -> str:
    text = _FRAGMENTS_DIR.joinpath(relative).read_text(encoding="utf-8")
    return text.strip() if strip else text


# ---------------------------------------------------------------------------
# Plan / execution instructions (existing)
# ---------------------------------------------------------------------------

# Plan-assess only: matches StatusAssessment schema (IG-372)
PLAN_ASSESS_INSTRUCTIONS_FRAGMENT = _read("instructions/plan_assess_instructions.xml", strip=True)

PLAN_GAP_ANALYSIS_INSTRUCTIONS_FRAGMENT = _read(
    "instructions/plan_gap_analysis_instructions.xml", strip=True
)

# Plan-generate only: matches PlanGeneration schema (IG-329)
PLAN_GENERATE_INSTRUCTIONS_FRAGMENT = _read(
    "instructions/plan_generate_instructions.xml", strip=True
)

# Continuation discriminator (RFC-226, RFC-214 §4, IG-538)
PLAN_CONTINUATION_DISCRIMINATE_FRAGMENT = _read(
    "instructions/plan_continuation_discriminate.xml", strip=True
)

# Prefetch static policy fragments (IG-183 merged policies)
EXECUTION_POLICIES_FRAGMENT = _read("system/policies/execution_policies.xml", strip=True)


# ---------------------------------------------------------------------------
# System prompts and response-length guides
# (consumed by ``soothe.foundation.sloop.prompts.system_templates``).
# Byte-for-byte preserved from previous Python literals — do not ``.strip()``.
# ---------------------------------------------------------------------------

DEFAULT_SYSTEM_PROMPT_BODY_FRAGMENT = _read("system/prompts/default_system_body.xml")
ASSISTANT_IDENTITY_FRAGMENT = _read("system/prompts/assistant_identity.xml", strip=True)
PROMPT_TIMESTAMP_FRAGMENT = _read("system/prompts/prompt_timestamp.xml", strip=True)
SIMPLE_SYSTEM_PROMPT_FRAGMENT = _read("system/prompts/simple_system.xml")
MEDIUM_SYSTEM_PROMPT_FRAGMENT = _read("system/prompts/medium_system.xml")

ARCHITECTURE_ANALYSIS_GUIDE_FRAGMENT = _read("system/response_guides/architecture_analysis.xml")
RESEARCH_SYNTHESIS_GUIDE_FRAGMENT = _read("system/response_guides/research_synthesis.xml")
LOOP_CONTINUATION_GUIDE_FRAGMENT = _read("system/response_guides/loop_continuation.xml")


# ---------------------------------------------------------------------------
# Classifier prompts (non-intake; intake loads via ``intention/prompts.py``)
# ---------------------------------------------------------------------------

SCENARIO_CLASSIFIER_SYSTEM_FRAGMENT = _read(
    "classifiers/scenario_classifier_system.xml", strip=True
)
SCENARIO_CLASSIFIER_USER_FRAGMENT = _read("classifiers/scenario_classifier_user.xml", strip=True)


# ---------------------------------------------------------------------------
# Planning prompts
# ---------------------------------------------------------------------------

STRUCTURED_PLAN_PARSE_PROMPT_FRAGMENT = _read("planning/structured_plan_parse.xml")


__all__ = [
    "ARCHITECTURE_ANALYSIS_GUIDE_FRAGMENT",
    "ASSISTANT_IDENTITY_FRAGMENT",
    "DEFAULT_SYSTEM_PROMPT_BODY_FRAGMENT",
    "EXECUTION_POLICIES_FRAGMENT",
    "LOOP_CONTINUATION_GUIDE_FRAGMENT",
    "MEDIUM_SYSTEM_PROMPT_FRAGMENT",
    "PLAN_ASSESS_INSTRUCTIONS_FRAGMENT",
    "PLAN_GAP_ANALYSIS_INSTRUCTIONS_FRAGMENT",
    "PLAN_CONTINUATION_DISCRIMINATE_FRAGMENT",
    "PLAN_GENERATE_INSTRUCTIONS_FRAGMENT",
    "PROMPT_TIMESTAMP_FRAGMENT",
    "RESEARCH_SYNTHESIS_GUIDE_FRAGMENT",
    "SCENARIO_CLASSIFIER_SYSTEM_FRAGMENT",
    "SCENARIO_CLASSIFIER_USER_FRAGMENT",
    "SIMPLE_SYSTEM_PROMPT_FRAGMENT",
    "STRUCTURED_PLAN_PARSE_PROMPT_FRAGMENT",
]
