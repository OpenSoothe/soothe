"""Tests for SemanticLoader (soothe.context.semantic)."""

from soothe.context.semantic import SemanticLoader


class TestSemanticLoaderMissingFiles:
    def test_returns_empty_when_no_paths(self) -> None:
        loader = SemanticLoader(soothe_home=None, workspace=None)
        assert loader.load_project_instructions() == ""
        assert loader.load_agent_instructions() == ""
        assert loader.load_memory() == ""

    def test_returns_empty_when_path_doesnt_exist(self, tmp_path) -> None:
        loader = SemanticLoader(soothe_home=tmp_path / "missing", workspace=tmp_path / "gone")
        assert loader.load_project_instructions() == ""


class TestSemanticLoaderWorkspace:
    def test_loads_from_workspace(self, tmp_path) -> None:
        (tmp_path / "CLAUDE.md").write_text("project instructions", encoding="utf-8")
        loader = SemanticLoader(workspace=tmp_path)
        assert loader.load_project_instructions() == "project instructions"

    def test_workspace_preferred_over_home(self, tmp_path) -> None:
        home = tmp_path / "home"
        home.mkdir()
        (home / "CLAUDE.md").write_text("from home", encoding="utf-8")
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (workspace / "CLAUDE.md").write_text("from workspace", encoding="utf-8")
        loader = SemanticLoader(soothe_home=home, workspace=workspace)
        assert loader.load_project_instructions() == "from workspace"

    def test_falls_back_to_home(self, tmp_path) -> None:
        home = tmp_path / "home"
        home.mkdir()
        (home / "AGENTS.md").write_text("agent instructions", encoding="utf-8")
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        loader = SemanticLoader(soothe_home=home, workspace=workspace)
        assert loader.load_agent_instructions() == "agent instructions"


class TestSemanticLoaderAllFiles:
    def test_loads_all_instruction_types(self, tmp_path) -> None:
        (tmp_path / "CLAUDE.md").write_text("project", encoding="utf-8")
        (tmp_path / "AGENTS.md").write_text("agent", encoding="utf-8")
        (tmp_path / "MEMORY.md").write_text("memory", encoding="utf-8")
        loader = SemanticLoader(workspace=tmp_path)
        assert loader.load_project_instructions() == "project"
        assert loader.load_agent_instructions() == "agent"
        assert loader.load_memory() == "memory"

    def test_oserror_returns_empty(self, tmp_path) -> None:
        """Gracefully handles unreadable files."""
        loader = SemanticLoader(soothe_home=None, workspace=tmp_path)
        assert loader.load_project_instructions() == ""
