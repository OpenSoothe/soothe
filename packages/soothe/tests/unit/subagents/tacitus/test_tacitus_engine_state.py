"""Tacitus graph state channel tests."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph

from soothe.subagents.tacitus.engine import TacitusEngineState, build_tacitus_engine
from soothe.subagents.tacitus.json_util import llm_response_text
from soothe.subagents.tacitus.protocol import SourceResult


def test_tacitus_engine_state_retains_private_keys() -> None:
    """Undeclared keys are dropped by LangGraph; TacitusEngineState must declare them."""

    def analyze(state: dict) -> dict:
        return {"_sub_questions": [{"question": "What is agentic memory?"}]}

    def generate(state: dict) -> dict:
        seen = state.get("_sub_questions", [])
        return {"_queries": [{"query": "agentic memory", "domain_hint": "public"}] if seen else []}

    graph = StateGraph(TacitusEngineState)
    graph.add_node("analyze", analyze)
    graph.add_node("generate", generate)
    graph.add_edge(START, "analyze")
    graph.add_edge("analyze", "generate")
    graph.add_edge("generate", END)
    out = graph.compile().invoke(
        {
            "messages": [],
            "research_topic": "agentic memory",
            "domain": "public",
            "search_summaries": [],
            "sources_gathered": [],
            "max_loops": 1,
            "loop_count": 0,
        }
    )
    assert out.get("_sub_questions")
    assert out.get("_queries")


def test_llm_response_text_prefers_reasoning_content_when_content_empty() -> None:
    msg = AIMessage(
        content="",
        additional_kwargs={
            "reasoning_content": '{"queries": [{"query": "test", "domain_hint": "web"}]}'
        },
    )
    assert "queries" in llm_response_text(msg)


def test_build_tacitus_passes_sub_questions_to_generate_queries() -> None:
    """Smoke test: analyze output reaches generate_queries via graph state."""
    analyze_json = (
        '{"sub_questions": [{"question": "latest agentic memory papers", '
        '"suggested_domain": "academic"}]}'
    )
    generate_json = (
        '{"queries": [{"query": "agentic memory papers 2025", "domain_hint": "academic"}]}'
    )
    mock_model = MagicMock()
    mock_model.invoke.side_effect = [
        AIMessage(content=analyze_json),
        AIMessage(content=generate_json),
        AIMessage(
            content="",
            additional_kwargs={
                "reasoning_content": (
                    '{"is_sufficient": true, "knowledge_gap": "", "follow_up_queries": []}'
                )
            },
        ),
        AIMessage(content="Final synthesized answer."),
    ]

    async def _mock_query(*_args: object, **_kwargs: object) -> list:
        return [
            SourceResult(
                content="Finding about agentic memory.",
                source_ref="https://example.com/paper",
                source_name="web_search",
                metadata={
                    "url": "https://example.com/paper",
                    "title": "Agentic Memory Survey",
                },
            )
        ]

    mock_source = MagicMock()
    mock_source.name = "mock"
    mock_source.query = _mock_query

    mock_router = MagicMock()
    mock_router.select.return_value = [mock_source]

    with patch(
        "soothe.subagents.tacitus.router.PublicSemanticRouter",
        return_value=mock_router,
    ):
        runnable = build_tacitus_engine(mock_model, sources=[], _domain="public")
        result = runnable.invoke(
            {
                "messages": [],
                "research_topic": "find latest agentic memory research papers",
                "domain": "public",
                "search_summaries": [],
                "sources_gathered": [],
                "max_loops": 1,
                "loop_count": 0,
            }
        )

    assert mock_model.invoke.call_count >= 2
    assert result.get("_queries")
    assert result.get("effort") == "normal"
    answer = result.get("answer", "")
    assert "Final synthesized answer." in answer
    assert "## References" in answer
    assert "example.com/paper" in answer
