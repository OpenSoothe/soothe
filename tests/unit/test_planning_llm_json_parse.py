"""Tests for resilient JSON extraction in LLMPlanner (`_load_llm_json_dict`)."""

from __future__ import annotations

import json

import pytest

from soothe.cognition.planning.llm import _load_llm_json_dict


def test_load_plain_object() -> None:
    assert _load_llm_json_dict('{"a": 1}') == {"a": 1}


def test_trailing_commas_nested() -> None:
    raw = """
    {
      "status": "continue",
      "decision": {
        "type": "execute_steps",
        "steps": [
          {"description": "one", "tools": [],},
        ],
      },
    }
    """
    data = _load_llm_json_dict(raw)
    assert data["status"] == "continue"
    assert data["decision"]["steps"][0]["description"] == "one"


def test_prose_before_and_after_json() -> None:
    raw = 'Thoughts first.\n{"status": "replan", "plan_action": "new"}\nTail note with } char'
    data = _load_llm_json_dict(raw)
    assert data["status"] == "replan"


def test_closing_brace_inside_string() -> None:
    raw = r'{"reasoning": "literal } in value", "x": 1}'
    data = _load_llm_json_dict(raw)
    assert data["x"] == 1
    assert "}" in data["reasoning"]


def test_markdown_json_fence_with_trailing_comma() -> None:
    raw = '```json\n{"a": 2,}\n```'
    assert _load_llm_json_dict(raw) == {"a": 2}


def test_utf8_bom_prefix() -> None:
    data = _load_llm_json_dict('\ufeff{"ok": true}')
    assert data["ok"] is True


def test_invalid_json_still_raises() -> None:
    with pytest.raises(json.JSONDecodeError):
        _load_llm_json_dict("{not json")
