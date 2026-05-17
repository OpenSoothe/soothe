"""Legacy import shim for LangChain wire helpers.

Canonical location: ``soothe_sdk.client.wire``.
"""

from soothe_sdk.client.wire import (
    coerce_tool_call_chunk_args_for_wire,
    deserialize_langchain_message_from_wire,
    envelope_langchain_message_dict,
    flatten_enveloped_message_dict,
    messages_from_wire_dicts,
    prepare_stream_data_for_wire,
    prepare_stream_message_for_wire,
    serialize_langchain_message_for_wire,
)

__all__ = [
    "coerce_tool_call_chunk_args_for_wire",
    "deserialize_langchain_message_from_wire",
    "envelope_langchain_message_dict",
    "flatten_enveloped_message_dict",
    "messages_from_wire_dicts",
    "prepare_stream_data_for_wire",
    "prepare_stream_message_for_wire",
    "serialize_langchain_message_for_wire",
]
