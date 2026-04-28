"""JSON parsing utilities for LLM responses.

Handles extraction and repair of JSON from LLM output with tolerance for:
- Markdown fences
- Trailing commas
- Truncated output
- String-aware bracket matching
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def _strip_leading_bom(text: str) -> str:
    """Remove UTF-8 BOM if present."""
    return text.lstrip("﻿")


def _strip_markdown_json_fence(response: str) -> str:
    """Extract JSON from ```json ... ``` or generic ``` ... ``` blocks."""
    json_str = response.strip()

    if "```json" in json_str:
        start = json_str.find("```json") + 7
        end = json_str.find("```", start)
        if end > start:
            return json_str[start:end].strip()
    elif "```" in json_str:
        start = json_str.find("```") + 3
        newline_pos = json_str.find("\n", start)
        if newline_pos > start:
            start = newline_pos + 1
        end = json_str.find("```", start)
        if end > start:
            return json_str[start:end].strip()

    return json_str


def _extract_balanced_json_object(text: str, start: int | None = None) -> str | None:
    """Return the substring from first ``{`` through its matching ``}``, string-aware.

    Avoids greedy ``{.*}`` mistakes when strings contain ``}`` or when prose follows JSON.
    """
    if start is None:
        start = text.find("{")
    if start < 0:
        return None

    depth = 0
    in_string = False
    backslash = False
    i = start
    while i < len(text):
        c = text[i]
        if backslash:
            backslash = False
        elif in_string:
            if c == "\\":
                backslash = True
            elif c == '"':
                in_string = False
        elif c == '"':
            in_string = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
        i += 1
    return None


def _strip_trailing_commas_json(text: str) -> str:
    """Remove JSON trailing commas (`,}` / `,]`) outside of string literals."""
    out: list[str] = []
    in_string = False
    backslash = False
    n = len(text)
    i = 0
    while i < n:
        c = text[i]
        if backslash:
            out.append(c)
            backslash = False
            i += 1
            continue
        if in_string:
            if c == "\\":
                backslash = True
                out.append(c)
            elif c == '"':
                in_string = False
                out.append(c)
            else:
                out.append(c)
            i += 1
            continue

        if c == '"':
            in_string = True
            out.append(c)
            i += 1
            continue

        if c == ",":
            j = i + 1
            while j < n and text[j] in " \t\n\r":
                j += 1
            if j < n and text[j] in "}]":
                i += 1
                continue

        out.append(c)
        i += 1

    return "".join(out)


def _try_parse_json_dict(raw: str) -> dict[str, Any] | None:
    """Parse ``raw`` as a JSON object; try trailing-comma repair on failure."""
    relaxed = _strip_trailing_commas_json(raw)
    variants = [raw] if raw == relaxed else [raw, relaxed]
    for candidate in variants:
        try:
            loaded = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(loaded, dict):
            return loaded
    return None


def _repair_truncated_json(text: str) -> str:
    """Repair truncated JSON by closing unclosed strings and brackets.

    Handles cases where LLM output is cut off mid-string or mid-structure.
    Attempt to make it parseable by adding necessary closing characters.

    Args:
        text: Potentially truncated JSON string

    Returns:
        Repaired JSON string (may still be invalid if severely truncated)
    """
    # Track bracket depth and string state
    bracket_stack: list[str] = []
    in_string = False
    backslash = False
    last_char = ""

    # Scan the string to find unclosed structures
    for c in text:
        if backslash:
            backslash = False
        elif in_string:
            if c == "\\":
                backslash = True
            elif c == '"':
                in_string = False
        elif c == '"':
            in_string = True
        elif c in "{[":
            bracket_stack.append(c)
        elif c == "}":
            if bracket_stack and bracket_stack[-1] == "{":
                bracket_stack.pop()
        elif c == "]":
            if bracket_stack and bracket_stack[-1] == "[":
                bracket_stack.pop()
        last_char = c

    # Build repair: close unclosed structures
    repair = ""

    # If still in a string, close it
    if in_string:
        repair += '"'

    # Close any remaining brackets in reverse order
    while bracket_stack:
        open_bracket = bracket_stack.pop()
        if open_bracket == "{":
            repair += "}"
        elif open_bracket == "[":
            repair += "]"

    # If the text ends with a comma (truncated before next value), remove it
    if last_char == ",":
        text = text[:-1]

    repaired = text + repair

    if repair:
        logger.debug(
            "[JSON-Repair] added %d chars (%s) to truncated JSON",
            len(repair),
            repair,
        )

    return repaired


def _load_llm_json_dict(response: str) -> dict[str, Any]:
    """Extract the first JSON object from an LLM response string.

    Tolerates markdown fences, leading prose, trailing commas, and stray text after JSON
    via balanced-brace extraction (string-aware).
    """
    json_str = _strip_leading_bom(_strip_markdown_json_fence(response)).strip()

    if not json_str:
        raise ValueError("Empty LLM response — cannot parse JSON")

    candidates: list[str] = []
    seen: set[str] = set()

    def _add_candidate(s: str) -> None:
        s = s.strip()
        if s and s not in seen:
            seen.add(s)
            candidates.append(s)

    _add_candidate(json_str)

    balanced = _extract_balanced_json_object(json_str)
    if balanced:
        _add_candidate(balanced)

    last_error: json.JSONDecodeError | None = None
    for cand in candidates:
        parsed = _try_parse_json_dict(cand)
        if parsed is not None:
            if cand != candidates[0]:
                logger.debug("Parsed LLM JSON using fallback candidate (length=%d)", len(cand))
            return parsed
        try:
            loaded = json.loads(_strip_trailing_commas_json(cand))
        except json.JSONDecodeError as e:
            last_error = e
        else:
            if not isinstance(loaded, dict):
                last_error = json.JSONDecodeError(
                    "LLM JSON root must be an object (got non-object)",
                    cand,
                    0,
                )

    if last_error is not None:
        raise last_error
    raise TypeError("LLM JSON root must be an object")
