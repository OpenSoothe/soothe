"""``ask_user`` tool — pauses the loop for a human answer."""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ConfigDict, Field, model_validator

logger = logging.getLogger(__name__)

# Old field names → new field names (for backward-compat coercion of in-flight loops).
_FIELD_RENAMES: dict[str, str] = {
    "title": "header",
    "short": "label",
    "long": "description",
}
# Old top-level question fields that should be renamed.
_QUESTION_FIELD_RENAMES: dict[str, str] = {
    **_FIELD_RENAMES,
    "description": "question",  # QuestionSpec.description → question
    # 'recommended' is dropped, not renamed.
}


class OptionSpec(BaseModel):
    """A single selectable option for a structured question.

    ``label`` is the answer display text shown in the recap and sent on
    resume. ``description`` is shown in the hover-preview box when the
    option is highlighted.
    """

    label: str = Field(description="Display text (1-5 words). The user selects this.")
    description: str = Field(description="What this option means or what happens if chosen.")

    model_config = ConfigDict(extra="forbid")


class QuestionSpec(BaseModel):
    """A structured question with options.

    The LLM emits 2-4 options. Put the recommended option first and add
    "(Recommended)" to its label. The CLI widget adds an implicit "Other"
    free-text row. ``header`` is the tab/chip label (max 12 chars);
    ``question`` is the full question text.
    """

    question: str = Field(description="The full question text. Clear, specific, ends with '?'.")
    header: str = Field(description="Short chip label (max 12 chars). E.g. 'Auth method'.")
    options: list[OptionSpec] = Field(
        description="2-4 options. Put the recommended one first with '(Recommended)' in its label. Never include an 'Other' option — it's auto-added.",
    )

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _validate(self) -> QuestionSpec:
        if not 2 <= len(self.options) <= 4:
            raise ValueError("2-4 options required")
        if len(self.header) > 12:
            raise ValueError("header must be ≤12 chars")
        if len(self.question.split()) > 100:
            raise ValueError("question must be ≤100 words")
        # Uniqueness: option labels must be distinct within each question.
        labels = [opt.label for opt in self.options]
        if len(labels) != len(set(labels)):
            raise ValueError("option labels must be unique")
        for opt in self.options:
            if not opt.label.strip():
                raise ValueError("option label must be non-empty")
            if not opt.description.strip():
                raise ValueError("option description must be non-empty")
        return self


class _AskUserArgs(BaseModel):
    """``questions`` (list of QuestionSpec) is the sole entry point."""

    questions: list[QuestionSpec] = Field(
        default_factory=list,
        description="1-4 questions to ask the user.",
    )

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def _coerce_llm_arg_quirks(cls, data: Any) -> Any:
        """Handle common LLM argument-shape quirks before Pydantic validation.

        Observed in production loops (f182, 065e, 9125):

        1. **Stringified JSON questions**: the model emits ``questions`` as a
           JSON string instead of a native list. Parse it.

        2. **Flat single question**: the model emits ``question``, ``header``,
           ``options`` as top-level tool args instead of wrapping them in
           ``questions: [{...}]``. Detect and wrap them.

        3. **Stringified options**: ``options`` may also arrive as a JSON
           string instead of a list. Parse it.

        4. **Old field names**: in-flight loops from before the schema rename
           may use ``title``/``description``/``short``/``long``/``recommended``.
           Rename them to the new fields.
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
            question_keys = {"question", "header", "options"}
            if any(k in data for k in question_keys):
                question: dict[str, Any] = {}
                for k in question_keys:
                    if k in data:
                        question[k] = data.pop(k)
                # Also handle old field names at top level.
                for old, new in _QUESTION_FIELD_RENAMES.items():
                    if old in data:
                        question[new] = data.pop(old)
                # Drop 'recommended' (removed from schema) at top level.
                data.pop("recommended", None)
                data["questions"] = [question]

        # Quirk 3+4: within each question, rename old fields and parse options.
        for q in data.get("questions", []):
            if not isinstance(q, dict):
                continue
            # Rename old field names → new.
            for old, new in _QUESTION_FIELD_RENAMES.items():
                if old in q and new not in q:
                    q[new] = q.pop(old)
            # Drop 'recommended' (removed from schema).
            q.pop("recommended", None)
            # Parse stringified options.
            raw_opts = q.get("options")
            if isinstance(raw_opts, str):
                try:
                    parsed_opts = json.loads(raw_opts)
                    if isinstance(parsed_opts, list):
                        q["options"] = parsed_opts
                except (json.JSONDecodeError, TypeError):
                    pass
            # Rename old option fields and strip extra keys.
            for opt in q.get("options", []):
                if isinstance(opt, dict):
                    for old, new in _FIELD_RENAMES.items():
                        if old in opt and new not in opt:
                            opt[new] = opt.pop(old)
                    opt.pop("index", None)

        return data

    @model_validator(mode="after")
    def _normalize(self) -> _AskUserArgs:
        # Drop questions whose question text is whitespace-only.
        self.questions = [q for q in self.questions if q.question.strip()]
        if not self.questions:
            raise ValueError("ask_user requires at least one non-empty question")
        # Uniqueness: question texts must be distinct.
        texts = [q.question for q in self.questions]
        if len(texts) != len(set(texts)):
            raise ValueError("question texts must be unique")
        return self


def _format_answers(questions: list, payload: object) -> str:
    """Render the resume payload as a model-readable Q&A block.

    ``questions`` may be ``list[QuestionSpec]``, ``list[dict]`` (structured,
    from wire), or ``list[str]`` (degraded backward compat). Question text is
    extracted from ``QuestionSpec`` or dict when available; falls back to
    ``str(q)``.
    """
    raw = payload.get("answers", payload) if isinstance(payload, dict) else payload
    answers = (
        [raw] if isinstance(raw, str) else [str(a) for a in raw] if isinstance(raw, list) else []
    )
    if not answers:
        return "Clarification dismissed without an answer. Decide how to proceed."
    pairs = []
    for i, q in enumerate(questions):
        question = (
            q.question
            if isinstance(q, QuestionSpec)
            else q.get("question", str(q))
            if isinstance(q, dict)
            else str(q)
        )
        pairs.append(f"Q: {question}\nA: {answers[i] if i < len(answers) else '(no answer)'}")
    return "User answered:\n" + "\n".join(pairs)


def _run_ask_user(questions: list[QuestionSpec] | None = None) -> str:
    """Pause the graph via ``interrupt()``; return formatted answers on resume."""
    from langgraph.types import interrupt

    qs = list(questions or [])
    cleaned = [q for q in qs if q.question.strip()]
    if not cleaned:
        raise ValueError("ask_user requires at least one non-empty question")
    logger.info(
        "[ask_user] LLM asked %d question(s): %s",
        len(cleaned),
        cleaned[0].question[:120],
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
            "Each question has a header (short label), question text, and 2-4 "
            "options (each with label + description). Put the recommended "
            "option first with '(Recommended)' in its label. The CLI renders "
            "a picker; the user can also type a custom answer. Use for "
            "decision gates: approval, confirmation, routing, or resolving "
            "ambiguity."
        ),
        func=_run_ask_user,
        coroutine=_arun_ask_user,
        args_schema=_AskUserArgs,
        infer_schema=False,
    )
