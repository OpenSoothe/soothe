"""Prefetched static StrangeLoop prompt fragments (IG-183).

All fragments are read once at import time to maximize prompt cache hit rate.
Cache Strategy (RFC-104, IG-183):
- Static fragments loaded at module init (0 file I/O per request)
- Module constants reused across all StrangeLoop invocations
- Estimated cache hit rate: >95% for static content

Asset layout (IG-706): ``intake/``, ``plan/``, ``execute/`` data dirs.

Jinja2 templates (e.g. ``synthesis_report_system.xml``) are loaded on demand via
``soothe.prompts.loader.load_prompt_fragment`` (shared systemwide loader).
"""

from pathlib import Path

_FRAGMENTS_DIR = Path(__file__).parent


def _read(relative: str, *, strip: bool = False) -> str:
    text = _FRAGMENTS_DIR.joinpath(relative).read_text(encoding="utf-8")
    return text.strip() if strip else text


# ---------------------------------------------------------------------------
# Plan-phase instructions (``plan/``)
# ---------------------------------------------------------------------------

# Plan-assess only: matches StatusAssessment schema (IG-372)
PLAN_ASSESS_INSTRUCTIONS_FRAGMENT = _read("plan/assess_instructions.xml", strip=True)

PLAN_GAP_ANALYSIS_INSTRUCTIONS_FRAGMENT = _read("plan/gap_analysis_instructions.xml", strip=True)

# Plan-generate only: matches PlanGenerationWire schema (IG-568)
PLAN_GENERATE_INSTRUCTIONS_FRAGMENT = _read("plan/generate_instructions.xml", strip=True)

# Continuation discriminator (RFC-226, RFC-214 §4, IG-538)
PLAN_CONTINUATION_DISCRIMINATE_FRAGMENT = _read("plan/continuation_discriminate.xml", strip=True)

STRUCTURED_PLAN_PARSE_PROMPT_FRAGMENT = _read("plan/structured_plan_parse.xml")

# ---------------------------------------------------------------------------
# Execute-phase policies (``execute/``)
# ---------------------------------------------------------------------------

EXECUTION_POLICIES_FRAGMENT = _read("execute/execution_policies.xml", strip=True)

# ---------------------------------------------------------------------------
# Intake classifier prompts (``intake/``)
# ---------------------------------------------------------------------------

INTAKE_PASS1_SYSTEM_FRAGMENT = _read("intake/pass1_system.xml", strip=True)
INTAKE_PASS2_SYSTEM_FRAGMENT = _read("intake/pass2_system.xml", strip=True)
INTAKE_PASS1_SOCIAL_REPLY_FRAGMENT = _read("intake/pass1_social_reply.xml", strip=True)


__all__ = [
    "EXECUTION_POLICIES_FRAGMENT",
    "INTAKE_PASS1_SOCIAL_REPLY_FRAGMENT",
    "INTAKE_PASS1_SYSTEM_FRAGMENT",
    "INTAKE_PASS2_SYSTEM_FRAGMENT",
    "PLAN_ASSESS_INSTRUCTIONS_FRAGMENT",
    "PLAN_CONTINUATION_DISCRIMINATE_FRAGMENT",
    "PLAN_GAP_ANALYSIS_INSTRUCTIONS_FRAGMENT",
    "PLAN_GENERATE_INSTRUCTIONS_FRAGMENT",
    "STRUCTURED_PLAN_PARSE_PROMPT_FRAGMENT",
]
