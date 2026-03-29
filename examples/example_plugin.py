"""Example plugin demonstrating the Soothe SDK."""

from soothe_sdk import plugin, subagent, tool, tool_group
from soothe_sdk.types import PluginHealth


@plugin(
    name="example-plugin",
    version="1.0.0",
    description="Example plugin with tools and subagent",
    author="Soothe Team",
    dependencies=["langchain>=0.1.0"],
    trust_level="standard",
)
class ExamplePlugin:
    """Example plugin showcasing SDK features."""

    async def on_load(self, context):
        """Initialize plugin when loaded."""
        self.logger = context.logger
        self.logger.info("Example plugin loaded!")

    async def on_unload(self):
        """Clean up when plugin is unloaded."""
        self.logger.info("Example plugin unloaded")

    async def health_check(self) -> PluginHealth:
        """Check plugin health."""
        return PluginHealth(status="healthy", message="Example plugin is running")

    # Simple tool
    @tool(name="greet", description="Greet someone by name")
    def greet(self, name: str) -> str:
        """Greet a person."""
        return f"Hello, {name}! Welcome to Soothe."

    # Tool group
    @tool_group(name="math", description="Mathematical operations")
    class MathTools:
        @tool(name="add", description="Add two numbers")
        def add(self, a: float, b: float) -> float:
            """Add two numbers."""
            return a + b

        @tool(name="multiply", description="Multiply two numbers")
        def multiply(self, a: float, b: float) -> float:
            """Multiply two numbers."""
            return a * b

    # Subagent
    @subagent(
        name="calculator",
        description="Simple calculator subagent",
        model="openai:gpt-4o-mini",
    )
    async def create_calculator(self, model, config, context):
        """Create a calculator subagent."""
        from langgraph.prebuilt import create_react_agent

        # Get math tools
        math_tools = self.MathTools()
        tools = [math_tools.add, math_tools.multiply]

        # Create agent
        agent = create_react_agent(model, tools)

        return {
            "name": "calculator",
            "description": "Simple calculator subagent",
            "runnable": agent,
        }


if __name__ == "__main__":
    # Test the plugin
    plugin_instance = ExamplePlugin()

    # Check manifest
    print(f"Plugin: {plugin_instance.manifest.name}")
    print(f"Version: {plugin_instance.manifest.version}")
    print(f"Description: {plugin_instance.manifest.description}")
    print(f"Dependencies: {plugin_instance.manifest.dependencies}")

    # Check tools
    tools = plugin_instance.get_tools()
    print(f"\nTools: {len(tools)}")
    for tool in tools:
        print(f"  - {tool._tool_name}: {tool._tool_description}")

    # Check subagents
    subagents = plugin_instance.get_subagents()
    print(f"\nSubagents: {len(subagents)}")
    for sub in subagents:
        print(f"  - {sub._subagent_name}: {sub._subagent_description}")

    # Test a tool
    result = plugin_instance.greet("World")
    print(f"\nTool test: {result}")

    # Test math tools
    math = plugin_instance.MathTools()
    print(f"Math test: 5 + 3 = {math.add(5, 3)}")
    print(f"Math test: 5 * 3 = {math.multiply(5, 3)}")

    print("\n✅ Example plugin works correctly!")
