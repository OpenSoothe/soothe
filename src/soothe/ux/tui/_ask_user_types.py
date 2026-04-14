"""Types for ask_user widget interactions (stub from deepagents-cli migration).

This module provides type definitions for interactive user prompts.
"""

from typing_extensions import TypedDict


class Choice(TypedDict):
    """A choice option for user selection.

    Args:
        label: Display label for the choice.
        value: Value to return if this choice is selected.
    """

    label: str
    value: str


class Question(TypedDict):
    """A question to ask the user.

    Args:
        question: The question text to display.
        choices: Optional list of choices for selection.
        other: Whether to allow "Other" as a choice option.
    """

    question: str
    choices: list[Choice] | None
    other: bool


# Result type from ask_user widget
AskUserWidgetResult = dict[str, str]


class AskUserRequest(TypedDict):
    """Request to ask user interactive questions.

    Args:
        questions: List of questions to ask.
        timeout_seconds: Optional timeout for the prompt.
        prompt_id: Unique identifier for this prompt.
    """

    questions: list[Question]
    timeout_seconds: int | None
    prompt_id: str
