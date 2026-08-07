"""``intake_scope`` validation for daemon ``loop_input`` agent turns."""

from __future__ import annotations

from soothe.sloop.intention.models import parse_intake_scope

from soothe_daemon.protocol.intent_hints import is_daemon_intent_hint


def validate_and_normalize_intake_scope(
    raw: object | None,
    *,
    intent_hint: str | None,
) -> tuple[str | None, str | None]:
    """Validate optional ``loop_input.intake_scope``.

    Args:
        raw: Client value from the wire message.
        intent_hint: Normalized ``intent_hint`` for the same turn (may be unset).

    Returns:
        ``(normalized_scope, error_message)``. On success ``error_message`` is
        ``None``. Unset / empty returns ``(None, None)``.
    """
    try:
        scope = parse_intake_scope(raw)
    except ValueError as exc:
        return None, str(exc)

    if scope is None:
        return None, None

    if is_daemon_intent_hint(intent_hint):
        return (
            None,
            "intake_scope cannot be combined with daemon intent_hint "
            f"{intent_hint!r}; omit one of them",
        )

    return scope.value, None
