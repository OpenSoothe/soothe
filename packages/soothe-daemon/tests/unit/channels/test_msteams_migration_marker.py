"""Unit tests for the MS Teams ref migration audit marker (IG-646 D8).

Covers the persisted migration-complete sentinel written to
``msteams_conversations_meta.json`` after legacy ref-schema backfill.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from soothe_daemon.channels.msteams import (
    MSTEAMS_REF_META_MIGRATION_KEY,
    MSTEAMS_REF_META_MIGRATION_SCHEMA,
    MSTeamsChannel,
)


@pytest.fixture
def isolated_state_dir(tmp_path, monkeypatch):
    """Redirect ``Path.home()`` so the daemon's state files land under tmp."""
    home = tmp_path / "home"
    (home / ".soothe" / "state").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(Path, "home", lambda: home)
    return home / ".soothe" / "state"


def _legacy_main_payload() -> dict:
    """A legacy-format refs file (pre meta sidecar): one valid conversation."""
    return {
        "c1": {
            "service_url": "https://smba.trafficmanager.net/",
            "conversation_id": "conv-1",
            "bot_id": "bot-1",
            "activity_id": "act-1",
            "conversation_type": "personal",
            "tenant_id": "tenant-1",
            # legacy inline updated_at carried in main file
            "updated_at": time.time() - 3600,
        }
    }


def _make_channel(state_dir: Path) -> MSTeamsChannel:
    config = {
        "app_id": "app",
        "app_password": "pw",
        "validate_inbound_auth": False,
        "prune_web_chat_refs": False,
        "prune_non_personal_refs": False,
    }
    manager = MagicMock()
    return MSTeamsChannel(config, manager)


class TestMigrationMarkerWrite:
    """The marker is written to the meta sidecar after legacy backfill."""

    def test_marker_present_after_load_with_legacy_refs(self, isolated_state_dir):
        # Seed a legacy refs file (no meta sidecar yet).
        refs_path = isolated_state_dir / "msteams_conversations.json"
        refs_path.write_text(json.dumps(_legacy_main_payload()), encoding="utf-8")

        channel = _make_channel(isolated_state_dir)

        # Backfill ran on load → in-memory sentinel is populated.
        assert channel._refs_migration is not None
        assert channel._refs_migration["schema"] == MSTEAMS_REF_META_MIGRATION_SCHEMA
        assert isinstance(channel._refs_migration["completed_at"], float)
        assert channel._refs_migration["completed_at"] > 0

        # Persist (the constructor's prune path already saved once; force a
        # save explicitly to exercise the write path under test).
        channel._save_refs()

        meta_path = isolated_state_dir / "msteams_conversations_meta.json"
        assert meta_path.exists()
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        assert MSTEAMS_REF_META_MIGRATION_KEY in meta
        marker = meta[MSTEAMS_REF_META_MIGRATION_KEY]
        assert marker["schema"] == MSTEAMS_REF_META_MIGRATION_SCHEMA
        assert isinstance(marker["completed_at"], float)
        assert marker["completed_at"] > 0


class TestMigrationMarkerPersistAcrossRestart:
    """The marker survives a process restart: it is read back, not overwritten.

    Once the sentinel has been persisted, a subsequent load should *preserve*
    the original ``completed_at`` rather than stamping a new one — otherwise
    the audit marker would be meaningless.
    """

    def test_marker_completed_at_stable_across_restart(self, isolated_state_dir):
        refs_path = isolated_state_dir / "msteams_conversations.json"
        refs_path.write_text(json.dumps(_legacy_main_payload()), encoding="utf-8")

        first = _make_channel(isolated_state_dir)
        first_completed_at = first._refs_migration["completed_at"]
        first._save_refs()

        # Second instantiation reads the now-existing meta sidecar.
        second = _make_channel(isolated_state_dir)
        after_restart = time.time()

        assert second._refs_migration is not None
        assert second._refs_migration["completed_at"] == first_completed_at, (
            "completed_at must be preserved from disk, not re-stamped"
        )
        # Sanity: it's in the past relative to the restart window.
        assert second._refs_migration["completed_at"] <= after_restart

        meta_path = isolated_state_dir / "msteams_conversations_meta.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        assert meta[MSTEAMS_REF_META_MIGRATION_KEY]["completed_at"] == first_completed_at


class TestMigrationMarkerNoRefs:
    """When there is no legacy refs file, no marker is written (nothing to backfill)."""

    def test_no_marker_when_refs_absent(self, isolated_state_dir):
        channel = _make_channel(isolated_state_dir)
        assert channel._refs_migration is None
        channel._save_refs()

        meta_path = isolated_state_dir / "msteams_conversations_meta.json"
        if meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            assert MSTEAMS_REF_META_MIGRATION_KEY not in meta
