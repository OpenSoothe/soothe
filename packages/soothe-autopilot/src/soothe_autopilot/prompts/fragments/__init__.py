"""Prefetched static Autopilot prompt fragments.

All fragments are read once at import time to maximize prompt cache hit rate,
mirroring `soothe.prompts.fragments`.
"""

from pathlib import Path

_FRAGMENTS_DIR = Path(__file__).parent


def _read(relative: str, *, strip: bool = True) -> str:
    text = _FRAGMENTS_DIR.joinpath(relative).read_text(encoding="utf-8")
    return text.strip() if strip else text


# ---------------------------------------------------------------------------
# Verify (DAG health / completion / placement / backoff)
# ---------------------------------------------------------------------------

DAG_HEALTH_VERIFICATION_PROMPT = _read("verify/dag_health.xml")
POST_COMPLETION_VERIFICATION_PROMPT = _read("verify/post_completion.xml")
GOAL_PLACEMENT_PROMPT = _read("verify/goal_placement.xml")
BACKOFF_REASONING_PROMPT = _read("verify/backoff.xml")

# ---------------------------------------------------------------------------
# Consensus (report-commit judgment)
# ---------------------------------------------------------------------------

CONSENSUS_JUDGE_INSTRUCTIONS = _read("consensus/judge_instructions.xml")

# ---------------------------------------------------------------------------
# Job maturity
# ---------------------------------------------------------------------------

MATURITY_ASSESS_INSTRUCTIONS = _read("maturity/assess_instructions.xml")
MATURITY_ASSESS_CLOSING = _read("maturity/assess_closing.xml")

# ---------------------------------------------------------------------------
# LoopRail guards
# ---------------------------------------------------------------------------

try:
    GUARD_SYSTEM_FRAGMENT = _read("rail/guard_system.xml")
except FileNotFoundError:
    import soothe.rails as _rails_pkg

    GUARD_SYSTEM_FRAGMENT = (
        (Path(_rails_pkg.__file__).resolve().parent / "guard_system.xml")
        .read_text(encoding="utf-8")
        .strip()
    )


__all__ = [
    "BACKOFF_REASONING_PROMPT",
    "CONSENSUS_JUDGE_INSTRUCTIONS",
    "DAG_HEALTH_VERIFICATION_PROMPT",
    "GOAL_PLACEMENT_PROMPT",
    "GUARD_SYSTEM_FRAGMENT",
    "MATURITY_ASSESS_CLOSING",
    "MATURITY_ASSESS_INSTRUCTIONS",
    "POST_COMPLETION_VERIFICATION_PROMPT",
]
