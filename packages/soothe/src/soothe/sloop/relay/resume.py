"""Resume: store answers, build resume directives, consume clarifications.

- `submit_answer` — store an answer (idempotent, schema-validated), unblock CE.
- `build_resume_directive` — get the graph re-invoke plan + CoreAgent resume spec.
- `get_core_agent_resume` — get the `Command(resume=...)` payload for the execute node.
- `consume` — mark the row as consumed (lifecycle complete).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Protocol

from soothe.sloop.clarification.protocol import (
    ClarificationAnswer,
    answer_to_state,
    request_to_state,
)
from soothe.sloop.relay.errors import InvalidAnswerSchemaError, RelayStateConflictError
from soothe.sloop.relay.origin_router import build_core_agent_resume
from soothe.sloop.relay.reconcile import reconcile_clarification
from soothe.sloop.relay.store import ClarificationStore, encode_answer
from soothe.sloop.relay.types import (
    CoreAgentResumeSpec,
    ResumeDirective,
    SubmitResult,
)

if TYPE_CHECKING:
    from soothe.sloop.relay.types import AnswerSource

logger = logging.getLogger(__name__)

_EmitFn = Any


class _CEProtocol(Protocol):
    async def answer_clarification(self, goal_id: str, answers: list[str]) -> None: ...


async def submit_answer(
    store: ClarificationStore,
    *,
    relay_id: str,
    answers: tuple[str, ...] | list[str],
    source: AnswerSource,
    idempotency_key: str | None = None,
    ce: _CEProtocol | None = None,
    emit: _EmitFn | None = None,
) -> SubmitResult:
    """Submit an answer to a parked clarification (idempotent).

    Raises `InvalidAnswerSchemaError` on validation failure.
    """
    row = await store.get(relay_id)
    if row is None:
        return SubmitResult(status="invalid_schema", relay_id=relay_id)

    if row.status in ("answered", "consumed"):
        return SubmitResult(
            status="already_answered",
            relay_id=relay_id,
            stored_answer=row.decode_answer(),
        )

    answer_tuple = tuple(answers)
    _validate_answers(row.origin, answer_tuple)

    answer = ClarificationAnswer(answers=answer_tuple, source=source, defer=False)
    update_fields: dict[str, Any] = {
        "status": "answered",
        "answer_json": encode_answer(answer),
        "answer_source": source,
        "answered_at": datetime.now(UTC).isoformat(),
    }
    if idempotency_key is not None:
        update_fields["idempotency_key"] = idempotency_key
    await store.update(relay_id, **update_fields)

    if ce is not None:
        try:
            await ce.answer_clarification(row.goal_id, list(answer_tuple))
        except Exception:
            logger.warning("[Relay] CE answer failed (relay=%s)", relay_id[:12], exc_info=True)

    if emit is not None:
        await emit(
            "goal_unblocked",
            {
                "goal_id": row.goal_id,
                "relay_id": relay_id,
                "old_status": "awaiting_clarification",
                "new_status": "pending",
            },
        )

    logger.info("[Relay] answered relay_id=%s source=%s", relay_id[:12], source)
    return SubmitResult(status="ok", relay_id=relay_id, stored_answer=answer)


async def build_resume_directive(
    store: ClarificationStore,
    *,
    relay_id: str,
    ce: Any | None = None,
    checkpointer: Any | None = None,
) -> ResumeDirective:
    """Build the StrangeLoop re-invoke plan for an answered clarification.

    Raises `RelayStateConflictError` on inconsistency.
    """
    from soothe.sloop.relay.origin_router import resume_station_for_origin

    report = await reconcile_clarification(
        store,
        relay_id=relay_id,
        ce=ce,
        checkpointer=checkpointer,
    )
    if not report.consistent:
        raise RelayStateConflictError(relay_id, report.conflict or "unknown conflict")

    row = await store.get(relay_id)
    if row is None:
        raise RelayStateConflictError(relay_id, "row not found after reconcile")

    answer = row.decode_answer()
    if answer is None:
        raise RelayStateConflictError(relay_id, "answered row has no answer_json")

    request = row.decode_request()

    instructive_reason: str | None = None
    if isinstance(answer.audit, dict) and answer.audit.get("instructive"):
        instructive_reason = str(answer.audit.get("reason") or "").strip() or None

    core_agent_resume = build_core_agent_resume(
        row,
        answers=answer.answers,
        instructive_reason=instructive_reason,
    )

    graph_input: dict[str, Any] = {
        "last_outcome": None,
        "pending_clarification_answer": answer_to_state(answer),
        "pending_clarification": request_to_state(request),
        "resume_relay_id": relay_id,
        "last_clarification_origin": row.origin,
    }
    station = resume_station_for_origin(row.origin)

    logger.info("[Relay] resume directive relay_id=%s station=%s", relay_id[:12], station)
    return ResumeDirective(
        relay_id=relay_id,
        graph_input=graph_input,
        core_agent_resume=core_agent_resume,
        resume_station=station,
    )


async def get_core_agent_resume(
    store: ClarificationStore,
    *,
    relay_id: str,
) -> CoreAgentResumeSpec | None:
    """Get the CoreAgent `Command(resume=...)` spec for an answered row."""
    row = await store.get(relay_id)
    if row is None:
        return None
    answer = row.decode_answer()
    if answer is None:
        return None
    instructive_reason: str | None = None
    if isinstance(answer.audit, dict) and answer.audit.get("instructive"):
        instructive_reason = str(answer.audit.get("reason") or "").strip() or None
    return build_core_agent_resume(
        row,
        answers=answer.answers,
        instructive_reason=instructive_reason,
    )


async def consume_clarification(store: ClarificationStore, *, relay_id: str) -> None:
    """Mark a clarification row as consumed (lifecycle complete)."""
    await store.update(relay_id, status="consumed", consumed_at=datetime.now(UTC).isoformat())
    logger.info("[Relay] consumed relay_id=%s", relay_id[:12])


def _validate_answers(origin: str, answers: tuple[str, ...]) -> None:
    """Validate answers against the origin's expected schema."""
    from soothe.sloop.clarification.origins import ORIGIN_TOOL_APPROVAL
    from soothe.sloop.relay.origin_router import ToolApprovalDecision

    if not answers or not any(a.strip() for a in answers):
        raise InvalidAnswerSchemaError("", "at least one non-empty answer required")

    if origin == ORIGIN_TOOL_APPROVAL:
        for i, ans in enumerate(answers):
            try:
                ToolApprovalDecision.from_answer_string(ans)
            except InvalidAnswerSchemaError as exc:
                raise InvalidAnswerSchemaError("", f"answer[{i}] ({ans!r}): {exc.detail}") from exc


__all__ = [
    "build_resume_directive",
    "consume_clarification",
    "get_core_agent_resume",
    "submit_answer",
]
