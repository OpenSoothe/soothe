"""Cron Service for Autopilot — Natural Language Scheduled Jobs."""

from __future__ import annotations

from soothe_daemon.cron.builtin import BUILTIN_JOBS, BuiltinJobSpec
from soothe_daemon.cron.extraction import (
    AutopilotDisabledError,
    CronExtractionService,
    ExtractionError,
)
from soothe_daemon.cron.messages import AUTOPILOT_REQUIRED_FOR_CRON
from soothe_daemon.cron.models import (
    DEFAULT_CRON_USER_ID,
    CronJob,
    DuplicateCronJobError,
    ExtractionResult,
    JobStatus,
    ScheduleKind,
    normalize_cron_description,
)
from soothe_daemon.cron.service import CronService
from soothe_daemon.cron.store import CronJobStore
from soothe_daemon.cron.store_factory import create_cron_job_store

__all__ = [
    "AUTOPILOT_REQUIRED_FOR_CRON",
    "BUILTIN_JOBS",
    "DEFAULT_CRON_USER_ID",
    "AutopilotDisabledError",
    "BuiltinJobSpec",
    "CronExtractionService",
    "CronJob",
    "CronJobStore",
    "CronService",
    "DuplicateCronJobError",
    "ExtractionError",
    "ExtractionResult",
    "JobStatus",
    "ScheduleKind",
    "create_cron_job_store",
    "normalize_cron_description",
]
