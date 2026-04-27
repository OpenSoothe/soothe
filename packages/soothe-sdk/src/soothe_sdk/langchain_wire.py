"""Legacy import shim for LangChain wire helpers.

Canonical location: ``soothe_sdk.client.wire``.
"""

from soothe_sdk.client.wire import envelope_langchain_message_dict, messages_from_wire_dicts

__all__ = ["envelope_langchain_message_dict", "messages_from_wire_dicts"]
