"""Tests for SootheConfig.create_chat_model_with_fallback."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from soothe.config import SootheConfig


def test_think_falls_back_to_default_on_failure() -> None:
    cfg = SootheConfig()
    default_model = MagicMock(name="default_model")
    with patch.object(
        SootheConfig,
        "create_chat_model",
        side_effect=[RuntimeError("think failed"), default_model],
    ):
        model = cfg.create_chat_model_with_fallback("think")
    assert model is default_model


def test_raises_when_both_roles_fail() -> None:
    cfg = SootheConfig()
    with patch.object(
        SootheConfig,
        "create_chat_model",
        side_effect=[RuntimeError("think failed"), RuntimeError("default failed")],
    ):
        with pytest.raises(RuntimeError, match="default failed"):
            cfg.create_chat_model_with_fallback("think")
