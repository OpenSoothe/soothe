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
