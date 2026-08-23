"""Executor step-failure traceback capture (Fix #2 / d15f incident).

When a step raises an unexpected (non-recoverable) exception during the
completion/aggregation path, the full traceback is appended to the
``StepExecutionRecord.error`` field (in ``executor.py``'s except blocks)
so it survives in the ``step.completed`` event payload (conversation.jsonl)
and the daemon event stream — not just the truncated ``str(e)`` rendered
on the TUI card.

The full ``_execute_step_collecting_events`` path has heavy graph/middleware
dependencies, so these tests verify the traceback-capture invariant the fix
introduces: for a non-recoverable exception, the traceback string is part
of the persisted error; for a recoverable network error, it is not.
"""

from __future__ import annotations

import traceback

from soothe.sloop.utils.network_errors import is_recoverable_tool_network_error


def _capture_error_msg(exc: BaseException, *, short_msg: str) -> str:
    """Mirror the executor's non-recoverable traceback-concatenation logic.

    In ``_execute_step_collecting_events`` and the parallel-step except
    block, ``error_msg`` is built from ``_extract_error_message`` and then
    the full traceback is appended when the exception is not a recoverable
    network error and not a ``GraphRecursionError``.
    """
    if not is_recoverable_tool_network_error(exc):
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)).strip()
        if tb:
            return f"{short_msg}\n\n{tb}" if short_msg else tb
    return short_msg


def test_traceback_appended_for_unexpected_typeerror() -> None:
    """The d15f crash signature: TypeError in the aggregation path.

    The persisted ``error`` field must contain both the short message and
    the full traceback so the exact crash site is recoverable from the
    step.completed event, even when the per-loop runner.log handler was
    detached mid-run.
    """
    try:
        None <= 0  # type: ignore[operator]
    except TypeError as exc:
        error_msg = _capture_error_msg(
            exc, short_msg="TypeError: '<=' not supported between instances of"
        )

    assert "TypeError" in error_msg
    assert "<=" in error_msg
    assert "Traceback" in error_msg
    assert "NoneType" in error_msg


def test_traceback_not_appended_for_recoverable_network_error() -> None:
    """Recoverable network errors keep the concise message (no traceback spam)."""
    exc = ConnectionRefusedError(61, "Connect call failed")
    try:
        raise exc
    except ConnectionRefusedError:
        error_msg = _capture_error_msg(exc, short_msg="Network/connection error")

    assert "Traceback" not in error_msg
    assert error_msg == "Network/connection error"
