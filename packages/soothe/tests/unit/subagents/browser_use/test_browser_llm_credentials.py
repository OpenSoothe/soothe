"""Tests for browser_use provider-aware LLM credential resolution."""

from __future__ import annotations

from soothe.config.models import ModelProviderConfig, SubagentConfig
from soothe.config.settings import SootheConfig
from soothe.subagents.browser_use.implementation import (
    _browser_history_had_no_progress,
    _format_browser_no_progress_error,
    _resolve_browser_llm_credentials,
    browser_use_model_role,
)


class _HistoryEntry:
    def __init__(self, *, url: str = "about:blank", action: object | None = None) -> None:
        self.state = type("State", (), {"url": url})()
        self.model_output = None if action is None else type("Output", (), {"action": action})()


class _History:
    def __init__(self, entries: list[_HistoryEntry]) -> None:
        self.history = entries


def test_resolve_browser_llm_credentials_uses_default_model_role() -> None:
    config = SootheConfig(
        providers=[
            ModelProviderConfig(
                name="dashscope",
                provider_type="openai",
                api_base_url="https://example.test/v1",
                api_key="test-key",
                models=["glm-5.2"],
            )
        ],
        router_profiles=[
            {
                "name": "production",
                "router": {"default": "dashscope:glm-5.2"},
            }
        ],
        active_router_profile="production",
    )
    model_name, base_url, api_key = _resolve_browser_llm_credentials(soothe_config=config)
    assert model_name == "glm-5.2"
    assert base_url == "https://example.test/v1"
    assert api_key == "test-key"


def test_browser_use_model_role_defaults_to_default() -> None:
    config = SootheConfig()
    assert browser_use_model_role(config) == "default"


def test_resolve_browser_llm_credentials_uses_configured_model_role() -> None:
    config = SootheConfig(
        providers=[
            ModelProviderConfig(
                name="dashscope",
                provider_type="openai",
                api_base_url="https://example.test/v1",
                api_key="test-key",
                models=["glm-5.2", "kimi-k2.5"],
            )
        ],
        router_profiles=[
            {
                "name": "production",
                "router": {
                    "default": "dashscope:glm-5.2",
                    "fast": "dashscope:kimi-k2.5",
                },
            }
        ],
        active_router_profile="production",
        subagents={
            "browser_use": SubagentConfig(enabled=True, model_role="fast"),
        },
    )
    model_name, base_url, api_key = _resolve_browser_llm_credentials(soothe_config=config)
    assert model_name == "kimi-k2.5"
    assert base_url == "https://example.test/v1"
    assert api_key == "test-key"


def test_browser_history_had_no_progress_detects_blank_tab_loop() -> None:
    history = _History([_HistoryEntry(), _HistoryEntry()])
    assert _browser_history_had_no_progress(history) is True


def test_browser_history_had_no_progress_false_after_navigation() -> None:
    history = _History([_HistoryEntry(url="https://wttr.in/Beijing")])
    assert _browser_history_had_no_progress(history) is False


def test_format_browser_no_progress_error_includes_model_and_steps() -> None:
    message = _format_browser_no_progress_error(model_name="kimi-k2.5", steps=10)
    assert "BrowserUse failed" in message
    assert "kimi-k2.5" in message
    assert "10 step(s)" in message
