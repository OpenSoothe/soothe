"""LLM-facing prompts must not expose internal IG-/RFC- identifiers."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from soothe.foundation.sloop.intention.prompts import (
    INTAKE_PASS1_HUMAN_TASK,
    INTAKE_PASS1_SYSTEM_PROMPT,
    INTAKE_PASS2_HUMAN_TASK,
    INTAKE_PASS2_SYSTEM_PROMPT,
)
from soothe.prompts.fragments import (
    EXECUTION_POLICIES_FRAGMENT,
    PLAN_ASSESS_INSTRUCTIONS_FRAGMENT,
    PLAN_CONTINUATION_DISCRIMINATE_FRAGMENT,
    PLAN_GENERATE_INSTRUCTIONS_FRAGMENT,
)
from soothe.prompts.system_templates import (
    _TOOL_ORCHESTRATION_GUIDE,
    EXECUTE_WORKSPACE_RULES_FRAGMENT,
    RESPONSE_LANGUAGE_HINT_FALLBACK,
)
from soothe.subagents.veritas.prompts import build_veritas_system_prompt

_INTERNAL_TERM_RE = re.compile(r"\b(?:IG|RFC)-\d+\b", re.IGNORECASE)

_FRAGMENTS_DIR = (
    Path(__file__).resolve().parents[4] / "src" / "soothe" / "prompts" / "fragments"
)


def _assert_no_internal_terms(text: str, *, label: str) -> None:
    match = _INTERNAL_TERM_RE.search(text)
    assert match is None, f"{label} contains internal term {match.group(0)!r}"


@pytest.mark.parametrize(
    "path",
    sorted(_FRAGMENTS_DIR.rglob("*.xml")),
    ids=lambda p: str(p.relative_to(_FRAGMENTS_DIR)),
)
def test_xml_fragments_omit_internal_terms(path: Path) -> None:
    _assert_no_internal_terms(path.read_text(encoding="utf-8"), label=str(path.name))


@pytest.mark.parametrize(
    ("label", "text"),
    [
        ("intake_pass1_system", INTAKE_PASS1_SYSTEM_PROMPT),
        ("intake_pass2_system", INTAKE_PASS2_SYSTEM_PROMPT),
        ("intake_pass1_human_task", INTAKE_PASS1_HUMAN_TASK),
        ("intake_pass2_human_task", INTAKE_PASS2_HUMAN_TASK),
        ("plan_assess", PLAN_ASSESS_INSTRUCTIONS_FRAGMENT),
        ("plan_generate", PLAN_GENERATE_INSTRUCTIONS_FRAGMENT),
        ("plan_continuation", PLAN_CONTINUATION_DISCRIMINATE_FRAGMENT),
        ("execution_policies", EXECUTION_POLICIES_FRAGMENT),
        (
            "synthesis_report_system",
            (_FRAGMENTS_DIR / "instructions" / "synthesis_report_system.xml").read_text(
                encoding="utf-8"
            ),
        ),
        ("execute_workspace_rules", EXECUTE_WORKSPACE_RULES_FRAGMENT),
        ("response_language_hint", RESPONSE_LANGUAGE_HINT_FALLBACK),
        ("tool_orchestration_guide", _TOOL_ORCHESTRATION_GUIDE),
        ("veritas_system", build_veritas_system_prompt()),
    ],
)
def test_python_prompt_constants_omit_internal_terms(label: str, text: str) -> None:
    _assert_no_internal_terms(text, label=label)
