"""Strip internal research / tool scaffolding from assistant-visible text.

Used by the daemon query path and UX display policy (single source of truth).
"""

from __future__ import annotations

import json
import re

# Internal JSON keys that indicate research/inquiry engine responses
INTERNAL_JSON_KEYS = frozenset(
    {
        "sub_questions",
        "queries",
        "is_sufficient",
        "knowledge_gap",
        "follow_up_queries",
    }
)

CONFUSED_RESPONSE_INDICATORS = [
    ("sub-questions", ["provide", "share", "empty", "not provided", "actually provided"]),
    ("sub_questions", ["provide", "share", "empty", "not provided", "actually provided"]),
    ("section appears to be empty", []),
    ("once you share them", ["json format"]),
]


def is_internal_json_content(content: str) -> bool:
    """Return True if JSON content contains internal-only keys."""
    try:
        parsed = json.loads(content)
        if isinstance(parsed, dict):
            return bool(INTERNAL_JSON_KEYS & set(parsed.keys()))
    except json.JSONDecodeError:
        pass
    return False


def find_matching_brace(text: str, start: int) -> int:
    """Return the index after the matching closing brace, or -1."""
    brace_count = 0
    for j in range(start, len(text)):
        if text[j] == "{":
            brace_count += 1
        elif text[j] == "}":
            brace_count -= 1
            if brace_count == 0:
                return j + 1
    return -1


def filter_json_code_blocks(text: str) -> str:
    """Remove JSON code blocks containing internal keys."""
    result_parts = []
    i = 0

    while i < len(text):
        json_start = text.find("```json", i)
        if json_start == -1:
            result_parts.append(text[i:])
            break

        result_parts.append(text[i:json_start])

        content_start = json_start + 7
        json_end = text.find("```", content_start)

        if json_end == -1:
            result_parts.append(text[json_start:])
            break

        json_content = text[content_start:json_end].strip()
        should_remove = is_internal_json_content(json_content)

        if should_remove:
            i = json_end + 3
        else:
            result_parts.append(text[json_start : json_end + 3])
            i = json_end + 3

    return "".join(result_parts)


def filter_plain_json(text: str) -> str:
    """Remove plain JSON objects containing internal keys."""
    result_parts = []
    i = 0

    while i < len(text):
        brace_pos = -1
        for j in range(i, len(text)):
            if text[j] == "{" and (j == 0 or text[j - 1] in " \t\n\r"):
                brace_pos = j
                break

        if brace_pos == -1:
            result_parts.append(text[i:])
            break

        result_parts.append(text[i:brace_pos])

        json_end = find_matching_brace(text, brace_pos)

        if json_end == -1:
            result_parts.append(text[brace_pos:])
            break

        json_text = text[brace_pos:json_end]
        should_remove = is_internal_json_content(json_text)

        if should_remove:
            i = json_end
        else:
            result_parts.append(json_text)
            i = json_end

    return "".join(result_parts)


def filter_confused_responses(text: str) -> str:
    """Remove confused LLM meta-responses about missing data."""
    text_lower = text.lower()

    for primary_indicator, secondary_indicators in CONFUSED_RESPONSE_INDICATORS:
        if primary_indicator in text_lower and (
            not secondary_indicators or any(s in text_lower for s in secondary_indicators)
        ):
            lines = text.split("\n")
            filtered = [line for line in lines if primary_indicator not in line.lower()]
            text = "\n".join(filtered)

    return text


def filter_search_data_tags(text: str) -> str:
    """Remove <search_data> blocks and synthesis instructions."""
    while "<search_data>" in text and "</search_data>" in text:
        start = text.find("<search_data>")
        end = text.find("</search_data>") + len("</search_data>")
        text = text[:start] + text[end:]

    text = text.replace("<search_data>", "").replace("</search_data>", "")

    synthesis_markers = [
        "Synthesize the search data into a clear answer.",
        "Do NOT reproduce raw results, source listings, or URLs.",
    ]
    for marker in synthesis_markers:
        text = text.replace(marker, "")

    return text


def normalize_internal_whitespace(text: str) -> str:
    """Normalize excessive whitespace (shared with DisplayPolicy.filter_content)."""
    text = re.sub(r"[ \t]+[🇦-🇿✨🎉👍😊😄😃😀😉🙌]+(?=\s*$)", "", text)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = re.sub(r"([.?!]),", r"\1", text)
    text = re.sub(r" {2,}", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text)


def strip_internal_tags(text: str) -> str:
    """Strip internal tool tags and research JSON from assistant text.

    Preserves behavior of the former ``message_processing.strip_internal_tags``.

    Args:
        text: Raw assistant text.

    Returns:
        Cleaned text for logging or display.
    """
    text = filter_json_code_blocks(text)
    text = filter_plain_json(text)
    text = filter_confused_responses(text)
    text = filter_search_data_tags(text)
    return normalize_internal_whitespace(text)


__all__ = [
    "INTERNAL_JSON_KEYS",
    "strip_internal_tags",
    "is_internal_json_content",
]
