"""LangGraph checkpoint serde with Soothe custom message type allowlist.

Registers ``LoopHumanMessage`` and ``LoopAIMessage`` so that langgraph's
msgpack-based checkpoint deserialization does not emit warnings (and will
continue to work when ``LANGGRAPH_STRICT_MSGPACK=true`` becomes the default).

This module lives in the SDK package so that both the host runtime and CLI can
use it without the CLI importing host runtime.

**Upstream Reviver warning:** LangGraph's ``jsonplus`` serde uses a module-level
``Reviver()`` without ``allowed_objects=``, which triggers a LangChain pending
deprecation on import. That is unrelated to ``allowed_msgpack_modules`` on
``JsonPlusSerializer``; filters are installed from the SDK and host bootstrap
(see ``soothe_sdk._upstream_warnings``).

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
# through LangGraph checkpoints.  Keep in sync with the host message module.
_SOOTHE_MSGPACK_MODULES: list[tuple[str, str]] = [
    ("soothe.foundation.sloop.utils.messages", "LoopHumanMessage"),
    ("soothe.foundation.sloop.utils.messages", "LoopAIMessage"),
    ("soothe.foundation.sloop.state.execution_checkpoint", "GoalIndexEntry"),
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
