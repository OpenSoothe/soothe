"""Claude Code agent wrapper plugin.

This plugin provides a Claude Code agent subagent for deep coding tasks.
"""

from typing import Any

from soothe.subagents.claude import create_claude_subagent
from soothe_sdk import plugin, subagent


@plugin(
    name="claude",
    version="1.0.0",
    description="Claude Code agent wrapper for deep coding tasks",
    trust_level="built-in",
)
class ClaudePlugin:
    """Claude Code agent plugin.

    Provides Claude subagent for advanced coding and reasoning tasks.
    """

    async def on_load(self, context: Any) -> None:
        """Verify Claude SDK is available.

        Args:
            context: Plugin context.

        Raises:
            PluginError: If anthropic library is not installed.
        """
        try:
            import anthropic  # noqa: F401
        except ImportError as e:
            from soothe.plugin.exceptions import PluginError

            raise PluginError(
                "anthropic library not installed. Install with: pip install anthropic",
                plugin_name="claude",
            ) from e

        context.logger.info("Claude plugin loaded")

    @subagent(
        name="claude",
        description=(
            "Claude Code agent for advanced coding, reasoning, and complex tasks. "
            "Uses Claude's extended thinking and tool use capabilities."
        ),
        model="anthropic:claude-sonnet-4-20250514",
    )
    async def create_claude(
        self,
        model: Any,
        config: Any,
        context: Any,  # noqa: ARG002
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Create Claude Code agent subagent.

        Args:
            model: Resolved model (BaseChatModel or string).
            config: Soothe configuration.
            context: Plugin context.
            **kwargs: Additional Claude config (permission_mode, max_turns, etc.).

        Returns:
            Subagent dict with name, description, and runnable.
        """
        # Extract common parameters
        permission_mode = kwargs.get("permission_mode", "accept-edits")
        max_turns = kwargs.get("max_turns", 20)
        system_prompt = kwargs.get("system_prompt")
        allowed_tools = kwargs.get("allowed_tools")
        disallowed_tools = kwargs.get("disallowed_tools")
        cwd = kwargs.get("cwd", config.workspace_dir)

        # Create subagent using existing factory
        runnable = create_claude_subagent(
            model=model,
            permission_mode=permission_mode,
            max_turns=max_turns,
            system_prompt=system_prompt,
            allowed_tools=allowed_tools,
            disallowed_tools=disallowed_tools,
            cwd=cwd,
        )

        return {
            "name": "claude",
            "description": (
                "Claude Code agent for advanced coding, reasoning, and complex tasks. "
                "Uses Claude's extended thinking and tool use capabilities."
            ),
            "runnable": runnable,
        }

    def get_subagents(self) -> list[Any]:
        """Get list of subagent factory functions.

        Returns:
            List containing the create_claude method.
        """
        return [self.create_claude]
