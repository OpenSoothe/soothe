"""Core managers module (RFC-228, RFC-626).

This module provides manager classes for job lifecycle operations:
- JobManager: Manages job lifecycle transitions and checkpoint persistence
"""

from soothe.foundation.core.managers.job_manager import JobManager

__all__ = ["JobManager"]
