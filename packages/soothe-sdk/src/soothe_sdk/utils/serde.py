"""LangGraph checkpoint serde with Soothe custom message type allowlist.

Registers ``LoopHumanMessage`` and ``LoopAIMessage`` so that langgraph's
msgpack-based checkpoint deserialization does not emit warnings (and will
continue to work when ``LANGGRAPH_STRICT_MSGPACK=true`` becomes the default).

This module lives in the SDK package so that both the daemon and CLI can
use it without the CLI importing daemon runtime.

**Upstream Warning Note:**
During import, you may see a deprecation warning from ``langchain_core.load.load.Reviver``.
This is a known upstream issue in langchain-core that emits a misleading warning about
"allowed_objects" (which doesn't exist; the actual parameter is ``allowed_msgpack_modules``).
Our code properly passes ``allowed_msgpack_modules`` to suppress future deprecation,
but the warning still appears during langgraph's module initialization.
See: langgraph/checkpoint/serde/jsonplus.py:45 (LC_REVIVER = Reviver())

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
# ``soothe.core.agent_loop.utils.messages`` (RFC-214).
_SOOTHE_MSGPACK_MODULES: list[tuple[str, str]] = [
    ("soothe.core.agent_loop.utils.messages", "LoopHumanMessage"),
    ("soothe.core.agent_loop.utils.messages", "LoopAIMessage"),
    ("soothe.core.agent_loop.state.checkpoint", "GoalExecutionRecord"),
]


def create_soothe_serde() -> JsonPlusSerializer:
    """Create a ``JsonPlusSerializer`` pre-configured for Soothe types.

    Returns:
        A ``JsonPlusSerializer`` instance whose ``allowed_msgpack_modules``
        includes all Soothe custom message types.
    """
    from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

    # Pass explicit allowed_msgpack_modules to suppress deprecation warning.
    # The warning mentions "allowed_objects" but that param doesn't exist.
    return JsonPlusSerializer(allowed_msgpack_modules=_SOOTHE_MSGPACK_MODULES)


def get_soothe_msgpack_allowlist() -> list[tuple[str, str]]:
    """Return the Soothe msgpack module allowlist.

    Useful when callers need to *merge* Soothe types into an existing
    ``JsonPlusSerializer`` via ``with_msgpack_allowlist()``.

    Returns:
        List of ``(module_path, class_name)`` tuples.
    """
    return list(_SOOTHE_MSGPACK_MODULES)
