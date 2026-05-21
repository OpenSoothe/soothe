"""Tests for CLI ``setup_logging`` quiet logger rules."""

from __future__ import annotations

import logging

from soothe_cli.config.logging_setup import setup_logging


def test_setup_logging_caps_websockets_at_warning_even_for_debug(tmp_path) -> None:
    log_file = tmp_path / "cli.log"
    setup_logging("DEBUG", log_file=log_file)

    assert logging.getLogger("websockets").level == logging.WARNING
    assert logging.getLogger("websockets.client").level == logging.WARNING
