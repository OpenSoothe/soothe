"""Shared fixtures for display card tests."""

from __future__ import annotations

import pytest
from soothe.backends.persistence.display_store import DisplayCardStore, get_display_card_store


@pytest.fixture(autouse=True)
def isolated_display_db(tmp_path, monkeypatch: pytest.MonkeyPatch) -> DisplayCardStore:
    """Use an isolated ``display.db`` for every display test."""
    import soothe.backends.persistence.display_store as display_store_mod
    from soothe_sdk.client import config as sdk_config

    data_dir = tmp_path / "soothe_data"
    data_dir.mkdir()
    monkeypatch.setattr(sdk_config, "SOOTHE_DATA_DIR", str(data_dir))
    display_store_mod._shared_store = None
    store = get_display_card_store()
    yield store
    display_store_mod._shared_store = None
