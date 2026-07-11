"""Tests for stream token usage extraction and estimation."""

from __future__ import annotations

from langchain_core.messages import AIMessage

from soothe_cli.runtime.token_usage import extract_stream_message_token_usage


def test_extract_usage_metadata_split_counts() -> None:
    message = AIMessage(
        content="hi",
        usage_metadata={"input_tokens": 100, "output_tokens": 25, "total_tokens": 125},
    )
    assert extract_stream_message_token_usage(message) == (100, 25, 125)


def test_extract_response_metadata_openai_shape() -> None:
    message = AIMessage(
        content="hi",
        response_metadata={
            "token_usage": {
                "prompt_tokens": 512,
                "completion_tokens": 64,
                "total_tokens": 576,
            }
        },
    )
    assert extract_stream_message_token_usage(message) == (512, 64, 576)


def test_extract_wire_dict_response_metadata_enveloped() -> None:
    wire = {
        "type": "ai",
        "data": {
            "type": "ai",
            "content": "",
            "response_metadata": {
                "token_usage": {"prompt_tokens": 200, "completion_tokens": 10, "total_tokens": 210}
            },
        },
    }
    assert extract_stream_message_token_usage(wire) == (200, 10, 210)


def test_message_has_token_usage_metadata() -> None:
    from soothe_cli.runtime.token_usage import message_has_token_usage_metadata

    assert message_has_token_usage_metadata({"type": "ai", "content": ""}) is False
    assert (
        message_has_token_usage_metadata(
            {
                "type": "ai",
                "usage_metadata": {"input_tokens": 1, "output_tokens": 2, "total_tokens": 3},
            }
        )
        is True
    )
