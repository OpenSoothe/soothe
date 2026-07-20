"""Tests for Deep Research JSON helpers."""

from langchain_core.messages import AIMessage

from soothe_nano.subagents.deep_research.json_util import (
    compact_search_query,
    fallback_queries,
    fallback_sub_questions,
    llm_response_text,
    parse_json_object,
)


def test_parse_json_object_from_fence() -> None:
    raw = 'Here is output:\n```json\n{"queries": [{"query": "test", "domain_hint": "web"}]}\n```'
    parsed = parse_json_object(raw)
    assert parsed is not None
    assert len(parsed["queries"]) == 1


def test_compact_search_query_strips_instructions() -> None:
    long = "搜索中美外交新闻\n\n请执行以下任务：\n1. 使用网络搜索"
    short = compact_search_query(long, max_len=50)
    assert "请执行" not in short
    assert len(short) <= 50


def test_llm_response_text_uses_reasoning_when_content_empty() -> None:
    msg = AIMessage(
        content="",
        additional_kwargs={"reasoning_content": '{"queries": []}'},
    )
    assert llm_response_text(msg) == '{"queries": []}'


def test_fallback_queries_from_sub_questions() -> None:
    subs = [{"question": "agentic memory survey", "suggested_domain": "academic"}]
    queries = fallback_queries("ignored topic", subs)
    assert len(queries) == 1
    assert "agentic memory" in queries[0]["query"]


def test_fallback_sub_questions_uses_topic() -> None:
    subs = fallback_sub_questions("find latest agentic memory papers")
    assert len(subs) == 1
    assert "agentic memory" in subs[0]["question"]
