"""Tests for RFC-904 decomposition proposal types (IG-751 P0)."""

import pytest
from pydantic import ValidationError

from soothe.config.models import DecomposeLoopConfig
from soothe.context.decomposition import DecompositionProposal, ProposedSubtask


class TestProposedSubtask:
    def test_requires_description(self) -> None:
        with pytest.raises(ValidationError):
            ProposedSubtask(description="  ")


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

    def test_rejects_bad_local_dep(self) -> None:
        with pytest.raises(ValidationError):
            DecompositionProposal(
                parent_step_id="R",
                subtasks=[ProposedSubtask(description="only", depends_on_local=[1])],
            )

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
