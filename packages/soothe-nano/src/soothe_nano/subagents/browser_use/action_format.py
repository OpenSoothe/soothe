"""Human-readable browser_use step labels for TUI activity rows."""

from __future__ import annotations

from typing import Any

from soothe_nano.subagents.browser_use._preview import preview_first

_ACTION_KEYS: tuple[tuple[str, str], ...] = (
    ("navigate", "Navigate"),
    ("go_to_url", "Navigate"),
    ("open_url", "Navigate"),
    ("search", "Search"),
    ("click", "Click"),
    ("click_element", "Click"),
    ("input_text", "Type"),
    ("input", "Type"),
    ("send_keys", "Keys"),
    ("scroll", "Scroll"),
    ("extract", "Extract"),
    ("extract_content", "Extract"),
    ("wait", "Wait"),
    ("go_back", "Back"),
    ("done", "Done"),
    ("complete", "Done"),
)


def _as_mapping(obj: Any) -> dict[str, Any] | None:
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "model_dump") and callable(obj.model_dump):
        try:
            dumped = obj.model_dump()
        except Exception:
            dumped = None
        if isinstance(dumped, dict):
            return dumped
    return None


def _detail_from_payload(key: str, payload: Any) -> str:
    data = _as_mapping(payload) or {}
    if key in ("navigate", "go_to_url", "open_url"):
        return preview_first(str(data.get("url") or payload or ""), 100)
    if key == "search":
        return preview_first(str(data.get("query") or data.get("text") or payload or ""), 80)
    if key in ("click", "click_element"):
        for field in ("element", "index", "selector", "text", "xpath"):
            if data.get(field) is not None:
                return preview_first(f"{field}={data.get(field)}", 80)
        return preview_first(str(payload), 60)
    if key in ("input_text", "input"):
        text = data.get("text") or data.get("value") or ""
        return preview_first(str(text), 80)
    if key == "wait":
        seconds = data.get("seconds")
        if seconds is not None:
            return f"{seconds}s"
        return preview_first(str(payload), 40)
    if key in ("extract", "extract_content"):
        return preview_first(str(data.get("goal") or data.get("query") or payload or ""), 80)
    if key == "scroll":
        direction = data.get("direction") or data.get("down")
        if direction is not None:
            return preview_first(str(direction), 40)
        return "page"
    if key in ("done", "complete"):
        return preview_first(str(data.get("text") or data.get("success") or ""), 80)
    return preview_first(str(payload), 80)


def _summarize_mapping(data: dict[str, Any]) -> tuple[str, str] | None:
    if "root" in data and data["root"] is not None:
        nested = _as_mapping(data["root"])
        if nested is not None:
            found = _summarize_mapping(nested)
            if found is not None:
                return found
    for key, label in _ACTION_KEYS:
        if key not in data or data[key] is None:
            continue
        return label, _detail_from_payload(key, data[key])
    return None


def summarize_browser_step_action(action: Any) -> tuple[str, str]:
    """Return ``(tool_name, args_preview)`` for one browser-use model action blob.

    Falls back to a truncated ``str(action)`` when the structure is unknown.
    """
    if action is None:
        return "Step", ""

    candidates: list[Any]
    if isinstance(action, list):
        candidates = list(action)
    else:
        candidates = [action]

    labels: list[str] = []
    details: list[str] = []
    for item in candidates:
        mapping = _as_mapping(item)
        parsed = _summarize_mapping(mapping) if mapping is not None else None
        if parsed is None:
            continue
        label, detail = parsed
        labels.append(label)
        if detail:
            details.append(detail)

    if labels:
        tool_name = labels[0] if len(labels) == 1 else "+".join(labels[:3])
        args_preview = " · ".join(details) if details else ""
        return tool_name, args_preview

    raw = preview_first(str(action), 100)
    return "Step", raw


__all__ = ["summarize_browser_step_action"]
