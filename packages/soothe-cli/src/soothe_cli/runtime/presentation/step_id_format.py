"""Step id display formatting for TUI plan panels.

Plan step ids embed a numeric suffix (``KFA-07`` → 7, ``STEP-1`` → 1,
``01`` → 1). The plan panel renders only that numeric token as a compact
visual prefix; the full scoped id is never shown to the operator.
"""

from __future__ import annotations

import re

from soothe_sdk.ux.task_namespace import (
    _is_wire_step_fragment,
    _step_id_from_unified_fragment,
)

_TRAILING_DIGITS = re.compile(r"(\d+)$")


def _canonical_step_id(step_id: str) -> str:
    """Normalize a wire-form fragment back to the canonical execute step id.

    Unified tool_call_ids carry the step id in underscore wire form
    (``KFA_07``); plan events and step cards use the canonical hyphen form
    (``KFA-07``). Recognize the wire form so both surfaces share one display.
    """
    text = str(step_id or "").strip()
    if not text:
        return text
    if _is_wire_step_fragment(text):
        return _step_id_from_unified_fragment(text)
    return text


def numeric_step_prefix(step_id: str) -> str:
    """Return the numeric-only visual prefix for a plan step id.

    Mirrors ``trailing_numeric_suffix_from_step_id`` semantics from the host
    (``soothe`` cannot be imported by ``soothe-cli`` per the monorepo DAG):

    - Prefer the segment after the last hyphen (``KFA-07`` → ``7``).
    - Otherwise use the last run of digits (``step_004`` → ``4``).
    - Leading zeros are dropped (``01`` → ``1``).

    Returns an empty string when no numeric suffix is present
    (``PLAN-RV`` → ``""``) or when the id is blank.
    """
    s = _canonical_step_id(step_id)
    if not s:
        return ""
    if "-" in s:
        tail = s.rsplit("-", 1)[-1]
        if tail.isdigit():
            return str(int(tail, 10))
    m = _TRAILING_DIGITS.search(s)
    if m:
        return str(int(m.group(1), 10))
    return ""
