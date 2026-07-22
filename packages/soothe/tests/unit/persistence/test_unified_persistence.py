"""Tests for unified persistence factory helpers."""

from __future__ import annotations

import pytest

from soothe.config.models import DurabilityProtocolConfig, PersistenceConfig, ProtocolsConfig
from soothe.config.settings import SootheConfig
from soothe.cron.store import CronJobStore
from soothe.cron.store_factory import create_cron_job_store
from soothe.cron.store_postgres import PostgresCronJobStore
from soothe.persistence.unified import configure_unified_persistence


def test_create_cron_job_store_sqlite() -> None:
    cfg = SootheConfig(persistence=PersistenceConfig(default_backend="sqlite"))
    store = create_cron_job_store(cfg)
    assert isinstance(store, CronJobStore)


def test_create_cron_job_store_postgresql() -> None:
    cfg = SootheConfig(
        persistence=PersistenceConfig(
            default_backend="postgresql",
            postgres_base_dsn="postgresql://postgres:postgres@localhost:5432",
        )
    )
    store = create_cron_job_store(cfg)
    assert isinstance(store, PostgresCronJobStore)


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
