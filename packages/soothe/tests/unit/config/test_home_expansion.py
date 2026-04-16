"""Test that workspace_dir with ~ is correctly expanded."""

from pathlib import Path

from soothe.config import SootheConfig
from soothe.utils import expand_path


def test_workspace_dir_tilde_expansion():
    """Test that workspace_dir with ~ is expanded correctly in config."""
    config_dict = {
        "workspace_dir": "~/.soothe/test",
    }
    config = SootheConfig(**config_dict)

    # Verify the workspace_dir is stored correctly
    assert config.workspace_dir == "~/.soothe/test"

    # Verify that expand_path resolves it correctly
    expanded = expand_path(config.workspace_dir)

    # Should not contain literal tilde
    assert "~" not in str(expanded)

    # Should be an absolute path
    assert expanded.is_absolute()

    # Should be under the user's home directory
    home = Path.home()
    assert str(expanded).startswith(str(home))


def test_workspace_dir_expansion_in_resolver():
    """Test that workspace_dir is properly expanded when used in resolver context."""
    config_dict = {
        "workspace_dir": "~/.soothe/test",
    }
    config = SootheConfig(**config_dict)

    # The resolved_cwd should expand the tilde
    # We can't directly test resolve_planner without a model, but we can test the path expansion
    expanded = expand_path(config.workspace_dir)

    # Verify it doesn't use the wrong home directory (e.g., /Users/dan instead of /Users/xiamingchen)
    import os

    expected_home = os.path.expanduser("~")
    assert str(expanded).startswith(expected_home)
    assert "/Users/dan" not in str(expanded)  # Should NOT reference wrong user


def test_workspace_dir_absolute_path_unchanged():
    """Test that absolute paths are handled correctly."""
    config_dict = {
        "workspace_dir": "/absolute/path/to/workspace",
    }
    config = SootheConfig(**config_dict)

    expanded = expand_path(config.workspace_dir)
    assert expanded == Path("/absolute/path/to/workspace").resolve()


def test_workspace_dir_env_var_expansion():
    """Test that environment variables in workspace_dir are expanded."""
    import os

    os.environ["TEST_WORKSPACE"] = "/test/workspace"
    config_dict = {
        "workspace_dir": "$TEST_WORKSPACE/project",
    }
    config = SootheConfig(**config_dict)

    expanded = expand_path(config.workspace_dir)
    assert str(expanded).startswith("/test/workspace/project")

    del os.environ["TEST_WORKSPACE"]
