"""Tests for daemon models_list response parsing."""

from __future__ import annotations

from soothe_cli.tui.model_config import parse_models_list_response


def test_parse_models_list_response_skips_placeholders() -> None:
    """Placeholder rows and empty specs are omitted from selector data."""
    resp = {
        "default_model": "dashscope:qwen-plus",
        "models": [
            {
                "spec": "dashscope:qwen-plus",
                "provider": "dashscope",
                "has_credentials": True,
            },
            {"placeholder": True, "provider": "openai"},
            {"spec": "", "provider": "anthropic"},
        ],
    }

    all_models, default_spec, profiles, wire_creds = parse_models_list_response(resp)

    assert all_models == [("dashscope:qwen-plus", "dashscope")]
    assert default_spec == "dashscope:qwen-plus"
    assert profiles == {"dashscope:qwen-plus": {"profile": {}, "overridden_keys": set()}}
    assert wire_creds == {"dashscope": True}
