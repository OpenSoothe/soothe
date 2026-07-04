"""Single-word thinking-row spinner labels and plan-phase mapping."""

from __future__ import annotations

# Turn-level thinking row (step cards carry finer detail).
SPINNER_LABEL_THINKING = "Thinking"
SPINNER_LABEL_INTERPRETING = "Interpreting"
SPINNER_LABEL_ASSESSING = "Assessing"
SPINNER_LABEL_PLANNING = "Planning"
SPINNER_LABEL_FINALIZING = "Finalizing"
SPINNER_LABEL_EXECUTING = "Executing"
SPINNER_LABEL_TOOLS = "Tools"
SPINNER_LABEL_OFFLOADING = "Offloading"
SPINNER_LABEL_SYNTHESIZING = "Synthesizing"
SPINNER_LABEL_WRITING = "Writing"
SPINNER_LABEL_RETRYING = "Retrying"
SPINNER_LABEL_INPUT = "Input"
SPINNER_LABEL_WAITING = "Waiting"
SPINNER_LABEL_CONNECTING = "Connecting"

# Backend plan_phase_status labels (orchestrator nodes) → display word.
_PLAN_PHASE_TO_SPINNER: dict[str, str] = {
    "Interpreting goal": SPINNER_LABEL_INTERPRETING,
    "Assessing goal progress": SPINNER_LABEL_ASSESSING,
    "Assessing continuation context": SPINNER_LABEL_ASSESSING,
    "Generating plan": SPINNER_LABEL_PLANNING,
    "Finalizing goal": SPINNER_LABEL_FINALIZING,
    # Canonical words (if backend adopts them later).
    SPINNER_LABEL_INTERPRETING: SPINNER_LABEL_INTERPRETING,
    SPINNER_LABEL_ASSESSING: SPINNER_LABEL_ASSESSING,
    SPINNER_LABEL_PLANNING: SPINNER_LABEL_PLANNING,
    SPINNER_LABEL_FINALIZING: SPINNER_LABEL_FINALIZING,
}


def map_plan_phase_spinner_label(label: str) -> str:
    """Map a backend plan-phase label to a single-word thinking-row label."""
    key = label.strip()
    if not key:
        return SPINNER_LABEL_THINKING
    return _PLAN_PHASE_TO_SPINNER.get(key, SPINNER_LABEL_THINKING)


def retry_spinner_hint(*, attempt: int, max_attempts: int) -> str | None:
    """Hint suffix for LLM retries, e.g. ``2/3``."""
    if attempt > 0 and max_attempts > 0:
        return f"{attempt}/{max_attempts}"
    return None


def daemon_connect_hint_extra(*, attempt: int, max_attempts: int) -> str | None:
    """Hint suffix for daemon connect retries, e.g. ``attempt 2/3``."""
    if max_attempts <= 1 or attempt <= 1:
        return None
    return f"attempt {attempt}/{max_attempts}"
