"""deep_research graph state smoke tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage

from soothe_nano.subagents.deep_research.engine import build_deep_research_engine
from soothe_nano.subagents.deep_research.protocol import SourceResult


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

    with patch(
        "soothe_nano.subagents.deep_research.engine.crawl_urls", new=AsyncMock(return_value=[])
    ):
        with patch(
            "soothe_nano.subagents.deep_research.engine.classify_report_scenario",
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
    answer = result.get("answer", "")
    assert "## Scope" in answer
    assert "## Key Findings" in answer
    assert "Done." in answer
    assert "Full report saved to:" not in answer


def test_synthesize_excludes_attached_pdf_body() -> None:
    """Plan may see attachment text; Synthesize uses LLM-extracted topic only."""
    pdf_marker = "UNIQUE_PDF_BODY_TOKEN_SHOULD_NOT_REACH_SYNTH"
    fat_topic = (
        "研究世界模型的最新进展\n\n"
        "--- Context ---\nAttached files: paper.pdf (material)\n\n"
        "--- Triarch attachments (extracted content) ---\n"
        f"{pdf_marker}\n"
        "--- Triarch UI language ---\nRespond in Simplified Chinese (zh-CN)."
    )
    extracted = "Web World Models and controllable infinite web environments"
    plan_json = (
        f'{{"research_topic": "{extracted}", '
        '"sub_questions": [{"question": "world models"}], '
        '"queries": [{"query": "web world model 2025"}]}'
    )
    reflect_json = '{"is_sufficient": true, "follow_up_queries": []}'
    synth_text = "## Scope\n\n**Scope:** public web\n\n## Key Findings\n\nok."
    mock_model = MagicMock()
    captured: list[str] = []
    responses = [
        AIMessage(content=plan_json),
        AIMessage(content=reflect_json),
        AIMessage(content=synth_text),
    ]

    async def _ainvoke_tracked(messages: list, *_a: object, **_k: object) -> AIMessage:
        first = messages[0]
        content = (
            first["content"] if isinstance(first, dict) else getattr(first, "content", str(first))
        )
        captured.append(str(content))
        return responses.pop(0)

    mock_model.ainvoke = AsyncMock(side_effect=_ainvoke_tracked)

    async def _search(*_args: object, **_kwargs: object) -> list[SourceResult]:
        return [
            SourceResult(
                content="Web finding.",
                source_ref="https://example.com/wwm",
                source_name="web_search",
                metadata={"url": "https://example.com/wwm", "title": "WWM"},
            )
        ]

    web_source = MagicMock()
    web_source.name = "web_search"
    web_source.query = _search

    with patch(
        "soothe_nano.subagents.deep_research.engine.crawl_urls", new=AsyncMock(return_value=[])
    ):
        with patch(
            "soothe_nano.subagents.deep_research.engine.classify_report_scenario",
            new=AsyncMock(
                return_value=MagicMock(
                    scenario="general_research",
                    sections=["Scope", "Key Findings"],
                    contextual_focus=["world models"],
                    evidence_emphasis="use sources",
                )
            ),
        ):
            runnable = build_deep_research_engine(mock_model, web_source)
            result = runnable.invoke(
                {
                    "messages": [HumanMessage(content=fat_topic)],
                    "search_summaries": [],
                    "sources_gathered": [],
                    "max_loops": 1,
                    "loop_count": 0,
                }
            )

    assert pdf_marker in captured[0], "PlanResearch should still see attachment text"
    synth_prompts = [p for p in captured if "Write a structured research report" in p]
    assert synth_prompts, "expected a Synthesize prompt"
    assert pdf_marker not in synth_prompts[0]
    assert extracted in synth_prompts[0]
    assert "Respond in Simplified Chinese" in synth_prompts[0]
    assert result.get("research_topic", "").startswith(extracted) or extracted in result.get(
        "answer", ""
    )
    assert result.get("answer")
