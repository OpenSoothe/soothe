"""Parser for the `--model-params` flag in `/model` slash-command arguments."""

from __future__ import annotations

import json
import shlex
from typing import Any


def _extract_model_params_flag(raw_arg: str) -> tuple[str, dict[str, Any] | None]:
    """Extract `--model-params` and its JSON value from a `/model` arg string.

    Handles quoted (`'...'` / `"..."`) and bare `{...}` values with balanced
    braces so that JSON containing spaces works without quoting.

    Note:
    The bare-brace mode counts `{` / `}` characters without awareness of
    JSON string contents. Values that contain literal braces inside strings
    (e.g., `{"stop": "end}here"}`) will mis-parse. Users should quote the
    value in that case.

    Args:
    raw_arg: The argument string after `/model `.

    Returns:
    Tuple of `(remaining_args, parsed_dict | None)`. Returns `None` for the
    dict when the flag is absent.

    Raises:
    ValueError: If the value is missing, has unclosed quotes,
    unbalanced braces, or is not valid JSON.
    TypeError: If the parsed JSON is not a dict.
    """
    flag = "--model-params"
    idx = raw_arg.find(flag)
    if idx == -1:
        return raw_arg, None

    before = raw_arg[:idx].rstrip()
    after = raw_arg[idx + len(flag) :].lstrip()

    if not after:
        msg = "--model-params requires a JSON object value"
        raise ValueError(msg)

    # Determine the JSON string boundaries.
    if after[0] in {"'", '"'}:
        quote = after[0]
        end = -1
        backslash_count = 0
        for i, ch in enumerate(after[1:], start=1):
            if ch == "\\":
                backslash_count += 1
                continue
            if ch == quote and backslash_count % 2 == 0:
                end = i
                break
            backslash_count = 0
        if end == -1:
            msg = f"Unclosed {quote} in --model-params value"
            raise ValueError(msg)
        # Parse the quoted token with shlex so escaped quotes are unescaped.
        json_str = shlex.split(after[: end + 1], posix=True)[0]
        rest = after[end + 1 :].lstrip()
    elif after[0] == "{":
        # Walk forward to find the matching closing brace.
        depth = 0
        end = -1
        for i, ch in enumerate(after):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        if end == -1:
            msg = "Unbalanced braces in --model-params value"
            raise ValueError(msg)
        json_str = after[: end + 1]
        rest = after[end + 1 :].lstrip()
    else:
        # Non-brace, non-quoted — take the next whitespace-delimited token.
        parts = after.split(None, 1)
        json_str = parts[0]
        rest = parts[1] if len(parts) > 1 else ""

    remaining = f"{before} {rest}".strip()
    try:
        params = json.loads(json_str)
    except json.JSONDecodeError:
        msg = f'Invalid JSON in --model-params: {json_str!r}. Expected format: --model-params \'{{"key": "value"}}\''
        raise ValueError(msg) from None
    if not isinstance(params, dict):
        msg = "--model-params must be a JSON object, got " + type(params).__name__
        raise TypeError(msg)
    return remaining, params
