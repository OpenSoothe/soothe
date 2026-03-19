"""Scout subagent -- codebase and data exploration specialist.

Explores codebases, documents, and data sources to gather information
and synthesise findings with citations.

The scout follows the same inquiry paradigm (explore -> reflect -> iterate ->
synthesise) used by the InquiryEngine, but runs as a deepagents SubAgent
with read-only filesystem tools.  For complex cross-domain exploration that
needs web + code sources, the InquiryEngine's ``code`` or ``deep`` profiles
are a better fit.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from soothe.utils import expand_path
from soothe.utils.tool_logging import wrap_tool_with_logging

if TYPE_CHECKING:
    from collections.abc import Callable

    from deepagents.middleware.subagents import SubAgent
    from langchain_core.language_models import BaseChatModel
    from langchain_core.tools import BaseTool

logger = logging.getLogger(__name__)


SCOUT_SYSTEM_PROMPT = """\
You are an expert codebase and data exploration specialist capable of \
gathering and synthesising information from diverse sources.

## Responsibilities

1. Analyse the exploration target to determine its type and scope.
2. Develop an effective search strategy before diving in.
3. Gather information from multiple source types systematically.
4. Evaluate completeness of findings via reflection.
5. Synthesise clear, actionable summaries with citations.

## Source Types

You work across source types including:
- Files and code (source code, configuration, scripts)
- Documents (PDFs, Word docs, text files, markdown)
- Data (CSV, Excel, JSON, logs)
- Structured content (APIs, outputs, configs)

## Process (Inquiry Paradigm)

Follow this iterative loop:

1. **Target analysis** -- determine what you are exploring and categorise it \
(code, document, data, media, general). Identify the key questions to answer.
2. **Strategy generation** -- plan which files to read, which patterns to search \
for, and in what order. Prioritise high-signal sources.
3. **Exploration** -- use file tools (`ls`, `read_file`, `glob`, `grep`) to \
systematically gather information. Track all sources.
4. **Reflection** -- after each exploration pass, evaluate whether findings are \
sufficient to answer the original question. Identify knowledge gaps.
5. **Follow-up** -- if gaps remain, generate targeted follow-up queries and \
repeat from step 3.
6. **Synthesis** -- combine all findings into a clear summary with source \
citations and a confidence score.

## Output Format

Provide a structured summary:
- **Target**: What was explored.
- **Findings**: Numbered list of key discoveries, each with source citation.
- **Confidence**: How confident you are in the completeness (low / medium / high).
- **Gaps**: Any remaining unknowns or areas needing deeper investigation.

## Guidelines

- Identify the target type before exploring.
- Use appropriate tools for each source type.
- Track all sources and citations.
- Evaluate relevance of each finding.
- Reflect on completeness before synthesising.
- Provide confidence scores for findings.
- You have read-only access -- you only gather information, never modify files.
"""

SCOUT_DESCRIPTION = (
    "Codebase and data exploration specialist for gathering and synthesising "
    "information from codebases, documents, and data. Uses systematic search "
    "strategies with reflection loops to ensure completeness. Read-only."
)


def create_scout_subagent(
    model: str | BaseChatModel | None = None,
    tools: list[BaseTool | Callable[..., Any] | dict[str, Any]] | None = None,
    cwd: str | None = None,
    **_kwargs: object,
) -> SubAgent:
    """Create a Scout subagent spec.

    Args:
        model: Optional model override (string or BaseChatModel instance).
        tools: Optional list of tools. If not specified, the scout will be
            given read-only filesystem tools (ls, read_file, glob, grep).
        cwd: Working directory for filesystem exploration tools.
        **_kwargs: Additional config (ignored for forward compat).

    Returns:
        `SubAgent` dict compatible with deepagents.
    """
    spec: SubAgent = {
        "name": "scout",
        "description": SCOUT_DESCRIPTION,
        "system_prompt": SCOUT_SYSTEM_PROMPT,
    }
    if model:
        spec["model"] = model

    if tools is not None:
        spec["tools"] = [wrap_tool_with_logging(tool, "scout", logger) for tool in tools]
    else:
        from deepagents.backends.filesystem import FilesystemBackend
        from deepagents.middleware.filesystem import FilesystemMiddleware

        from soothe.backends.filesystem_secure import SecureFilesystemBackend

        resolved_cwd = str(expand_path(cwd)) if cwd else str(Path.cwd())
        base_backend = FilesystemBackend(root_dir=resolved_cwd, virtual_mode=True)
        secure_backend = SecureFilesystemBackend(
            backend=base_backend,
            root_dir=resolved_cwd,
            policy=None,
            policy_context=None,
            allow_outside_root=False,
        )
        fs_middleware = FilesystemMiddleware(backend=secure_backend)
        read_only_tools = [
            fs_middleware._create_ls_tool(),
            fs_middleware._create_read_file_tool(),
            fs_middleware._create_glob_tool(),
            fs_middleware._create_grep_tool(),
        ]
        spec["tools"] = [wrap_tool_with_logging(tool, "scout", logger) for tool in read_only_tools]

    return spec
