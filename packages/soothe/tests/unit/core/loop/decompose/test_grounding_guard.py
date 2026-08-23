"""Unit tests for the decompose_task LLM grounding critic (d15f hallucination defense).

Replaces the former filesystem-path existence guard with an LLM-driven
evidence-vs-proposal consistency check (sandbox-compatible).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from soothe.context.decomposition import DecompositionProposal, ProposedSubtask
from soothe.sloop.decompose.grounding_guard import (
    GroundingVerdict,
    UngroundedClaim,
    build_no_evidence_guidance,
    build_ungrounded_claims_guidance,
    check_proposal_grounded,
)

# ── fixtures ────────────────────────────────────────────────────────────────


def _proposal(*descs: str) -> DecompositionProposal:
    return DecompositionProposal(
        parent_step_id="SUZ-01",
        subtasks=[ProposedSubtask(description=d, full_description=d) for d in descs],
    )


def _verdict_grounded() -> GroundingVerdict:
    return GroundingVerdict(grounded=True, ungrounded_claims=[])


def _verdict_ungrounded(claims: list[tuple[int, str, str]]) -> GroundingVerdict:
    return GroundingVerdict(
        grounded=False,
        ungrounded_claims=[UngroundedClaim(subtask=i, claim=c, reason=r) for i, c, r in claims],
    )


# ── build_no_evidence_guidance ─────────────────────────────────────────────


def test_build_no_evidence_guidance() -> None:
    msg = build_no_evidence_guidance(step_id="SUZ-01")
    assert "SUZ-01" in msg
    assert "NOT queued" in msg
    assert "evidence" in msg.lower()


# ── build_ungrounded_claims_guidance ────────────────────────────────────────


def test_build_ungrounded_claims_guidance_lists_claims() -> None:
    verdict = _verdict_ungrounded(
        [(0, "client/swift/ 的 Swift 端代码", "证据中未出现 swift 相关内容")]
    )
    msg = build_ungrounded_claims_guidance(verdict, step_id="SUZ-01")
    assert "SUZ-01" in msg
    assert "NOT queued" in msg
    assert "client/swift/" in msg
    assert "swift" in msg.lower()


def test_build_ungrounded_claims_guidance_truncates_many_claims() -> None:
    claims = [(i, f"claim-{i}", f"reason-{i}") for i in range(8)]
    verdict = _verdict_ungrounded(claims)
    msg = build_ungrounded_claims_guidance(verdict, step_id="SUZ-01")
    assert "…" in msg  # truncation marker for >5 claims


# ── check_proposal_grounded ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_check_grounded_returns_verdict_when_grounded() -> None:
    """Proposal whose claims appear in evidence → grounded=True."""
    mock_model = MagicMock()
    proposal = _proposal("Clean up packages/soothe: dead code in sloop/state/checkpoint.py")
    evidence = ["packages/soothe/src/soothe/sloop/state/checkpoint.py exists"]
    with patch(
        "soothe_nano.llm.ainvoke_structured_traced",
        new_callable=AsyncMock,
        return_value=_verdict_grounded().model_dump(),
    ):
        verdict = await check_proposal_grounded(
            proposal,
            evidence_corpus=evidence,
            fast_model=mock_model,
            step_id="SUZ-01",
        )
    assert verdict is not None
    assert verdict.grounded is True
    assert verdict.ungrounded_claims == []


@pytest.mark.asyncio
async def test_check_grounded_returns_verdict_when_ungrounded() -> None:
    """Proposal whose claims are absent from evidence → grounded=False."""
    mock_model = MagicMock()
    proposal = _proposal("Clean up client/swift/ and client/kotlin/ dead code")
    evidence = ["packages/soothe/ exists"]
    ungrounded = _verdict_ungrounded([(0, "client/swift/", "no swift reference in evidence")])
    with patch(
        "soothe_nano.llm.ainvoke_structured_traced",
        new_callable=AsyncMock,
        return_value=ungrounded.model_dump(),
    ):
        verdict = await check_proposal_grounded(
            proposal,
            evidence_corpus=evidence,
            fast_model=mock_model,
            step_id="SUZ-01",
        )
    assert verdict is not None
    assert verdict.grounded is False
    assert len(verdict.ungrounded_claims) == 1
    assert verdict.ungrounded_claims[0].claim == "client/swift/"


@pytest.mark.asyncio
async def test_check_grounded_fails_open_when_no_fast_model() -> None:
    """No fast model → fail-open (None), don't block the proposal."""
    proposal = _proposal("do some work")
    verdict = await check_proposal_grounded(
        proposal,
        evidence_corpus=["some evidence"],
        fast_model=None,
        step_id="SUZ-01",
    )
    assert verdict is None


@pytest.mark.asyncio
async def test_check_grounded_fails_open_on_llm_error() -> None:
    """LLM call raises → fail-open (None), don't block the proposal."""
    mock_model = MagicMock()
    proposal = _proposal("do some work")
    with patch(
        "soothe_nano.llm.ainvoke_structured_traced",
        new_callable=AsyncMock,
        side_effect=RuntimeError("provider down"),
    ):
        verdict = await check_proposal_grounded(
            proposal,
            evidence_corpus=["some evidence"],
            fast_model=mock_model,
            step_id="SUZ-01",
        )
    assert verdict is None


@pytest.mark.asyncio
async def test_check_grounded_fails_open_when_no_evidence() -> None:
    """Empty evidence corpus → None (defensive; tool.py gate catches this first)."""
    mock_model = MagicMock()
    proposal = _proposal("do some work")
    verdict = await check_proposal_grounded(
        proposal,
        evidence_corpus=[],
        fast_model=mock_model,
        step_id="SUZ-01",
    )
    assert verdict is None
