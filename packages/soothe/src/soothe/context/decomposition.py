"""Decomposition proposal types for recursive step decompose (RFC-904 / IG-751).

Threads emit proposals; CE reconcile commits children. These models must not
write the StepDAG directly.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator
from soothe_sdk.intention.models import TaskComplexity

from soothe.context.models import ExecutionHint

StepOutcome = Literal["complete", "decompose", "blocked"]


class ProposedSubtask(BaseModel):
    """One proposed child step inside a ``DecompositionProposal``."""

    description: str
    full_description: str = ""
    expected_output: str = ""
    execution_hint: ExecutionHint | None = "auto"
    depends_on_local: list[int] | None = None
    in_scope: bool = Field(
        default=True,
        description="Eval assertion that this child is within the original user goal.",
    )
    necessary_for_user_goal: bool = Field(
        default=True,
        description="Eval assertion that this child is necessary to complete the user goal.",
    )
    task_complexity: TaskComplexity = Field(
        default=TaskComplexity.SIMPLE,
        description=(
            "Complexity of this child step: simple (single focused step) or "
            "complex (needs further decomposition)."
        ),
    )

    @field_validator("description")
    @classmethod
    def _description_nonempty(cls, value: str) -> str:
        text = (value or "").strip()
        if not text:
            raise ValueError("subtask description must be non-empty")
        return text


class DecompositionProposal(BaseModel):
    """Local parent-relative proposal queued for CE reconcile (RFC-904)."""

    parent_step_id: str
    subtasks: list[ProposedSubtask] = Field(min_length=1)
    wave_seq: int = 0

    @field_validator("parent_step_id")
    @classmethod
    def _parent_nonempty(cls, value: str) -> str:
        text = (value or "").strip()
        if not text:
            raise ValueError("parent_step_id must be non-empty")
        return text

    @field_validator("subtasks")
    @classmethod
    def _validate_local_deps(cls, subtasks: list[ProposedSubtask]) -> list[ProposedSubtask]:
        n = len(subtasks)
        for idx, sub in enumerate(subtasks):
            deps = sub.depends_on_local or []
            for dep in deps:
                if dep < 0 or dep >= n or dep == idx:
                    raise ValueError(
                        f"subtask[{idx}] depends_on_local={dep} is out of range or self-ref"
                    )
        return subtasks
