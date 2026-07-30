"""Shared structured-output method order for intake classifiers."""

from __future__ import annotations

# JSON-only intake prompts: prefer response_format so the first request succeeds
# when the model emits schema JSON in content instead of a function_calling tool call.
INTAKE_JSON_FIRST_METHODS: tuple[str | None, ...] = (
    "json_schema",
    "json_mode",
    "function_calling",
    None,
)

__all__ = ["INTAKE_JSON_FIRST_METHODS"]
