"""Tests for the ToolMeta registry (single source of truth for display metadata)."""

from soothe_sdk.utils.tool_meta import (
    TOOL_REGISTRY,
    ToolMeta,
    get_all_path_arg_keys,
    get_tool_categories,
    get_tool_display_name,
    get_tool_meta,
    get_tools_with_header_info,
)


class TestToolMetaDisplayNames:
    """Verify display names match the old curated dict in display.py."""

    def test_curated_display_names(self) -> None:
        expected = {
            "execute": "Shell Execute",
            "ls": "List Files",
            "read_file": "Read File",
            "write_file": "Write File",
            "edit_file": "Edit File",
            "glob": "Search Files",
            "grep": "Search Content",
            "web_search": "Web Search",
            "fetch_url": "Web Crawl",
            "wizsearch_search": "Multi-Engine Search",
            "wizsearch_crawl": "Headless Crawl",
            "research": "Research",
        }
        for name, expected_display in expected.items():
            assert get_tool_display_name(name) == expected_display, f"{name}: expected {expected_display!r}"

    def test_unknown_tool_fallback(self) -> None:
        assert get_tool_display_name("unknown_tool") == "Unknown Tool"

    def test_canonical_name_with_title_fallback(self) -> None:
        assert get_tool_display_name("current_datetime") == "Current DateTime"


class TestToolMetaAliases:
    """Verify alias resolution."""

    def test_shell_alias_resolves_to_execute(self) -> None:
        meta = get_tool_meta("shell")
        assert meta is not None
        assert meta.name == "execute"

    def test_bash_alias_resolves_to_execute(self) -> None:
        meta = get_tool_meta("bash")
        assert meta is not None
        assert meta.name == "execute"

    def test_run_command_alias_resolves_to_execute(self) -> None:
        meta = get_tool_meta("run_command")
        assert meta is not None
        assert meta.name == "execute"

    def test_list_files_alias_resolves_to_ls(self) -> None:
        meta = get_tool_meta("list_files")
        assert meta is not None
        assert meta.name == "ls"

    def test_search_web_alias_resolves_to_web_search(self) -> None:
        meta = get_tool_meta("search_web")
        assert meta is not None
        assert meta.name == "web_search"

    def test_crawl_web_alias_resolves_to_fetch_url(self) -> None:
        meta = get_tool_meta("crawl_web")
        assert meta is not None
        assert meta.name == "fetch_url"

    def test_alias_has_same_display_name(self) -> None:
        assert get_tool_display_name("shell") == "Shell Execute"
        assert get_tool_display_name("list_files") == "List Files"
        assert get_tool_display_name("search_web") == "Web Search"


class TestToolMetaRegistry:
    """Verify registry completeness and consistency."""

    def test_no_duplicate_canonical_names(self) -> None:
        seen: set[str] = set()
        for name, meta in TOOL_REGISTRY.items():
            if name == meta.name:
                assert name not in seen, f"Duplicate canonical name: {name}"
                seen.add(name)

    def test_all_canonical_tools_have_arg_keys(self) -> None:
        no_args_ok = {"compact_conversation", "current_datetime", "list_goals"}
        seen_ids: set[int] = set()
        for name, meta in TOOL_REGISTRY.items():
            if id(meta) in seen_ids:
                continue
            seen_ids.add(id(meta))
            if name in no_args_ok:
                continue
            assert meta.arg_keys, f"Tool {name} has no arg_keys defined"

    def test_path_arg_keys_subset_of_arg_keys(self) -> None:
        seen_ids: set[int] = set()
        for meta in TOOL_REGISTRY.values():
            if id(meta) in seen_ids:
                continue
            seen_ids.add(id(meta))
            for pk in meta.path_arg_keys:
                assert pk in meta.arg_keys, f"{meta.name}: path_arg_key {pk!r} not in arg_keys"


class TestDerivedSets:
    """Verify registry-derived sets are supersets of old hardcoded values."""

    def test_path_arg_keys_covers_old_file_tool_path_keys(self) -> None:
        old_keys = {"file_path", "path", "path_name", "target_file", "file", "filepath", "filename", "relative_path"}
        result = get_all_path_arg_keys()
        for k in old_keys:
            assert k in result, f"Missing path arg key: {k!r}"

    def test_tools_with_header_info_covers_old_set(self) -> None:
        old_set = {
            "ls", "list_files", "read_file", "write_file", "edit_file",
            "glob", "grep", "execute", "shell", "bash", "run_command",
            "web_search", "fetch_url", "search_web", "crawl_web",
            "task", "write_todos",
        }
        result = get_tools_with_header_info()
        for t in old_set:
            assert t in result, f"Missing tool with header info: {t!r}"

    def test_tool_categories_covers_old_dict(self) -> None:
        old_cats = {
            "read_file": "file_ops", "write_file": "file_ops", "delete_file": "file_ops",
            "list_files": "file_ops", "search_files": "file_ops", "glob": "file_ops",
            "ls": "file_ops", "run_command": "execution", "run_python": "execution",
            "run_background": "execution", "kill_process": "execution",
            "transcribe_audio": "media", "get_video_info": "media", "analyze_image": "media",
            "create_goal": "goals", "complete_goal": "goals", "fail_goal": "goals",
        }
        result = get_tool_categories()
        for name, cat in old_cats.items():
            assert name in result, f"Missing tool in categories: {name!r}"
            assert result[name] == cat, f"{name}: expected {cat!r}, got {result[name]!r}"


class TestGetToolMeta:
    """Test get_tool_meta lookup function."""

    def test_returns_meta_for_known_tool(self) -> None:
        meta = get_tool_meta("read_file")
        assert meta is not None
        assert meta.name == "read_file"
        assert meta.category == "file_ops"
        assert meta.source == "deepagents"

    def test_returns_none_for_unknown_tool(self) -> None:
        assert get_tool_meta("nonexistent_tool") is None

    def test_returns_meta_for_alias(self) -> None:
        meta = get_tool_meta("shell")
        assert meta is not None
        assert meta.name == "execute"
