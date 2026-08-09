"""Autopilot cognition — contract + guidance intake (IG-733).

Pipeline: GOAL.md / user guidance / channel guidance → cognition → CE goals →
dispatch → exec. Guidance never spawns goals; it only accumulates on CE nodes.
"""

from __future__ import annotations

from soothe.autopilot.cognition.contract import (
    GOAL_MD_FILENAME,
    load_job_goal_md,
    resolve_job_goal_md_path,
    write_job_goal_md,
)
from soothe.autopilot.cognition.guidance import (
    absorb_channel_guidance,
    absorb_guidance,
    absorb_user_guidance,
    collect_operator_guidance,
)
from soothe.autopilot.cognition.models import (
    GUIDANCE_SCOPES,
    GUIDANCE_SOURCES,
    GuidanceScope,
    GuidanceSource,
)

__all__ = [
    "GOAL_MD_FILENAME",
    "GUIDANCE_SCOPES",
    "GUIDANCE_SOURCES",
    "GuidanceScope",
    "GuidanceSource",
    "absorb_channel_guidance",
    "absorb_guidance",
    "absorb_user_guidance",
    "collect_operator_guidance",
    "load_job_goal_md",
    "resolve_job_goal_md_path",
    "write_job_goal_md",
]
