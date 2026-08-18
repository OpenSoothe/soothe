"""Pure-Python card-ledger primitives shared by host and clients.

This module defines the on-disk and on-wire record shape (``CardMutation``)
and an in-memory projection (``InMemoryCardLedger``) used by:

* the host-side display store (writer) that persists mutations via
  ``DisplayCardStore`` (SQLite ``display.db`` or PostgreSQL), and
* any consumer that needs to reconstruct the current card set from a
  mutation stream (replay-to-client, future desktop client, debug tooling).

No I/O lives here — durable stores and async locks belong to the host-side
ledger wrapper.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from soothe_sdk.display.transcript_types import (
    UPDATABLE_FIELDS,
    MessageData,
    MessageType,
    ToolStatus,
)

CARD_SCHEMA_VERSION = 1

CardOp = Literal["header", "create", "update", "finalize"]
"""Mutation operations recorded in the display card store.

* ``header`` — segment header; carries schema version and loop id.
* ``create`` — full ``MessageData`` payload for a new card.
* ``update`` — partial diff against an existing card (live structural updates).
* ``finalize`` — terminal state (success/error/duration).
"""

_HEADER_CARD_ID = "__header__"
_HEADER_KIND = "header"


@dataclass(frozen=True, slots=True)
class CardMutation:
    """One display-card mutation record (wire / store).

    The ``data`` payload shape depends on ``op``:

    * ``op="header"`` → ``{"card_schema_version": int, "loop_id": str,
      "created_by": str}``.
    * ``op="create"`` → full ``MessageData`` wire dict (output of
      ``card_to_wire_dict``).
    * ``op="update"`` / ``op="finalize"`` → subset of ``MessageData`` fields,
      restricted to ``UPDATABLE_FIELDS``.
    """

    seq: int
    ts: str
    op: CardOp
    card_id: str
    kind: str
    data: dict[str, Any]

    def to_jsonl_dict(self) -> dict[str, Any]:
        """Serialize for durable store / debug export (stable key order)."""
        return {
            "seq": self.seq,
            "ts": self.ts,
            "op": self.op,
            "card_id": self.card_id,
            "kind": self.kind,
            "data": self.data,
        }

    @classmethod
    def from_jsonl_dict(cls, raw: dict[str, Any]) -> CardMutation:
        """Build a ``CardMutation`` from a parsed store / export dict."""
        return cls(
            seq=int(raw["seq"]),
            ts=str(raw["ts"]),
            op=str(raw["op"]),  # type: ignore[arg-type]  # validated by the host ledger
            card_id=str(raw["card_id"]),
            kind=str(raw["kind"]),
            data=dict(raw.get("data") or {}),
        )


def utc_now_iso() -> str:
    """ISO-8601 UTC timestamp suitable for the ``ts`` field on a mutation."""
    return datetime.now(UTC).isoformat()


def card_to_wire_dict(card: MessageData) -> dict[str, Any]:
    """Convert a ``MessageData`` to a JSON-safe dict for the wire / disk.

    ``StrEnum`` values serialize as their string value via ``dataclasses.asdict``;
    ``None`` fields are preserved so the receiver can round-trip via
    ``card_from_wire_dict``.
    """
    return dataclasses.asdict(card)


def card_from_wire_dict(data: dict[str, Any]) -> MessageData:
    """Reconstruct a ``MessageData`` from a wire / disk dict.

    Enum fields (``type``, ``tool_status``) are cast back to their typed enums
    so consumers can rely on identity comparisons against ``MessageType.*`` /
    ``ToolStatus.*``.
    """
    payload = dict(data)
    type_value = payload.get("type")
    if isinstance(type_value, str):
        payload["type"] = MessageType(type_value)
    status_value = payload.get("tool_status")
    if isinstance(status_value, str):
        payload["tool_status"] = ToolStatus(status_value)
    return MessageData(**payload)


@dataclass
class _LedgerHeader:
    """Header metadata for a live card segment."""

    card_schema_version: int = CARD_SCHEMA_VERSION
    loop_id: str = ""
    created_by: str = ""


def build_header_mutation(*, loop_id: str, created_by: str) -> CardMutation:
    """Make the seq=0 header record written when a new ledger file is created."""
    return CardMutation(
        seq=0,
        ts=utc_now_iso(),
        op="header",
        card_id=_HEADER_CARD_ID,
        kind=_HEADER_KIND,
        data={
            "card_schema_version": CARD_SCHEMA_VERSION,
            "loop_id": loop_id,
            "created_by": created_by,
        },
    )


@dataclass
class InMemoryCardLedger:
    """Latest-state-per-``card_id`` projection of a mutation stream.

    Insertion order is preserved so ``snapshot()`` returns cards in the order
    they were first created. ``apply()`` is the only mutation entry point;
    ``next_seq`` is the sequence number to assign to the next produced
    mutation.
    """

    loop_id: str = ""
    next_seq: int = 1
    header: _LedgerHeader = field(default_factory=_LedgerHeader)
    _cards: dict[str, MessageData] = field(default_factory=dict)

    def apply(self, mutation: CardMutation) -> None:
        """Fold one mutation into the in-memory state.

        Args:
            mutation: A ``header``/``create``/``update``/``finalize`` record.

        Raises:
            ValueError: For unknown ``op`` values, missing ``card_id`` on
                non-header records, or ``update``/``finalize`` against an
                unknown ``card_id``.
        """
        op = mutation.op
        if op == "header":
            self.header = _LedgerHeader(
                card_schema_version=int(
                    mutation.data.get("card_schema_version", CARD_SCHEMA_VERSION)
                ),
                loop_id=str(mutation.data.get("loop_id", "")),
                created_by=str(mutation.data.get("created_by", "")),
            )
            if self.header.loop_id and not self.loop_id:
                self.loop_id = self.header.loop_id
            # Header occupies seq 0; first real mutation is seq 1.
            self.next_seq = max(self.next_seq, mutation.seq + 1)
            return

        if not mutation.card_id:
            msg = f"non-header mutation must carry a card_id (got op={op!r})"
            raise ValueError(msg)

        if op == "create":
            self._cards[mutation.card_id] = card_from_wire_dict(mutation.data)
        elif op in ("update", "finalize"):
            existing = self._cards.get(mutation.card_id)
            if existing is None:
                msg = (
                    f"cannot apply op={op!r} to unknown card_id={mutation.card_id!r}; "
                    "ledger missing prior create record"
                )
                raise ValueError(msg)
            for key, value in mutation.data.items():
                if key not in UPDATABLE_FIELDS:
                    # Silently ignore non-updatable fields; preserves identity
                    # invariants on id/type/timestamp.
                    continue
                setattr(existing, key, value)
        else:
            msg = f"unknown card mutation op: {op!r}"
            raise ValueError(msg)

        self.next_seq = max(self.next_seq, mutation.seq + 1)

    def snapshot(self) -> list[MessageData]:
        """Return cards in insertion order (live render-ready)."""
        return list(self._cards.values())

    def card_count(self) -> int:
        """Number of distinct cards currently in the ledger."""
        return len(self._cards)

    def get(self, card_id: str) -> MessageData | None:
        """Return one card by id, or ``None`` if not present."""
        return self._cards.get(card_id)

    def to_mutations(self, *, start_seq: int = 1) -> list[CardMutation]:
        """Produce a ``create``-only mutation stream for the current snapshot.

        Used by replay-to-client (snapshot the ledger then stream as if every
        card were freshly created) and by backfill (materialize a ledger from
        bound ``MessageData`` produced by ``CardBinder.convert_messages_to_data``).
        """
        out: list[CardMutation] = []
        for offset, (card_id, card) in enumerate(self._cards.items()):
            out.append(
                CardMutation(
                    seq=start_seq + offset,
                    ts=utc_now_iso(),
                    op="create",
                    card_id=card_id,
                    kind=str(card.type),
                    data=card_to_wire_dict(card),
                )
            )
        return out

    @classmethod
    def from_mutations(
        cls,
        mutations: Iterable[CardMutation],
        *,
        loop_id: str = "",
    ) -> InMemoryCardLedger:
        """Build a ledger by folding ``mutations`` in order."""
        ledger = cls(loop_id=loop_id)
        for mutation in mutations:
            ledger.apply(mutation)
        return ledger


def cards_to_mutations(
    cards: Iterable[MessageData],
    *,
    start_seq: int = 1,
) -> list[CardMutation]:
    """Convert an ordered ``MessageData`` list into ``create`` mutations.

    Used by backfill: ``CardBinder.convert_messages_to_data`` returns a
    ``list[MessageData]``; this helper turns each into a ``create`` mutation
    ready for the host ledger's append path.
    """
    out: list[CardMutation] = []
    for offset, card in enumerate(cards):
        out.append(
            CardMutation(
                seq=start_seq + offset,
                ts=utc_now_iso(),
                op="create",
                card_id=card.id,
                kind=str(card.type),
                data=card_to_wire_dict(card),
            )
        )
    return out


def _short_key_hash(value: str) -> str:
    """Stable short hash for content-derived identity keys."""
    import hashlib

    return hashlib.sha1(value.encode("utf-8"), usedforsecurity=False).hexdigest()[:12]


def card_stable_key(card: MessageData, *, ordinal: int) -> str:
    """Return a stable identity key for aligning rebound cards across flushes.

    Args:
        card: Bound display card.
        ordinal: 1-based ordinal among cards that share the same natural key
            prefix (used for streaming assistant text whose content grows).
    """
    t = card.type
    if t == MessageType.STEP_PROGRESS and card.step_progress_id:
        return f"step:{card.step_progress_id}"
    if t == MessageType.COGNITION_REASON:
        it = card.cognition_plan_iteration
        if card.cognition_plan_status or card.cognition_plan_action:
            return f"cognition-plan:{it}"
        return f"cognition-reason:{it}:{_short_key_hash(card.content or '')}"
    if t == MessageType.COGNITION_GOAL_TREE:
        return f"goal-tree:{_short_key_hash(card.cognition_goal_snapshot_json or '')}"
    if t == MessageType.USER:
        return f"user:{_short_key_hash(card.content or '')}"
    if t == MessageType.QUEUED_USER:
        return f"queued-user:{_short_key_hash(card.content or '')}"
    if t == MessageType.ASSISTANT:
        phase = card.loop_output_phase or "_"
        return f"asst:{phase}:#{ordinal}"
    if t == MessageType.ERROR:
        return f"error:{_short_key_hash(card.content or '')}"
    if t == MessageType.APP:
        return f"app:{_short_key_hash(card.content or '')}"
    if t == MessageType.SUMMARIZATION:
        return f"summarization:{_short_key_hash(card.content or '')}"
    if t == MessageType.DIFF:
        return f"diff:{card.diff_file_path or _short_key_hash(card.content or '')}"
    if t == MessageType.SKILL and card.skill_name:
        return f"skill:{card.skill_name}"
    return f"{t}:#{ordinal}"


def assign_card_stable_keys(cards: Iterable[MessageData]) -> list[str]:
    """Assign stable keys for an ordered card list (ordinal-aware)."""
    from collections import defaultdict

    counters: dict[str, int] = defaultdict(int)
    keys: list[str] = []
    for card in cards:
        t = card.type
        if t == MessageType.ASSISTANT:
            phase = card.loop_output_phase or "_"
            prefix = f"asst:{phase}"
            counters[prefix] += 1
            keys.append(card_stable_key(card, ordinal=counters[prefix]))
        elif t == MessageType.STEP_PROGRESS and card.step_progress_id:
            keys.append(card_stable_key(card, ordinal=1))
        elif t == MessageType.COGNITION_REASON and (
            card.cognition_plan_status or card.cognition_plan_action
        ):
            keys.append(card_stable_key(card, ordinal=1))
        else:
            prefix = str(t)
            counters[prefix] += 1
            keys.append(card_stable_key(card, ordinal=counters[prefix]))
    return keys


def align_cards_preserving_ids(
    previous: list[MessageData],
    new_cards: list[MessageData],
) -> tuple[list[MessageData], bool]:
    """Reuse previous ``card.id`` values when stable keys match.

    Returns:
        ``(aligned_cards, needs_full_replace)``. ``needs_full_replace`` is True
        when a previous key is absent from ``new_cards`` (card removed from the
        live projection); callers should fall back to ``replace_with``.
    """
    import dataclasses

    prev_keys = assign_card_stable_keys(previous)
    new_keys = assign_card_stable_keys(new_cards)
    prev_by_key = {key: card for key, card in zip(prev_keys, previous, strict=True)}
    new_key_set = set(new_keys)
    if any(key not in new_key_set for key in prev_by_key):
        return list(new_cards), True

    aligned: list[MessageData] = []
    for key, card in zip(new_keys, new_cards, strict=True):
        prior = prev_by_key.get(key)
        if prior is not None:
            aligned.append(dataclasses.replace(card, id=prior.id, timestamp=prior.timestamp))
        else:
            aligned.append(
                dataclasses.replace(
                    card,
                    id=f"card-{_short_key_hash(key)}",
                )
            )
    return aligned, False


def _updatable_field_diff(prior: MessageData, current: MessageData) -> dict[str, Any]:
    """Return changed ``UPDATABLE_FIELDS`` between two cards with the same id."""
    patch: dict[str, Any] = {}
    for name in UPDATABLE_FIELDS:
        old_val = getattr(prior, name, None)
        new_val = getattr(current, name, None)
        if old_val != new_val:
            if isinstance(new_val, StrEnum):
                patch[name] = str(new_val)
            else:
                patch[name] = new_val
    return patch


def diff_card_snapshots(
    previous: list[MessageData],
    current: list[MessageData],
    *,
    start_seq: int,
) -> list[CardMutation]:
    """Diff two aligned snapshots into append-only create/update mutations.

    ``current`` cards must already share ids with ``previous`` when they
    represent the same stable key (see ``align_cards_preserving_ids``).
    """
    prev_map = {card.id: card for card in previous}
    mutations: list[CardMutation] = []
    seq = start_seq
    ts = utc_now_iso()
    for card in current:
        prior = prev_map.get(card.id)
        if prior is None:
            mutations.append(
                CardMutation(
                    seq=seq,
                    ts=ts,
                    op="create",
                    card_id=card.id,
                    kind=str(card.type),
                    data=card_to_wire_dict(card),
                )
            )
            seq += 1
            continue
        patch = _updatable_field_diff(prior, card)
        if not patch:
            continue
        mutations.append(
            CardMutation(
                seq=seq,
                ts=ts,
                op="update",
                card_id=card.id,
                kind=str(card.type),
                data=patch,
            )
        )
        seq += 1
    return mutations


__all__ = [
    "CARD_SCHEMA_VERSION",
    "CardMutation",
    "CardOp",
    "InMemoryCardLedger",
    "align_cards_preserving_ids",
    "assign_card_stable_keys",
    "build_header_mutation",
    "card_from_wire_dict",
    "card_stable_key",
    "card_to_wire_dict",
    "cards_to_mutations",
    "diff_card_snapshots",
    "utc_now_iso",
]
