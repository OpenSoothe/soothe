"""Mirror host skill directories into the workspace when virtual mode is enabled."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from langchain.agents.middleware.types import AgentMiddleware
from langchain_core.messages import HumanMessage

from soothe.core.workspace.tool_path_resolution import filesystem_virtual_mode_from_soothe_config
from soothe.skills.catalog import parse_slash_skill_user_line
from soothe.skills.workspace_sync import (
    sync_external_skills_to_workspace,
    sync_specific_skill_to_workspace,
)

if TYPE_CHECKING:
    from langchain.agents.middleware.types import AgentState
    from langgraph.runtime import Runtime

    from soothe.config import SootheConfig

logger = logging.getLogger(__name__)


class SkillWorkspaceSyncMiddleware(AgentMiddleware):
    """Copy external skills into ``<workspace>/.soothe/skills`` before agent tools run.

      When ``security.allow_paths_outside_workspace`` is false (virtual mode), the
    filesystem backend only allows paths under the workspace root. User skills under
      ``~/.agents/skills`` or ``~/.soothe/skills`` are mirrored into the workspace so
      execute-step ``<SKILL_CONTEXT>`` folder paths and on-demand reads work. Package
      built-in skills are not copied (reference text is inlined in prompts).
    """

    def __init__(self, config: SootheConfig) -> None:
        self._config = config

    async def abefore_agent(
        self,
        state: AgentState,
        runtime: Runtime,  # noqa: ARG002
    ) -> dict[str, Any] | None:
        """Mirror external skills when virtual mode and workspace are configured.

        If the first human message contains a ``/skill:<name>`` invocation,
        only that specific skill is mirrored. Otherwise, all external skills
        are mirrored (backward-compatible behavior).
        """
        if not filesystem_virtual_mode_from_soothe_config(self._config):
            return None

        from langgraph.config import get_config

        try:
            lg_config = get_config()
        except Exception:
            return None
        if not isinstance(lg_config, dict):
            return None
        configurable = lg_config.get("configurable")
        if not isinstance(configurable, dict):
            return None

        workspace = configurable.get("workspace")
        if not workspace or not str(workspace).strip():
            return None

        ws = Path(str(workspace)).expanduser().resolve()

        # Try to extract skill name from the first human message
        skill_name = self._extract_skill_name_from_state(state)

        if skill_name:
            # Targeted sync: only sync the addressed skill
            mirrored_path = sync_specific_skill_to_workspace(self._config, ws, skill_name)
            if mirrored_path:
                logger.info(
                    "[SkillSync] Mirrored skill '%s' to %s",
                    skill_name,
                    mirrored_path,
                )
        else:
            # Fall back to syncing all external skills
            mirrored = sync_external_skills_to_workspace(self._config, ws)
            if mirrored:
                logger.info(
                    "[SkillSync] Mirrored %d external skill(s) under %s",
                    len(mirrored),
                    ws / ".soothe" / "skills",
                )
        return None

    def _extract_skill_name_from_state(self, state: AgentState) -> str | None:
        """Extract skill name from the first human message if it's a /skill: invocation.

        Args:
            state: Agent state containing messages.

        Returns:
            Skill name if the first human message is a ``/skill:<name>`` line,
            otherwise ``None``.
        """
        messages = state.get("messages", [])
        for msg in messages:
            if isinstance(msg, HumanMessage):
                content = msg.content
                if isinstance(content, str):
                    parsed = parse_slash_skill_user_line(content)
                    if parsed is not None:
                        return parsed[0]  # skill_name (lowercased)
                break  # Only check first human message
        return None
