"""deep_research graph state smoke tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import AIMessage

from soothe.subagents.deep_research.engine import build_deep_research_engine
from soothe.subagents.deep_research.protocol import SourceResult


def test_build_deep_research_smoke() -> None:
    plan_json = (
        '{"sub_questions": [{"question": "latest agentic memory"}], '
        '"queries": [{"query": "agentic memory 2025"}]}'
    )
    reflect_json = '{"is_sufficient": true, "follow_up_queries": []}'
    mock_model = MagicMock()
    responses = [
        AIMessage(content=plan_json),
        AIMessage(content=reflect_json),
        AIMessage(content="## Scope\n\n**Scope:** public web\n\n## Key Findings\n\nDone."),
    ]

    async def _ainvoke(*_args: object, **_kwargs: object) -> AIMessage:
        return responses.pop(0)

    mock_model.ainvoke = AsyncMock(side_effect=_ainvoke)

    async def _search(*_args: object, **_kwargs: object) -> list[SourceResult]:
        return [
            SourceResult(
                content="Finding about agentic memory.",
                source_ref="https://example.com/paper",
                source_name="web_search",
                metadata={"url": "https://example.com/paper", "title": "Survey"},
            )
        ]

    web_source = MagicMock()
    web_source.name = "web_search"
    web_source.query = _search

    with patch("soothe.subagents.deep_research.engine.crawl_urls", new=AsyncMock(return_value=[])):
        with patch(
            "soothe.subagents.deep_research.engine.classify_report_scenario",
            new=AsyncMock(
                return_value=MagicMock(
                    scenario="general_research",
                    sections=["Scope", "Key Findings"],
                    contextual_focus=["memory"],
                    evidence_emphasis="use sources",
                )
            ),
        ):
            runnable = build_deep_research_engine(mock_model, web_source)
            result = runnable.invoke(
                {
                    "messages": [],
                    "research_topic": "agentic memory research",
                    "search_summaries": [],
                    "sources_gathered": [],
                    "max_loops": 1,
                    "loop_count": 0,
                }
            )

    assert result.get("effort") == "normal"
    assert "Key Findings" in result.get("answer", "")
