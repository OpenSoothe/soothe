"""RFC-204: Proposal Queue for Layer 2 → Layer 3 communication.

Layer 2 tools write proposals to this queue during execution. Layer 3
processes them after the iteration completes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

logger = logging.getLogger(__name__)

ProposalType = Literal["report_progress", "suggest_goal", "add_finding", "flag_blocker"]


@dataclass
class Proposal:
    """A proposal from Layer 2 to Layer 3.

    Args:
        type: Proposal type string.
        goal_id: The goal this proposal relates to.
        payload: Type-specific data as dict.
        timestamp: When the proposal was made.
    """

    type: ProposalType
    goal_id: str
    payload: dict = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(tz=UTC))


class ProposalQueue:
    """Collects proposals from Layer 2 tools during goal execution.

    Proposals are drained and processed by Layer 3 after iteration completes.
    """

    def __init__(self) -> None:
        """Initialize empty proposal queue."""
        self._proposals: list[Proposal] = []

    def enqueue(self, proposal: Proposal) -> None:
        """Add a proposal to the queue.

        Args:
            proposal: The proposal to enqueue.
        """
        self._proposals.append(proposal)
        logger.debug("Proposal enqueued: type=%s, goal=%s", proposal.type, proposal.goal_id)

    def drain(self) -> list[Proposal]:
        """Remove and return all proposals.

        Returns:
            List of all enqueued proposals.
        """
        proposals = self._proposals
        self._proposals = []
        return proposals

    def is_empty(self) -> bool:
        """Check if the queue is empty.

        Returns:
            True if no proposals are pending.
        """
        return len(self._proposals) == 0
