"""Tests for SystemPromptOptimizationMiddleware."""

from types import SimpleNamespace

from langchain.agents.middleware.types import ModelRequest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from soothe.cognition.intention import RoutingClassification
from soothe.config import SootheConfig
from soothe.core.middleware import SystemPromptOptimizationMiddleware


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
    """Chitchat queries (LLM-classified) should receive minimal system prompt."""
    config = SootheConfig()
    middleware = SystemPromptOptimizationMiddleware(config=config)

    # LLM classified this as "chitchat"
    classification = RoutingClassification(
        task_complexity="chitchat",
        reasoning="Greeting/quick question",
    )

    request = MockModelRequest(
        state={"unified_classification": classification},
        system_message=SystemMessage(content="original prompt"),
    )

    modified = middleware.modify_request(request)

    # Should have minimal prompt
    assert "helpful AI assistant" in modified.system_message.content
    assert len(modified.system_message.content) < 500  # Simple prompt with creator info
    assert "Today's date is" in modified.system_message.content


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
        state={"unified_classification": classification},
        system_message=SystemMessage(content="original prompt"),
    )

    modified = middleware.modify_request(request)

    # Should have medium prompt with guidelines
    assert "proactive AI assistant" in modified.system_message.content
    assert "Be direct and concise" in modified.system_message.content
    assert 300 < len(modified.system_message.content) < 950  # Medium + nested RFC-104 XML + date


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
        state={"unified_classification": classification},
        system_message=SystemMessage(content="original prompt"),
    )

    modified = middleware.modify_request(request)

    # Should have full prompt with all guidelines
    assert "proactive AI assistant" in modified.system_message.content
    assert "around-the-clock operation" in modified.system_message.content
    assert len(modified.system_message.content) > 400


def test_no_classification_uses_default_prompt():
    """Requests without classification should use the default prompt."""
    config = SootheConfig()
    middleware = SystemPromptOptimizationMiddleware(config=config)

    request = MockModelRequest(
        state={},  # No classification
        system_message=SystemMessage(content="original prompt"),
    )

    modified = middleware.modify_request(request)

    # Should return original request unchanged
    assert modified.system_message.content == "original prompt"


def test_optimization_disabled_uses_default_prompt():
    """When optimization is disabled, should use default prompt."""
    config = SootheConfig()
    config.performance.optimize_system_prompts = False
    middleware = SystemPromptOptimizationMiddleware(config=config)

    classification = RoutingClassification(
        task_complexity="chitchat",
        reasoning="Greeting",
    )

    request = MockModelRequest(
        state={"unified_classification": classification},
        system_message=SystemMessage(content="original prompt"),
    )

    modified = middleware.modify_request(request)

    # Should return original request (optimization disabled)
    assert modified.system_message.content == "original prompt"


def test_performance_disabled_uses_default_prompt():
    """When performance is disabled, should use default prompt."""
    config = SootheConfig()
    config.performance.enabled = False
    middleware = SystemPromptOptimizationMiddleware(config=config)

    classification = RoutingClassification(
        task_complexity="chitchat",
        reasoning="Greeting",
    )

    request = MockModelRequest(
        state={"unified_classification": classification},
        system_message=SystemMessage(content="original prompt"),
    )

    modified = middleware.modify_request(request)

    # Should return original request (performance disabled)
    assert modified.system_message.content == "original prompt"


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
        state={"unified_classification": classification},
        system_message=SystemMessage(content="original prompt"),
    )

    modified = middleware.modify_request(request)

    # Complex queries use custom prompt
    assert "custom assistant" in modified.system_message.content
    assert config.assistant_name in modified.system_message.content


def test_all_prompts_include_current_date():
    """All prompt levels should include current date."""
    import datetime as dt

    config = SootheConfig()
    middleware = SystemPromptOptimizationMiddleware(config=config)

    now = dt.datetime.now(dt.UTC).astimezone()
    expected_date = now.strftime("%Y-%m-%d")

    # Test all complexity levels
    for complexity in ["chitchat", "medium", "complex"]:
        classification = RoutingClassification(
            task_complexity=complexity,
            reasoning="Test",
        )

        request = MockModelRequest(
            state={"unified_classification": classification},
            system_message=SystemMessage(content="original"),
        )

        modified = middleware.modify_request(request)
        assert f"Today's date is {expected_date}" in modified.system_message.content


def test_chitchat_query_treated_as_chitchat():
    """Chitchat queries should be treated as chitchat for prompt selection."""
    config = SootheConfig()
    middleware = SystemPromptOptimizationMiddleware(config=config)

    # Chitchat complexity maps to simple prompt
    classification = RoutingClassification(
        task_complexity="chitchat",
        reasoning="Chitchat greeting",
    )

    request = MockModelRequest(
        state={"unified_classification": classification},
        system_message=SystemMessage(content="original prompt"),
    )

    modified = middleware.modify_request(request)

    # Should get simple prompt
    assert "helpful AI assistant" in modified.system_message.content
    assert len(modified.system_message.content) < 500  # Simple prompt with creator info


def test_explicit_subagent_routing_first_hop_tools_are_task_only() -> None:
    """Explicit /browser-style routing narrows root tools to ``task`` on first hop."""
    config = SootheConfig()
    middleware = SystemPromptOptimizationMiddleware(config=config)
    classification = RoutingClassification(
        task_complexity="medium",
        preferred_subagent="browser",
        routing_hint="subagent",
    )
    model = GenericFakeChatModel(messages=iter([AIMessage(content="x")]))
    tools = [SimpleNamespace(name="search_web"), SimpleNamespace(name="task")]
    request = ModelRequest(
        model=model,
        messages=[HumanMessage(content="latest news")],
        system_message=SystemMessage(content="orig"),
        tools=tools,
        state={"unified_classification": classification},
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
        preferred_subagent="browser",
        routing_hint="subagent",
    )
    model = GenericFakeChatModel(messages=iter([AIMessage(content="x")]))
    tools = [SimpleNamespace(name="search_web"), SimpleNamespace(name="task")]
    request = ModelRequest(
        model=model,
        messages=[HumanMessage(content="hi"), AIMessage(content="delegating")],
        system_message=SystemMessage(content="orig"),
        tools=tools,
        state={"unified_classification": classification},
    )
    modified = middleware.modify_request(request)
    assert len(modified.tools) == 2
    assert "SUBAGENT_ROUTING_DIRECTIVE" not in modified.system_message.content
