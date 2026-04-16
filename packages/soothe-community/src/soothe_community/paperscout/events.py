"""PaperScout subagent events.

This module defines events for the PaperScout subagent.
Events are self-registered at module load time following RFC-0018.
"""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict

from soothe_sdk import SubagentEvent


class PaperScoutStepEvent(SubagentEvent):
    """Workflow step progress event."""

    type: Literal["soothe.community.paperscout.step"] = "soothe.community.paperscout.step"
    step: str = ""
    status: str = ""

    model_config = ConfigDict(extra="allow")


class PaperScoutPaperFoundEvent(SubagentEvent):
    """New relevant paper discovered."""

    type: Literal["soothe.community.paperscout.paper_found"] = "soothe.community.paperscout.paper_found"
    paper_title: str = ""
    arxiv_id: str = ""
    score: float = 0.0

    model_config = ConfigDict(extra="allow")


class PaperScoutEmailSentEvent(SubagentEvent):
    """Email notification sent."""

    type: Literal["soothe.community.paperscout.email_sent"] = "soothe.community.paperscout.email_sent"
    recipient: str = ""
    papers_count: int = 0

    model_config = ConfigDict(extra="allow")


class PaperScoutErrorEvent(SubagentEvent):
    """Error during execution."""

    type: Literal["soothe.community.paperscout.error"] = "soothe.community.paperscout.error"
    error_message: str = ""
    step: str = ""

    model_config = ConfigDict(extra="allow")


# Register all PaperScout events with the plugin-level registry
from soothe_sdk import register_event  # noqa: E402
from soothe_sdk import VerbosityTier

register_event(
    PaperScoutStepEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="{step}: {status}",
)
register_event(
    PaperScoutPaperFoundEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="Found paper: {paper_title} (score: {score:.2f})",
)
register_event(
    PaperScoutEmailSentEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="Email sent to {recipient} with {papers_count} papers",
)
register_event(
    PaperScoutErrorEvent,
    verbosity=VerbosityTier.DEBUG,
    summary_template="Error in {step}: {error_message}",
)

# Event type constants for convenient imports
PAPERSCOUT_STEP = "soothe.community.paperscout.step"
PAPERSCOUT_PAPER_FOUND = "soothe.community.paperscout.paper_found"
PAPERSCOUT_EMAIL_SENT = "soothe.community.paperscout.email_sent"
PAPERSCOUT_ERROR = "soothe.community.paperscout.error"

__all__ = [
    "PAPERSCOUT_EMAIL_SENT",
    "PAPERSCOUT_ERROR",
    "PAPERSCOUT_PAPER_FOUND",
    "PAPERSCOUT_STEP",
    "PaperScoutEmailSentEvent",
    "PaperScoutErrorEvent",
    "PaperScoutPaperFoundEvent",
    "PaperScoutStepEvent",
]
