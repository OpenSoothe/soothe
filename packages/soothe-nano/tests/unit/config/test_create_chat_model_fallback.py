"""Tests for role→default fallback in create_chat_model."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from soothe_nano.config.settings import SootheConfig
from soothe_nano.utils.llm.factory import LLMFactory


def test_think_falls_back_to_default_on_failure() -> None:
    cfg = SootheConfig(
        router_profiles=[
            {
                "name": "default",
                "router": {
                    "default": "openai:gpt-4o-mini",
                    "think": "openai:o3-mini",
                },
            }
        ]
    )
    default_model = MagicMock(name="default_model")
    with patch.object(
        LLMFactory,
        "_create_from_spec",
        side_effect=[RuntimeError("think failed"), default_model],
    ):
        model = cfg.create_chat_model("think")
    assert model is default_model


def test_raises_when_both_roles_fail() -> None:
    cfg = SootheConfig(
        router_profiles=[
            {
                "name": "default",
                "router": {
                    "default": "openai:gpt-4o-mini",
                    "think": "openai:o3-mini",
                },
            }
        ]
    )
    with patch.object(
        LLMFactory,
        "_create_from_spec",
        side_effect=[RuntimeError("think failed"), RuntimeError("default failed")],
    ):
        with pytest.raises(RuntimeError, match="default failed"):
            cfg.create_chat_model("think")


def test_skips_fallback_when_specs_match() -> None:
    cfg = SootheConfig(
        router_profiles=[
            {
                "name": "default",
                "router": {
                    "default": "openai:gpt-4o-mini",
                    "think": None,
                },
            }
        ]
    )
    with patch.object(
        LLMFactory,
        "_create_from_spec",
        side_effect=RuntimeError("instantiation failed"),
    ) as create_from_spec:
        with pytest.raises(RuntimeError, match="instantiation failed"):
            cfg.create_chat_model("think")
    create_from_spec.assert_called_once()


def test_default_role_does_not_fallback() -> None:
    cfg = SootheConfig()
    with patch.object(
        LLMFactory,
        "_create_from_spec",
        side_effect=RuntimeError("default failed"),
    ) as create_from_spec:
        with pytest.raises(RuntimeError, match="default failed"):
            cfg.create_chat_model("default")
    create_from_spec.assert_called_once()
