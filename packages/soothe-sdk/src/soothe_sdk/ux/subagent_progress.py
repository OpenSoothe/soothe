"""Helper functions for subagent event processing.

This module provides utilities for CLI/TUI to extract subagent information
from curated ``soothe.subagent.*`` wire types.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from soothe_sdk.wire.protocol import preview_first


def get_subagent_name_from_event(event_type: str) -> str | None:
    """Extract built-in subagent id from a curated wire event type.

    Args:
        event_type: Full event type string.

    Returns:
        Subagent segment (e.g., ``deep_research``, ``browser_use``) for ``soothe.subagent.<id>.…``,
        else None.

    Example:
        >>> get_subagent_name_from_event("soothe.subagent.deep_research.started")
        'deep_research'
        >>> get_subagent_name_from_event("soothe.cognition.plan.created")
        None
    """
    if not event_type.startswith("soothe.subagent."):
        return None

    parts = event_type.split(".")
    if len(parts) >= 4:
        return parts[2]  # soothe.subagent.<subagent>.<...>
    return None


def _summarize_started(data: Mapping[str, Any]) -> str:
    for key in ("search_target", "topic_preview", "task_preview"):
        text = str(data.get(key, "") or "").strip()
        if text:
            return preview_first(text, 120)
    return ""


def _summarize_action_step(data: Mapping[str, Any]) -> str:
    parts = [
        str(data.get("status", "") or "").strip(),
        preview_first(str(data.get("action_preview", "")), 80),
        preview_first(str(data.get("url", "")), 80),
    ]
    return " · ".join(p for p in parts if p)


def _summarize_tool_step(data: Mapping[str, Any]) -> str:
    tn = str(data.get("tool_name", "") or "").strip()
    ap = preview_first(str(data.get("args_preview", "")), 60)
    ip = preview_first(str(data.get("input_preview", "")), 80)
    preview = ap or ip
    if tn and preview:
        return f"{tn}({preview})"
    return tn or preview or "step"


def _summarize_completed(data: Mapping[str, Any]) -> str:
    ms = int(data.get("duration_ms", 0) or 0)
    summary = preview_first(str(data.get("summary", "") or "").strip(), 100)
    report_path = preview_first(str(data.get("report_path", "") or "").strip(), 80)
    if summary and report_path:
        return f"{summary} → {report_path}" + (f" ({ms}ms)" if ms else "")
    if summary:
        return summary + (f" ({ms}ms)" if ms else "")
    if "cost_usd" in data:
        cost = data.get("cost_usd", 0.0)
        try:
            c = float(cost)
        except (TypeError, ValueError):
            c = 0.0
        return f"${c:.2f}, {ms}ms"
    if "total_findings" in data:
        tf = int(data.get("total_findings", 0) or 0)
        return f"{tf} findings ({ms}ms)" if ms else f"{tf} findings"
    if "answer_length" in data:
        al = int(data.get("answer_length", 0) or 0)
        return f"{al} chars ({ms}ms)" if ms else f"{al} chars"
    ok = data.get("success", True)
    status = "done" if ok else "failed"
    return f"{status} ({ms}ms)" if ms else status


def _summarize_progress(data: Mapping[str, Any]) -> str:
    phase = str(data.get("phase", "") or "").strip()
    msg = preview_first(str(data.get("message", "")), 80)
    loop_count = int(data.get("loop_count", 0) or 0)
    total_loops = int(data.get("total_loops", 0) or 0)
    if phase and msg:
        base = f"{phase}: {msg}"
    else:
        base = phase or msg
    if total_loops > 0:
        return (
            f"{base} ({loop_count}/{total_loops})" if base else f"loop {loop_count}/{total_loops}"
        )
    return base


def _summarize_crawl(data: Mapping[str, Any]) -> str:
    urls = int(data.get("urls_crawled", 0) or 0)
    success = int(data.get("success_count", 0) or 0)
    return f"{success}/{urls} URLs crawled"


def summarize_subagent_wire_activity(event_type: str, data: Mapping[str, Any]) -> str:
    """One short line for Task tool cards / compact CLI mirroring (metadata-only).

    Args:
        event_type: Allowlisted ``soothe.subagent.*`` type.
        data: Event payload (excluding ``type``).

    Returns:
        Non-empty summary string, or empty when nothing to show.
    """
    if event_type.endswith(".failed"):
        return preview_first(str(data.get("message", "")), 120)
    if event_type.endswith(".started"):
        return _summarize_started(data)
    if event_type.endswith(".progress"):
        return _summarize_progress(data)
    if event_type.endswith(".step.completed"):
        if any(k in data for k in ("action_preview", "url", "status")):
            action_line = _summarize_action_step(data)
            if action_line:
                return action_line
        return _summarize_tool_step(data)
    if event_type.endswith(".milestone"):
        decision = str(data.get("decision", "") or "").strip()
        fc = int(data.get("findings_count", 0) or 0)
        it = int(data.get("iterations_used", 0) or 0)
        base = decision or "milestone"
        return f"{base} ({fc} findings, {it} iter)"
    if event_type.endswith(".gather.summary"):
        rc = int(data.get("result_count", 0) or 0)
        st = int(data.get("sources_touched", 0) or 0)
        qp = preview_first(str(data.get("query_preview", "")), 60)
        tail = f"{rc} hits, {st} sources"
        return f"{qp} → {tail}" if qp else tail
    if event_type.endswith(".crawl.summary"):
        return _summarize_crawl(data)
    if event_type.endswith(".requested"):
        qc = int(data.get("question_count", 0) or 0)
        label = "question" if qc == 1 else "questions"
        return f"Veritas clarifying ({qc} {label})" if qc else "Veritas clarifying"
    if event_type.endswith(".answered"):
        conf = float(data.get("confidence", 0) or 0)
        if data.get("defer"):
            return f"Veritas defer (conf={conf:.2f})"
        return f"Veritas answered (conf={conf:.2f})"
    if event_type.endswith(".deferred"):
        return preview_first(str(data.get("reason", "")), 120)
    if event_type.endswith(".completed"):
        return _summarize_completed(data)

    return ""


__all__ = [
    "get_subagent_name_from_event",
    "summarize_subagent_wire_activity",
]
