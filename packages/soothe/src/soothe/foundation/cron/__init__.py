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

from soothe.foundation.cron.extraction import CronExtractionService, ExtractionError
from soothe.foundation.cron.models import CronJob, ExtractionResult, JobStatus, ScheduleKind
from soothe.foundation.cron.service import CronService
from soothe.foundation.cron.store import CronJobStore

__all__ = [
    "CronExtractionService",
    "CronJob",
    "CronJobStore",
    "CronService",
    "ExtractionError",
    "ExtractionResult",
    "JobStatus",
    "ScheduleKind",
]
