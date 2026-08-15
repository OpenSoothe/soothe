"""Tests for the daemon cron store factory (unified persistence branch)."""

from __future__ import annotations

from soothe.config.models import PersistenceConfig
from soothe.config.settings import SootheConfig

from soothe_daemon.cron.store import CronJobStore
from soothe_daemon.cron.store_factory import create_cron_job_store
from soothe_daemon.cron.store_postgres import PostgresCronJobStore


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
