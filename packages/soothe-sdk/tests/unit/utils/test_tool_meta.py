"""Tests for the ToolMeta registry (single source of truth for display metadata)."""

from soothe_sdk.tools.metadata import (
    TOOL_REGISTRY,
    extract_filesystem_path_for_policy,
    get_all_path_arg_keys,
    get_file_write_tool_names,
    get_outcome_type,
    get_tool_categories,
    get_tool_display_name,
    get_tool_meta,
    get_tools_with_header_info,
    is_policy_filesystem_tool,
)


class TestOutcomeTypeCoverage:
    """Verify outcome_type field coverage and correctness."""

    def test_all_tools_have_outcome_type(self) -> None:
        """Every registered tool should have explicit outcome_type."""
        seen_ids: set[int] = set()
        for name, meta in TOOL_REGISTRY.items():
            if id(meta) in seen_ids:
                continue
            seen_ids.add(id(meta))
            # All tools should have explicit outcome_type (not relying on fallback)
            assert meta.outcome_type is not None, f"Tool {meta.name} missing outcome_type"

    def test_file_read_tools_have_correct_outcome_type(self) -> None:
        """File read tools should have outcome_type='file_read'."""
        file_read_tools = [
            "read_file",
            "ls",
            "grep",
            "glob",
            "file_info",
            "inspect_data",
            "summarize_data",
            "check_data_quality",
            "extract_text",
            "get_data_info",
            "ask_about_file",
        ]
        for name in file_read_tools:
            meta = get_tool_meta(name)
            assert meta is not None
            assert meta.outcome_type == "file_read", (
                f"{name}: expected file_read, got {meta.outcome_type}"
            )

    def test_file_write_tools_have_correct_outcome_type(self) -> None:
        """File write tools should have outcome_type='file_write'."""
        for name in get_file_write_tool_names():
            meta = get_tool_meta(name)
            assert meta is not None
            assert meta.outcome_type == "file_write", (
                f"{name}: expected file_write, got {meta.outcome_type}"
            )

    def test_get_file_write_tool_names_is_complete(self) -> None:
        """Every known file write tool is returned by get_file_write_tool_names()."""
        expected = {
            "write_file",
            "edit_file",
            "delete_file",
            "edit_lines",
            "insert_lines",
            "delete_lines",
            "apply_diff",
        }
        assert get_file_write_tool_names() == frozenset(expected)

    def test_media_tools_have_file_read_outcome_type(self) -> None:
        """Media tools should have outcome_type='file_read' (they read files)."""
        media_tools = [
            "analyze_image",
            "transcribe_audio",
            "get_video_info",
            "analyze_video",
            "extract_text_from_image",
            "audio_qa",
        ]
        for name in media_tools:
            meta = get_tool_meta(name)
            assert meta is not None
            assert meta.outcome_type == "file_read", (
                f"{name}: expected file_read, got {meta.outcome_type}"
            )

    def test_execution_tools_have_code_exec_outcome_type(self) -> None:
        """Execution tools should have outcome_type='code_exec'."""
        execution_tools = [
            "run_command",
            "run_python",
            "run_background",
            "tail_background_log",
            "kill_process",
        ]
        for name in execution_tools:
            meta = get_tool_meta(name)
            assert meta is not None
            assert meta.outcome_type == "code_exec", (
                f"{name}: expected code_exec, got {meta.outcome_type}"
            )

    def test_web_tools_have_web_search_outcome_type(self) -> None:
        """Web tools should have outcome_type='web_search'."""
        web_tools = [
            "web_search",
            "fetch_url",
            "wizsearch_search",
            "wizsearch_crawl",
            "requests_get",
            "requests_delete",
        ]
        for name in web_tools:
            meta = get_tool_meta(name)
            assert meta is not None
            assert meta.outcome_type == "web_search", (
                f"{name}: expected web_search, got {meta.outcome_type}"
            )

    def test_http_mutating_requests_tools_have_generic_outcome(self) -> None:
        """POST/PATCH/PUT request tools use outcome_type='generic'."""
        for name in ("requests_post", "requests_patch", "requests_put"):
            meta = get_tool_meta(name)
            assert meta is not None
            assert meta.outcome_type == "generic", (
                f"{name}: expected generic, got {meta.outcome_type}"
            )

    def test_subagent_tools_have_correct_outcome_type(self) -> None:
        """Subagent tools should have outcome_type='subagent'."""
        subagent_tools = ["task", "deep_research"]
        for name in subagent_tools:
            meta = get_tool_meta(name)
            assert meta is not None
            assert meta.outcome_type == "subagent", (
                f"{name}: expected subagent, got {meta.outcome_type}"
            )

    def test_generic_tools_have_generic_outcome_type(self) -> None:
        """Generic tools should have outcome_type='generic'."""
        generic_tools = ["current_datetime", "ask_user", "compact_conversation", "write_todos"]
        for name in generic_tools:
            meta = get_tool_meta(name)
            assert meta is not None
            assert meta.outcome_type == "generic", (
                f"{name}: expected generic, got {meta.outcome_type}"
            )


class TestGetOutcomeTypeHelper:
    """Test the get_outcome_type() helper function."""

    def test_returns_explicit_outcome_type(self) -> None:
        """Helper should return explicit outcome_type from ToolMeta."""
        assert get_outcome_type("read_file") == "file_read"
        assert get_outcome_type("write_file") == "file_write"
        assert get_outcome_type("run_command") == "code_exec"

    def test_resolves_aliases_correctly(self) -> None:
        """Helper should resolve aliases to canonical tool and return its outcome_type."""
        # shell is alias of run_command
        assert get_outcome_type("shell") == "code_exec"
        # list_files is alias of ls
        assert get_outcome_type("list_files") == "file_read"

    def test_returns_generic_for_unknown_tool(self) -> None:
        """Helper should return 'generic' for unknown tools."""
        assert get_outcome_type("nonexistent_tool") == "generic"

    def test_valid_outcome_types_only(self) -> None:
        """All outcome_type values should be valid types expected by schemas.py."""
        valid_types = {"file_read", "file_write", "web_search", "code_exec", "subagent", "generic"}
        seen_ids: set[int] = set()
        for meta in TOOL_REGISTRY.values():
            if id(meta) in seen_ids:
                continue
            seen_ids.add(id(meta))
            if meta.outcome_type:
                assert meta.outcome_type in valid_types, (
                    f"{meta.name}: invalid outcome_type {meta.outcome_type}"
                )


class TestToolMetaDisplayNames:
    """Verify display names from ToolMeta registry."""

    def test_curated_display_names(self) -> None:
        """Display names are PascalCase from ToolMeta registry."""
        expected = {
            "run_command": "RunCommand",
            "ls": "ListFiles",
            "read_file": "ReadFile",
            "write_file": "WriteFile",
            "edit_file": "EditFile",
            "glob": "Glob",
            "grep": "Grep",
            "web_search": "WebSearch",
            "fetch_url": "FetchUrl",
            "wizsearch_search": "WebSearch",
            "wizsearch_crawl": "HeadlessCrawl",
            "deep_research": "Deep Research",
        }
        for name, expected_display in expected.items():
            assert get_tool_display_name(name) == expected_display, (
                f"{name}: expected {expected_display!r}"
            )

    def test_unknown_tool_fallback(self) -> None:
        """Unknown tools use title() fallback (PascalCase, no spaces)."""
        assert get_tool_display_name("unknown_tool") == "UnknownTool"

    def test_canonical_name_with_explicit_display_name(self) -> None:
        """Tools with explicit display_name return that value."""
        assert get_tool_display_name("current_datetime") == "CurrentDateTime"


class TestToolMetaAliases:
    """Verify alias resolution."""

    def test_shell_alias_resolves_to_run_command(self) -> None:
        meta = get_tool_meta("shell")
        assert meta is not None
        assert meta.name == "run_command"

    def test_bash_alias_resolves_to_run_command(self) -> None:
        meta = get_tool_meta("bash")
        assert meta is not None
        assert meta.name == "run_command"

    def test_run_command_canonical(self) -> None:
        meta = get_tool_meta("run_command")
        assert meta is not None
        assert meta.name == "run_command"

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
        """Aliases resolve to canonical tool's display name."""
        assert get_tool_display_name("shell") == "RunCommand"
        assert get_tool_display_name("list_files") == "ListFiles"
        assert get_tool_display_name("search_web") == "WebSearch"


class TestToolMetaRegistry:
    """Verify registry completeness and consistency."""

    def test_no_duplicate_canonical_names(self) -> None:
        seen: set[str] = set()
        for name, meta in TOOL_REGISTRY.items():
            if name == meta.name:
                assert name not in seen, f"Duplicate canonical name: {name}"
                seen.add(name)

    def test_all_canonical_tools_have_arg_keys(self) -> None:
        no_args_ok = {"compact_conversation", "current_datetime"}
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
        old_keys = {
            "file_path",
            "path",
            "path_name",
            "target_file",
            "file",
            "filepath",
            "filename",
            "relative_path",
        }
        result = get_all_path_arg_keys()
        for k in old_keys:
            assert k in result, f"Missing path arg key: {k!r}"

    def test_tools_with_header_info_covers_old_set(self) -> None:
        old_set = {
            "ls",
            "list_files",
            "read_file",
            "write_file",
            "edit_file",
            "glob",
            "grep",
            "run_command",
            "shell",
            "bash",
            "web_search",
            "fetch_url",
            "search_web",
            "crawl_web",
            "task",
            "write_todos",
        }
        result = get_tools_with_header_info()
        for t in old_set:
            assert t in result, f"Missing tool with header info: {t!r}"

    def test_tool_categories_covers_old_dict(self) -> None:
        old_cats = {
            "read_file": "file_ops",
            "write_file": "file_ops",
            "delete_file": "file_ops",
            "list_files": "file_ops",
            "search_files": "file_ops",
            "glob": "file_ops",
            "ls": "file_ops",
            "run_command": "execution",
            "run_python": "execution",
            "run_background": "execution",
            "kill_process": "execution",
            "transcribe_audio": "media",
            "get_video_info": "media",
            "analyze_image": "media",
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
        assert meta.source == "soothe_deepagents"

    def test_returns_none_for_unknown_tool(self) -> None:
        assert get_tool_meta("nonexistent_tool") is None

    def test_returns_meta_for_alias(self) -> None:
        meta = get_tool_meta("shell")
        assert meta is not None
        assert meta.name == "run_command"


class TestPolicyFilesystemMetadata:
    """IG-300: policy-facing filesystem classification and path extraction."""

    def test_is_policy_filesystem_tool(self) -> None:
        assert is_policy_filesystem_tool("read_file")
        assert is_policy_filesystem_tool("glob")
        assert not is_policy_filesystem_tool("run_command")
        assert is_policy_filesystem_tool("fs_custom")

    def test_extract_path_prefers_registered_keys(self) -> None:
        p = extract_filesystem_path_for_policy("read_file", {"file_path": "/a/b", "path": "/c/d"})
        assert p == "/a/b"

    def test_extract_path_grep_optional(self) -> None:
        assert extract_filesystem_path_for_policy("grep", {"pattern": "foo"}) is None
        assert (
            extract_filesystem_path_for_policy("grep", {"pattern": "x", "path": "/tmp"}) == "/tmp"
        )

    def test_extract_path_glob_defaults_virtual_root(self) -> None:
        """IG-366: pattern-only glob uses virtual ``/`` for workspace containment."""
        assert extract_filesystem_path_for_policy("glob", {"pattern": "**/README*"}) == "/"
        assert (
            extract_filesystem_path_for_policy("glob", {"pattern": "x", "path": "/pkg"}) == "/pkg"
        )
        assert extract_filesystem_path_for_policy("glob", {"pattern": "x", "path": ""}) == "/"
