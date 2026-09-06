"""Single projection / hydration of relay state to the `relay_state` channel.

Owns the projection of both the inbox and the serializable subset of
`LoopPhaseScratch` into one graph channel — the single reentrancy boundary.
Fields that must survive a worker exit are projected before parking; a fresh
worker rehydrates on resume.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from soothe.sloop.clarification.protocol import (
    request_from_state,
    request_to_state,
)
from soothe.sloop.relay.ticket import (
    ticket_from_state,
    ticket_to_state,
)

if TYPE_CHECKING:
    from soothe.sloop.orchestrator.runtime_context import LoopPhaseScratch
    from soothe.sloop.relay.inbox import RelayInbox

logger = logging.getLogger(__name__)


@dataclass
class ScratchProjection:
    """Serializable subset of `LoopPhaseScratch`.

    `iteration_perf_start` (ephemeral timer) and `step_results` (CE-backed)
    are deliberately NOT projected — they do not need to survive a worker exit.
    """

    plan_result: dict[str, Any] | None = None
    decision: dict[str, Any] | None = None
    plan_draft_path: str | None = None
    plan_draft_markdown: str | None = None
    plan_review_comments: str | None = None
    decompose_proposals: list[Any] = field(default_factory=list)
    follow_on_exec: dict[str, Any] | None = None
    plan_rejected: bool = False


def _serialize_model(obj: Any) -> dict[str, Any] | None:
    """Serialize a Pydantic model or dataclass to a JSON-safe dict.

    Returns `None` for falsy values. Falls back to `dict(obj)` for plain
    mappings and `None` for anything else.
    """
    if obj is None:
        return None
    dump = getattr(obj, "model_dump", None)
    if callable(dump):
        return dump(mode="json")  # type: ignore[no-any-return]
    if isinstance(obj, Mapping):
        return dict(obj)
    if hasattr(obj, "__dict__"):
        return {k: v for k, v in vars(obj).items() if not k.startswith("_")}
    return None


def _deserialize_model(d: Any, model_cls: type) -> Any:
    """Reconstruct a Pydantic model or dataclass from a dict.

    Returns `None` when `d` is falsy. Tries `model_cls.model_validate`
    (Pydantic v2), then `model_cls(**d)`, then `None`.
    """
    if not d:
        return None
    validate = getattr(model_cls, "model_validate", None)
    if callable(validate):
        try:
            return validate(d)
        except Exception:
            logger.debug(
                "[channel] model_validate failed for %s", model_cls.__name__, exc_info=True
            )
    if isinstance(d, Mapping):
        try:
            return model_cls(**dict(d))
        except Exception:
            logger.debug("[channel] %s(**d) failed", model_cls.__name__, exc_info=True)
    return None


def project_scratch(scratch: LoopPhaseScratch) -> ScratchProjection:
    """Project the serializable subset of scratch onto a `ScratchProjection`."""
    return ScratchProjection(
        plan_result=_serialize_model(getattr(scratch, "plan_result", None)),
        decision=_serialize_model(getattr(scratch, "decision", None)),
        plan_draft_path=getattr(scratch, "plan_draft_path", None),
        plan_draft_markdown=getattr(scratch, "plan_draft_markdown", None),
        plan_review_comments=getattr(scratch, "plan_review_comments", None),
        decompose_proposals=list(getattr(scratch, "decompose_proposals", []) or []),
        follow_on_exec=dict(getattr(scratch, "follow_on_exec", {}) or {}) or None,
        plan_rejected=bool(getattr(scratch, "plan_rejected", False)),
    )


def hydrate_scratch(scratch: LoopPhaseScratch, projection: ScratchProjection) -> None:
    """Restore serializable fields onto scratch from a projection.

    Idempotent: skips a field when the live scratch already has a non-empty
    value so re-hydration does not clobber fresh state.
    """
    if projection.plan_result is not None and getattr(scratch, "plan_result", None) is None:
        from soothe.sloop.state.schemas import PlanResult

        scratch.plan_result = _deserialize_model(projection.plan_result, PlanResult)
    if projection.decision is not None and getattr(scratch, "decision", None) is None:
        from soothe.sloop.state.schemas import AgentDecision

        scratch.decision = _deserialize_model(projection.decision, AgentDecision)
    if projection.plan_draft_path and not (getattr(scratch, "plan_draft_path", None) or "").strip():
        scratch.plan_draft_path = projection.plan_draft_path
    if (
        projection.plan_draft_markdown
        and not (getattr(scratch, "plan_draft_markdown", None) or "").strip()
    ):
        scratch.plan_draft_markdown = projection.plan_draft_markdown
    if (
        projection.plan_review_comments
        and not (getattr(scratch, "plan_review_comments", None) or "").strip()
    ):
        scratch.plan_review_comments = projection.plan_review_comments
    if projection.decompose_proposals and not getattr(scratch, "decompose_proposals", None):
        scratch.decompose_proposals = list(projection.decompose_proposals)
    if projection.follow_on_exec is not None and getattr(scratch, "follow_on_exec", None) is None:
        scratch.follow_on_exec = dict(projection.follow_on_exec) or None
    if projection.plan_rejected and not getattr(scratch, "plan_rejected", False):
        scratch.plan_rejected = True


def _fallback_plan_markdown_from_disk(path: str) -> str | None:
    """Read a plan artifact from disk when the projection lacks its markdown body."""
    try:
        from pathlib import Path

        return Path(path).read_text(encoding="utf-8")
    except OSError:
        logger.debug("[channel] could not reload plan artifact %s", path, exc_info=True)
        return None


def project_inbox(inbox: RelayInbox) -> list[dict[str, Any]]:
    """Serialize a `RelayInbox` to a JSON-safe list for channel storage."""
    entries: list[dict[str, Any]] = []
    for entry in inbox:
        entries.append(
            {
                "request": request_to_state(entry.request),
                "resume_ticket": ticket_to_state(entry.resume_ticket),
                "step_id": entry.step_id,
            }
        )
    return entries


def hydrate_inbox(relay_state: Mapping[str, Any] | None) -> RelayInbox:
    """Rebuild a `RelayInbox` from the `relay_state` channel.

    Returns an empty inbox when the channel is absent or malformed (defensive
    against a partial checkpoint).
    """
    from soothe.sloop.relay.inbox import RelayInbox

    inbox = RelayInbox()
    if not isinstance(relay_state, Mapping):
        return inbox
    raw_entries = relay_state.get("inbox")
    if not isinstance(raw_entries, list):
        return inbox
    for raw in raw_entries:
        if not isinstance(raw, Mapping):
            continue
        request_state = raw.get("request")
        if not isinstance(request_state, Mapping):
            continue
        try:
            request = request_from_state(request_state)
        except (ValueError, TypeError):
            logger.debug("[channel] skipping malformed inbox entry on hydrate", exc_info=True)
            continue
        ticket = ticket_from_state(raw.get("resume_ticket"))
        if ticket is None:
            continue
        inbox.enqueue(
            request,
            resume_ticket=ticket,
            step_id=raw.get("step_id"),
        )
    return inbox


def build_relay_state_update(
    *,
    inbox: RelayInbox,
    scratch: LoopPhaseScratch | None,
    active_origin: str | None,
    answer: dict[str, Any] | None,
    audit: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Assemble the full `relay_state` dict for a graph channel update.

    Returns `{"relay_state": {...}}` ready to merge into a node's return dict.
    """
    state: dict[str, Any] = {
        "inbox": project_inbox(inbox),
        "active_origin": active_origin,
        "answer": answer,
        "audit": list(audit or []),
    }
    if scratch is not None:
        projection = project_scratch(scratch)
        state["scratch"] = {
            "plan_result": projection.plan_result,
            "decision": projection.decision,
            "plan_draft_path": projection.plan_draft_path,
            "plan_draft_markdown": projection.plan_draft_markdown,
            "plan_review_comments": projection.plan_review_comments,
            "decompose_proposals": projection.decompose_proposals,
            "follow_on_exec": projection.follow_on_exec,
            "plan_rejected": projection.plan_rejected,
        }
    return {"relay_state": state}


def hydrate_scratch_from_relay_state(
    scratch: LoopPhaseScratch,
    relay_state: Mapping[str, Any] | None,
) -> None:
    """Restore scratch fields from the `relay_state` channel.

    Reads the `scratch` sub-dict from `relay_state`. Falls back to reading the
    plan artifact from disk when the markdown body is missing.
    """
    if not isinstance(relay_state, Mapping):
        return
    scratch_state = relay_state.get("scratch")
    if not isinstance(scratch_state, Mapping):
        return
    projection = ScratchProjection(
        plan_result=scratch_state.get("plan_result"),
        decision=scratch_state.get("decision"),
        plan_draft_path=scratch_state.get("plan_draft_path"),
        plan_draft_markdown=scratch_state.get("plan_draft_markdown"),
        plan_review_comments=scratch_state.get("plan_review_comments"),
        decompose_proposals=list(scratch_state.get("decompose_proposals") or []),
        follow_on_exec=scratch_state.get("follow_on_exec"),
        plan_rejected=bool(scratch_state.get("plan_rejected", False)),
    )
    hydrate_scratch(scratch, projection)
    path = (getattr(scratch, "plan_draft_path", None) or "").strip()
    if path and not (getattr(scratch, "plan_draft_markdown", None) or "").strip():
        text = _fallback_plan_markdown_from_disk(path)
        if text:
            scratch.plan_draft_markdown = text
            scratch.plan_draft_path = path


__all__ = [
    "ScratchProjection",
    "build_relay_state_update",
    "hydrate_inbox",
    "hydrate_scratch",
    "hydrate_scratch_from_relay_state",
    "project_inbox",
    "project_scratch",
]
