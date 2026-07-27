"""Tests for SystemPromptMiddleware (RFC-214 volatility-tiered architecture)."""

import re
from types import SimpleNamespace
from unittest.mock import patch

from langchain.agents.middleware.types import ModelRequest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from soothe_nano.middleware import SystemPromptMiddleware
from soothe_nano.middleware.progressive_listing import ProgressiveListingMiddleware
from soothe_nano.middleware.tool_enforcement import ToolEnforcementMiddleware
from soothe_sdk.intention.models import RoutingClassification

from soothe.config import SootheConfig

_VOLATILE_PROMPT_SECTION_RE = re.compile(
    r"<(?:ENVIRONMENT|TIMESTAMP)>.*?</(?:ENVIRONMENT|TIMESTAMP)>\n?",
    re.DOTALL,
)


def _stable_prompt_body_length(content: str) -> int:
    """Length of prompt text excluding platform- and time-volatile XML blocks."""
    return len(_VOLATILE_PROMPT_SECTION_RE.sub("", content))


class MockModelRequest(ModelRequest[dict]):
    """Mock ModelRequest for testing."""

    def __init__(
        self,
        state: dict,
        system_message: SystemMessage,
        tools: list | None = None,
    ) -> None:
        """Initialize mock request.

        Args:
            state: Agent state dictionary.
            system_message: System message to include.
            tools: Optional bound tools list.
        """
        # Don't call super().__init__ - it has deprecated behavior
        # Instead, manually initialize the fields we need
        object.__setattr__(self, "_model", "test")
        object.__setattr__(self, "_messages", [system_message])
        object.__setattr__(self, "_state", state)
        object.__setattr__(self, "_system_message", system_message)
        object.__setattr__(self, "_tools", list(tools or []))

    def override(self, **kwargs: object) -> "MockModelRequest":
        """Override request properties.

        Args:
            kwargs: Properties to override (supports system_message, tools).

        Returns:
            New mock request with overridden properties.
        """
        new_system = kwargs.get("system_message", self._system_message)
        new_tools = kwargs.get("tools", self._tools)
        if not isinstance(new_system, SystemMessage):
            new_system = self._system_message
        tools_list = new_tools if isinstance(new_tools, list) else self._tools
        return MockModelRequest(
            state=self.state,
            system_message=new_system,
            tools=tools_list,
        )

    @property
    def model(self) -> str:
        """Get the model name."""
        return self._model

    @property
    def messages(self) -> list:
        """Get the messages."""
        return self._messages

    @property
    def state(self) -> dict:
        """Get the state."""
        return self._state

    @property
    def system_message(self) -> SystemMessage:
        """Get the system message."""
        return self._system_message

    @system_message.setter
    def system_message(self, value: SystemMessage) -> None:
        """Set the system message."""
        object.__setattr__(self, "_system_message", value)

    @property
    def tools(self) -> list:
        """Get bound tools."""
        return self._tools

    @tools.setter
    def tools(self, value: list) -> None:
        object.__setattr__(self, "_tools", value)


def test_simple_query_gets_minimal_prompt():
    """Minimal task complexity (e.g. chitchat intake) should receive minimal system prompt (RFC-214)."""
    config = SootheConfig()
    middleware = SystemPromptMiddleware(config=config)

    # LLM routed with minimal complexity
    classification = RoutingClassification(
        task_complexity="minimal",
        reasoning="Greeting/quick question",
    )

    request = MockModelRequest(
        state={"routing_classification": classification},
        system_message=SystemMessage(content="original prompt"),
    )

    modified = middleware.modify_request(request)

    content = modified.system_message.content
    assert content.startswith("<ASSISTANT_IDENTITY>")
    assert config.agent.name in content
    # Should have minimal prompt (no date line - date is in user envelope per RFC-214).
    # Threshold accounts for the RESPONSE_LANGUAGE_HINT block now living in the system prompt.
    assert "helpful AI assistant" in content
    assert _stable_prompt_body_length(content) < 900
    # RFC-214: Date line NOT in system prompt - it's in user message envelope
    assert "Today's date is" not in content


def test_medium_query_gets_medium_prompt():
    """Medium queries (LLM-classified) should receive medium system prompt."""
    config = SootheConfig()
    middleware = SystemPromptMiddleware(config=config)

    # LLM classified this as "medium"
    classification = RoutingClassification(
        task_complexity="medium",
        reasoning="Multi-step task",
    )

    request = MockModelRequest(
        state={"routing_classification": classification},
        system_message=SystemMessage(content="original prompt"),
    )

    modified = middleware.modify_request(request)

    # Should have medium prompt with guidelines
    assert "Handle practical tasks" in modified.system_message.content
    assert "Be direct and concise" in modified.system_message.content
    # RFC-214: no date line in system prompt
    assert "Today's date is" not in modified.system_message.content


def test_simple_query_gets_compact_prompt() -> None:
    """Simple task complexity should use compact system prompt tier."""
    config = SootheConfig()
    middleware = SystemPromptMiddleware(config=config)
    classification = RoutingClassification(task_complexity="simple")
    request = MockModelRequest(
        state={"routing_classification": classification},
        system_message=SystemMessage(content="original prompt"),
    )
    modified = middleware.modify_request(request)
    assert "helpful AI assistant" in modified.system_message.content
    # RFC-214: Date is in user envelope, not system prompt
    assert "Today's date is" not in modified.system_message.content


def test_complex_query_gets_full_prompt():
    """Complex queries (LLM-classified) should receive full system prompt."""
    config = SootheConfig()
    middleware = SystemPromptMiddleware(config=config)

    # LLM classified this as "complex"
    classification = RoutingClassification(
        task_complexity="complex",
        reasoning="Architectural decision",
    )

    request = MockModelRequest(
        state={"routing_classification": classification},
        system_message=SystemMessage(content="original prompt"),
    )

    modified = middleware.modify_request(request)

    # Should have full prompt with all guidelines
    assert "Never reference your internal architecture" in modified.system_message.content
    assert "run_command" in modified.system_message.content
    assert len(modified.system_message.content) > 400


def test_no_classification_uses_medium_optimized_prompt():
    """Requests without classification still get optimized medium-tier system prompt."""
    config = SootheConfig()
    middleware = SystemPromptMiddleware(config=config)

    request = MockModelRequest(
        state={},  # No classification
        system_message=SystemMessage(content="original prompt"),
    )

    modified = middleware.modify_request(request)

    assert modified.system_message.content != "original prompt"
    assert "Handle practical tasks" in modified.system_message.content
    # RFC-214: Date is in user envelope
    assert "Today's date is" not in modified.system_message.content


def test_execution_hints_extracted_to_state():
    """RFC-214: Execution hints extracted from state for user envelope, not merged into system."""
    config = SootheConfig()
    middleware = SystemPromptMiddleware(config=config)
    classification = RoutingClassification(task_complexity="medium")
    hint_body = (
        "Suggested subagent: deep_research. Expected output: paths under src/. "
        "Consider using the suggested approach first."
    )
    request = MockModelRequest(
        state={
            "routing_classification": classification,
            "system_prompt": f"You are Soothe agent.\n\nExecution hints: {hint_body}",
        },
        system_message=SystemMessage(content="original prompt"),
    )
    modified = middleware.modify_request(request)
    # RFC-214: Execution hints NOT in system prompt - they go to user envelope
    assert "Execution hints:" not in modified.system_message.content
    # But they should be extracted into state for user envelope building
    assert request.state.get("_soothe_execution_hints") == hint_body


def test_custom_system_prompt_for_complex_queries():
    """Complex queries should use custom system prompt if configured."""
    config = SootheConfig()
    config.agent.system_prompt = "You are a custom assistant for {assistant_name}."
    middleware = SystemPromptMiddleware(config=config)

    classification = RoutingClassification(
        task_complexity="complex",
        reasoning="Complex task",
    )

    request = MockModelRequest(
        state={"routing_classification": classification},
        system_message=SystemMessage(content="original prompt"),
    )

    modified = middleware.modify_request(request)

    # Complex queries use custom prompt
    assert "custom assistant" in modified.system_message.content
    assert config.agent.name in modified.system_message.content


def test_all_prompts_do_not_include_date():
    """RFC-214: Date line is NOT in system prompt - it's in user message envelope."""
    config = SootheConfig()
    middleware = SystemPromptMiddleware(config=config)

    # Test all complexity levels - none should have date in system prompt
    for complexity in ["minimal", "simple", "medium", "complex"]:
        classification = RoutingClassification(
            task_complexity=complexity,
            reasoning="Test",
        )

        request = MockModelRequest(
            state={"routing_classification": classification},
            system_message=SystemMessage(content="original"),
        )

        modified = middleware.modify_request(request)
        assert "Today's date is" not in modified.system_message.content


def test_minimal_task_complexity_uses_compact_prompt():
    """Minimal task complexity should use compact system prompt tier."""
    config = SootheConfig()
    middleware = SystemPromptMiddleware(config=config)

    # Minimal complexity maps to simple prompt
    classification = RoutingClassification(
        task_complexity="minimal",
        reasoning="Quiz greeting",
    )

    request = MockModelRequest(
        state={"routing_classification": classification},
        system_message=SystemMessage(content="original prompt"),
    )

    modified = middleware.modify_request(request)

    # Should get simple prompt. Threshold accounts for the RESPONSE_LANGUAGE_HINT
    # block now living in the system prompt.
    assert "helpful AI assistant" in modified.system_message.content
    assert _stable_prompt_body_length(modified.system_message.content) < 900


def test_explicit_subagent_routing_first_hop_tools_are_task_only() -> None:
    """Explicit slash-style routing narrows root tools to ``task`` on first hop."""
    config = SootheConfig()
    enforcement = ToolEnforcementMiddleware()
    middleware = SystemPromptMiddleware(config=config)
    classification = RoutingClassification(
        task_complexity="medium",
        preferred_subagent="plugin_agent",
        routing_hint="subagent",
    )
    model = GenericFakeChatModel(messages=iter([AIMessage(content="x")]))
    tools = [SimpleNamespace(name="search_web"), SimpleNamespace(name="task")]
    request = ModelRequest(
        model=model,
        messages=[HumanMessage(content="draft a plan")],
        system_message=SystemMessage(content="orig"),
        tools=tools,
        state={"routing_classification": classification},
    )
    enforced = enforcement.modify_request(request)
    modified = middleware.modify_request(enforced)
    assert len(enforced.tools) == 1
    assert getattr(enforced.tools[0], "name", None) == "task"
    assert "SUBAGENT_ROUTING_DIRECTIVE" in modified.system_message.content
    assert "MUST use" in modified.system_message.content


def test_explicit_subagent_routing_after_assistant_message_full_tools() -> None:
    """After the first model reply, restore full tools and omit routing directive."""
    config = SootheConfig()
    enforcement = ToolEnforcementMiddleware()
    middleware = SystemPromptMiddleware(config=config)
    classification = RoutingClassification(
        task_complexity="medium",
        preferred_subagent="deep_research",
        routing_hint="subagent",
    )
    model = GenericFakeChatModel(messages=iter([AIMessage(content="x")]))
    tools = [SimpleNamespace(name="search_web"), SimpleNamespace(name="task")]
    request = ModelRequest(
        model=model,
        messages=[HumanMessage(content="hi"), AIMessage(content="delegating")],
        system_message=SystemMessage(content="orig"),
        tools=tools,
        state={"routing_classification": classification},
    )
    enforced = enforcement.modify_request(request)
    modified = middleware.modify_request(enforced)
    assert len(enforced.tools) == 2
    assert "SUBAGENT_ROUTING_DIRECTIVE" not in modified.system_message.content


def test_step_subagent_configurable_first_hop_tools_are_task_only() -> None:
    """Host ``soothe_step_subagent`` narrows root tools to ``task`` on first hop."""
    from soothe.sloop.config_keys import SOOTHE_STEP_SUBAGENT_CONFIG_KEY
    from soothe.sloop.goal_step_guard import GoalStepGuardMiddleware

    config = SootheConfig()
    guard = GoalStepGuardMiddleware()
    middleware = SystemPromptMiddleware(config=config)
    classification = RoutingClassification(
        task_complexity="medium",
        reasoning="test",
    )
    model = GenericFakeChatModel(messages=iter([AIMessage(content="x")]))
    tools = [SimpleNamespace(name="read_file"), SimpleNamespace(name="task")]
    request = ModelRequest(
        model=model,
        messages=[HumanMessage(content="Execute: map src/")],
        system_message=SystemMessage(content="orig"),
        tools=tools,
        state={"routing_classification": classification},
    )
    lg_config = {
        "configurable": {"thread_id": "t1", SOOTHE_STEP_SUBAGENT_CONFIG_KEY: "plugin_agent"}
    }
    with patch("langgraph.config.get_config", return_value=lg_config):
        enforced = guard.modify_request(request)
        modified = middleware.modify_request(enforced)
    assert len(enforced.tools) == 1
    assert getattr(enforced.tools[0], "name", None) == "task"
    assert "SUBAGENT_ROUTING_DIRECTIVE" in modified.system_message.content
    assert "plugin_agent" in modified.system_message.content


def test_step_subagent_configurable_after_assistant_message_still_task_only() -> None:
    """Wired catalog step subagents stay task-only after the first model hop."""
    from soothe.sloop.config_keys import SOOTHE_STEP_SUBAGENT_CONFIG_KEY
    from soothe.sloop.goal_step_guard import GoalStepGuardMiddleware

    config = SootheConfig()
    guard = GoalStepGuardMiddleware()
    middleware = SystemPromptMiddleware(config=config)
    classification = RoutingClassification(
        task_complexity="medium",
        reasoning="test",
    )
    model = GenericFakeChatModel(messages=iter([AIMessage(content="x")]))
    tools = [SimpleNamespace(name="run_command"), SimpleNamespace(name="task")]
    request = ModelRequest(
        model=model,
        messages=[
            HumanMessage(content="Execute: use plugin_agent"),
            AIMessage(content="delegating"),
            ToolMessage(content="plan draft", tool_call_id="t1"),
        ],
        system_message=SystemMessage(content="orig"),
        tools=tools,
        state={"routing_classification": classification},
    )
    lg_config = {
        "configurable": {"thread_id": "t1", SOOTHE_STEP_SUBAGENT_CONFIG_KEY: "plugin_agent"}
    }
    with patch("langgraph.config.get_config", return_value=lg_config):
        enforced = guard.modify_request(request)
        modified = middleware.modify_request(enforced)
    assert len(enforced.tools) == 1
    assert getattr(enforced.tools[0], "name", None) == "task"
    assert "plugin_agent" in modified.system_message.content


def test_step_subagent_overrides_wire_preferred_on_first_hop() -> None:
    """Host step wire wins over preferred_subagent when GoalStep runs after ToolEnforcement."""
    from soothe.sloop.config_keys import SOOTHE_STEP_SUBAGENT_CONFIG_KEY
    from soothe.sloop.goal_step_guard import GoalStepGuardMiddleware

    config = SootheConfig()
    enforcement = ToolEnforcementMiddleware()
    guard = GoalStepGuardMiddleware()
    middleware = SystemPromptMiddleware(config=config)
    classification = RoutingClassification(
        task_complexity="medium",
        preferred_subagent="general_purpose",
        routing_hint="subagent",
    )
    model = GenericFakeChatModel(messages=iter([AIMessage(content="x")]))
    tools = [SimpleNamespace(name="search_web"), SimpleNamespace(name="task")]
    request = ModelRequest(
        model=model,
        messages=[HumanMessage(content="step")],
        system_message=SystemMessage(content="orig"),
        tools=tools,
        state={"routing_classification": classification},
    )
    lg_config = {"configurable": {SOOTHE_STEP_SUBAGENT_CONFIG_KEY: "plugin_agent"}}
    with patch("langgraph.config.get_config", return_value=lg_config):
        after_te = enforcement.modify_request(request)
        enforced = guard.modify_request(after_te)
        modified = middleware.modify_request(enforced)
    content = modified.system_message.content
    assert "subagent_type='plugin_agent'" in content


def test_intake_only_step_subagent_hint_is_rejected_by_host_resolver() -> None:
    """Host step resolver drops intake-only names before CoreAgent runs."""
    from soothe.sloop.config_keys import SOOTHE_STEP_SUBAGENT_CONFIG_KEY
    from soothe.sloop.goal_step_guard import GoalStepGuardMiddleware
    from soothe.sloop.state.schemas import resolve_step_wire_subagent

    assert resolve_step_wire_subagent(execution_hint="subagent", subagent="deep_research") is None
    assert resolve_step_wire_subagent(execution_hint="subagent", subagent="planner") is None

    # Host incorrectly setting step wire still narrows via GoalStepGuard (not nano).
    guard = GoalStepGuardMiddleware()
    model = GenericFakeChatModel(messages=iter([AIMessage(content="x")]))
    tools = [SimpleNamespace(name="read_file"), SimpleNamespace(name="task")]
    request = ModelRequest(
        model=model,
        messages=[HumanMessage(content="Execute: research")],
        system_message=SystemMessage(content="orig"),
        tools=tools,
        state={},
    )
    lg_config = {"configurable": {SOOTHE_STEP_SUBAGENT_CONFIG_KEY: "deep_research"}}
    with patch("langgraph.config.get_config", return_value=lg_config):
        enforced = guard.modify_request(request)
    assert len(enforced.tools) == 1
    assert getattr(enforced.tools[0], "name", None) == "task"


def test_goal_synthesis_disables_all_tools() -> None:
    """Goal-completion synthesis must not expose tools (read-only ledger synthesis)."""
    from soothe.sloop.config_keys import SOOTHE_GOAL_SYNTHESIS_CONFIG_KEY
    from soothe.sloop.goal_step_guard import GoalStepGuardMiddleware

    config = SootheConfig()
    guard = GoalStepGuardMiddleware()
    middleware = SystemPromptMiddleware(config=config)
    model = GenericFakeChatModel(messages=iter([AIMessage(content="x")]))
    tools = [SimpleNamespace(name="read_file"), SimpleNamespace(name="task")]
    request = ModelRequest(
        model=model,
        messages=[HumanMessage(content="Synthesize findings")],
        system_message=SystemMessage(content="orig"),
        tools=tools,
        state={},
    )
    lg_config = {"configurable": {SOOTHE_GOAL_SYNTHESIS_CONFIG_KEY: True}}
    with patch("langgraph.config.get_config", return_value=lg_config):
        enforced = guard.modify_request(request)
        modified = middleware.modify_request(enforced)
    assert enforced.tools == []
    assert modified.tools == []


def test_memory_section_uses_memory_summary_tag():
    """RFC-214: Memory section should use <MEMORY_SUMMARY> tag."""
    from soothe_sdk.protocols.memory import MemoryItem

    config = SootheConfig()
    middleware = SystemPromptMiddleware(config=config)

    memories = [
        MemoryItem(content="User prefers Python", source_thread="thread_123"),
    ]

    section = middleware._build_memory_section(memories)
    assert "<MEMORY_SUMMARY>" in section
    assert "</MEMORY_SUMMARY>" in section


class TestSkillActivationInStateDict:
    def test_state_dict_includes_skill_activation(self) -> None:
        """state_dict passes skill_activation through so _compose_skills_block can see it."""
        config = SootheConfig()
        middleware = SystemPromptMiddleware(config=config)

        activation = {"sent": set(), "activated": {"a"}, "invoked": set(), "just_invoked": set()}
        request = ModelRequest(
            model=GenericFakeChatModel(messages=iter([AIMessage(content="x")])),
            messages=[HumanMessage(content="hi")],
            system_message=SystemMessage(content="orig"),
            tools=[],
            state={"skill_activation": activation},
        )
        # We test indirectly: modify_request must not crash, and the
        # skill_activation key should reach _compose_skills_block.
        with patch("langgraph.config.get_config", return_value={"configurable": {}}):
            modified = middleware.modify_request(request)
        # If skill_activation were missing from state_dict, _compose_skills_block
        # would always return (None, []) — but the middleware should still succeed.
        assert modified is not None


class TestComposeSkillsBlockJustInvokedExclusion:
    def test_just_invoked_skills_excluded_from_listing_entries(self) -> None:
        """just_invoked skill names are filtered from listing_entries."""
        from soothe_nano.skills.index import SkillIndexEntry

        weather = SkillIndexEntry(
            name="weather",
            description="Get weather",
            tags="",
            source="user",
            path="/skills/weather",
            mtime=0.0,
        )
        translate = SkillIndexEntry(
            name="translate",
            description="Translate text",
            tags="",
            source="user",
            path="/skills/translate",
            mtime=0.0,
        )
        just_invoked = {"weather"}
        new_entries = [weather, translate]

        # This mirrors the filtering logic in _compose_skills_block
        listing_entries = [e for e in new_entries if e.name not in just_invoked]

        assert len(listing_entries) == 1
        assert listing_entries[0].name == "translate"

    def test_skill_context_blocks_exclude_just_invoked(self) -> None:
        """invoked - just_invoked produces correct SKILL_CONTEXT block list."""
        activation = {
            "sent": set(),
            "activated": set(),
            "invoked": {"weather"},
            "invoked_bodies": {"weather": "Weather body"},
            "just_invoked": {"weather"},
        }
        invoked = activation.get("invoked", set())
        just_invoked = activation.get("just_invoked", set())
        bodies = activation.get("invoked_bodies", {})

        # This mirrors the SKILL_CONTEXT block logic in _compose_skills_block
        skill_context_blocks = []
        for name in sorted(invoked - just_invoked):
            body = bodies.get(name)
            if body:
                skill_context_blocks.append(
                    f'<SKILL_CONTEXT name="{name}">\n{body}\n</SKILL_CONTEXT>'
                )

        assert skill_context_blocks == []

        # After just_invoked clears (turn 2+), weather body appears
        activation2 = {**activation, "just_invoked": set()}
        invoked2 = activation2.get("invoked", set())
        just_invoked2 = activation2.get("just_invoked", set())
        blocks2 = []
        for name in sorted(invoked2 - just_invoked2):
            body = bodies.get(name)
            if body:
                blocks2.append(f'<SKILL_CONTEXT name="{name}">\n{body}\n</SKILL_CONTEXT>')
        assert len(blocks2) == 1
        assert "weather" in blocks2[0]

    def test_skill_context_blocks_include_preloaded_auto_invoke(self) -> None:
        """Turn-0 auto-invoked skills must appear in SKILL_CONTEXT on hop 0."""
        activation = {
            "sent": set(),
            "activated": {"weather"},
            "invoked": {"weather"},
            "invoked_bodies": {"weather": "curl wttr.in/Beijing"},
            "just_invoked": set(),
        }
        invoked = activation.get("invoked", set())
        just_invoked = activation.get("just_invoked", set())
        bodies = activation.get("invoked_bodies", {})

        skill_context_blocks = []
        for name in sorted(invoked - just_invoked):
            body = bodies.get(name)
            if body:
                skill_context_blocks.append(
                    f'<SKILL_CONTEXT name="{name}">\n{body}\n</SKILL_CONTEXT>'
                )

        assert len(skill_context_blocks) == 1
        assert "wttr.in" in skill_context_blocks[0]

    def test_compose_includes_skill_context_guide_when_preloaded(self) -> None:
        from soothe_nano.middleware.system_prompt import SystemPromptMiddleware

        config = SootheConfig()
        listing = ProgressiveListingMiddleware(config=config)
        middleware = SystemPromptMiddleware(config=config)
        state = {
            "skill_activation": {
                "sent": set(),
                "activated": {"weather"},
                "invoked": {"weather"},
                "invoked_bodies": {"weather": "curl wttr.in/Beijing"},
                "just_invoked": set(),
            }
        }
        request = ModelRequest(
            model=GenericFakeChatModel(messages=iter([AIMessage(content="x")])),
            messages=[HumanMessage(content="hi")],
            system_message=SystemMessage(content="base"),
            tools=[],
            state=state,
        )
        listing.modify_request(request)
        prompt = middleware._get_prompt_for_complexity("medium", state)
        assert "<SKILL_CONTEXT_GUIDE>" in prompt
        assert '<SKILL_CONTEXT name="weather">' in prompt
        assert "search_tools" in prompt


class TestToolSelectionGuidance:
    def test_prompt_includes_tool_selection_block(self) -> None:
        from soothe_nano.middleware.system_prompt import SystemPromptMiddleware

        middleware = SystemPromptMiddleware(config=SootheConfig())
        prompt = middleware._get_prompt_for_complexity("simple", {})
        assert "<TOOL_SELECTION>" in prompt
        assert "read_command" in prompt
        assert "run_command" in prompt


class TestWorkspaceInjection:
    """`_should_inject_workspace` is unconditional on `state['workspace']`.

    Regression for trace fe0d: workspace queries fired on the first execute
    step (empty messages, no prior ToolMessages) and the gate suppressed the
    WORKSPACE section, so the LLM hallucinated `/Users/user/ai-demo`.
    """

    def _middleware(self) -> SystemPromptMiddleware:
        return SystemPromptMiddleware(config=SootheConfig())

    def test_injects_when_workspace_set_with_empty_messages(self) -> None:
        mw = self._middleware()
        assert mw._should_inject_workspace({"workspace": "/abs/path", "messages": []}) is True

    def test_skips_when_workspace_missing(self) -> None:
        mw = self._middleware()
        assert mw._should_inject_workspace({"messages": []}) is False
        assert mw._should_inject_workspace({"workspace": None, "messages": []}) is False
        assert mw._should_inject_workspace({"workspace": "", "messages": []}) is False

    def test_injects_without_prior_tool_messages(self) -> None:
        """Pre-fix, this returned False because no ToolMessage was in history."""
        mw = self._middleware()
        state = {
            "workspace": "/abs/path",
            "messages": [HumanMessage("what is your current workspace")],
        }
        assert mw._should_inject_workspace(state) is True

    def test_minimal_complexity_still_emits_workspace_blocks(self, tmp_path) -> None:
        """Minimal-complexity execute steps must include WORKSPACE_RULES, <WORKSPACE>,
        and AGENT_INSTRUCTIONS when a workspace is bound.

        Regression for the trace fe0d follow-up: previously the minimal branch
        in ``_get_prompt_for_complexity`` short-circuited before reaching the
        semi-static tier, so direct-answer execute steps had no workspace
        grounding and hallucinated paths.
        """
        (tmp_path / "AGENTS.md").write_text("# Rules\n\nBe concise.\n", encoding="utf-8")
        mw = self._middleware()
        prompt = mw._get_prompt_for_complexity("minimal", {"workspace": str(tmp_path)})
        assert "<WORKSPACE_RULES>" in prompt
        assert "<WORKSPACE>" in prompt
        assert "<AGENT_INSTRUCTIONS>" in prompt
        assert "Be concise." in prompt

    def test_response_language_hint_lives_in_system_prompt(self, tmp_path) -> None:
        """Language hint was moved out of the per-turn user envelope into the
        cache-stable system prelude. The tag is uppercase to match the system
        prompt's tag convention.
        """
        mw = self._middleware()
        prompt = mw._get_prompt_for_complexity("simple", {"workspace": str(tmp_path)})
        assert "<RESPONSE_LANGUAGE_HINT>" in prompt
        assert "same natural language as the user's goal" in prompt
        # The lowercase legacy tag must not leak back in.
        assert "<response_language_hint>" not in prompt
        # Hint sits in the behavioral prelude (before workspace tail / ENVIRONMENT).
        assert prompt.find("<RESPONSE_LANGUAGE_HINT>") < prompt.find("<ENVIRONMENT")

    def test_response_language_hint_uses_explicit_language_from_state(self, tmp_path) -> None:
        from soothe.sloop.intention.models import ResponseLanguage

        mw = self._middleware()
        classification = RoutingClassification(task_complexity="simple")
        request = MockModelRequest(
            state={
                "routing_classification": classification,
                "response_language": ResponseLanguage.ZH,
                "workspace": str(tmp_path),
            },
            system_message=SystemMessage(content="original prompt"),
        )
        modified = mw.modify_request(request)
        assert "Chinese (zh)" in modified.system_message.content

    def test_workspace_rules_use_execute_semantics(self, tmp_path) -> None:
        """WORKSPACE_RULES must describe path semantics for filesystem and shell tools."""
        (tmp_path / "AGENTS.md").write_text("# Rules\n", encoding="utf-8")
        mw = self._middleware()
        prompt = mw._get_prompt_for_complexity("simple", {"workspace": str(tmp_path)})
        assert "run_command, run_python" in prompt
        assert "cwd = workspace root" in prompt
        assert "inspect this directory immediately" in prompt

    def test_workspace_tail_block_order(self, tmp_path) -> None:
        """Execute-step workspace blocks live at the system-prompt tail:
        ENVIRONMENT, WORKSPACE_RULES, WORKSPACE, AGENT_INSTRUCTIONS (before TIMESTAMP).
        """
        (tmp_path / "AGENTS.md").write_text("# Rules\n\nBe terse.\n", encoding="utf-8")
        mw = self._middleware()
        prompt = mw._get_prompt_for_complexity("medium", {"workspace": str(tmp_path)})

        idx_env = prompt.find("<ENVIRONMENT")
        idx_rules = prompt.find("<WORKSPACE_RULES>")
        idx_ws = prompt.find("<WORKSPACE>\n<root>")
        idx_instr = prompt.find("<AGENT_INSTRUCTIONS>")
        idx_ts = prompt.find("<TIMESTAMP>")

        assert idx_env >= 0
        assert idx_rules >= 0
        assert idx_ws >= 0
        assert idx_instr >= 0
        assert idx_ts >= 0
        assert idx_env < idx_rules < idx_ws < idx_instr < idx_ts, (
            "Expected order: ENVIRONMENT < WORKSPACE_RULES < <WORKSPACE> < "
            f"AGENT_INSTRUCTIONS < TIMESTAMP; got env={idx_env}, "
            f"rules={idx_rules}, ws={idx_ws}, instr={idx_instr}, ts={idx_ts}"
        )
        # Workspace tail follows behavioral prelude (language hint precedes ENVIRONMENT).
        assert prompt.find("<RESPONSE_LANGUAGE_HINT>") < idx_env

    def test_state_schema_declares_workspace_channel(self) -> None:
        """LangGraph drops undeclared keys between nodes — `workspace`
        MUST be declared in ``_SystemPromptState`` so the executor's input
        dict and ``WorkspaceContextMiddleware``'s updates actually reach
        ``modify_request``. Trace 705623 regression: without this declaration
        the workspace blocks silently vanish from the execute-step system
        prompt even when state["workspace"] was set upstream.
        """
        from soothe_nano.middleware.system_prompt import _SystemPromptState

        annotations = getattr(_SystemPromptState, "__annotations__", {})
        assert "workspace" in annotations, (
            "_SystemPromptState must declare `workspace` so LangGraph "
            "preserves it across node boundaries; otherwise the execute-step "
            "system prompt loses WORKSPACE_RULES, <WORKSPACE>, and "
            "AGENT_INSTRUCTIONS."
        )
        # Annotations are stringified by ``from __future__ import annotations``
        # so we assert on the string form (NotRequired survives) rather than
        # ``__required_keys__`` which loses the marker at runtime.
        assert "NotRequired" in str(annotations["workspace"])


def test_available_tools_block_when_progressive_enabled() -> None:
    from soothe_nano.middleware.progressive_tools import ProgressiveToolMiddleware

    config = SootheConfig()
    config.progressive_tools.enabled = True
    config.progressive_tools.core_tools = ["run_command", "read_file", "search_tools"]
    progressive = ProgressiveToolMiddleware(config=config)
    listing = ProgressiveListingMiddleware(
        config=config,
        progressive_tool_middleware=progressive,
    )
    core = SimpleNamespace(name="run_command", description="Shell")
    deferred = SimpleNamespace(name="wizsearch_search", description="Web search tool")
    progressive.set_tool_catalog([core, deferred])

    middleware = SystemPromptMiddleware(config=config)
    request = MockModelRequest(
        state={"routing_classification": RoutingClassification(task_complexity="simple")},
        system_message=SystemMessage(content="base"),
        tools=[core],
    )

    listing.modify_request(request)
    modified = middleware.modify_request(request)
    content = modified.system_message.content
    assert "<AVAILABLE_TOOLS>" in content
    assert "wizsearch_search" in content
    assert "search_tools(query)" in content
    assert "not yet bound" in content


def test_simple_complexity_emits_agent_instructions(tmp_path) -> None:
    """Simple-tier execute steps must inline AGENTS.md/CLAUDE.md (headline cap)."""
    (tmp_path / "CLAUDE.md").write_text("# Dev rules\n\nUse ruff.\n", encoding="utf-8")
    mw = SystemPromptMiddleware(config=SootheConfig())
    prompt = mw._get_prompt_for_complexity("simple", {"workspace": str(tmp_path)})
    assert "<AGENT_INSTRUCTIONS>" in prompt
    assert "Use ruff." in prompt


def test_modify_request_resolves_workspace_from_langgraph_config(tmp_path) -> None:
    """Trace 416c: workspace on configurable must reach execute-step system prompt."""
    (tmp_path / "CLAUDE.md").write_text("# Dev rules\n\nUse ruff.\n", encoding="utf-8")
    mw = SystemPromptMiddleware(config=SootheConfig())
    request = MockModelRequest(
        state={"routing_classification": {"task_complexity": "simple"}, "messages": []},
        system_message=SystemMessage(content="original"),
    )
    with patch(
        "langgraph.config.get_config",
        return_value={"configurable": {"workspace": str(tmp_path)}},
    ):
        modified = mw.modify_request(request)
    content = modified.system_message.content
    assert "<AGENT_INSTRUCTIONS>" in content
    assert "<WORKSPACE_RULES>" in content
    assert "Use ruff." in content


def test_modify_request_resolves_workspace_from_human_message(tmp_path) -> None:
    """Workspace on LoopHumanMessage must reach execute-step system prompt."""
    from soothe.sloop.utils.messages import LoopHumanMessage

    (tmp_path / "CLAUDE.md").write_text("# Dev rules\n\nUse ruff.\n", encoding="utf-8")
    mw = SystemPromptMiddleware(config=SootheConfig())
    request = MockModelRequest(
        state={
            "routing_classification": {"task_complexity": "simple"},
            "messages": [
                LoopHumanMessage(content="EXECUTION TASK:\nDo work", workspace=str(tmp_path))
            ],
        },
        system_message=SystemMessage(content="original"),
    )
    modified = mw.modify_request(request)
    content = modified.system_message.content
    assert "<AGENT_INSTRUCTIONS>" in content
    assert "<WORKSPACE_RULES>" in content


def test_modify_request_resolves_workspace_from_request_messages_first_hop(tmp_path) -> None:
    """First execute-step hop: workspace on request.messages before state merge."""
    from soothe.sloop.utils.messages import LoopHumanMessage

    (tmp_path / "CLAUDE.md").write_text("# Dev rules\n\nUse ruff.\n", encoding="utf-8")
    mw = SystemPromptMiddleware(config=SootheConfig())
    human = LoopHumanMessage(
        content="EXECUTION TASK:\nFind verify command",
        workspace=str(tmp_path),
        phase="execute_step",
    )
    request = MockModelRequest(
        state={"routing_classification": {"task_complexity": "simple"}, "messages": []},
        system_message=SystemMessage(content="original"),
    )
    object.__setattr__(request, "_messages", [human])
    modified = mw.modify_request(request)
    content = modified.system_message.content
    assert "<WORKSPACE_RULES>" in content
    assert "<AGENT_INSTRUCTIONS>" in content
    assert "<ENVIRONMENT" in content
    assert "<WORKSPACE>\n<root>" in content
    assert str(tmp_path) in content


def test_execute_step_has_workspace_tail_plan_generate_does_not(tmp_path) -> None:
    """Workspace blocks are execute-step only; plan-generate stays lean."""
    from soothe_sdk.protocols.planner import PlanContext

    from soothe.sloop.prompts import PromptBuilder
    from soothe.sloop.state.schemas import LoopState
    from soothe.sloop.utils.messages import LoopHumanMessage

    (tmp_path / "CLAUDE.md").write_text("# Dev rules\n\nUse ruff.\n", encoding="utf-8")
    ws = str(tmp_path)

    plan_system = (
        PromptBuilder()
        .build_plan_messages(
            "run verify",
            LoopState(goal="run verify", thread_id="t1", max_iterations=8),
            PlanContext(workspace=ws),
            plan_phase="generate",
        )[0]
        .content
    )
    assert "<WORKSPACE_RULES>" not in plan_system
    assert "<ENVIRONMENT" not in plan_system
    assert "<WORKSPACE>" not in plan_system

    mw = SystemPromptMiddleware(config=SootheConfig())
    request = MockModelRequest(
        state={"routing_classification": {"task_complexity": "simple"}, "messages": []},
        system_message=SystemMessage(content="original"),
    )
    object.__setattr__(
        request,
        "_messages",
        [
            LoopHumanMessage(
                content="EXECUTION TASK:\nRun verify",
                workspace=ws,
                phase="execute_step",
            )
        ],
    )
    execute_system = mw.modify_request(request).system_message.content
    for tag in ("<WORKSPACE_RULES>", "<AGENT_INSTRUCTIONS>", "<ENVIRONMENT", "<WORKSPACE>\n<root>"):
        assert tag in execute_system
    assert "Use ruff." in execute_system
