"""LangGraph checkpoint serde with Soothe custom message type allowlist.

Registers ``LoopHumanMessage`` and ``LoopAIMessage`` so that langgraph's
msgpack-based checkpoint deserialization does not emit warnings (and will
continue to work when ``LANGGRAPH_STRICT_MSGPACK=true`` becomes the default).

This module lives in the SDK package so that both the daemon and CLI can
use it without the CLI importing daemon runtime.

Usage::

    from soothe_sdk.utils.serde import create_soothe_serde

    serde = create_soothe_serde()
    checkpointer = AsyncSqliteSaver(conn, serde=serde)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

# Module-class pairs for all Soothe custom message types that travel
# through LangGraph checkpoints.  Keep in sync with
# ``soothe.cognition.agent_loop.messages``.
_SOOTHE_MSGPACK_MODULES: list[tuple[str, str]] = [
    ("soothe.cognition.agent_loop.messages", "LoopHumanMessage"),
    ("soothe.cognition.agent_loop.messages", "LoopAIMessage"),
]


def create_soothe_serde() -> JsonPlusSerializer:
    """Create a ``JsonPlusSerializer`` pre-configured for Soothe types.

    Returns:
        A ``JsonPlusSerializer`` instance whose ``allowed_msgpack_modules``
        includes all Soothe custom message types.
    """
    from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

    return JsonPlusSerializer(allowed_msgpack_modules=_SOOTHE_MSGPACK_MODULES)


def get_soothe_msgpack_allowlist() -> list[tuple[str, str]]:
    """Return the Soothe msgpack module allowlist.

    Useful when callers need to *merge* Soothe types into an existing
    ``JsonPlusSerializer`` via ``with_msgpack_allowlist()``.

    Returns:
        List of ``(module_path, class_name)`` tuples.
    """
    return list(_SOOTHE_MSGPACK_MODULES)
