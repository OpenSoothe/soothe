# IG-303 Scenario Classifier JSON Fence Parsing

## Objective

Fix scenario classification fallback caused by model responses wrapped in markdown code fences (for example, ```json ... ```), so valid JSON classification outputs are parsed successfully.

## Scope

- Update `scenario_classifier.py` parsing flow to:
  - normalize model response content to plain text
  - extract JSON payload from fenced/wrapped content
  - validate using pydantic JSON validation
- Add unit tests in package test directory for:
  - raw JSON response
  - fenced JSON response
  - malformed response fallback

## Non-Goals

- Changing scenario prompt format.
- Changing fallback scenario semantics.

## Validation

- Run focused unit tests for classifier parsing behavior.

## Completion Criteria

- Fenced JSON responses no longer trigger fallback warnings.
- Malformed content still falls back safely.
