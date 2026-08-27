"""``ask_user`` tool — pauses the loop for a human answer (RFC-622)."""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field, model_validator

logger = logging.getLogger(__name__)


class OptionSpec(BaseModel):
    """A single selectable option for a structured question (RFC-622 §9c).

    ``short`` is the answer label shown in the recap and sent on resume.
    ``long`` is shown in the hover-preview box when the option is highlighted.
    """

    short: str = Field(description="Short option label (≤12 words). Sent on resume.")
    long: str = Field(description="Long description (1–3 sentences). Shown on hover.")


class QuestionSpec(BaseModel):
    """A structured question with options (RFC-622 §9c).

    The LLM emits exactly 3 options plus a recommended index. The CLI widget
    adds a 4th implicit "custom" free-text row. ``title`` is the tab label
    (≤3 words); ``description`` is the question body (≤100 words).
    """

    title: str = Field(description="Tab label (≤3 words).")
    description: str = Field(description="Question body (≤100 words).")
    options: list[OptionSpec] = Field(
        description="Exactly 3 options with short/long descriptions.",
    )
    recommended: int = Field(
        default=-1,
        description="Index of the recommended option (0–2), or -1 for none.",
    )

    @model_validator(mode="after")
    def _validate(self) -> QuestionSpec:
        if len(self.options) != 3:
            raise ValueError("exactly 3 options required")
        if self.recommended not in (-1, 0, 1, 2):
            raise ValueError("recommended must be -1, 0, 1, or 2")
        if len(self.title.split()) > 3:
            raise ValueError("title must be ≤3 words")
        if len(self.description.split()) > 100:
            raise ValueError("description must be ≤100 words")
        for opt in self.options:
            if not opt.short.strip():
                raise ValueError("option short must be non-empty")
            if len(opt.short.split()) > 12:
                raise ValueError("option short must be ≤12 words")
            if not opt.long.strip():
                raise ValueError("option long must be non-empty")
        return self


class _AskUserArgs(BaseModel):
    """``questions`` (list of QuestionSpec) is the sole entry point."""

    questions: list[QuestionSpec] = Field(
        default_factory=list,
        description="The question(s) to ask the user, each with structured options.",
    )

    @model_validator(mode="before")
    @classmethod
    def _coerce_llm_arg_quirks(cls, data: Any) -> Any:
        """Handle common LLM argument-shape quirks before Pydantic validation.

        Observed in production loops (f182, 065e):

        1. **Stringified JSON questions**: the model emits ``questions`` as a
           JSON string ``'[{"title": ...}]'`` instead of a native list.
           Parse it before validation.

        2. **Flat single question**: the model emits ``title``, ``description``,
           ``options``, ``recommended`` as top-level tool args instead of
           wrapping them in ``questions: [{...}]``. Detect and wrap them.

        3. **Stringified options**: ``options`` may also arrive as a JSON
           string instead of a list. Parse it.

        4. **String-typed numerics**: ``recommended`` may arrive as ``"-1"``
           instead of ``-1``. Coerce to int.
        """
        if not isinstance(data, dict):
            return data

        # Quirk 1: questions as stringified JSON.
        raw_questions = data.get("questions")
        if isinstance(raw_questions, str):
            raw_stripped = raw_questions.strip()
            if raw_stripped:
                try:
                    parsed = json.loads(raw_stripped)
                    if isinstance(parsed, list):
                        data["questions"] = parsed
                except (json.JSONDecodeError, TypeError):
                    pass

        # Quirk 2: flat single question fields at top level — wrap them.
        if "questions" not in data or not data.get("questions"):
            question_keys = {"title", "description", "options", "recommended"}
            if any(k in data for k in question_keys):
                question: dict[str, Any] = {}
                for k in question_keys:
                    if k in data:
                        question[k] = data.pop(k)
                data["questions"] = [question]

        # Quirk 3: options as stringified JSON (within each question).
        for q in data.get("questions", []):
            if isinstance(q, dict):
                raw_opts = q.get("options")
                if isinstance(raw_opts, str):
                    try:
                        parsed_opts = json.loads(raw_opts)
                        if isinstance(parsed_opts, list):
                            q["options"] = parsed_opts
                    except (json.JSONDecodeError, TypeError):
                        pass
                # Quirk 4: recommended as string.
                rec = q.get("recommended")
                if isinstance(rec, str):
                    try:
                        q["recommended"] = int(rec)
                    except ValueError:
                        pass
                # Strip extra keys the model may emit (e.g. "index" inside options).
                for opt in q.get("options", []):
                    if isinstance(opt, dict):
                        opt.pop("index", None)

        return data

    @model_validator(mode="after")
    def _normalize(self) -> _AskUserArgs:
        # Drop questions whose title is whitespace-only.
        self.questions = [q for q in self.questions if q.title.strip()]
        if not self.questions:
            raise ValueError("ask_user requires at least one non-empty question")
        return self


def _format_answers(questions: list, payload: object) -> str:
    """Render the resume payload as a model-readable Q&A block.

    ``questions`` may be ``list[QuestionSpec]``, ``list[dict]`` (structured,
    from wire), or ``list[str]`` (degraded backward compat). Title is extracted
    from ``QuestionSpec`` or dict when available; falls back to ``str(q)``.
    """
    raw = payload.get("answers", payload) if isinstance(payload, dict) else payload
    answers = (
        [raw] if isinstance(raw, str) else [str(a) for a in raw] if isinstance(raw, list) else []
    )
    if not answers:
        return "Clarification dismissed without an answer. Decide how to proceed."
    pairs = []
    for i, q in enumerate(questions):
        title = (
            q.title
            if isinstance(q, QuestionSpec)
            else q.get("title", str(q))
            if isinstance(q, dict)
            else str(q)
        )
        pairs.append(f"Q: {title}\nA: {answers[i] if i < len(answers) else '(no answer)'}")
    return "User answered:\n" + "\n".join(pairs)


def _run_ask_user(questions: list[QuestionSpec] | None = None) -> str:
    """Pause the graph via ``interrupt()``; return formatted answers on resume."""
    from langgraph.types import interrupt

    qs = list(questions or [])
    cleaned = [q for q in qs if q.title.strip()]
    if not cleaned:
        raise ValueError("ask_user requires at least one non-empty question")
    logger.info(
        "[ask_user] LLM asked %d question(s): %s",
        len(cleaned),
        cleaned[0].title[:120],
    )
    payload = interrupt({"type": "ask_user", "questions": [q.model_dump() for q in cleaned]})
    return _format_answers(cleaned, payload)


async def _arun_ask_user(questions: list[QuestionSpec] | None = None) -> str:
    return _run_ask_user(questions)


def build_ask_user_tool() -> StructuredTool:
    """Build the ``ask_user`` StructuredTool."""
    return StructuredTool.from_function(
        name="ask_user",
        description=(
            "Ask the user a question and pause the loop until they answer. "
            "Each question has a title (≤3 words), description (≤100 words), "
            "exactly 3 options (each with short/long text), and a recommended "
            "index (0–2 or -1). The CLI renders options as a picker; the user "
            "can also type a custom answer. Use for decision gates: approval, "
            "confirmation, routing, or resolving ambiguity."
        ),
        func=_run_ask_user,
        coroutine=_arun_ask_user,
        args_schema=_AskUserArgs,
        infer_schema=False,
    )
