"""JSON Schema wire helpers for client-provided structured output."""

from __future__ import annotations

from typing import Any

DEFAULT_DIRECT_LLM_SCHEMA_NAME = "SootheDirectLLMOutput"


def validate_response_schema(schema: Any) -> dict[str, Any]:
    """Validate a client ``response_schema`` payload.

    Args:
        schema: Raw wire value.

    Returns:
        Normalized JSON Schema dict.

    Raises:
        ValueError: If the schema is not a usable JSON Schema object.
    """
    if not isinstance(schema, dict):
        msg = "response_schema must be a JSON object"
        raise ValueError(msg)
    if not schema:
        msg = "response_schema must not be empty"
        raise ValueError(msg)
    schema_type = schema.get("type")
    if not isinstance(schema_type, str) or not schema_type.strip():
        msg = 'response_schema must include a non-empty "type" field'
        raise ValueError(msg)
    return schema


def resolve_schema_name(schema: dict[str, Any], explicit: str | None = None) -> str:
    """Derive provider schema name from wire fields or schema ``title``."""
    if explicit and explicit.strip():
        return explicit.strip()
    title = schema.get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()
    return DEFAULT_DIRECT_LLM_SCHEMA_NAME


def build_json_schema_response_format(
    json_schema: dict[str, Any],
    *,
    name: str,
    strict: bool,
) -> dict[str, Any]:
    """Build OpenAI-compatible ``response_format`` for json_schema mode."""
    return {
        "type": "json_schema",
        "json_schema": {
            "name": name,
            "strict": strict,
            "schema": json_schema,
        },
    }
