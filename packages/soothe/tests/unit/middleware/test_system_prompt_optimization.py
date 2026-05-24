"""Tests for SystemPromptOptimizationMiddleware (RFC-214 volatility-tiered architecture)."""

from types import SimpleNamespace
from unittest.mock import patch

from langchain.agents.middleware.types import ModelRequest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from soothe.config import SootheConfig
from soothe.core.intention import RoutingClassification
from soothe.middleware import SystemPromptOptimizationMiddleware


class MockModelRequest(ModelRequest[dict]):
    """Mock ModelRequest for testing."""

    def __init__(self, state: dict, system_message: SystemMessage) -> None:
        """Initialize mock request.

        Args:
            state: Agent state dictionary.
            system_message: System message to include.
        """
        # Don't call super().__init__ - it has deprecated behavior
        # Instead, manually initialize the fields we need
        object.__setattr__(self, "_model", "test")
        object.__setattr__(self, "_messages", [system_message])
        object.__setattr__(self, "_state", state)
        object.__setattr__(self, "_system_message", system_message)

    def override(self, **kwargs: object) -> "MockModelRequest":
        """Override request properties.

        Args:
            kwargs: Properties to override (supports system_message).

        Returns:
            New mock request with overridden properties.
        """
        new_system = kwargs.get("system_message", self._system_message)
        return MockModelRequest(state=self.state, system_message=new_system)

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


def test_simple_query_gets_minimal_prompt():
    """Minimal task complexity (e.g. quiz path) should receive minimal system prompt (RFC-214)."""
    config = SootheConfig()
    middleware = SystemPromptOptimizationMiddleware(config=config)

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

    # Should have minimal prompt (no date line - date is in user envelope per RFC-214)
    assert "helpful AI assistant" in modified.system_message.content
    assert len(modified.system_message.content) < 500
    # RFC-214: Date line NOT in system prompt - it's in user message envelope
    assert "Today's date is" not in modified.system_message.content


def test_medium_query_gets_medium_prompt():
    """Medium queries (LLM-classified) should receive medium system prompt."""
    config = SootheConfig()
    middleware = SystemPromptOptimizationMiddleware(config=config)

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
    assert "proactive AI assistant" in modified.system_message.content
    assert "Be direct and concise" in modified.system_message.content
    # RFC-214: no date line in system prompt
    assert "Today's date is" not in modified.system_message.content


def test_simple_query_gets_compact_prompt() -> None:
    """Simple task complexity should use compact system prompt tier."""
    config = SootheConfig()
    middleware = SystemPromptOptimizationMiddleware(config=config)
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
    middleware = SystemPromptOptimizationMiddleware(config=config)

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
    assert "proactive AI assistant" in modified.system_message.content
    assert "around-the-clock operation" in modified.system_message.content
    assert len(modified.system_message.content) > 400


def test_no_classification_uses_medium_optimized_prompt():
    """Requests without classification still get optimized medium-tier system prompt."""
    config = SootheConfig()
    middleware = SystemPromptOptimizationMiddleware(config=config)

    request = MockModelRequest(
        state={},  # No classification
        system_message=SystemMessage(content="original prompt"),
    )

    modified = middleware.modify_request(request)

    assert modified.system_message.content != "original prompt"
    assert "proactive AI assistant" in modified.system_message.content
    # RFC-214: Date is in user envelope
    assert "Today's date is" not in modified.system_message.content


def test_execution_hints_extracted_to_state():
    """RFC-214: Execution hints extracted from state for user envelope, not merged into system."""
    config = SootheConfig()
    middleware = SystemPromptOptimizationMiddleware(config=config)
    classification = RoutingClassification(task_complexity="medium")
    hint_body = (
        "Suggested subagent: explore. Expected output: paths under src/. "
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
    config.system_prompt = "You are a custom assistant for {assistant_name}."
    middleware = SystemPromptOptimizationMiddleware(config=config)

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
    assert config.assistant_name in modified.system_message.content


def test_all_prompts_do_not_include_date():
    """RFC-214: Date line is NOT in system prompt - it's in user message envelope."""
    config = SootheConfig()
    middleware = SystemPromptOptimizationMiddleware(config=config)

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
    middleware = SystemPromptOptimizationMiddleware(config=config)

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

    # Should get simple prompt
    assert "helpful AI assistant" in modified.system_message.content
    assert len(modified.system_message.content) < 500


def test_explicit_subagent_routing_first_hop_tools_are_task_only() -> None:
    """Explicit slash-style routing narrows root tools to ``task`` on first hop."""
    config = SootheConfig()
    middleware = SystemPromptOptimizationMiddleware(config=config)
    classification = RoutingClassification(
        task_complexity="medium",
        preferred_subagent="tacitus",
        routing_hint="subagent",
    )
    model = GenericFakeChatModel(messages=iter([AIMessage(content="x")]))
    tools = [SimpleNamespace(name="search_web"), SimpleNamespace(name="task")]
    request = ModelRequest(
        model=model,
        messages=[HumanMessage(content="latest news")],
        system_message=SystemMessage(content="orig"),
        tools=tools,
        state={"routing_classification": classification},
    )
    modified = middleware.modify_request(request)
    assert len(modified.tools) == 1
    assert getattr(modified.tools[0], "name", None) == "task"
    assert "SUBAGENT_ROUTING_DIRECTIVE" in modified.system_message.content
    assert "MUST use" in modified.system_message.content


def test_explicit_subagent_routing_after_assistant_message_full_tools() -> None:
    """After the first model reply, restore full tools and omit routing directive."""
    config = SootheConfig()
    middleware = SystemPromptOptimizationMiddleware(config=config)
    classification = RoutingClassification(
        task_complexity="medium",
        preferred_subagent="tacitus",
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
    modified = middleware.modify_request(request)
    assert len(modified.tools) == 2
    assert "SUBAGENT_ROUTING_DIRECTIVE" not in modified.system_message.content


def test_step_subagent_configurable_first_hop_tools_are_task_only() -> None:
    """AgentLoop ``soothe_step_subagent`` narrows root tools to ``task`` on first hop."""
    config = SootheConfig()
    middleware = SystemPromptOptimizationMiddleware(config=config)
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
    lg_config = {"configurable": {"thread_id": "t1", "soothe_step_subagent": "explore"}}
    with patch("langgraph.config.get_config", return_value=lg_config):
        modified = middleware.modify_request(request)
    assert len(modified.tools) == 1
    assert getattr(modified.tools[0], "name", None) == "task"
    assert "SUBAGENT_ROUTING_DIRECTIVE" in modified.system_message.content
    assert "explore" in modified.system_message.content


def test_step_subagent_overrides_wire_preferred_on_first_hop() -> None:
    """``soothe_step_subagent`` configurable wins over wire ``preferred_subagent`` on first hop."""
    config = SootheConfig()
    middleware = SystemPromptOptimizationMiddleware(config=config)
    classification = RoutingClassification(
        task_complexity="medium",
        preferred_subagent="tacitus",
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
    lg_config = {"configurable": {"soothe_step_subagent": "explore"}}
    with patch("langgraph.config.get_config", return_value=lg_config):
        modified = middleware.modify_request(request)
    content = modified.system_message.content
    assert "subagent_type='explore'" in content
    assert "subagent_type='tacitus'" not in content


def test_goal_synthesis_disables_all_tools() -> None:
    """Goal-completion synthesis must not expose tools (read-only ledger synthesis)."""
    config = SootheConfig()
    middleware = SystemPromptOptimizationMiddleware(config=config)
    model = GenericFakeChatModel(messages=iter([AIMessage(content="x")]))
    tools = [SimpleNamespace(name="read_file"), SimpleNamespace(name="task")]
    request = ModelRequest(
        model=model,
        messages=[HumanMessage(content="Synthesize findings")],
        system_message=SystemMessage(content="orig"),
        tools=tools,
        state={},
    )
    lg_config = {"configurable": {"soothe_goal_synthesis": True}}
    with patch("langgraph.config.get_config", return_value=lg_config):
        modified = middleware.modify_request(request)
    assert modified.tools == []


def test_memory_section_uses_memory_summary_tag():
    """RFC-214: Memory section should use <MEMORY_SUMMARY> tag."""
    from soothe.protocols.memory import MemoryItem

    config = SootheConfig()
    middleware = SystemPromptOptimizationMiddleware(config=config)

    memories = [
        MemoryItem(content="User prefers Python", source_thread="thread_123"),
    ]

    section = middleware._build_memory_section(memories)
    assert "<MEMORY_SUMMARY>" in section
    assert "</MEMORY_SUMMARY>" in section
