"""Cron Service for Autopilot — Natural Language Scheduled Jobs (RFC-229).

This module provides natural language scheduled job submission for Autopilot.
Users describe jobs in plain language; the daemon extracts schedule semantics
via LLM, persists jobs to database, monitors for due jobs, and executes them
through the existing AutopilotService goal workflow.

Key components:
- CronService: Orchestrator for NL extraction, persistence, and execution
- CronExtractionService: LLM-based schedule extraction
- CronJob: Data model for scheduled jobs
- CronJobStore: Database persistence adapter
"""

from __future__ import annotations

from soothe.foundation.cron.extraction import (
    AutopilotDisabledError,
    CronExtractionService,
    ExtractionError,
)
from soothe.foundation.cron.messages import AUTOPILOT_REQUIRED_FOR_CRON
from soothe.foundation.cron.models import (
    DEFAULT_CRON_USER_ID,
    CronJob,
    DuplicateCronJobError,
    ExtractionResult,
    JobStatus,
    ScheduleKind,
    normalize_cron_description,
)
from soothe.foundation.cron.service import CronService
from soothe.foundation.cron.store import CronJobStore
from soothe.foundation.cron.store_factory import create_cron_job_store

__all__ = [
    "AUTOPILOT_REQUIRED_FOR_CRON",
    "DEFAULT_CRON_USER_ID",
    "AutopilotDisabledError",
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
