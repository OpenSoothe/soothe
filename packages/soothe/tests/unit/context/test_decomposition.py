"""Tests for decomposition proposal types."""

import pytest
from pydantic import ValidationError

from soothe.config.models import DecomposeLoopConfig
from soothe.context.decomposition import DecompositionProposal, ProposedSubtask


class TestProposedSubtask:
    def test_empty_description_coerced(self) -> None:
        sub = ProposedSubtask(description="  ")
        assert sub.description == "(untitled subtask)"


class TestDecompositionProposal:
    def test_basic(self) -> None:
        prop = DecompositionProposal(
            parent_step_id="AAA-01",
            subtasks=[
                ProposedSubtask(description="A", full_description="do A"),
                ProposedSubtask(description="B", depends_on_local=[0]),
            ],
        )
        assert len(prop.subtasks) == 2
        assert prop.subtasks[1].depends_on_local == [0]

    def test_bad_local_dep_dropped(self) -> None:
        """Out-of-range or self-ref deps are dropped, not rejected."""
        prop = DecompositionProposal(
            parent_step_id="R",
            subtasks=[ProposedSubtask(description="only", depends_on_local=[1])],
        )
        assert prop.subtasks[0].depends_on_local is None

    def test_self_ref_dep_dropped(self) -> None:
        """Self-referential deps are dropped."""
        prop = DecompositionProposal(
            parent_step_id="R",
            subtasks=[
                ProposedSubtask(description="A", depends_on_local=[0]),
                ProposedSubtask(description="B", depends_on_local=[0, 1]),
            ],
        )
        assert prop.subtasks[0].depends_on_local is None
        assert prop.subtasks[1].depends_on_local == [0]

    def test_rejects_empty_subtasks(self) -> None:
        with pytest.raises(ValidationError):
            DecompositionProposal(parent_step_id="R", subtasks=[])


class TestDecomposeLoopConfig:
    def test_defaults(self) -> None:
        cfg = DecomposeLoopConfig()
        assert cfg.max_depth == 3
        assert cfg.max_branch_root == 5
        assert cfg.max_branch_inner == 3
        assert "enabled" not in DecomposeLoopConfig.model_fields
