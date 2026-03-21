"""Tool display names for user-facing messages.

Maps internal tool names (snake_case) to user-facing display names (PascalCase)
for consistent presentation in CLI and TUI interfaces.
"""

from __future__ import annotations

# Map tool internal names (snake_case) to display names (PascalCase)
TOOL_DISPLAY_NAMES: dict[str, str] = {
    # File operations
    "read_file": "ReadFile",
    "write_file": "WriteFile",
    "delete_file": "DeleteFile",
    "search_files": "SearchFiles",
    "list_files": "ListFiles",
    "file_info": "FileInfo",
    "edit_file_lines": "EditFileLines",
    "insert_lines": "InsertLines",
    "delete_lines": "DeleteLines",
    "apply_diff": "ApplyDiff",
    # Execution
    "run_command": "RunCommand",
    "run_python": "RunPython",
    "run_background": "RunBackground",
    "kill_process": "KillProcess",
    # Data operations
    "inspect_data": "InspectData",
    "summarize_data": "SummarizeData",
    "check_data_quality": "CheckDataQuality",
    "extract_text": "ExtractText",
    "get_data_info": "GetDataInfo",
    "ask_about_file": "AskAboutFile",
    # Goals
    "create_goal": "CreateGoal",
    "list_goals": "ListGoals",
    "complete_goal": "CompleteGoal",
    "fail_goal": "FailGoal",
    # Web
    "search_web": "SearchWeb",
    "crawl_web": "CrawlWeb",
    # Research
    "research": "Research",
    # Media
    "analyze_image": "AnalyzeImage",
    "extract_text_from_image": "ExtractTextFromImage",
    "analyze_video": "AnalyzeVideo",
    "get_video_info": "GetVideoInfo",
    "transcribe_audio": "TranscribeAudio",
    "audio_qa": "AudioQA",
    # DateTime
    "current_datetime": "CurrentDateTime",
}


def get_tool_display_name(internal_name: str) -> str:
    """Get user-facing display name for a tool.

    Args:
        internal_name: Tool name in snake_case (e.g., "read_file")

    Returns:
        PascalCase display name (e.g., "ReadFile")

    Examples:
        >>> get_tool_display_name("read_file")
        'ReadFile'
        >>> get_tool_display_name("unknown_tool")
        'UnknownTool'
    """
    return TOOL_DISPLAY_NAMES.get(
        internal_name,
        internal_name.replace("_", " ").title().replace(" ", ""),
    )
