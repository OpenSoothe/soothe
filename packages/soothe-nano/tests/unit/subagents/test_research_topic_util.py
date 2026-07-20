"""Tests for research topic extraction / attachment stripping."""

from __future__ import annotations

from soothe_nano.subagents._research_topic_util import (
    planned_research_topic,
    topic_without_attachments,
    ui_language_suffix,
)


def test_topic_without_attachments_strips_triarch_pdf_body() -> None:
    topic = (
        "请基于已附加的知识库材料进行深度研究：梳理核心论点\n\n"
        "研究世界模型的最新进展\n\n"
        "--- Context ---\n"
        "Attached files: 2512.23676v1.pdf (material)\n\n"
        "--- Triarch attachments (extracted content) ---\n"
        "--- Attachment: 2512.23676v1.pdf (application/pdf) ---\n"
        "Pages: 34 (text-only extraction)\n\n"
        "WebWorldModelsJichenFeng AbstractLanguageagents...\n"
        "--- Triarch UI language ---\n"
        "Respond in Simplified Chinese (zh-CN)."
    )
    cleaned = topic_without_attachments(topic)
    assert "研究世界模型的最新进展" in cleaned
    assert "Respond in Simplified Chinese" in cleaned
    assert "WebWorldModelsJichenFeng" not in cleaned
    assert "Triarch attachments" not in cleaned
    assert "Attached files:" not in cleaned


def test_topic_without_attachments_plain_topic_unchanged() -> None:
    topic = "Compare vector databases for RAG workloads"
    assert topic_without_attachments(topic) == topic


def test_topic_without_attachments_preserves_ui_language_only() -> None:
    topic = (
        "--- Context ---\nAttached files: x.pdf\n\n"
        "--- Triarch UI language ---\nRespond in English (en-US)."
    )
    cleaned = topic_without_attachments(topic)
    assert cleaned.startswith("--- Triarch UI language ---")
    assert "Attached files" not in cleaned


def test_planned_research_topic_prefers_llm_extraction() -> None:
    raw = (
        "请深度研究\n\n--- Context ---\nAttached files: p.pdf\n\n"
        "--- Triarch attachments (extracted content) ---\nLONG PDF TEXT\n"
        "--- Triarch UI language ---\nRespond in Simplified Chinese (zh-CN)."
    )
    planned = planned_research_topic(
        {
            "research_topic": "Web World Models: neuro-symbolic web-stack world models",
            "queries": [{"query": "web world model"}],
        },
        raw,
    )
    assert planned.startswith("Web World Models:")
    assert "LONG PDF TEXT" not in planned
    assert "Respond in Simplified Chinese" in planned
    assert ui_language_suffix(raw) in planned


def test_planned_research_topic_falls_back_when_missing() -> None:
    raw = "研究世界模型\n\n--- Triarch attachments (extracted content) ---\nPDF"
    planned = planned_research_topic({"queries": []}, raw)
    assert planned == "研究世界模型"
    assert "PDF" not in planned


def test_planned_research_topic_strips_echoed_attachments() -> None:
    raw = "ask\n\n--- Triarch UI language ---\nRespond in English (en-US)."
    planned = planned_research_topic(
        {"research_topic": ("Good topic\n--- Triarch attachments (extracted content) ---\nBAD")},
        raw,
    )
    assert "Good topic" in planned
    assert "BAD" not in planned
    assert "Respond in English" in planned
