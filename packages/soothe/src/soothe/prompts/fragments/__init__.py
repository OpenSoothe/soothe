"""Prefetched static host prompt fragments.

All fragments are read once at import time to maximize prompt cache hit rate.
Cache Strategy (RFC-104):
- Static fragments loaded at module init (0 file I/O per request)
- Module constants reused across all StrangeLoop invocations

Asset layout: ``intake/``, ``system/``, ``classifiers/``, ``instructions/``,
``decompose/``.

CoreAgent identity/system-body fragments are re-exported from
``soothe.prompts`` (canonical: ``soothe_nano.prompts.fragments``).

Jinja2 templates (e.g. ``synthesis_report_system.xml``) are loaded on demand via
``soothe.prompts.loader.load_prompt_fragment``.
"""

from __future__ import annotations

import re
from pathlib import Path

_FRAGMENTS_DIR = Path(__file__).parent
_WRAPPED_XML_RE = re.compile(
    r"^<(?P<tag>[A-Za-z_][\w.]*)>\s*(?P<body>.*?)\s*</(?P=tag)>\s*$",
    re.DOTALL,
)


def _read(relative: str, *, strip: bool = False) -> str:
    text = _FRAGMENTS_DIR.joinpath(relative).read_text(encoding="utf-8")
    return text.strip() if strip else text


def _read_xml_body(relative: str) -> str:
    """Load a single-root XML fragment and return its inner text."""
    text = _read(relative, strip=True)
    match = _WRAPPED_XML_RE.match(text)
    if match is None:
        msg = f"Fragment is not a single-root XML document: {relative}"
        raise ValueError(msg)
    return match.group("body").strip()


PROMPT_TIMESTAMP_FRAGMENT = _read("system/prompt_timestamp.xml", strip=True)

SCENARIO_CLASSIFIER_SYSTEM_FRAGMENT = _read(
    "classifiers/scenario_classifier_system.xml", strip=True
)
SCENARIO_CLASSIFIER_USER_FRAGMENT = _read("classifiers/scenario_classifier_user.xml", strip=True)

THREAD_POLICY_SYSTEM_ADDENDUM = _read_xml_body("decompose/thread_policy_system.xml")
WRITE_TODOS_TOOL_DESCRIPTION = _read_xml_body("decompose/write_todos_tool.xml")
DECOMPOSE_TASK_TOOL_DESCRIPTION = _read_xml_body("decompose/decompose_task_tool.xml")
APPROVED_PLAN_EXECUTE_HINT = _read_xml_body("decompose/approved_plan_execute_hint.xml")
THREAD_USER_HINT_ROOT_FRAGMENT = _read_xml_body("decompose/user_hint_root.xml")
THREAD_USER_HINT_CHILD_FRAGMENT = _read_xml_body("decompose/user_hint_child.xml")
EVAL_POLICY_SYSTEM_ADDENDUM = _read_xml_body("eval/eval_policy_system.xml")
EVAL_DECISION_SYSTEM = _read_xml_body("eval/eval_decision_system.xml")
ASK_MODE_ADDENDUM = _read_xml_body("decompose/ask_mode_addendum.xml")
PLAN_MODE_ADDENDUM = _read_xml_body("decompose/plan_mode_addendum.xml")
WESTWORLD_FANOUT_ADDENDUM = _read_xml_body("decompose/westworld_fanout_addendum.xml")


__all__ = [
    "APPROVED_PLAN_EXECUTE_HINT",
    "ASK_MODE_ADDENDUM",
    "DECOMPOSE_TASK_TOOL_DESCRIPTION",
    "EVAL_DECISION_SYSTEM",
    "EVAL_POLICY_SYSTEM_ADDENDUM",
    "PLAN_MODE_ADDENDUM",
    "PROMPT_TIMESTAMP_FRAGMENT",
    "SCENARIO_CLASSIFIER_SYSTEM_FRAGMENT",
    "SCENARIO_CLASSIFIER_USER_FRAGMENT",
    "THREAD_POLICY_SYSTEM_ADDENDUM",
    "THREAD_USER_HINT_CHILD_FRAGMENT",
    "THREAD_USER_HINT_ROOT_FRAGMENT",
    "WESTWORLD_FANOUT_ADDENDUM",
    "WRITE_TODOS_TOOL_DESCRIPTION",
]
