"""Unit tests for the per-request veritas JSON Schema (RFC-623)."""

from __future__ import annotations

import jsonschema
import pytest

from soothe.subagents.veritas.schemas import build_veritas_response_schema


def test_schema_min_max_items_match_question_count() -> None:
    schema = build_veritas_response_schema(3)
    answers_branch = next(
        branch for branch in schema["oneOf"] if branch["properties"]["defer"]["const"] is False
    )
    answers_field = answers_branch["properties"]["answers"]
    assert answers_field["minItems"] == 3
    assert answers_field["maxItems"] == 3


def test_schema_answer_is_question_min_max_match_question_count() -> None:
    """answer_is_question array must match question_count in the non-defer branch."""
    schema = build_veritas_response_schema(3)
    answers_branch = next(
        branch for branch in schema["oneOf"] if branch["properties"]["defer"]["const"] is False
    )
    aiq_field = answers_branch["properties"]["answer_is_question"]
    assert aiq_field["minItems"] == 3
    assert aiq_field["maxItems"] == 3
    assert "answer_is_question" in answers_branch["required"]


def test_schema_rejects_zero_question_count() -> None:
    with pytest.raises(ValueError):
        build_veritas_response_schema(0)


def test_schema_accepts_defer_with_no_answers() -> None:
    schema = build_veritas_response_schema(2)
    payload = {
        "defer": True,
        "confidence": 0.0,
        "rationale": "I do not know.",
    }
    jsonschema.validate(instance=payload, schema=schema)


def test_schema_accepts_n_non_empty_answers() -> None:
    schema = build_veritas_response_schema(2)
    payload = {
        "defer": False,
        "confidence": 0.7,
        "rationale": "user clearly stated both packages",
        "answers": ["soothe-daemon", "yes, create an IG"],
        "answer_is_question": [False, False],
    }
    jsonschema.validate(instance=payload, schema=schema)


def test_schema_accepts_reasoning_field() -> None:
    """reasoning is an optional property in both branches."""
    schema = build_veritas_response_schema(1)
    payload = {
        "defer": False,
        "confidence": 0.8,
        "rationale": "user stated it",
        "answers": ["soothe"],
        "answer_is_question": [False],
        "reasoning": "The user explicitly mentioned soothe.",
    }
    jsonschema.validate(instance=payload, schema=schema)


def test_schema_rejects_empty_answers_when_not_deferring() -> None:
    schema = build_veritas_response_schema(2)
    payload = {
        "defer": False,
        "confidence": 0.5,
        "rationale": "broken response",
        "answers": [],
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=payload, schema=schema)


def test_schema_rejects_wrong_count_answers() -> None:
    schema = build_veritas_response_schema(2)
    payload = {
        "defer": False,
        "confidence": 0.5,
        "rationale": "broken response",
        "answers": ["only one"],
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=payload, schema=schema)


def test_schema_rejects_empty_string_answer() -> None:
    schema = build_veritas_response_schema(1)
    payload = {
        "defer": False,
        "confidence": 0.6,
        "rationale": "broken",
        "answers": [""],
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=payload, schema=schema)


def test_schema_rejects_empty_rationale() -> None:
    schema = build_veritas_response_schema(1)
    payload = {
        "defer": True,
        "confidence": 0.0,
        "rationale": "",
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=payload, schema=schema)


def test_coerce_veritas_response_fills_metadata_for_answers_only() -> None:
    from soothe.subagents.veritas.schemas import coerce_veritas_response

    raw = {"answers": ["pkg-a", "yes"]}
    coerced = coerce_veritas_response(raw, 2)
    jsonschema.validate(instance=coerced, schema=build_veritas_response_schema(2))
    assert coerced["defer"] is False


def test_coerce_veritas_response_fills_answer_is_question_default() -> None:
    """When the model omits answer_is_question, coerce fills [False]*N."""
    from soothe.subagents.veritas.schemas import coerce_veritas_response

    raw = {"answers": ["pkg-a", "yes"]}
    coerced = coerce_veritas_response(raw, 2)
    assert coerced["answer_is_question"] == [False, False]


def test_coerce_veritas_response_fills_reasoning_default() -> None:
    """When the model omits reasoning, coerce fills empty string."""
    from soothe.subagents.veritas.schemas import coerce_veritas_response

    raw = {"answers": ["pkg-a", "yes"]}
    coerced = coerce_veritas_response(raw, 2)
    assert coerced["reasoning"] == ""


def test_coerce_veritas_response_preserves_answer_is_question() -> None:
    """When the model provides answer_is_question, coerce preserves it."""
    from soothe.subagents.veritas.schemas import coerce_veritas_response

    raw = {"answers": ["pkg-a", "maybe?"], "answer_is_question": [False, True]}
    coerced = coerce_veritas_response(raw, 2)
    assert coerced["answer_is_question"] == [False, True]


def test_coerce_veritas_response_uses_configured_confidence() -> None:
    """coerced_confidence parameter controls the filled confidence value."""
    from soothe.subagents.veritas.schemas import coerce_veritas_response

    raw = {"answers": ["pkg-a", "yes"]}
    coerced = coerce_veritas_response(raw, 2, coerced_confidence=0.85)
    assert coerced["confidence"] == 0.85
