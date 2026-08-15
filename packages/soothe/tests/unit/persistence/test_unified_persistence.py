"""Tests for unified persistence factory helpers."""

from __future__ import annotations

import pytest

from soothe.config.models import DurabilityProtocolConfig, PersistenceConfig, ProtocolsConfig
from soothe.config.settings import SootheConfig
from soothe.persistence.unified import configure_unified_persistence


def test_configure_unified_rejects_mixed_durability_override() -> None:
    cfg = SootheConfig(
        persistence=PersistenceConfig(default_backend="postgresql"),
        agent={
            "protocols": ProtocolsConfig(
                durability=DurabilityProtocolConfig(backend="sqlite"),
            )
        },
    )
    with pytest.raises(ValueError, match="Mixed persistence mode forbidden"):
        configure_unified_persistence(cfg)
