"""Host middleware: inject ``ask_user`` gate directive into the system prompt.

The ``ask_user`` host tool and the platonic-coding skill's ``<GATE-INSTRUCTION>``
are necessary but not sufficient — the LLM may still write clarifying questions
as plain prose (observed in loop 612e). This middleware appends a top-level
system prompt directive telling the model to call the ``ask_user`` tool at every
confirmation/clarification gate, which has higher adherence weight than a
reference file read as a tool result.

Runs in ``host_suffix`` position (after ``SystemPromptMiddleware``) so it sees
the fully-built system prompt and can append to it.
"""

from __future__ import annotations

from collections.abc import Callable

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ContextT, ModelRequest, ModelResponse
from langchain_core.messages import SystemMessage

_ASK_USER_DIRECTIVE = """


<ASK_USER_GATE_DIRECTIVE>
When you need to ask the user a question, present a choice, or get approval
before proceeding, you MUST call the `ask_user` tool with the question. Do NOT
write questions as plain text in your response.

Why: the runtime clarification relay only engages on a structured `ask_user`
tool call. A plain-text question is invisible to the relay — the loop will not
pause, the goal will finalize without the user's input, and the user's typed
reply will start a brand-new goal instead of resuming this one. Calling
`ask_user` pauses the loop and resumes on the same turn once the user answers.

Rules:
- At every confirmation gate, clarification question, design approval, or
  routing menu: call `ask_user` with the question text.
- Prefer one question per `ask_user` call.
- For a multiple-choice decision, put the options in the question text of a
  single call (e.g. "Which approach: A) ... B) ... C) ...?").
- This applies to ALL modes (brainstorm, implementation, review, workflow).
</ASK_USER_GATE_DIRECTIVE>"""


class AskUserPromptMiddleware(AgentMiddleware):
    """Append the ``ask_user`` gate directive to the system prompt."""

    def wrap_model_call(
        self,
        request: ModelRequest[ContextT],
        handler: Callable[[ModelRequest[ContextT]], ModelResponse[ContextT]],
    ) -> ModelResponse[ContextT]:
        """Append the directive to the system message before the model call.

        Uses ``wrap_model_call`` (not ``modify_request``) because the host
        suffix runs after ``SystemPromptMiddleware.modify_request`` which
        already set the system message. ``wrap_model_call`` sees the final
        request and can augment the system message inline.
        """
        sm = getattr(request, "system_message", None)
        if sm is not None and isinstance(sm, SystemMessage):
            content = sm.content
            if isinstance(content, str) and _DIRECTIVE_TAG not in content:
                new_content = content.rstrip() + _ASK_USER_DIRECTIVE
                new_request = request.override(system_message=SystemMessage(content=new_content))
                return handler(new_request)
        return handler(request)


_DIRECTIVE_TAG = "<ASK_USER_GATE_DIRECTIVE>"

__all__ = ["AskUserPromptMiddleware"]
