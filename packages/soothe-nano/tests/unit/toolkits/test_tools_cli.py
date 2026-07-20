"""Tests for CLI tools functionality."""

from unittest.mock import MagicMock

from langchain_community.tools import ShellTool
from langchain_core.utils.function_calling import convert_to_openai_tool
from langchain_experimental.tools.python.tool import PythonREPLTool
from soothe.foundation.sloop.utils.messages import LoopHumanMessage

from soothe_nano.toolkits.execution import (
    ExecutionToolkit,
    KillProcessTool,
    RunBackgroundTool,
    RunCommandShellTool,
    RunPythonREPLTool,
    TailBackgroundLogTool,
)


class TestRunCommandShellToolWorkspaceResolution:
    """RFC-103 / IG-300: client workspace must win over daemon workspace_root."""

    def test_effective_workspace_prefers_injected_runtime_config(self) -> None:
        """ToolNode passes workspace on ToolRuntime.config (thread-pool safe)."""
        tool = RunCommandShellTool(workspace_root="/daemon/default")
        runtime = MagicMock()
        runtime.config = {"configurable": {"workspace": "/client/source"}}
        assert tool._get_effective_workspace(runtime) == "/client/source"

    def test_effective_workspace_reads_loop_human_workspace_from_state(self) -> None:
        """When configurable omits workspace, fall back to LoopHumanMessage in state."""
        tool = RunCommandShellTool(workspace_root="/daemon/default")
        runtime = MagicMock()
        runtime.config = {"configurable": {"thread_id": "t1"}}
        runtime.state = {
            "messages": [
                LoopHumanMessage(
                    content="Execute: x",
                    thread_id="t1",
                    workspace="/client/from_state",
                    phase="execute_step",
                )
            ]
        }
        assert tool._get_effective_workspace(runtime) == "/client/from_state"

    def test_effective_workspace_reads_state_workspace_key(self) -> None:
        """Subgraphs (explore) set ``state['workspace']`` without LoopHumanMessage."""
        tool = RunCommandShellTool(workspace_root="/daemon/default")
        runtime = MagicMock()
        runtime.config = {"configurable": {"thread_id": "t1"}}
        runtime.state = {"workspace": "/thread/explore/ws", "messages": []}
        assert tool._get_effective_workspace(runtime) == "/thread/explore/ws"


class TestRunCommandShellToolOpenAiSchema:
    """OpenAI bind_tools requires JSON-serializable tool parameters (no ToolRuntime in schema)."""

    def test_run_command_openai_parameters_exclude_runtime(self) -> None:
        tool = RunCommandShellTool()
        params = convert_to_openai_tool(tool)["function"]["parameters"]
        props = params.get("properties") or {}
        assert "runtime" not in props
        assert "command" in props

    def test_run_background_openai_parameters_exclude_runtime(self) -> None:
        tool = RunBackgroundTool()
        params = convert_to_openai_tool(tool)["function"]["parameters"]
        props = params.get("properties") or {}
        assert "runtime" not in props
        assert "command" in props


class TestRunCommandShellToolInitialization:
    """Test RunCommandShellTool (langchain_community ShellTool) configuration."""

    def test_default_initialization(self) -> None:
        tool = RunCommandShellTool()

        assert tool.name == "run_command"
        assert tool.timeout == 60
        assert tool.max_output_length == 100_000
        assert tool.workspace_root == ""
        assert isinstance(tool, ShellTool)

    def test_custom_configuration(self) -> None:
        tool = RunCommandShellTool(
            workspace_root="/tmp/test",
            timeout=120,
            max_output_length=5000,
        )

        assert tool.workspace_root == "/tmp/test"
        assert tool.timeout == 120
        assert tool.max_output_length == 5000

    def test_security_configuration_field(self) -> None:
        tool = RunCommandShellTool()
        assert tool.security_config is None

    def test_execution_toolkit_returns_five_tools(self) -> None:
        tools = ExecutionToolkit().get_tools()

        assert len(tools) == 5
        assert isinstance(tools[0], RunCommandShellTool)
        assert isinstance(tools[0], ShellTool)
        assert isinstance(tools[1], RunPythonREPLTool)
        assert isinstance(tools[1], PythonREPLTool)
        assert isinstance(tools[2], RunBackgroundTool)
        assert isinstance(tools[3], TailBackgroundLogTool)
        assert isinstance(tools[4], KillProcessTool)


class TestRunCommandShellToolCommandValidation:
    """Test command validation via operation security protocol."""

    def test_dangerous_command_is_denied(self) -> None:
        tool = RunCommandShellTool()
        verdict, _reason = tool._security_decision("rm -rf /", tool.name)
        assert verdict == "deny"

    def test_safe_command_is_allowed(self) -> None:
        tool = RunCommandShellTool()
        verdict, _reason = tool._security_decision("echo hello", tool.name)
        assert verdict == "allow"


class TestCliToolExecution:
    """Test CLI command execution."""

    def test_run_with_banned_command(self) -> None:
        tool = RunCommandShellTool()

        result = tool._run("rm -rf /")

        assert "Error" in result
        assert "Command blocked by security rule" in result


class TestBackgroundTools:
    """Test background execution tools."""

    def test_run_background_metadata(self) -> None:
        tool = RunBackgroundTool()

        assert tool.name == "run_background"
        assert "background" in tool.description.lower()

    def test_kill_process_metadata(self) -> None:
        tool = KillProcessTool()

        assert tool.name == "kill_process"
        assert "terminate" in tool.description.lower()

    def test_run_background_denied_command(self) -> None:
        tool = RunBackgroundTool()
        result = tool._run("sudo rm -rf /")
        assert result["status"] == "error"
        assert result["log_path"] is None
        assert "Command blocked by security rule" in result["message"]
